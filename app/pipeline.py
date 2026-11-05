"""V2 single-request orchestration; module logic stays in the five owners."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from time import perf_counter
from typing import Any

from app.audit import FlowAuditLog
from app.build_services import PipelineServices
from core.config import configured_path
from core.contracts import AgentRequest, AgentResult, RuntimeSample, ToolCall, Transcript
from core.interfaces import Environment
from modules.planner.service import PlanInvalidError

_SENSITIVE_KEYS = re.compile(
    r"(content|body|message|phone|account|contact|recipient|name|address|token|password|email|location|text)",
    re.IGNORECASE,
)


def _redact(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {name: _redact(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value


class Pipeline:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.services = PipelineServices(config)

    def run(
        self,
        sample: RuntimeSample,
        audio_path: str | Path,
        environment: Environment,
        *,
        transcript_override: str | None = None,
        transcript_reference: str | None = None,
    ) -> AgentResult:
        if transcript_override is not None and transcript_reference is not None:
            raise ValueError("transcript_override and transcript_reference cannot both be provided")
        if transcript_reference is not None and not transcript_reference.strip():
            raise ValueError("transcript_reference must not be empty")
        if transcript_override is not None and self.config.get("run", {}).get("mode") != "mock":
            raise ValueError("transcript_override is only supported in mock mode")

        started = perf_counter()
        self.services.reset_budget()
        audit_log = self._create_audit(sample.id)
        if audit_log:
            audit_log.emit("sample_started", {})
        try:
            if transcript_reference is not None:
                transcript = Transcript(text=" ".join(transcript_reference.split()), language="vi")
                if audit_log:
                    audit_log.emit("transcript_reference_loaded", {})
            elif transcript_override is not None:
                transcript = Transcript(text=" ".join(transcript_override.split()), language="vi")
            else:
                transcript = self.services.asr.transcribe(str(audio_path))
            if audit_log and transcript_reference is None and transcript_override is None:
                audit_log.emit("asr_completed", {"character_count": len(transcript.text)})
            if audit_log and audit_log.level == "full":
                source = (
                    "transcript_reference"
                    if transcript_reference is not None
                    else "transcript_override"
                    if transcript_override is not None
                    else "asr"
                )
                audit_log.emit(
                    "transcript_ready",
                    {"source": source, "text": transcript.text, "language": transcript.language},
                )

            request = AgentRequest(
                sample_id=sample.id,
                transcript=transcript.text,
                context=sample.context.model_dump(mode="json"),
                history=sample.history,
            )
            catalog = environment.list_available_tools()
            candidates = self.services.discovery.retrieve(request, catalog)
            if audit_log:
                audit_log.emit(
                    "discovery_completed",
                    {"candidate_count": len(candidates), "candidate_names": [tool.name for tool in candidates]},
                )

            try:
                plan = self.services.planner.generate_plan(request, candidates)
            except PlanInvalidError as exc:
                if audit_log:
                    details = {"reason": "PLAN_INVALID"}
                    if audit_log.level == "full":
                        details["error"] = str(exc)
                    audit_log.emit("plan_rejected", details)
                result = self._result(
                    sample.id,
                    "PLAN_INVALID",
                    environment,
                    trace=[{"event": "plan_rejected", "reason": "PLAN_INVALID", "message": str(exc)}],
                )
            else:
                planning = self.config.get("planning", {})
                planning_mode = planning.get("mode", "strict_single_shot")
                if planning_mode not in {"strict_single_shot", "adaptive_on_issue"}:
                    raise ValueError(f"Unknown planning mode: {planning_mode!r}")
                if audit_log:
                    audit_log.emit(
                        "plan_created",
                        {
                            "plan_version": 0,
                            "goal_count": len(plan.goals),
                            "task_count": len(plan.tasks),
                            "planner_call_index": getattr(self.services.planner, "call_count", 0),
                        },
                    )
                if audit_log and audit_log.level == "full":
                    audit_log.emit("plan_generated", {"plan": plan.model_dump(mode="json")})
                detailed_audit = (
                    audit_log.emit
                    if audit_log is not None and audit_log.level == "full"
                    else None
                )

                def event_sink(event):
                    if audit_log is None:
                        return
                    audit_log.emit(
                        event.event,
                        {
                            **event.details,
                            "task_id": event.task_id,
                            "tool_name": event.tool,
                            "status": event.status,
                        },
                    )

                run_result = self.services.runtime.execute_plan(
                    plan,
                    self.services.resolver,
                    environment,
                    request=request,
                    discovery=self.services.discovery,
                    planner=self.services.planner,
                    adaptive=planning_mode == "adaptive_on_issue",
                    max_repair_calls=planning.get("max_repair_calls", 0),
                    detailed_audit=detailed_audit,
                    event_sink=event_sink if audit_log else None,
                )
                result = AgentResult(
                    id=sample.id,
                    status=run_result.execution_status,
                    tool_calls=[ToolCall.model_validate(call) for call in run_result.tool_calls],
                    state_hash=run_result.state_hash,
                    trace=[event.model_dump(mode="json") for event in run_result.audit_events],
                )

            result.trace.append(
                {
                    "event": "pipeline_completed",
                    "status": result.status,
                    "qwen_calls": self.services.llm.calls_used,
                    "planner_calls": getattr(self.services.planner, "call_count", 0),
                },
            )
            if audit_log:
                if audit_log.level == "full":
                    audit_log.emit(
                        "final_result",
                        {
                            "status": result.status,
                            "tool_calls": [call.model_dump(mode="json") for call in result.tool_calls],
                            "state_hash": result.state_hash,
                        },
                    )
                audit_log.emit(
                    "pipeline_completed",
                    {
                        "status": result.status,
                        "tool_call_count": len(result.tool_calls),
                        "qwen_calls": self.services.llm.calls_used,
                        "elapsed_seconds": perf_counter() - started,
                    },
                )
                audit_log.finish(result, elapsed_seconds=perf_counter() - started)
            if self.config.get("run", {}).get("save_traces", True):
                self._save_trace(result, transcript)
            return result
        except Exception:
            if audit_log:
                audit_log.emit("pipeline_failed", {"elapsed_seconds": perf_counter() - started})
                audit_log.finish(elapsed_seconds=perf_counter() - started)
            raise

    def _create_audit(self, sample_id: str) -> FlowAuditLog | None:
        run_settings = self.config.get("run", {})
        level = run_settings.get("audit_level")
        if level is None:
            level = "debug" if run_settings.get("audit_enabled", False) else "off"
        if level == "off":
            return None
        console = run_settings.get("audit_console", "off")
        if isinstance(console, bool):
            console = "flow" if console else "off"
        directory = run_settings.get("audit_dir")
        if directory is None and run_settings.get("audit_file"):
            legacy_path = configured_path(self.config, run_settings["audit_file"])
            directory = str(legacy_path.parent / "audit")
            warnings.warn(
                "run.audit_file is deprecated; use run.audit_dir for per-sample flow/debug files",
                FutureWarning,
                stacklevel=2,
            )
        return FlowAuditLog(
            configured_path(self.config, directory or "outputs/audit"),
            sample_id,
            level=level,
            console=console,
        )

    def _save_trace(self, result: AgentResult, transcript: Transcript) -> None:
        output_dir = Path(self.config["_project_root"]) / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "traces.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "id": result.id,
                        "status": result.status,
                        "tool_names": [call.name for call in result.tool_calls],
                        "trace": _redact(result.trace),
                        "asr_character_count": len(transcript.text),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    @staticmethod
    def _result(
        sample_id: str,
        status: str,
        environment: Environment,
        *,
        trace: list[dict[str, Any]],
    ) -> AgentResult:
        return AgentResult(
            id=sample_id,
            status=status,
            tool_calls=[ToolCall.model_validate(call) for call in environment.get_tool_calls()],
            state_hash=environment.get_state_hash(),
            trace=trace,
        )

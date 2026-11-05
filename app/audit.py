"""V2 flow audit with safe debug metadata and opt-in full local details."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.contracts import AgentResult

_SAFE_FIELDS = {
    "task_id",
    "tool_name",
    "status",
    "code",
    "reason",
    "candidate_count",
    "candidate_names",
    "goal_count",
    "task_count",
    "fields",
    "effect_status",
    "elapsed_seconds",
    "tool_call_count",
    "qwen_calls",
    "character_count",
    "steps",
    "guard",
    "plan_version",
    "base_plan_version",
    "planner_call_index",
    "call_index",
    "issue_ids",
    "field",
    "kind",
    "added_task_count",
    "updated_task_count",
    "sources",
}


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in details.items() if key in _SAFE_FIELDS}


def _flow_entries(event: str, details: dict[str, Any]) -> list[str]:
    task_id = details.get("task_id") or "?"
    if event == "asr_completed":
        return [f"ASR   chars={details.get('character_count', 0)}"]
    if event == "transcript_reference_loaded":
        return ["ASR   source=train_reference"]
    if event == "discovery_completed":
        return [f"DISCOVER candidates={details.get('candidate_count', 0)}"]
    if event == "plan_created":
        return [
            f"PLAN  created version={details.get('plan_version', 0)} "
            f"tasks={details.get('task_count', 0)}"
        ]
    if event == "plan_accepted":
        return [
            f"GOAL  goals={details.get('goal_count', 0)}",
            f"PLAN  tasks={details.get('task_count', 0)}",
        ]
    if event == "plan_rejected":
        return ["BLOCK plan reason=PLAN_INVALID"]
    if event == "arguments_resolved":
        fields = ",".join(details.get("fields", [])) or "-"
        return [f"BIND  {task_id} fields={fields} status={details.get('status', 'UNKNOWN')}"]
    if event == "arguments_grounded":
        return [f"GROUND {task_id} sources={len(details.get('sources', {}))}"]
    if event == "task_blocked":
        return [f"BLOCK {task_id} issues={len(details.get('issue_ids', []))}"]
    if event == "information_need_created":
        return [f"NEED  {task_id} {details.get('field', '?')} kind={details.get('kind', '?')}"]
    if event == "recovery_retrieval_completed":
        return [f"RECOVER {task_id} candidates={details.get('candidate_count', 0)}"]
    if event in {"repair_requested", "repair_generated"}:
        return [
            f"REPAIR {task_id} call={details.get('call_index', '?')} "
            f"status={details.get('status', 'RUNNING')}"
        ]
    if event in {"patch_accepted", "patch_rejected"}:
        return [f"PATCH {task_id} {event.removeprefix('patch_').upper()}"]
    if event == "explore_task_added":
        return [f"EXPLORE {task_id} {details.get('tool_name', '?')} PENDING"]
    if event == "task_skipped":
        if details.get("reason") == "dependency_skipped":
            return [f"BRANCH {task_id} dependency=SKIPPED -> skip"]
        return [f"BRANCH {task_id} guard=FALSE -> skip"]
    if event in {"tool_started", "tool_completed", "lookup_started", "lookup_completed"}:
        tool = details.get("tool_name") or "?"
        status = details.get("status", "UNKNOWN")
        kind = "LOOKUP" if event.startswith("lookup_") else "TOOL"
        return [f"{kind} {task_id} {tool} {status}"]
    if event == "issue":
        return [f"BLOCK {task_id} reason={details.get('status', details.get('code', 'issue'))}"]
    if event == "user_information_requested":
        return [f"ASK   {task_id} sys.ask_missing_info NEEDS_USER"]
    if event == "pipeline_completed":
        return [
            f"RUN   status={details.get('status', 'UNKNOWN')} "
            f"qwen={details.get('qwen_calls', 0)} tools={details.get('tool_call_count', 0)}"
        ]
    return []


def _sample_filename(sample_id: str) -> str:
    encoded = quote(sample_id, safe="._-")
    if encoded in {"", ".", ".."}:
        return f"_{quote(sample_id, safe='')}"
    return encoded


class FlowAuditLog:
    def __init__(
        self,
        directory: str | Path,
        sample_id: str,
        *,
        level: str = "flow",
        console: str = "summary",
    ):
        if level not in {"flow", "debug", "full"}:
            raise ValueError(f"Unknown audit level: {level!r}")
        if console not in {"off", "summary", "flow"}:
            raise ValueError(f"Unknown audit console mode: {console!r}")
        self.directory = Path(directory)
        self.sample_id = sample_id
        self.level = level
        self.console = console
        self.lines: list[str] = []
        self.sequence = 0
        self.event_sequence = 0
        self.filename = _sample_filename(sample_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.debug_path = self.directory / f"{self.filename}.events.jsonl"
        if level in {"debug", "full"}:
            self.debug_path.write_text("", encoding="utf-8")

    def emit(self, event: str, details: dict[str, Any]) -> None:
        self.event_sequence += 1
        for line in _flow_entries(event, details):
            self.sequence += 1
            self.lines.append(f"{self.sequence:02d} {line}")
        if self.level in {"debug", "full"}:
            record = {
                "sample_id": self.sample_id,
                "sequence": self.event_sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "details": details if self.level == "full" else _safe_details(details),
            }
            with self.debug_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def finish(self, result: AgentResult | None = None, *, elapsed_seconds: float | None = None) -> None:
        status = result.status if result is not None else "FAILED"
        tool_count = len(result.tool_calls) if result is not None else 0
        duration = f" | {elapsed_seconds:.2f}s" if elapsed_seconds is not None else ""
        summary = f"{self.sample_id} {status} tools={tool_count}{duration}"
        flow = "\n".join(
            [f"LifeMate | {self.sample_id} | FLOW", *self.lines, f"END   {status} | tool_calls={tool_count}"]
        )
        (self.directory / f"{self.filename}.flow.txt").write_text(flow + "\n", encoding="utf-8")
        if self.console == "summary":
            print(summary, file=sys.stderr, flush=True)
        elif self.console == "flow":
            print(flow, file=sys.stderr, flush=True)


def print_sample_summary(sample_id: str, result: AgentResult, elapsed_seconds: float) -> None:
    print(
        f"{sample_id} {result.status} tools={len(result.tool_calls)} {elapsed_seconds:.2f}s",
        file=sys.stderr,
        flush=True,
    )


def print_dataset_summary(results: list[AgentResult]) -> None:
    satisfied = sum(result.status == "SATISFIED" for result in results)
    waiting = sum(result.status == "NEEDS_USER" for result in results)
    blocked = sum(result.status == "BLOCKED" for result in results)
    unsupported = sum(result.status == "UNSUPPORTED" for result in results)
    failed = sum(result.status in {"FAILED", "PLAN_INVALID"} for result in results)
    partial = sum(result.status == "PARTIAL" for result in results)
    tool_calls = sum(len(result.tool_calls) for result in results)
    print(
        f"TOTAL {len(results)} | success={satisfied} needs_user={waiting} blocked={blocked} "
        f"partial={partial} unsupported={unsupported} failed={failed} | tool_calls={tool_calls}",
        file=sys.stderr,
        flush=True,
    )

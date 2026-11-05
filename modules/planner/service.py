"""One-call Qwen planner and a lightweight deterministic mock implementation."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.contracts import (
    AgentRequest,
    PlanGoal,
    PlanPatch,
    PlanTask,
    PlanTaskUpdate,
    TaskPlan,
    ToolCandidate,
    ToolSpec,
)

_PROMPT_PATH = Path(__file__).with_name("prompts") / "plan.txt"
_REPAIR_PROMPT_PATH = Path(__file__).with_name("prompts") / "repair.txt"


class PlanInvalidError(ValueError):
    """The single planner response could not be parsed or violated V2 plan rules."""


class SingleShotPlanner:
    def __init__(self, llm: Any, *, max_new_tokens: int = 900, repair_max_new_tokens: int = 700):
        self.llm = llm
        self.settings = {"max_new_tokens": max_new_tokens, "max_json_repair": 0}
        self.repair_settings = {"max_new_tokens": repair_max_new_tokens, "max_json_repair": 0}
        self.call_count = 0
        self.repair_call_count = 0

    def generate_plan(self, request: AgentRequest, candidates: list[ToolSpec]) -> TaskPlan:
        self.call_count += 1
        try:
            response = self.llm.generate_json(
                "plan",
                {
                    "instructions": _PROMPT_PATH.read_text(encoding="utf-8"),
                    "request": request.model_dump(mode="json"),
                    "candidates": [tool.model_dump(mode="json") for tool in candidates],
                },
                TaskPlan,
                self.settings,
            )
        except (ValidationError, ValueError) as exc:
            raise PlanInvalidError(str(exc)) from exc
        allowed = {tool.name for tool in candidates}
        unknown = {task.tool for task in response.tasks} - allowed
        if unknown:
            raise PlanInvalidError(f"plan uses tools outside the candidate set: {sorted(unknown)}")
        return response

    def repair_plan(
        self,
        request: AgentRequest,
        state_snapshot: dict[str, Any],
        issues: list[dict[str, Any]],
        candidates: list[ToolCandidate],
        *,
        base_plan_version: int,
    ) -> PlanPatch:
        self.call_count += 1
        self.repair_call_count += 1
        try:
            response = self.llm.generate_json(
                "repair_plan",
                {
                    "instructions": _REPAIR_PROMPT_PATH.read_text(encoding="utf-8"),
                    "request": request.model_dump(mode="json"),
                    "state": state_snapshot,
                    "issues": issues,
                    "recovery_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                    "base_plan_version": base_plan_version,
                },
                PlanPatch,
                self.repair_settings,
            )
        except (ValidationError, ValueError) as exc:
            raise PlanInvalidError(str(exc)) from exc
        allowed = {candidate.tool.name for candidate in candidates}
        unknown = {task.tool for task in response.add_tasks} - allowed
        if unknown:
            raise PlanInvalidError(f"repair uses tools outside the recovery candidate set: {sorted(unknown)}")
        return response


class MockPlanner:
    """Deterministic mock; intentionally supports only simple smoke-test requests."""

    def generate_plan(self, request: AgentRequest, candidates: list[ToolSpec]) -> TaskPlan:
        text = request.transcript.casefold()
        available = {tool.name for tool in candidates}
        if not text.strip():
            return TaskPlan()
        if any(phrase in text for phrase in ("không cần làm gì", "thôi không", "cứ để nguyên")):
            return TaskPlan(goals=[PlanGoal(id="g1", description="No action requested", no_op=True)])
        if ("mưa" in text or "thời tiết" in text) and "weather.get_forecast" in available:
            current_time = request.context.get("current_time")
            date = None
            if isinstance(current_time, str):
                try:
                    tomorrow = datetime.fromisoformat(current_time.replace("Z", "+00:00")) + timedelta(days=1)
                    date = tomorrow.date().isoformat()
                except ValueError:
                    date = None
            return TaskPlan(
                goals=[PlanGoal(id="g1", description="Check tomorrow's weather")],
                tasks=[
                    PlanTask(
                        id="t1",
                        goal_id="g1",
                        tool="weather.get_forecast",
                        arguments={
                            "date": {
                                "$time": {
                                    "base": "context.current_time",
                                    "relative_day": 1,
                                    "period": None,
                                    "exact_time": None,
                                }
                            }
                            if date is not None
                            else {"date": None}
                        },
                    )
                ],
            )
        if "nhắn" in text and "sms.send" in available:
            content = ""
            if " là " in f" {request.transcript.strip()} ":
                content = request.transcript.split("là", 1)[1].strip().rstrip(".")
            return TaskPlan(
                goals=[PlanGoal(id="g1", description="Send the requested message")],
                tasks=[
                    PlanTask(
                        id="t1",
                        goal_id="g1",
                        tool="sms.send",
                        arguments={"content": content},
                    )
                ],
            )
        return TaskPlan()

    def repair_plan(
        self,
        request: AgentRequest,
        state_snapshot: dict[str, Any],
        issues: list[dict[str, Any]],
        candidates: list[ToolCandidate],
        *,
        base_plan_version: int,
    ) -> PlanPatch:
        candidate_by_name = {candidate.tool.name: candidate for candidate in candidates}
        for issue in issues:
            need = issue.get("information_need") or {}
            if need.get("kind") != "ENTITY" or "contacts.search" not in candidate_by_name:
                continue
            task_id = str(need.get("task_id", issue.get("task_id", "")))
            task = next((item for item in state_snapshot.get("tasks", []) if item.get("id") == task_id), None)
            if task is None:
                break
            query = need.get("constraints", {}).get("query")
            if not isinstance(query, str) or not query:
                break
            recovery_id = f"{task_id}__recovery_1"
            arguments = dict(task.get("arguments", {}))
            arguments["contact_id"] = {
                "$ref": {
                    "task_id": recovery_id,
                    "path": ["contacts"],
                    "match": {"name": query},
                    "field": "id",
                    "require_unique": True,
                }
            }
            dependencies = list(task.get("depends_on", []))
            dependencies.append(recovery_id)
            return PlanPatch(
                action="patch",
                base_plan_version=base_plan_version,
                addressed_issue_ids=[need.get("issue_id", "")],
                add_tasks=[
                    PlanTask(
                        id=recovery_id,
                        goal_id=task["goal_id"],
                        tool="contacts.search",
                        arguments={"query": query},
                    )
                ],
                updates=[
                    PlanTaskUpdate(
                        task_id=task_id,
                        arguments=arguments,
                        depends_on=tuple(dependencies),
                    )
                ],
                rationale="resolve the recipient through an allowed read-only contact lookup",
            )
        return PlanPatch(
            action="ask_user",
            base_plan_version=base_plan_version,
            addressed_issue_ids=[
                issue.get("issue_id", "")
                for issue in issues
                if isinstance(issue.get("issue_id"), str)
            ],
            message="Additional information is required to continue safely.",
        )

"""One-call Qwen planner and a lightweight deterministic mock implementation."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.contracts import AgentRequest, PlanGoal, PlanTask, TaskPlan, ToolSpec

_PROMPT_PATH = Path(__file__).with_name("prompts") / "plan.txt"


class PlanInvalidError(ValueError):
    """The single planner response could not be parsed or violated V2 plan rules."""


class SingleShotPlanner:
    def __init__(self, llm: Any, *, max_new_tokens: int = 900):
        self.llm = llm
        self.settings = {"max_new_tokens": max_new_tokens, "max_json_repair": 0}
        self.call_count = 0

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
                        arguments={"date": date},
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

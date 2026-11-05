"""Dependency and three-valued condition helpers."""

from __future__ import annotations

from typing import Any

from core.contracts import PlanCondition, PlanTask


def condition_value(condition: PlanCondition, observations: dict[str, Any]) -> bool | None:
    if condition.task_id not in observations:
        return None
    value: Any = observations[condition.task_id]
    for token in condition.path:
        if isinstance(token, int) and isinstance(value, list) and 0 <= token < len(value):
            value = value[token]
        elif isinstance(token, str) and isinstance(value, dict) and token in value:
            value = value[token]
        else:
            return None
    if value is None:
        return None
    return value == condition.equals


def ready_tasks(
    tasks: list[PlanTask],
    task_states: dict[str, str],
) -> list[PlanTask]:
    terminal = {"DONE", "SKIPPED"}
    return [
        task
        for task in tasks
        if task_states[task.id] == "PENDING"
        and all(task_states[dependency] in terminal for dependency in task.depends_on)
    ]

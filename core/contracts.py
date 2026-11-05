"""Versioned contracts shared by the five V2 modules and app adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core import SCHEMA_VERSION


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RuntimeContext(ContractModel):
    current_time: str | None = None
    timezone: str | None = None
    location: dict[str, float] | None = None
    user_profile: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    installed_apps: dict[str, dict[str, Any]] = Field(default_factory=dict)


class InputEnvelope(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str
    audio_path: str
    context: RuntimeContext


class Transcript(ContractModel):
    text: str
    language: str = "vi"
    confidence: float | None = None


class AgentRequest(ContractModel):
    sample_id: str
    transcript: str
    context: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class ToolSpec(ContractModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    resolver_hints: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["read", "write", "meta"] | None = None
    app: str | None = None


class ToolCall(ContractModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class FrozenDict(dict):
    def __init__(self, value: dict[str, Any] | None = None):
        dict.__init__(self, value or {})

    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("validated task plan data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze_plan_value(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({key: _freeze_plan_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_plan_value(item) for item in value)
    return value


class PlanGoal(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    id: str
    description: str
    no_op: bool = False


class ArgumentReference(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    task_id: str
    path: tuple[str | int, ...]
    match: dict[str, Any] | None = None
    field: str
    require_unique: bool = True

    @field_validator("match", mode="after")
    @classmethod
    def freeze_match(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _freeze_plan_value(value) if value is not None else None


class PlanCondition(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    task_id: str
    path: tuple[str | int, ...]
    equals: Any


class PlanTask(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    id: str
    goal_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    when: PlanCondition | None = None

    @field_validator("arguments", mode="after")
    @classmethod
    def freeze_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _freeze_plan_value(value)


class TaskPlan(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["2.0"] = SCHEMA_VERSION
    goals: tuple[PlanGoal, ...] = ()
    tasks: tuple[PlanTask, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> TaskPlan:
        goal_ids = {goal.id for goal in self.goals}
        task_ids = {task.id for task in self.tasks}
        if len(goal_ids) != len(self.goals) or len(task_ids) != len(self.tasks):
            raise ValueError("goal and task IDs must be unique")
        by_id = {task.id: task for task in self.tasks}
        goal_task_counts = {goal_id: 0 for goal_id in goal_ids}
        for task in self.tasks:
            if task.goal_id not in goal_ids:
                raise ValueError(f"unknown goal_id {task.goal_id!r}")
            goal_task_counts[task.goal_id] += 1
            missing = set(task.depends_on) - task_ids
            if missing:
                raise ValueError(f"task {task.id!r} has unknown dependencies: {sorted(missing)}")
            if task.id in task.depends_on:
                raise ValueError(f"task {task.id!r} cannot depend on itself")
        for goal in self.goals:
            count = goal_task_counts[goal.id]
            if goal.no_op and count:
                raise ValueError(f"no-op goal {goal.id!r} cannot contain tasks")
            if not goal.no_op and not count:
                raise ValueError(f"goal {goal.id!r} must contain at least one task or be an explicit no-op")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task dependencies contain a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in by_id[task_id].depends_on:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_ids:
            visit(task_id)

        def ancestors(task_id: str) -> set[str]:
            found: set[str] = set()
            pending = list(by_id[task_id].depends_on)
            while pending:
                dependency = pending.pop()
                if dependency not in found:
                    found.add(dependency)
                    pending.extend(by_id[dependency].depends_on)
            return found

        for task in self.tasks:
            allowed_sources = ancestors(task.id)
            if task.when is not None and task.when.task_id not in allowed_sources:
                raise ValueError(f"condition source must be a dependency of task {task.id!r}")
            for reference in _plan_references(task.arguments):
                if reference.task_id not in allowed_sources:
                    raise ValueError(f"reference source must be a dependency of task {task.id!r}")
        return self


def _plan_references(value: Any) -> list[ArgumentReference]:
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise ValueError("a $ref argument must contain only the $ref key")
            return [ArgumentReference.model_validate(value["$ref"])]
        return [reference for item in value.values() for reference in _plan_references(item)]
    if isinstance(value, (list, tuple)):
        return [reference for item in value for reference in _plan_references(item)]
    return []


class ResolutionResult(ContractModel):
    status: Literal[
        "READY",
        "MISSING",
        "AMBIGUOUS",
        "NOT_FOUND",
        "INVALID",
        "STALE",
        "NEEDS_EXPLORE",
        "NEEDS_USER",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)
    field: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    suggested_arguments: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class ToolResult(ContractModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    effect_status: Literal["CONFIRMED", "NOT_APPLIED", "UNKNOWN"] = "UNKNOWN"


class AuditEvent(ContractModel):
    sequence: int
    event: str
    task_id: str | None = None
    tool: str | None = None
    status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunResult(ContractModel):
    execution_status: Literal["SATISFIED", "NEEDS_USER", "UNSUPPORTED", "BLOCKED", "FAILED", "PLAN_INVALID"]
    task_states: dict[str, str] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    state_hash: str = ""


class RuntimeSample(ContractModel):
    """Inference-safe sample, deliberately excluding labels and reference transcripts."""

    id: str
    audio: str
    context: RuntimeContext
    history: list[dict[str, Any]] = Field(default_factory=list)


class AgentResult(ContractModel):
    id: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    state_hash: str
    status: str
    trace: list[dict[str, Any]] = Field(default_factory=list)


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO datetime and surface malformed context rather than guessing."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

"""Stable protocols for the five module ownership boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from core.contracts import (
    AgentRequest,
    InformationNeed,
    PlanPatch,
    PlanTask,
    ResolutionResult,
    RunResult,
    TaskPlan,
    ToolCandidate,
    ToolSpec,
    Transcript,
)

T = TypeVar("T", bound=BaseModel)


class ASR(Protocol):
    def transcribe(self, audio_path: str | Path) -> Transcript: ...


class Discovery(Protocol):
    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]: ...
    def retrieve_for_need(
        self,
        need: InformationNeed,
        catalog: list[ToolSpec],
        history: list[str] | None = None,
    ) -> list[ToolCandidate]: ...


class Planner(Protocol):
    def generate_plan(self, request: AgentRequest, candidates: list[ToolSpec]) -> TaskPlan: ...
    def repair_plan(
        self,
        request: AgentRequest,
        state_snapshot: dict[str, Any],
        issues: list[dict[str, Any]],
        candidates: list[ToolCandidate],
        *,
        base_plan_version: int,
    ) -> PlanPatch: ...


class Resolver(Protocol):
    def resolve(
        self,
        task: PlanTask,
        observations: dict[str, Any],
        tool_spec: ToolSpec,
        *,
        context: dict[str, Any] | None = None,
        transcript: str = "",
    ) -> ResolutionResult: ...


class Environment(Protocol):
    def list_available_tools(self) -> list[ToolSpec]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_tool_calls(self) -> list[dict[str, Any]]: ...
    def get_state_hash(self) -> str: ...


class Runtime(Protocol):
    def execute_plan(
        self,
        plan: TaskPlan,
        resolver: Resolver,
        environment: Environment,
        *,
        request: AgentRequest | None = None,
        discovery: Discovery | None = None,
        planner: Planner | None = None,
        adaptive: bool = False,
        max_repair_calls: int = 0,
    ) -> RunResult: ...


class LLMClient(Protocol):
    def generate_json(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        response_model: type[T],
        settings: dict[str, Any] | None = None,
    ) -> T: ...

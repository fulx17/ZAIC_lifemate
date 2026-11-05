"""Stable protocols for the five module ownership boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from core.contracts import (
    AgentRequest,
    PlanTask,
    ResolutionResult,
    RunResult,
    TaskPlan,
    ToolSpec,
    Transcript,
)

T = TypeVar("T", bound=BaseModel)


class ASR(Protocol):
    def transcribe(self, audio_path: str | Path) -> Transcript: ...


class Discovery(Protocol):
    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]: ...


class Planner(Protocol):
    def generate_plan(self, request: AgentRequest, candidates: list[ToolSpec]) -> TaskPlan: ...


class Resolver(Protocol):
    def resolve(
        self, task: PlanTask, observations: dict[str, Any], tool_spec: ToolSpec
    ) -> ResolutionResult: ...


class Environment(Protocol):
    def list_available_tools(self) -> list[ToolSpec]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_tool_calls(self) -> list[dict[str, Any]]: ...
    def get_state_hash(self) -> str: ...


class Runtime(Protocol):
    def execute_plan(self, plan: TaskPlan, resolver: Resolver, environment: Environment) -> RunResult: ...


class LLMClient(Protocol):
    def generate_json(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        response_model: type[T],
        settings: dict[str, Any] | None = None,
    ) -> T: ...

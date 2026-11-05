"""Structured errors shared across pipeline modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PipelineError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ContractError(PipelineError):
    """Invalid or inconsistent shared contract data."""


class ModelUnavailableError(PipelineError):
    """A configured local model cannot be loaded without violating offline policy."""


class BudgetExceededError(PipelineError):
    """A per-request compute or model-call budget has been exhausted."""


class GraphInvariantError(PipelineError):
    """A proposed task graph or patch violates graph invariants."""

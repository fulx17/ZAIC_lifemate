"""Mutable state owned exclusively by the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.contracts import AuditEvent


@dataclass
class ExecutionState:
    task_states: dict[str, str]
    observations: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)

    def emit(
        self,
        event: str,
        *,
        task_id: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.audit_events.append(
            AuditEvent(
                sequence=len(self.audit_events) + 1,
                event=event,
                task_id=task_id,
                tool=tool,
                status=status,
                details=details or {},
            )
        )

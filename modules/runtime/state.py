"""Mutable state owned exclusively by the runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.contracts import AuditEvent


@dataclass
class ExecutionState:
    task_states: dict[str, str]
    plan_version: int = 0
    observations: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    repair_attempts: int = 0
    issue_attempt_counts: dict[str, int] = field(default_factory=dict)
    tried_explorations: set[str] = field(default_factory=set)
    exploration_fingerprints: set[str] = field(default_factory=set)
    event_sink: Callable[[AuditEvent], None] | None = None

    def emit(
        self,
        event: str,
        *,
        task_id: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        audit_event = AuditEvent(
            sequence=len(self.audit_events) + 1,
            event=event,
            task_id=task_id,
            tool=tool,
            status=status,
            details=details or {},
        )
        self.audit_events.append(audit_event)
        if self.event_sink is not None:
            self.event_sink(audit_event)

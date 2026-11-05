"""Bounded runtime orchestration with issue-triggered recovery and patch validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from time import monotonic
from typing import Any

from pydantic import ValidationError

from core.contracts import (
    AgentRequest,
    AuditEvent,
    InformationNeed,
    PlanPatch,
    PlanTask,
    RunResult,
    TaskPlan,
    ToolCandidate,
    ToolSpec,
)
from core.errors import BudgetExceededError
from core.interfaces import Discovery, Environment, Planner, Resolver
from modules.runtime.scheduler import condition_value, ready_tasks
from modules.runtime.state import ExecutionState
from modules.runtime.verifier import verify_tool_result

_SENSITIVE_OBSERVATION_KEYS = re.compile(
    r"(message|content|body|phone|account|token|password|email|secret)",
    re.IGNORECASE,
)


class RuntimeService:
    def __init__(
        self,
        *,
        max_steps: int = 12,
        timeout_seconds: float = 120,
        max_explore_tasks: int = 3,
        per_issue_attempts: int = 1,
    ):
        if max_steps < 1 or timeout_seconds <= 0 or max_explore_tasks < 0 or per_issue_attempts < 1:
            raise ValueError("runtime limits must be positive")
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.max_explore_tasks = max_explore_tasks
        self.per_issue_attempts = per_issue_attempts

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
        detailed_audit: Callable[[str, dict[str, Any]], None] | None = None,
        event_sink: Callable[[AuditEvent], None] | None = None,
    ) -> RunResult:
        catalog = {tool.name: tool for tool in environment.list_available_tools()}
        tasks = list(plan.tasks)
        state = ExecutionState(
            task_states={task.id: "PENDING" for task in tasks},
            event_sink=event_sink,
        )
        state.emit(
            "plan_accepted",
            status="READY",
            details={"goal_count": len(plan.goals), "task_count": len(tasks), "plan_version": state.plan_version},
        )
        if not plan.goals:
            state.emit("execution_stopped", status="UNSUPPORTED", details={"reason": "no_goal"})
            return self._result("UNSUPPORTED", state, environment)
        if not tasks:
            if all(goal.no_op for goal in plan.goals):
                state.emit("execution_stopped", status="SATISFIED", details={"reason": "explicit_no_op"})
                return self._result("SATISFIED", state, environment)
            self._issue(state, None, "NEEDS_USER", "plan has goals but no executable tasks")
            return self._result("NEEDS_USER", state, environment)
        if len(tasks) > self.max_steps:
            self._issue(state, None, "RUNTIME_BUDGET", "plan exceeds the task execution budget")
            state.emit("execution_stopped", status="BLOCKED", details={"reason": "runtime_budget"})
            return self._result("BLOCKED", state, environment)

        started = monotonic()
        initial_call_count = len(environment.get_tool_calls())
        recovery_task_ids: set[str] = set()
        request_context = request.context if request else {}
        transcript = request.transcript if request else ""

        while any(status == "PENDING" for status in state.task_states.values()):
            tool_calls = len(environment.get_tool_calls()) - initial_call_count
            if tool_calls >= self.max_steps or monotonic() - started >= self.timeout_seconds:
                self._mark_stalled(tasks, state, code="RUNTIME_BUDGET", message="execution budget exhausted")
                state.emit("execution_stopped", status="BLOCKED", details={"reason": "runtime_budget"})
                break

            ready = ready_tasks(tasks, state.task_states)
            if not ready:
                self._mark_stalled(tasks, state)
                break

            task = ready[0]
            if any(state.task_states.get(dependency) == "SKIPPED" for dependency in task.depends_on):
                state.task_states[task.id] = "SKIPPED"
                state.emit(
                    "task_skipped",
                    task_id=task.id,
                    status="SKIPPED",
                    details={"reason": "dependency_skipped"},
                )
                continue
            if task.when is not None:
                branch = condition_value(task.when, state.observations)
                if branch is False:
                    state.task_states[task.id] = "SKIPPED"
                    state.emit("task_skipped", task_id=task.id, status="SKIPPED", details={"guard": "FALSE"})
                    continue
                if branch is None:
                    issues = [
                        {
                            "task_id": task.id,
                            "issue_id": f"{task.id}:condition:unknown",
                            "code": "UNKNOWN_CONDITION",
                            "field": "condition",
                            "message": "condition could not be established",
                        }
                    ]
                    state.task_states[task.id] = "BLOCKED"
                    self._record_issues(state, task, issues)
                    self._ask_for_information(
                        environment,
                        catalog,
                        task,
                        "condition",
                        state,
                        initial_call_count=initial_call_count,
                        detailed_audit=detailed_audit,
                    )
                    continue

            task_spec = catalog.get(task.tool)
            if task_spec is None:
                state.task_states[task.id] = "BLOCKED"
                self._issue(state, task, "UNSUPPORTED_TOOL", "tool is not in this sample's allowed catalog")
                continue
            resolution = resolver.resolve(
                task,
                state.observations,
                task_spec,
                context=request_context,
                transcript=transcript,
            )
            state.emit(
                "arguments_resolved",
                task_id=task.id,
                tool=task.tool,
                status=resolution.status,
                details={"fields": sorted(resolution.arguments)},
            )
            if detailed_audit is not None:
                detailed_audit(
                    "argument_resolution_detail",
                    {
                        "task_id": task.id,
                        "tool_name": task.tool,
                        "resolution": resolution.model_dump(mode="json"),
                    },
                )
            if resolution.status != "READY":
                state.task_states[task.id] = "BLOCKED"
                issues = [issue.model_dump(mode="json") for issue in resolution.issues]
                if not issues:
                    issues = [
                        {
                            "task_id": task.id,
                            "issue_id": f"{task.id}:{resolution.field or 'arguments'}:{resolution.status.lower()}",
                            "code": resolution.status,
                            "field": resolution.field,
                            "message": resolution.message or resolution.status.lower(),
                        }
                    ]
                self._record_issues(state, task, issues)
                state.emit(
                    "task_blocked",
                    task_id=task.id,
                    status=resolution.status,
                    details={
                        "issue_ids": [issue.get("issue_id") for issue in issues],
                        "fields": [issue.get("field") for issue in issues],
                    },
                )
                for issue in issues:
                    need = issue.get("information_need")
                    if need:
                        state.emit(
                            "information_need_created",
                            task_id=task.id,
                            status=issue.get("code"),
                            details={
                                "issue_id": issue.get("issue_id"),
                                "field": issue.get("field"),
                                "kind": need.get("kind"),
                                "constraints": need.get("constraints", {}),
                            },
                        )
                repair_outcome: str | None = None
                if (
                    adaptive
                    and request is not None
                    and discovery is not None
                    and planner is not None
                    and state.repair_attempts < max_repair_calls
                ):
                    repair_outcome = self._repair(
                        task,
                        issues,
                        tasks,
                        plan,
                        state,
                        request,
                        catalog,
                        discovery,
                        planner,
                        recovery_task_ids,
                        detailed_audit=detailed_audit,
                    )
                if repair_outcome == "patched":
                    continue
                if repair_outcome == "ask_user" or (
                    repair_outcome is None
                    and resolution.status in {
                    "NEEDS_USER",
                    "MISSING",
                    "UNDERSPECIFIED",
                    "UNRESOLVED",
                    "AMBIGUOUS",
                    "NOT_FOUND",
                    "UNSUPPORTED",
                    }
                ):
                    self._ask_for_information(
                        environment,
                        catalog,
                        task,
                        [
                            issue.get("field")
                            for issue in issues
                            if isinstance(issue.get("field"), str)
                        ]
                        or [resolution.field or "required_argument"],
                        state,
                        initial_call_count=initial_call_count,
                        detailed_audit=detailed_audit,
                    )
                continue

            state.emit(
                "arguments_grounded",
                task_id=task.id,
                tool=task.tool,
                status="READY",
                details={"sources": resolution.provenance},
            )
            validation = environment.validate(task.tool, resolution.arguments)
            if not validation.get("ok"):
                state.task_states[task.id] = "BLOCKED"
                self._issue(
                    state,
                    task,
                    "INVALID_ARGUMENTS",
                    str(validation.get("error", "schema validation failed")),
                )
                continue

            state.task_states[task.id] = "RUNNING"
            state.emit(
                "tool_started",
                task_id=task.id,
                tool=task.tool,
                status="RUNNING",
                details={"fields": sorted(resolution.arguments)},
            )
            if detailed_audit is not None:
                detailed_audit(
                    "tool_call_detail",
                    {"task_id": task.id, "tool_name": task.tool, "arguments": resolution.arguments},
                )
            state_hash_before = environment.get_state_hash()
            try:
                raw_result = environment.call_tool(task.tool, resolution.arguments)
            except Exception as exc:
                if detailed_audit is not None:
                    detailed_audit(
                        "tool_exception_detail",
                        {
                            "task_id": task.id,
                            "tool_name": task.tool,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        },
                    )
                state.task_states[task.id] = "FAILED"
                state.observations[task.id] = {"error_type": type(exc).__name__}
                self._issue(
                    state,
                    task,
                    "UNCERTAIN_EFFECT",
                    f"environment call raised {type(exc).__name__}; it will not be retried",
                )
                state.emit(
                    "tool_uncertain",
                    task_id=task.id,
                    tool=task.tool,
                    status="UNCERTAIN",
                    details={"effect_status": "UNKNOWN"},
                )
                continue
            if detailed_audit is not None:
                detailed_audit(
                    "tool_result_detail",
                    {"task_id": task.id, "tool_name": task.tool, "raw_result": raw_result},
                )
            result = verify_tool_result(
                raw_result,
                is_write=task_spec.kind == "write",
                arguments=resolution.arguments,
                state_changed=environment.get_state_hash() != state_hash_before,
            )
            state.observations[task.id] = result.data
            if result.ok:
                state.task_states[task.id] = "DONE"
                state.emit(
                    "tool_completed",
                    task_id=task.id,
                    tool=task.tool,
                    status="DONE",
                    details={"effect_status": result.effect_status},
                )
                if task.id in recovery_task_ids:
                    state.emit(
                        "explore_tool_completed",
                        task_id=task.id,
                        tool=task.tool,
                        status="DONE",
                    )
            else:
                state.task_states[task.id] = "FAILED"
                self._issue(state, task, "TOOL_FAILED", result.error or "tool did not confirm success")
                state.emit(
                    "tool_completed",
                    task_id=task.id,
                    tool=task.tool,
                    status="FAILED",
                    details={"effect_status": result.effect_status},
                )

        status = self._final_status(state, recovery_task_ids)
        steps = len(environment.get_tool_calls()) - initial_call_count
        state.emit("execution_finished", status=status, details={"steps": steps, "plan_version": state.plan_version})
        return self._result(status, state, environment, state.plan_version, getattr(planner, "call_count", 0))

    def _repair(
        self,
        task: PlanTask,
        issues: list[dict[str, Any]],
        tasks: list[PlanTask],
        original_plan: TaskPlan,
        state: ExecutionState,
        request: AgentRequest,
        catalog: dict[str, ToolSpec],
        discovery: Discovery,
        planner: Planner,
        recovery_task_ids: set[str],
        *,
        detailed_audit: Callable[[str, dict[str, Any]], None] | None,
    ) -> str | None:
        unresolved = [
            issue
            for issue in issues
            if issue.get("information_need")
            and state.issue_attempt_counts.get(issue.get("issue_id", ""), 0) < self.per_issue_attempts
            and self._need_fingerprint(issue.get("issue_id", ""), state.observations)
            not in state.tried_explorations
        ]
        if not unresolved:
            return None
        needs = [
            InformationNeed.model_validate(issue["information_need"])
            for issue in unresolved
        ]
        state.repair_attempts += 1
        candidates_by_name: dict[str, ToolCandidate] = {}
        for need in needs:
            fingerprint = self._need_fingerprint(need.issue_id, state.observations)
            state.tried_explorations.add(fingerprint)
            state.issue_attempt_counts[need.issue_id] = state.issue_attempt_counts.get(need.issue_id, 0) + 1
            candidates = discovery.retrieve_for_need(need, list(catalog.values()), [])
            for candidate in candidates:
                current = candidates_by_name.get(candidate.tool.name)
                if current is None or candidate.score > current.score:
                    candidates_by_name[candidate.tool.name] = candidate
        candidates = sorted(candidates_by_name.values(), key=lambda item: (-item.score, item.rank, item.tool.name))
        state.emit(
            "recovery_retrieval_completed",
            task_id=task.id,
            status="READY" if candidates else "EMPTY",
            details={
                "issue_ids": [need.issue_id for need in needs],
                "candidate_count": len(candidates),
                "candidate_names": [candidate.tool.name for candidate in candidates],
                "candidates": [
                    {
                        "tool_name": candidate.tool.name,
                        "score": candidate.score,
                        "rationale": candidate.rationale,
                        "provider_evidence": candidate.provider_evidence,
                    }
                    for candidate in candidates
                ],
            },
        )
        snapshot = {
            "plan_version": state.plan_version,
            "goals": [goal.model_dump(mode="json") for goal in original_plan.goals],
            "tasks": [
                {
                    **item.model_dump(mode="json"),
                    "status": state.task_states.get(item.id, "PENDING"),
                }
                for item in tasks
            ],
            "observations": self._compact_observations(state.observations),
            "open_issues": state.issues,
            "repair_attempts": state.repair_attempts,
        }
        state.emit(
            "repair_requested",
            task_id=task.id,
            status="RUNNING",
            details={"call_index": state.repair_attempts, "plan_version": state.plan_version},
        )
        if detailed_audit is not None:
            detailed_audit(
                "repair_input_detail",
                {"task_id": task.id, "state": snapshot, "issues": issues},
            )
        try:
            patch = planner.repair_plan(
                request,
                snapshot,
                issues,
                candidates,
                base_plan_version=state.plan_version,
            )
        except (ValidationError, ValueError) as exc:
            state.emit(
                "patch_rejected",
                task_id=task.id,
                status="INVALID",
                details={"reason": str(exc), "plan_version": state.plan_version},
            )
            return None
        except BudgetExceededError:
            state.emit(
                "repair_skipped",
                task_id=task.id,
                status="BUDGET_EXHAUSTED",
                details={"plan_version": state.plan_version},
            )
            return None
        state.emit(
            "repair_generated",
            task_id=task.id,
            status=patch.action.upper(),
            details={
                "call_index": state.repair_attempts,
                "base_plan_version": patch.base_plan_version,
                "added_task_count": len(patch.add_tasks),
                "updated_task_count": len(patch.updates),
            },
        )
        if detailed_audit is not None:
            detailed_audit("repair_patch_detail", {"task_id": task.id, "patch": patch.model_dump(mode="json")})
        addressed = set(patch.addressed_issue_ids)
        active_issue_ids = {issue.get("issue_id") for issue in issues}
        if not addressed or not addressed <= active_issue_ids:
            state.emit(
                "patch_rejected",
                task_id=task.id,
                status="INVALID",
                details={"reason": "patch references issues outside the current repair request"},
            )
            return None
        if patch.action == "ask_user":
            state.emit(
                "repair_decision",
                task_id=task.id,
                status="ASK_USER",
                details={"message": patch.message},
            )
            return "ask_user"
        if patch.action == "stop":
            state.emit(
                "repair_decision",
                task_id=task.id,
                status="STOP",
                details={"message": patch.message},
            )
            return "stop"
        try:
            merged = self._apply_patch(
                patch,
                tasks,
                state,
                original_plan,
                catalog,
                max_explore_tasks=self.max_explore_tasks,
                existing_explore_count=len(recovery_task_ids),
            )
        except (ValueError, ValidationError) as exc:
            state.emit(
                "patch_rejected",
                task_id=task.id,
                status="INVALID",
                details={"reason": str(exc), "base_plan_version": patch.base_plan_version},
            )
            return None
        state.plan_version += 1
        tasks[:] = merged
        state.emit(
            "patch_accepted",
            task_id=task.id,
            status="READY",
            details={
                "base_plan_version": patch.base_plan_version,
                "plan_version": state.plan_version,
                "added_task_count": len(patch.add_tasks),
                "updated_task_count": len(patch.updates),
            },
        )
        for added in patch.add_tasks:
            state.task_states[added.id] = "PENDING"
            recovery_task_ids.add(added.id)
            state.exploration_fingerprints.add(self._task_fingerprint(added))
            state.emit(
                "explore_task_added",
                task_id=added.id,
                tool=added.tool,
                status="PENDING",
                details={"plan_version": state.plan_version},
            )
        for issue in unresolved:
            issue_id = issue.get("issue_id")
            state.issues = [item for item in state.issues if item.get("issue_id") != issue_id]
        for update in patch.updates:
            if state.task_states.get(update.task_id) == "BLOCKED":
                state.task_states[update.task_id] = "PENDING"
        return "patched"

    @staticmethod
    def _apply_patch(
        patch: PlanPatch,
        tasks: list[PlanTask],
        state: ExecutionState,
        original_plan: TaskPlan,
        catalog: dict[str, ToolSpec],
        *,
        max_explore_tasks: int,
        existing_explore_count: int,
    ) -> list[PlanTask]:
        if patch.base_plan_version != state.plan_version:
            raise ValueError("patch base_plan_version is stale")
        if existing_explore_count + len(patch.add_tasks) > max_explore_tasks:
            raise ValueError("patch exceeds max_explore_tasks")
        if not patch.add_tasks and not patch.updates:
            raise ValueError("patch makes no plan progress")
        existing = {task.id: task for task in tasks}
        if len({update.task_id for update in patch.updates}) != len(patch.updates):
            raise ValueError("patch updates a task more than once")
        target_task_ids = {
            issue.get("task_id")
            for issue in state.issues
            if issue.get("issue_id") in set(patch.addressed_issue_ids)
        }
        if not target_task_ids or not target_task_ids.intersection(update.task_id for update in patch.updates):
            raise ValueError("patch must update a task associated with an addressed issue")
        if any(update.task_id not in target_task_ids for update in patch.updates):
            raise ValueError("patch cannot update tasks outside the addressed issue")
        updated = dict(existing)
        for change in patch.updates:
            current = existing.get(change.task_id)
            if current is None:
                raise ValueError(f"patch updates unknown task {change.task_id!r}")
            if state.task_states.get(change.task_id) not in {"PENDING", "BLOCKED"}:
                raise ValueError(f"patch cannot modify task in {state.task_states.get(change.task_id)} state")
            fields: dict[str, Any] = {}
            if change.arguments is not None:
                fields["arguments"] = change.arguments
            if change.depends_on is not None:
                fields["depends_on"] = change.depends_on
            updated[change.task_id] = PlanTask.model_validate(
                {**current.model_dump(mode="json"), **fields}
            )
        for added in patch.add_tasks:
            if added.id in existing:
                raise ValueError(f"patch adds duplicate task id {added.id!r}")
            target_goal_ids = {existing[task_id].goal_id for task_id in target_task_ids}
            if added.goal_id not in target_goal_ids:
                raise ValueError("patch adds task outside the addressed goal")
            spec = catalog.get(added.tool)
            if spec is None:
                raise ValueError(f"patch uses tool outside this sample's allowed catalog: {added.tool}")
            if spec.kind != "read":
                raise ValueError(f"recovery task {added.id!r} must use a read-only tool")
            related_updates = [
                update
                for update in patch.updates
                if update.task_id in target_task_ids
                and update.depends_on is not None
                and added.id in update.depends_on
            ]
            if not related_updates:
                raise ValueError("recovery task must be a dependency of the blocked issue task")
            updated[added.id] = added
        merged = list(updated.values())
        TaskPlan(goals=original_plan.goals, tasks=merged)
        fingerprints = set(state.exploration_fingerprints)
        for added in patch.add_tasks:
            fingerprint = RuntimeService._task_fingerprint(added)
            if fingerprint in fingerprints:
                raise ValueError("patch contains duplicate recovery tasks")
            fingerprints.add(fingerprint)
        addressed = set(patch.addressed_issue_ids)
        if not addressed:
            raise ValueError("patch must identify the issues it addresses")
        known_issue_ids = {issue.get("issue_id") for issue in state.issues}
        if not addressed <= known_issue_ids:
            raise ValueError("patch references an unknown issue")
        return merged

    @staticmethod
    def _task_fingerprint(task: PlanTask) -> str:
        return json.dumps(
            {"tool": task.tool, "arguments": task.arguments},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _need_fingerprint(issue_id: str, observations: dict[str, Any]) -> str:
        payload = json.dumps(observations, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{issue_id}:{digest}"

    @staticmethod
    def _compact_observations(observations: dict[str, Any]) -> dict[str, Any]:
        def compact(value: Any, *, depth: int = 0, key: str = "") -> Any:
            if _SENSITIVE_OBSERVATION_KEYS.search(key):
                return "[REDACTED]"
            if depth >= 6:
                return "[TRUNCATED]"
            if isinstance(value, dict):
                return {
                    str(name): compact(item, depth=depth + 1, key=str(name))
                    for name, item in list(value.items())[:50]
                }
            if isinstance(value, (list, tuple)):
                return [compact(item, depth=depth + 1, key=key) for item in value[:10]]
            if isinstance(value, str) and len(value) > 500:
                return f"{value[:500]}[TRUNCATED]"
            return value

        return compact(observations)

    def _ask_for_information(
        self,
        environment: Environment,
        catalog: dict[str, ToolSpec],
        task: PlanTask,
        field: str | list[str],
        state: ExecutionState,
        *,
        initial_call_count: int,
        detailed_audit: Callable[[str, dict[str, Any]], None] | None,
    ) -> None:
        tool = catalog.get("sys.ask_missing_info")
        if tool is None or len(environment.get_tool_calls()) - initial_call_count >= self.max_steps:
            return
        fields = [field] if isinstance(field, str) else list(dict.fromkeys(field))
        arguments = {"tool_name": task.tool, "params": fields}
        if environment.validate(tool.name, arguments).get("ok"):
            raw_result = environment.call_tool(tool.name, arguments)
            if detailed_audit is not None:
                detailed_audit(
                    "missing_information_call_detail",
                    {
                        "task_id": task.id,
                        "tool_name": tool.name,
                        "arguments": arguments,
                        "raw_result": raw_result,
                    },
                )
            state.emit(
                "user_information_requested",
                task_id=task.id,
                tool=tool.name,
                status="NEEDS_USER",
                details={"fields": fields},
            )

    @staticmethod
    def _record_issues(state: ExecutionState, task: PlanTask, issues: list[dict[str, Any]]) -> None:
        for issue in issues:
            record = {
                "task_id": task.id,
                "issue_id": issue.get("issue_id", f"{task.id}:{issue.get('field', 'arguments')}"),
                "code": issue.get("code", "BLOCKED"),
                "field": issue.get("field"),
                "message": issue.get("why_not_ready") or issue.get("message", "task is blocked"),
            }
            state.issues.append(record)
            state.emit(
                "issue",
                task_id=task.id,
                status=record["code"],
                details={"field": record["field"], "issue_id": record["issue_id"]},
            )

    @staticmethod
    def _issue(
        state: ExecutionState,
        task: PlanTask | None,
        code: str,
        message: str,
    ) -> None:
        task_id = task.id if task else None
        issue_id = f"{task_id or 'run'}:{code.lower()}"
        state.issues.append(
            {"task_id": task_id, "issue_id": issue_id, "code": code, "message": message}
        )
        state.emit("issue", task_id=task_id, status=code, details={"code": code, "issue_id": issue_id})

    @staticmethod
    def _mark_stalled(
        tasks: list[PlanTask],
        state: ExecutionState,
        *,
        code: str = "DEPENDENCY_BLOCKED",
        message: str = "task dependencies did not complete",
    ) -> None:
        for task in tasks:
            if state.task_states.get(task.id) != "PENDING":
                continue
            state.task_states[task.id] = "BLOCKED"
            RuntimeService._issue(state, task, code, message)

    @staticmethod
    def _final_status(state: ExecutionState, recovery_task_ids: set[str]) -> str:
        completed_goal_task = any(
            value == "DONE" and task_id not in recovery_task_ids
            for task_id, value in state.task_states.items()
        )
        if any(value == "FAILED" for value in state.task_states.values()):
            return "FAILED"
        if state.issues:
            user_blocking = {
                "NEEDS_USER",
                "MISSING",
                "UNDERSPECIFIED",
                "UNRESOLVED",
                "AMBIGUOUS",
                "NOT_FOUND",
                "UNSUPPORTED",
                "UNKNOWN_CONDITION",
            }
            if any(issue["code"] in user_blocking for issue in state.issues):
                return "PARTIAL" if completed_goal_task else "NEEDS_USER"
            if any(issue["code"] == "UNSUPPORTED_TOOL" for issue in state.issues):
                return "UNSUPPORTED"
            return "PARTIAL" if completed_goal_task else "BLOCKED"
        if all(value in {"DONE", "SKIPPED"} for value in state.task_states.values()):
            return "SATISFIED"
        return "BLOCKED"

    @staticmethod
    def _result(
        status: str,
        state: ExecutionState,
        environment: Environment,
        plan_version: int = 0,
        qwen_calls: int = 0,
    ) -> RunResult:
        return RunResult(
            execution_status=status,
            task_states=state.task_states,
            issues=state.issues,
            audit_events=state.audit_events,
            tool_calls=environment.get_tool_calls(),
            state_hash=environment.get_state_hash(),
            plan_version=plan_version,
            qwen_calls=qwen_calls,
        )

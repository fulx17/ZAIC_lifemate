"""Single-plan execution loop; it never invokes a language model."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from core.contracts import (
    PlanTask,
    ResolutionResult,
    RunResult,
    TaskPlan,
    ToolSpec,
)
from core.interfaces import Environment, Resolver
from modules.runtime.scheduler import condition_value, ready_tasks
from modules.runtime.state import ExecutionState
from modules.runtime.verifier import verify_tool_result


class RuntimeService:
    def __init__(self, *, max_steps: int = 12, timeout_seconds: float = 120):
        if max_steps < 1 or timeout_seconds <= 0:
            raise ValueError("runtime limits must be positive")
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def execute_plan(
        self,
        plan: TaskPlan,
        resolver: Resolver,
        environment: Environment,
        *,
        detailed_audit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        catalog = {tool.name: tool for tool in environment.list_available_tools()}
        state = ExecutionState(task_states={task.id: "PENDING" for task in plan.tasks})
        state.emit(
            "plan_accepted",
            status="READY",
            details={"goal_count": len(plan.goals), "task_count": len(plan.tasks)},
        )
        if not plan.goals:
            state.emit("execution_stopped", status="UNSUPPORTED", details={"reason": "no_goal"})
            return self._result("UNSUPPORTED", state, environment)
        if not plan.tasks:
            if all(goal.no_op for goal in plan.goals):
                state.emit("execution_stopped", status="SATISFIED", details={"reason": "explicit_no_op"})
                return self._result("SATISFIED", state, environment)
            issue = {"code": "NEEDS_USER", "message": "plan has goals but no executable tasks"}
            state.issues.append(issue)
            state.emit("issue", status="NEEDS_USER", details={"code": issue["code"]})
            return self._result("NEEDS_USER", state, environment)
        if len(plan.tasks) > self.max_steps:
            issue = {"code": "RUNTIME_BUDGET", "message": "plan exceeds the task execution budget"}
            state.issues.append(issue)
            state.emit("execution_stopped", status="BLOCKED", details={"reason": "runtime_budget"})
            return self._result("BLOCKED", state, environment)

        started = monotonic()
        initial_call_count = len(environment.get_tool_calls())
        while any(status == "PENDING" for status in state.task_states.values()):
            steps = len(environment.get_tool_calls()) - initial_call_count
            if steps >= self.max_steps or monotonic() - started >= self.timeout_seconds:
                state.issues.append({"code": "RUNTIME_BUDGET", "message": "execution budget exhausted"})
                self._mark_stalled(
                    plan,
                    state,
                    code="RUNTIME_BUDGET",
                    message="execution budget exhausted",
                )
                state.emit("execution_stopped", status="BLOCKED", details={"reason": "runtime_budget"})
                break

            ready = ready_tasks(plan.tasks, state.task_states)
            if not ready:
                self._mark_stalled(plan, state)
                break

            task = ready[0]
            if any(state.task_states[dependency] == "SKIPPED" for dependency in task.depends_on):
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
                    state.task_states[task.id] = "BLOCKED"
                    self._issue(state, task, "UNKNOWN_CONDITION", "condition could not be established")
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
            resolution = resolver.resolve(task, state.observations, task_spec)
            state.emit(
                "arguments_resolved",
                task_id=task.id,
                tool=task.tool,
                status=resolution.status,
                details={"fields": sorted(resolution.arguments)},
            )
            if resolution.status == "NEEDS_EXPLORE":
                resolution = self._explore(
                    task,
                    resolution,
                    resolver,
                    task_spec,
                    catalog,
                    environment,
                    state,
                    initial_call_count=initial_call_count,
                    detailed_audit=detailed_audit,
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
                status = resolution.status
                self._issue(state, task, status, resolution.message or status.lower(), field=resolution.field)
                if status in {"NEEDS_USER", "MISSING", "AMBIGUOUS", "NOT_FOUND"}:
                    self._ask_for_information(
                        environment,
                        catalog,
                        task,
                        resolution.field or "required_argument",
                        state,
                        initial_call_count=initial_call_count,
                        detailed_audit=detailed_audit,
                    )
                continue

            if len(environment.get_tool_calls()) - initial_call_count >= self.max_steps:
                state.task_states[task.id] = "BLOCKED"
                self._issue(state, task, "RUNTIME_BUDGET", "tool-call budget exhausted")
                continue
            validation = environment.validate(task.tool, resolution.arguments)
            if not validation.get("ok"):
                state.task_states[task.id] = "BLOCKED"
                self._issue(state, task, "INVALID_ARGUMENTS", str(validation.get("error", "schema validation failed")))
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
                    "tool_completed",
                    task_id=task.id,
                    tool=task.tool,
                    status="FAILED",
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
                state.emit("tool_completed", task_id=task.id, tool=task.tool, status="DONE")
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

        status = self._final_status(plan, state)
        steps = len(environment.get_tool_calls()) - initial_call_count
        state.emit("execution_finished", status=status, details={"steps": steps})
        return self._result(status, state, environment)

    def _explore(
        self,
        task: PlanTask,
        resolution: ResolutionResult,
        resolver: Resolver,
        spec: ToolSpec,
        catalog: dict[str, ToolSpec],
        environment: Environment,
        state: ExecutionState,
        *,
        initial_call_count: int,
        detailed_audit: Callable[[str, dict[str, Any]], None] | None,
    ) -> ResolutionResult:
        if not resolution.suggested_tools:
            return resolution
        name = resolution.suggested_tools[0]
        explore_spec = catalog.get(name)
        if explore_spec is None or explore_spec.kind != "read":
            return ResolutionResult(status="NEEDS_USER", field=resolution.field, message="safe lookup is unavailable")
        if len(environment.get_tool_calls()) - initial_call_count >= self.max_steps:
            return ResolutionResult(
                status="NEEDS_USER",
                field=resolution.field,
                message="tool-call budget exhausted",
            )
        validation = environment.validate(name, resolution.suggested_arguments)
        if not validation.get("ok"):
            return ResolutionResult(
                status="NEEDS_USER",
                field=resolution.field,
                message="lookup arguments are incomplete",
            )
        synthetic_id = f"{task.id}__lookup"
        if synthetic_id in state.observations:
            return ResolutionResult(status="NEEDS_USER", field=resolution.field, message="lookup was already attempted")
        state.emit("lookup_started", task_id=task.id, tool=name, status="RUNNING")
        if detailed_audit is not None:
            detailed_audit(
                "lookup_call_detail",
                {"task_id": task.id, "tool_name": name, "arguments": resolution.suggested_arguments},
            )
        raw_result = environment.call_tool(name, resolution.suggested_arguments)
        if detailed_audit is not None:
            detailed_audit(
                "lookup_result_detail",
                {"task_id": task.id, "tool_name": name, "raw_result": raw_result},
            )
        verified = verify_tool_result(raw_result, is_write=False)
        if not verified.ok:
            return ResolutionResult(status="NEEDS_USER", field=resolution.field, message="lookup did not succeed")
        state.observations[synthetic_id] = verified.data
        state.emit("lookup_completed", task_id=task.id, tool=name, status="DONE")
        lookup_ref = {
            "$ref": {
                "task_id": synthetic_id,
                "path": ["contacts"],
                "match": {"name": resolution.suggested_arguments.get("query")},
                "field": "id",
                "require_unique": True,
            }
        }
        retry_task = task.model_copy(
            update={"arguments": {**task.arguments, resolution.field or "contact_id": lookup_ref}}
        )
        return resolver.resolve(retry_task, state.observations, spec)

    def _ask_for_information(
        self,
        environment: Environment,
        catalog: dict[str, ToolSpec],
        task: PlanTask,
        field: str,
        state: ExecutionState,
        *,
        initial_call_count: int,
        detailed_audit: Callable[[str, dict[str, Any]], None] | None,
    ) -> None:
        tool = catalog.get("sys.ask_missing_info")
        if tool is None or len(environment.get_tool_calls()) - initial_call_count >= self.max_steps:
            return
        arguments = {"tool_name": task.tool, "params": [field]}
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
            state.emit("user_information_requested", task_id=task.id, tool=tool.name, status="NEEDS_USER")

    @staticmethod
    def _issue(
        state: ExecutionState,
        task: PlanTask,
        code: str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        issue = {"task_id": task.id, "code": code, "message": message}
        if field:
            issue["field"] = field
        state.issues.append(issue)
        state.emit("issue", task_id=task.id, status=code, details={"field": field} if field else {"code": code})

    @staticmethod
    def _mark_stalled(
        plan: TaskPlan,
        state: ExecutionState,
        *,
        code: str = "DEPENDENCY_BLOCKED",
        message: str = "task dependencies did not complete",
    ) -> None:
        for task in plan.tasks:
            if state.task_states[task.id] != "PENDING":
                continue
            state.task_states[task.id] = "BLOCKED"
            RuntimeService._issue(state, task, code, message)

    @staticmethod
    def _final_status(plan: TaskPlan, state: ExecutionState) -> str:
        if any(value == "FAILED" for value in state.task_states.values()):
            return "FAILED"
        if state.issues:
            user_blocking = {"NEEDS_USER", "MISSING", "AMBIGUOUS", "NOT_FOUND", "UNKNOWN_CONDITION"}
            if any(issue["code"] in user_blocking for issue in state.issues):
                return "NEEDS_USER"
            if any(issue["code"] == "UNSUPPORTED_TOOL" for issue in state.issues):
                return "UNSUPPORTED"
            return "BLOCKED"
        if all(value in {"DONE", "SKIPPED"} for value in state.task_states.values()):
            return "SATISFIED"
        return "BLOCKED"

    @staticmethod
    def _result(status: str, state: ExecutionState, environment: Environment) -> RunResult:
        return RunResult(
            execution_status=status,
            task_states=state.task_states,
            issues=state.issues,
            audit_events=state.audit_events,
            tool_calls=environment.get_tool_calls(),
            state_hash=environment.get_state_hash(),
        )

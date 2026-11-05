from __future__ import annotations

from core.contracts import (
    AgentRequest,
    InformationNeed,
    PlanGoal,
    PlanPatch,
    PlanTask,
    PlanTaskUpdate,
    TaskPlan,
    ToolSpec,
)
from modules.discovery.service import DiscoveryService
from modules.planner.service import MockPlanner
from modules.resolver.service import ResolverService
from modules.runtime.engine import RuntimeService
from modules.runtime.state import ExecutionState


def _ride_tool() -> ToolSpec:
    return ToolSpec(
        name="ride_hailing.book",
        kind="write",
        parameters={
            "properties": {
                "pickup": {"type": "string"},
                "dropoff": {"type": "string"},
                "vehicle": {"type": "string"},
                "schedule_time": {"type": "string"},
                "payment": {"type": "string"},
            },
            "required": ["pickup", "dropoff", "vehicle", "schedule_time"],
        },
    )


def test_public_0002_semantics_keep_context_address_and_block_unknown_destination_and_time() -> None:
    task = PlanTask(
        id="book",
        goal_id="g1",
        tool="ride_hailing.book",
        arguments={
            "pickup": {"$context": "user_profile.work_address"},
            "dropoff": {
                "$need": {
                    "kind": "LOCATION",
                    "description": "địa chỉ nha khoa cần đến",
                    "constraints": {"query": "lịch khám răng"},
                }
            },
            "vehicle": "car4",
            "schedule_time": {
                "$time": {
                    "base": "context.current_time",
                    "relative_day": 0,
                    "period": "afternoon",
                    "exact_time": None,
                }
            },
            "payment": {"$optional_missing": True},
        },
    )
    context = {
        "current_time": "2026-11-16T11:30:00+07:00",
        "timezone": "Asia/Ho_Chi_Minh",
        "user_profile": {"work_address": "Tòa nhà Blue Pearl, Quận 7, TP.HCM"},
    }

    request = AgentRequest(
        sample_id="public_0002",
        transcript="Đặt xe bốn chỗ từ công ty đi khám răng chiều nay, đặt ngay bây giờ.",
        context=context,
    )
    result = ResolverService().resolve(
        task,
        {},
        _ride_tool(),
        context=context,
        transcript=request.transcript,
    )

    assert result.status == "UNRESOLVED"
    assert result.arguments["pickup"] == context["user_profile"]["work_address"]
    assert "schedule_time" not in result.arguments
    assert "payment" not in result.arguments
    assert {issue.field for issue in result.issues} == {"dropoff", "schedule_time"}
    assert next(issue for issue in result.issues if issue.field == "schedule_time").code == "UNDERSPECIFIED"

    class Environment:
        def __init__(self) -> None:
            self.tools = [
                _ride_tool(),
                ToolSpec(
                    name="sys.ask_missing_info",
                    kind="meta",
                    parameters={
                        "properties": {"tool_name": {"type": "string"}, "params": {"type": "array"}},
                        "required": ["tool_name", "params"],
                    },
                ),
            ]
            self.calls: list[dict] = []

        def list_available_tools(self):
            return self.tools

        def validate(self, name, arguments):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append({"name": name, "arguments": arguments})
            return {"ok": True}

        def get_tool_calls(self):
            return self.calls

        def get_state_hash(self):
            return "fixture-state-hash"

    environment = Environment()
    runtime_result = RuntimeService().execute_plan(
        TaskPlan(goals=[PlanGoal(id="g1", description="book a ride")], tasks=[task]),
        ResolverService(),
        environment,
        request=request,
    )
    assert [call["name"] for call in environment.calls] == ["sys.ask_missing_info"]
    assert runtime_result.execution_status == "NEEDS_USER"


def test_temporal_date_uses_sample_context_not_system_clock() -> None:
    task = PlanTask(
        id="weather",
        goal_id="g1",
        tool="weather.get_forecast",
        arguments={
            "date": {
                "$time": {
                    "base": "context.current_time",
                    "relative_day": 1,
                    "period": None,
                    "exact_time": None,
                }
            }
        },
    )
    result = ResolverService().resolve(
        task,
        {},
        ToolSpec(
            name="weather.get_forecast",
            parameters={"properties": {"date": {"type": "string"}}, "required": ["date"]},
        ),
        context={"current_time": "2026-11-30T23:30:00-05:00"},
        transcript="Ngày mai xem dự báo thời tiết.",
    )

    assert result.status == "READY"
    assert result.arguments == {"date": "2026-12-01"}
    assert result.provenance["date"] == "context.current_time+1d"


def test_time_period_does_not_ground_invented_clock_time() -> None:
    task = PlanTask(
        id="book",
        goal_id="g1",
        tool="ride_hailing.book",
        arguments={
            "schedule_time": {
                "$time": {
                    "base": "context.current_time",
                    "relative_day": 0,
                    "period": "afternoon",
                    "exact_time": "14:00",
                }
            }
        },
    )
    result = ResolverService().resolve(
        task,
        {},
        _ride_tool(),
        context={"current_time": "2026-11-16T11:30:00+07:00"},
        transcript="Đón xe chiều nay; tôi sẽ đặt ngay bây giờ.",
    )

    assert result.status == "UNSUPPORTED"
    assert result.issues[0].field == "schedule_time"


def test_elapsed_24_hours_is_not_rewritten_as_a_calendar_day() -> None:
    task = PlanTask(
        id="alarm",
        goal_id="g1",
        tool="alarm.set",
        arguments={
            "schedule_time": {
                "$time": {
                    "base": "context.current_time",
                    "elapsed_hours": 24,
                    "exact_time": None,
                }
            }
        },
    )
    result = ResolverService().resolve(
        task,
        {},
        ToolSpec(
            name="alarm.set",
            parameters={"properties": {"schedule_time": {"type": "string"}}, "required": ["schedule_time"]},
        ),
        context={"current_time": "2026-03-28T12:30:00+01:00"},
        transcript="Đặt báo thức sau 24 giờ.",
    )

    assert result.status == "READY"
    assert result.arguments["schedule_time"] == "2026-03-29T12:30:00+01:00"
    assert result.provenance["schedule_time"] == "context.current_time+24h"


def test_discovery_recovers_only_allowed_read_only_provider_for_appointment_need() -> None:
    need_tool = ToolSpec(name="calendar.list_events", description="List calendar events", kind="read")
    unrelated = ToolSpec(name="device.debug_dump", description="Dump device diagnostics", kind="read")
    side_effect = ToolSpec(name="ride_hailing.book", description="Book a ride", kind="write")
    request_need = {
        "issue_id": "book:dropoff:unresolved",
        "task_id": "book",
        "field": "dropoff",
        "kind": "LOCATION",
        "question": "Find the location of the dental appointment",
        "capability_hints": ["appointment", "event"],
    }

    candidates = DiscoveryService(recovery_top_k=5).retrieve_for_need(
        InformationNeed.model_validate(request_need),
        [need_tool, unrelated, side_effect],
    )

    assert [candidate.tool.name for candidate in candidates] == ["calendar.list_events"]
    assert candidates[0].provider_evidence


def test_patch_cannot_modify_completed_task() -> None:
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="send a message")],
        tasks=[PlanTask(id="send", goal_id="g1", tool="sms.send", arguments={"content": "hello"})],
    )
    state = ExecutionState(
        task_states={"send": "DONE"},
        issues=[
            {
                "task_id": "send",
                "issue_id": "send:contact_id:unresolved",
                "code": "UNRESOLVED",
                "field": "contact_id",
            }
        ],
    )
    patch = PlanPatch(
        action="patch",
        base_plan_version=0,
        addressed_issue_ids=["send:contact_id:unresolved"],
        updates=[PlanTaskUpdate(task_id="send", arguments={"content": "changed"})],
    )

    try:
        RuntimeService._apply_patch(
            patch,
            list(plan.tasks),
            state,
            plan,
            {"sms.send": ToolSpec(name="sms.send", kind="write")},
            max_explore_tasks=3,
            existing_explore_count=0,
        )
    except ValueError as exc:
        assert "cannot modify task in DONE state" in str(exc)
    else:
        raise AssertionError("patch unexpectedly modified a completed task")


def test_patch_cannot_add_tool_outside_sample_allowlist() -> None:
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="send a message")],
        tasks=[PlanTask(id="send", goal_id="g1", tool="sms.send", arguments={"content": "hello"})],
    )
    state = ExecutionState(
        task_states={"send": "BLOCKED"},
        issues=[
            {
                "task_id": "send",
                "issue_id": "send:contact_id:unresolved",
                "code": "UNRESOLVED",
                "field": "contact_id",
            }
        ],
    )
    patch = PlanPatch(
        action="patch",
        base_plan_version=0,
        addressed_issue_ids=["send:contact_id:unresolved"],
        add_tasks=[PlanTask(id="recovery", goal_id="g1", tool="bank.transfer")],
        updates=[
            PlanTaskUpdate(
                task_id="send",
                arguments={"content": "hello"},
                depends_on=("recovery",),
            )
        ],
    )

    try:
        RuntimeService._apply_patch(
            patch,
            list(plan.tasks),
            state,
            plan,
            {"sms.send": ToolSpec(name="sms.send", kind="write")},
            max_explore_tasks=3,
            existing_explore_count=0,
        )
    except ValueError as exc:
        assert "outside this sample's allowed catalog" in str(exc)
    else:
        raise AssertionError("patch unexpectedly added a tool outside the allowed catalog")


def test_generic_user_place_does_not_count_as_a_grounded_address() -> None:
    task = PlanTask(
        id="book",
        goal_id="g1",
        tool="ride_hailing.book",
        arguments={"dropoff": {"$user": {"value": "khám răng", "evidence": "khám răng"}}},
    )
    result = ResolverService().resolve(
        task,
        {},
        _ride_tool(),
        transcript="Đưa tôi đi khám răng chiều nay.",
    )

    assert result.status == "UNDERSPECIFIED"
    assert result.field == "dropoff"
    assert result.arguments == {}


def test_mock_repair_adds_only_a_read_lookup_then_binds_unique_contact() -> None:
    class Environment:
        def __init__(self) -> None:
            self.tools = [
                ToolSpec(
                    name="contacts.search",
                    parameters={"properties": {"query": {"type": "string"}}, "required": ["query"]},
                    kind="read",
                ),
                ToolSpec(
                    name="sms.send",
                    parameters={
                        "properties": {"contact_id": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["content"],
                        "x-one-of": [["contact_id"]],
                    },
                    kind="write",
                ),
                ToolSpec(
                    name="sys.ask_missing_info",
                    parameters={
                        "properties": {"tool_name": {"type": "string"}, "params": {"type": "array"}},
                        "required": ["tool_name", "params"],
                    },
                    kind="meta",
                ),
            ]
            self.calls: list[dict] = []

        def list_available_tools(self):
            return self.tools

        def validate(self, name, arguments):
            return {"ok": name in {tool.name for tool in self.tools}, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append({"name": name, "arguments": arguments})
            if name == "contacts.search":
                return {"ok": True, "contacts": [{"id": "c1", "name": arguments["query"]}]}
            return {"ok": True, "done": True}

        def get_tool_calls(self):
            return self.calls

        def get_state_hash(self):
            return "fixture-state-hash"

    environment = Environment()
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="send a message")],
        tasks=[
            PlanTask(
                id="send",
                goal_id="g1",
                tool="sms.send",
                arguments={"recipient_name": "Lan", "content": "hello"},
            )
        ],
    )
    result = RuntimeService().execute_plan(
        plan,
        ResolverService(),
        environment,
        request=AgentRequest(sample_id="fixture", transcript="Nhắn cho Lan: hello"),
        discovery=DiscoveryService(),
        planner=MockPlanner(),
        adaptive=True,
        max_repair_calls=1,
    )

    assert [call["name"] for call in environment.calls] == ["contacts.search", "sms.send"]
    assert environment.calls[-1]["arguments"] == {"contact_id": "c1", "content": "hello"}
    assert result.execution_status == "SATISFIED"
    assert result.plan_version == 1

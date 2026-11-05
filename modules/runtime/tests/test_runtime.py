from core.contracts import PlanCondition, PlanGoal, PlanTask, ResolutionResult, TaskPlan, ToolSpec
from modules.runtime.engine import RuntimeService


class IdentityResolver:
    def resolve(self, task, observations, tool_spec):
        return ResolutionResult(status="READY", arguments=dict(task.arguments))


class FakeEnvironment:
    def __init__(self, tools, responses=None):
        self.tools = {tool.name: tool for tool in tools}
        self.responses = responses or {}
        self.calls = []

    def list_available_tools(self):
        return list(self.tools.values())

    def validate(self, name, arguments):
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": "not installed"}
        missing = [field for field in tool.parameters.get("required", []) if arguments.get(field) in (None, "", [], {})]
        return {"ok": not missing, "error": f"missing {missing}" if missing else None}

    def call_tool(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        return self.responses.get(name, {"ok": True})

    def get_tool_calls(self):
        return list(self.calls)

    def get_state_hash(self):
        return "test-hash"


def test_false_guard_skips_write_and_unknown_guard_does_not_run_it() -> None:
    schemas = [
        ToolSpec(
            name="weather.get_forecast",
            parameters={"properties": {"date": {"type": "string"}}, "required": ["date"]},
            kind="read",
        ),
        ToolSpec(
            name="sms.send",
            parameters={"properties": {"content": {"type": "string"}}, "required": ["content"]},
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
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="conditional message")],
        tasks=[
            PlanTask(id="weather", goal_id="g1", tool="weather.get_forecast", arguments={"date": "2026-11-29"}),
            PlanTask(
                id="send",
                goal_id="g1",
                tool="sms.send",
                arguments={"content": "hello"},
                depends_on=("weather",),
                when=PlanCondition(task_id="weather", path=["forecast", 0, "rain"], equals=True),
            ),
        ],
    )

    false_env = FakeEnvironment(schemas, {"weather.get_forecast": {"ok": True, "forecast": [{"rain": False}]}})
    false_result = RuntimeService().execute_plan(plan, IdentityResolver(), false_env)
    assert [call["name"] for call in false_env.get_tool_calls()] == ["weather.get_forecast"]
    assert false_result.task_states["send"] == "SKIPPED"
    assert false_result.execution_status == "SATISFIED"

    unknown_env = FakeEnvironment(schemas, {"weather.get_forecast": {"ok": True, "forecast": []}})
    unknown_result = RuntimeService().execute_plan(plan, IdentityResolver(), unknown_env)
    assert [call["name"] for call in unknown_env.get_tool_calls()] == [
        "weather.get_forecast",
        "sys.ask_missing_info",
    ]
    assert unknown_result.execution_status == "NEEDS_USER"
    assert unknown_result.task_states["send"] == "BLOCKED"


def test_invalid_or_unavailable_tool_never_executes() -> None:
    environment = FakeEnvironment([ToolSpec(name="weather.get_forecast")])
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="message")],
        tasks=[PlanTask(id="send", goal_id="g1", tool="sms.send")],
    )
    result = RuntimeService().execute_plan(plan, IdentityResolver(), environment)
    assert result.execution_status == "UNSUPPORTED"
    assert environment.get_tool_calls() == []


def test_uncertain_write_failure_is_not_retried() -> None:
    class RaisingEnvironment(FakeEnvironment):
        def call_tool(self, name, arguments):
            self.calls.append({"name": name, "arguments": arguments})
            raise TimeoutError("dispatch timed out")

    environment = RaisingEnvironment(
        [
            ToolSpec(
                name="sms.send",
                parameters={
                    "properties": {"phone_number": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["phone_number", "content"],
                },
                kind="write",
            )
        ]
    )
    plan = TaskPlan(
        goals=[PlanGoal(id="g1", description="send")],
        tasks=[
            PlanTask(
                id="send",
                goal_id="g1",
                tool="sms.send",
                arguments={"phone_number": "0900000000", "content": "hello"},
            )
        ],
    )
    result = RuntimeService().execute_plan(plan, IdentityResolver(), environment)
    assert len(environment.calls) == 1
    assert result.execution_status == "FAILED"
    assert result.issues[0]["code"] == "UNCERTAIN_EFFECT"


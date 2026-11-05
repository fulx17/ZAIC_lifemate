from core.contracts import PlanGoal, PlanTask, TaskPlan, ToolSpec
from modules.resolver.service import ResolverService
from modules.runtime.engine import RuntimeService


class FixtureEnvironment:
    def __init__(self, tools, responses):
        self.tools = {tool.name: tool for tool in tools}
        self.responses = responses
        self.calls = []

    def list_available_tools(self):
        return list(self.tools.values())

    def validate(self, name, arguments):
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": "tool unavailable"}
        missing = [
            field
            for field in tool.parameters.get("required", [])
            if arguments.get(field) in (None, "", [], {})
        ]
        return {"ok": not missing, "error": f"missing {missing}" if missing else None}

    def call_tool(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        return self.responses.get(name, {"ok": True})

    def get_tool_calls(self):
        return list(self.calls)

    def get_state_hash(self):
        return "fixture-hash"


def _schemas():
    return [
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


def _plan():
    return TaskPlan(
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


def test_unique_lookup_binds_id_before_write() -> None:
    environment = FixtureEnvironment(
        _schemas(),
        {
            "contacts.search": {"ok": True, "contacts": [{"id": "c1", "name": "Lan"}]},
            "sms.send": {"ok": True, "done": True},
        },
    )

    result = RuntimeService().execute_plan(_plan(), ResolverService(), environment)

    assert [call["name"] for call in environment.calls] == ["contacts.search", "sms.send"]
    assert environment.calls[-1]["arguments"] == {"contact_id": "c1", "content": "hello"}
    assert result.execution_status == "SATISFIED"


def test_ambiguous_lookup_asks_user_without_write() -> None:
    environment = FixtureEnvironment(
        _schemas(),
        {
            "contacts.search": {
                "ok": True,
                "contacts": [{"id": "c1", "name": "Lan"}, {"id": "c2", "name": "Lan"}],
            }
        },
    )

    result = RuntimeService().execute_plan(_plan(), ResolverService(), environment)

    assert [call["name"] for call in environment.calls] == [
        "contacts.search",
        "sys.ask_missing_info",
    ]
    assert result.execution_status == "NEEDS_USER"

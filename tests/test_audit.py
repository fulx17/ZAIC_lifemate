import json

from app.audit import FlowAuditLog
from core.contracts import AgentResult


def test_flow_audit_is_concise_and_does_not_store_argument_values(tmp_path, capsys) -> None:
    audit = FlowAuditLog(tmp_path, "sample-1", level="flow", console="flow")
    audit.emit("plan_accepted", {"goal_count": 1, "task_count": 1})
    audit.emit(
        "tool_started",
        {
            "task_id": "t1",
            "tool_name": "sms.send",
            "fields": ["phone_number", "content"],
            "arguments": {"phone_number": "0900000000", "content": "private message"},
        },
    )
    audit.emit("tool_completed", {"task_id": "t1", "tool_name": "sms.send", "status": "DONE"})
    audit.finish(
        AgentResult(id="sample-1", status="SATISFIED", state_hash="hash", tool_calls=[]),
        elapsed_seconds=0.25,
    )

    flow = (tmp_path / "sample-1.flow.txt").read_text(encoding="utf-8")
    console = capsys.readouterr().err
    assert "GOAL  goals=1" in flow
    assert "PLAN  tasks=1" in flow
    assert "sms.send" in flow
    assert "SATISFIED" in flow
    assert "0900000000" not in flow
    assert "private message" not in flow
    assert "END   SATISFIED | tool_calls=0" in console


def test_debug_audit_is_allowlisted_jsonl_without_sensitive_metadata(tmp_path) -> None:
    audit = FlowAuditLog(tmp_path, "sample-2", level="debug", console="off")
    audit.emit(
        "tool_started",
        {
            "task_id": "t1",
            "tool_name": "sms.send",
            "fields": ["phone_number", "content"],
            "arguments": {"phone_number": "0900000000", "content": "private message"},
            "context": {"user_profile": {"name": "private name"}},
        },
    )
    audit.finish(
        AgentResult(id="sample-2", status="NEEDS_USER", state_hash="hash", tool_calls=[]),
    )

    debug_path = tmp_path / "sample-2.events.jsonl"
    text = debug_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    assert len(records) == 1
    assert records[0]["details"] == {
        "task_id": "t1",
        "tool_name": "sms.send",
        "fields": ["phone_number", "content"],
    }
    assert "0900000000" not in text
    assert "private message" not in text
    assert "private name" not in text

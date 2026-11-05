from app.competition_io import submission_record
from core.contracts import AgentResult, ToolCall


def test_submission_uses_exact_keys_and_preserves_call_order() -> None:
    record = submission_record(
        AgentResult(
            id="sample",
            tool_calls=[
                ToolCall(name="weather.get_forecast", arguments={"date": "2026-01-01"}),
                ToolCall(name="sms.send", arguments={"contact_id": "c1", "content": "hi"}),
            ],
            state_hash="verified-hash",
            status="SATISFIED",
        )
    )
    assert list(record) == ["id", "tool_calls", "state_hash"]
    assert [call["name"] for call in record["tool_calls"]] == ["weather.get_forecast", "sms.send"]

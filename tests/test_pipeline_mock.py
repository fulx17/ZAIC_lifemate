import contextlib
import io
import json
from pathlib import Path

import pytest

from core.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def _run(name: str) -> dict:
    config = load_config(ROOT / "configs" / "mock.yaml")
    return _run_fixture(ROOT / "tests" / "fixtures" / name, config)


def _run_fixture(fixture_path: Path, config: dict) -> dict:
    from app.run_one import _run_fixture as run_fixture

    return run_fixture(fixture_path, config)


def test_mock_planner_executes_one_safe_weather_read() -> None:
    result = _run("rainy_reschedule.json")

    assert [call["name"] for call in result["tool_calls"]] == ["weather.get_forecast"]
    assert result["tool_calls"][0]["arguments"] == {"date": "2026-11-29"}
    assert result["status"] == "SATISFIED"
    assert len(result["state_hash"]) == 64


def test_corrected_request_does_not_execute_superseded_action() -> None:
    result = _run("corrected_intent.json")
    assert [call["name"] for call in result["tool_calls"]] == ["weather.get_forecast"]
    assert result["status"] == "SATISFIED"


def test_missing_contact_uses_the_official_missing_information_tool() -> None:
    result = _run("missing_contact.json")
    assert [call["name"] for call in result["tool_calls"]] == ["sys.ask_missing_info"]
    assert result["tool_calls"][0]["arguments"] == {
        "tool_name": "sms.send",
        "params": ["contact_id"],
    }
    assert result["status"] == "NEEDS_USER"


def test_unsupported_request_makes_no_tool_call() -> None:
    result = _run("unsupported_request.json")
    assert result["tool_calls"] == []
    assert result["status"] == "UNSUPPORTED"


def test_invalid_single_shot_plan_is_rejected_without_tool_execution(monkeypatch) -> None:
    import app.build_services as build_services
    from app.pipeline import Pipeline
    from app.run_one import _fixture_environment
    from core.contracts import RuntimeSample
    from core.llm import MockLLMClient

    fixture_path = ROOT / "tests" / "fixtures" / "rainy_reschedule.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    invalid_plan = {
        "schema_version": "2.0",
        "goals": [{"id": "g1", "description": "loop"}],
        "tasks": [
            {"id": "a", "goal_id": "g1", "tool": "weather.get_forecast", "depends_on": ["b"]},
            {"id": "b", "goal_id": "g1", "tool": "weather.get_forecast", "depends_on": ["a"]},
        ],
    }
    llm = MockLLMClient({"plan": invalid_plan})
    monkeypatch.setattr(build_services, "build_llm", lambda _: llm)
    config = load_config(ROOT / "configs" / "mock.yaml")
    config["modules"]["planner_impl"] = "qwen_single_shot"
    result = Pipeline(config).run(
        RuntimeSample.model_validate(fixture["sample"]),
        fixture_path,
        _fixture_environment(fixture),
        transcript_override=fixture["transcript"],
    )
    assert result.status == "PLAN_INVALID"
    assert result.tool_calls == []
    assert len(llm.calls) == 1
    completed = next(event for event in result.trace if event["event"] == "pipeline_completed")
    assert completed["qwen_calls"] == 1


def test_flow_audit_is_short_and_redacts_user_content(tmp_path: Path, capsys) -> None:
    fixture_path = ROOT / "tests" / "fixtures" / "rainy_reschedule.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    config = load_config(ROOT / "configs" / "mock.yaml")
    config["run"]["audit_level"] = "flow"
    config["run"]["audit_dir"] = str(tmp_path)
    config["run"]["audit_console"] = "flow"
    from app.pipeline import Pipeline
    from app.run_one import _fixture_environment
    from core.contracts import RuntimeSample

    result = Pipeline(config).run(
        RuntimeSample.model_validate(fixture["sample"]),
        fixture_path,
        _fixture_environment(fixture),
        transcript_override=fixture["transcript"],
    )
    flow = (tmp_path / "fixture_rainy.flow.txt").read_text(encoding="utf-8")
    assert result.status == "SATISFIED"
    assert "DISCOVER candidates=" in flow
    assert "GOAL" in flow and "PLAN" in flow and "BIND" in flow and "TOOL" in flow
    assert "END   SATISFIED" in flow
    assert fixture["transcript"] not in flow
    assert "Sếp Dũng" not in flow
    assert "LifeMate | fixture_rainy | FLOW" in capsys.readouterr().err


def test_debug_audit_uses_events_file_and_contains_no_raw_transcript(tmp_path: Path) -> None:
    fixture_path = ROOT / "tests" / "fixtures" / "rainy_reschedule.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    config = load_config(ROOT / "configs" / "mock.yaml")
    config["run"]["audit_level"] = "debug"
    config["run"]["audit_dir"] = str(tmp_path)
    config["run"]["audit_console"] = "off"
    from app.pipeline import Pipeline
    from app.run_one import _fixture_environment
    from core.contracts import RuntimeSample

    Pipeline(config).run(
        RuntimeSample.model_validate(fixture["sample"]),
        fixture_path,
        _fixture_environment(fixture),
        transcript_override=fixture["transcript"],
    )
    debug_path = tmp_path / "fixture_rainy.events.jsonl"
    text = debug_path.read_text(encoding="utf-8")
    assert '"event": "tool_completed"' in text
    assert fixture["transcript"] not in text
    assert "Sếp Dũng" not in text


def test_full_audit_records_transcript_plan_arguments_and_tool_result(tmp_path: Path) -> None:
    fixture_path = ROOT / "tests" / "fixtures" / "rainy_reschedule.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    config = load_config(ROOT / "configs" / "mock.yaml")
    config["run"]["audit_level"] = "full"
    config["run"]["audit_dir"] = str(tmp_path)
    config["run"]["audit_console"] = "off"
    from app.pipeline import Pipeline
    from app.run_one import _fixture_environment
    from core.contracts import RuntimeSample

    Pipeline(config).run(
        RuntimeSample.model_validate(fixture["sample"]),
        fixture_path,
        _fixture_environment(fixture),
        transcript_override=fixture["transcript"],
    )

    events_path = tmp_path / "fixture_rainy.events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    by_name = {event["event"]: event["details"] for event in events}
    event_names = [event["event"] for event in events]
    assert event_names.index("plan_accepted") < event_names.index("tool_started")
    assert event_names.index("tool_started") < event_names.index("tool_result_detail")
    assert event_names.index("tool_result_detail") < event_names.index("tool_completed")
    assert by_name["transcript_ready"] == {
        "source": "transcript_override",
        "text": fixture["transcript"],
        "language": "vi",
    }
    assert by_name["plan_generated"]["plan"]["tasks"][0]["tool"] == "weather.get_forecast"
    assert by_name["argument_resolution_detail"]["resolution"]["arguments"] == {"date": "2026-11-29"}
    assert by_name["tool_call_detail"]["arguments"] == {"date": "2026-11-29"}
    assert by_name["tool_result_detail"]["raw_result"] == {
        "ok": True,
        "forecast": [{"date": "2026-11-29", "rain": True}],
    }


def test_actual_sample_mock_smoke_does_not_read_gold_labels() -> None:
    manifest = ROOT / "train+public_test" / "train+public_test" / "train" / "train.jsonl"
    if not manifest.is_file():
        pytest.skip("local train bundle is not present")
    from app.run_one import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert main(
            [
                "--config",
                str(ROOT / "configs" / "mock.yaml"),
                "--split",
                "train",
                "--id",
                "train_0001",
                "--audit-level",
                "off",
            ]
        ) == 0
    result = json.loads(output.getvalue())
    assert result["status"] in {"NEEDS_USER", "UNSUPPORTED"}
    assert result["tool_calls"] == []
    assert "trace" not in result


def test_train_transcript_reference_is_offline_only_and_not_audited(tmp_path: Path) -> None:
    manifest = ROOT / "train+public_test" / "train+public_test" / "train" / "train.jsonl"
    if not manifest.is_file():
        pytest.skip("local train bundle is not present")
    from app.dataset_io import get_sample_by_id, get_train_reference_transcript
    from app.environment import MockEnvironment
    from app.pipeline import Pipeline
    from core.contracts import ToolSpec

    loaded = get_sample_by_id(manifest, "train_0002", "train")
    reference = get_train_reference_transcript(manifest, "train_0002")
    config = load_config(ROOT / "configs" / "mock.yaml")
    config["run"]["audit_level"] = "debug"
    config["run"]["audit_dir"] = str(tmp_path)
    config["run"]["audit_console"] = "off"
    environment = MockEnvironment(
        [
            ToolSpec(
                name="weather.get_forecast",
                parameters={
                    "type": "object",
                    "properties": {"date": {"type": "string"}},
                    "required": ["date"],
                },
                kind="read",
            )
        ]
    )
    Pipeline(config).run(
        loaded.sample,
        loaded.audio_path,
        environment,
        transcript_reference=reference,
    )

    events_path = tmp_path / "train_0002.events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert not any(event["event"] == "asr_completed" for event in events)
    assert any(event["event"] == "transcript_reference_loaded" for event in events)
    assert reference not in events_path.read_text(encoding="utf-8")


def test_transcript_reference_cli_mode_rejects_public_test() -> None:
    from app.run_one import main

    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--split",
                "public_test",
                "--id",
                "public_0002",
                "--input-mode",
                "transcript_reference",
            ]
        )
    assert exc_info.value.code == 2


def test_run_dataset_keeps_train_reference_access_inside_offline_mode(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    import app.run_dataset as run_dataset
    from app.dataset_io import get_train_reference_transcript
    from core.contracts import AgentResult

    manifest = ROOT / "train+public_test" / "train+public_test" / "train" / "train.jsonl"
    if not manifest.is_file():
        pytest.skip("local train bundle is not present")
    output_path = tmp_path / "reference.jsonl"
    captured_references = []

    class CapturingPipeline:
        def __init__(self, config):
            pass

        def run(self, sample, audio_path, environment, *, transcript_reference=None):
            captured_references.append((sample.id, transcript_reference))
            return AgentResult(id=sample.id, status="NEEDS_USER", tool_calls=[], state_hash="test-hash")

    monkeypatch.setattr(run_dataset, "Pipeline", CapturingPipeline)
    assert run_dataset.main(
        [
            "--config",
            str(ROOT / "configs" / "mock.yaml"),
            "--split",
            "train",
            "--limit",
            "1",
            "--input-mode",
            "transcript_reference",
            "--output",
            str(output_path),
        ]
    ) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["input_mode"] == "transcript_reference"
    assert summary["processed"] == 1
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1
    expected = get_train_reference_transcript(manifest, captured_references[0][0])
    assert captured_references == [(captured_references[0][0], expected)]

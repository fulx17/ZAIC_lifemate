"""Run one sample or synthetic fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.dataset_io import discover_bundle_root, get_sample_by_id, get_train_reference_transcript
from app.environment import MockEnvironment, OfficialEnvironment, load_catalog_schemas
from app.pipeline import Pipeline
from core.config import configured_path, load_config
from core.contracts import RuntimeSample, ToolSpec


def _fixture_environment(fixture: dict[str, Any]) -> MockEnvironment:
    installed_apps = fixture["sample"]["context"].get("installed_apps", {})
    installed = [tool for app in installed_apps.values() for tool in app.get("tools", [])]
    available = fixture.get("tools", [*installed, "sys.ask_missing_info"])
    specifications = {
        "weather.get_forecast": {"properties": {"date": {"type": "string"}}, "required": ["date"]},
        "calendar.list_events": {"properties": {}, "required": []},
        "calendar.update_event": {
            "properties": {"event_id": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["event_id", "start", "end"],
        },
        "contacts.search": {"properties": {"query": {"type": "string"}}, "required": ["query"]},
        "sms.send": {
            "properties": {
                "contact_id": {"type": "string"},
                "phone_number": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["content"],
            "x-one-of": [["contact_id"], ["phone_number"]],
        },
        "sys.ask_missing_info": {
            "properties": {
                "tool_name": {"type": "string"},
                "params": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tool_name", "params"],
        },
    }
    schemas = [
        ToolSpec(
            name=name,
            description=name.replace(".", " "),
            parameters={"type": "object", **specifications.get(name, {"properties": {}, "required": []})},
            kind=(
                "meta"
                if name == "sys.ask_missing_info"
                else "read"
                if name.endswith(("get_forecast", "list_events", "search"))
                else "write"
            ),
        )
        for name in available
    ]
    state = fixture.get("environment", {})
    is_rain = bool(state.get("rain", True))
    events = state.get(
        "events",
        [
            {
                "id": "evt_fixture",
                "title": "chạy bộ",
                "start": "2026-11-29T08:00:00+07:00",
                "end": "2026-11-29T09:00:00+07:00",
            }
        ],
    )
    contact = state.get("contact", {"id": "contact_fixture", "name": "Sếp Dũng"})
    responses = {
        "weather.get_forecast": lambda args, _: {"ok": True, "forecast": [{"date": args["date"], "rain": is_rain}]},
        "calendar.list_events": {"ok": True, "events": events},
        "calendar.update_event": lambda args, state: _mock_update_event(args, state),
        "contacts.search": {"ok": True, "contacts": [contact]},
        "sms.send": lambda args, state: _mock_send_message(args, state),
    }
    return MockEnvironment(schemas, responses, initial_state={"events": events})


def _mock_update_event(arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    updated = None
    for event in state.get("events", []):
        if event.get("id") == arguments.get("event_id"):
            event.update({key: arguments[key] for key in ("start", "end") if key in arguments})
            updated = dict(event)
            break
    return {"ok": True, "item": updated or dict(arguments)}


def _mock_send_message(arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    messages = state.setdefault("messages", [])
    message = {"id": "msg_fixture", **arguments}
    messages.append(message)
    return {"ok": True, "message": message}


def _run_fixture(fixture_path: Path, config: dict[str, Any]) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    sample_data = fixture["sample"]
    sample = RuntimeSample.model_validate(sample_data)
    environment = _fixture_environment(fixture)
    result = Pipeline(config).run(
        sample,
        Path(fixture_path),
        environment,
        transcript_override=fixture["transcript"],
    )
    return result.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one LifeMate pipeline request")
    parser.add_argument("--config", default="configs/mock.yaml")
    parser.add_argument("--split", choices=["train", "public_test"], default="public_test")
    parser.add_argument("--id")
    parser.add_argument("--fixture")
    parser.add_argument("--adapter", choices=["mock", "official"])
    parser.add_argument("--input-mode", choices=["audio", "transcript_reference"], default="audio")
    parser.add_argument("--audit-level", choices=["off", "flow", "debug", "full"])
    parser.add_argument("--audit-console", choices=["off", "summary", "flow"])
    parser.add_argument("--audit-dir")
    parser.add_argument("--include-trace", action="store_true")
    args = parser.parse_args(argv)
    if args.fixture and args.input_mode != "audio":
        parser.error("--input-mode transcript_reference cannot be used with --fixture")
    if args.input_mode == "transcript_reference" and args.split != "train":
        parser.error("--input-mode transcript_reference is available only for --split train")
    config = load_config(args.config)
    run_settings = config.setdefault("run", {})
    if args.audit_level is not None:
        run_settings["audit_level"] = args.audit_level
    elif "audit_level" not in run_settings:
        run_settings["audit_level"] = "debug" if run_settings.get("audit_enabled", False) else "flow"
    if args.audit_console is not None:
        run_settings["audit_console"] = args.audit_console
    elif "audit_console" not in run_settings:
        run_settings["audit_console"] = "flow" if run_settings.get("audit_enabled", False) else "summary"
    if args.audit_dir is not None:
        run_settings["audit_dir"] = args.audit_dir
    if args.adapter:
        config.setdefault("environment", {})["adapter"] = args.adapter
    if args.fixture:
        result = _run_fixture(Path(args.fixture).resolve(), config)
        if not args.include_trace:
            result.pop("trace", None)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    if not args.id:
        parser.error("--id is required unless --fixture is used")
    bundle_root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    manifest = bundle_root / config["dataset"][f"{args.split}_manifest"]
    loaded = get_sample_by_id(manifest, args.id, args.split)
    transcript_reference = (
        get_train_reference_transcript(manifest, args.id)
        if args.input_mode == "transcript_reference"
        else None
    )
    adapter = config.get("environment", {}).get("adapter", "mock")
    if adapter == "official":
        environment = OfficialEnvironment(bundle_root, args.split, args.id)
    elif adapter == "mock":
        schemas = load_catalog_schemas(bundle_root, args.split, loaded.sample.context.installed_apps)
        environment = MockEnvironment(schemas)
    else:
        raise ValueError(f"Unknown environment adapter: {adapter}")
    result = Pipeline(config).run(
        loaded.sample,
        loaded.audio_path,
        environment,
        transcript_reference=transcript_reference,
    )
    result_data = result.model_dump(mode="json")
    if not args.include_trace:
        result_data.pop("trace", None)
    print(json.dumps(result_data, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

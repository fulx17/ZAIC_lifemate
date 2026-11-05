"""Shared offline-only dataset helpers for module evaluators."""

from __future__ import annotations

from typing import Any

from app.dataset_io import discover_bundle_root, load_jsonl, validate_split_record
from app.environment import load_catalog_schemas
from core.config import configured_path
from core.contracts import ToolSpec


def load_train_records(config: dict[str, Any], limit: int | None) -> tuple[list[dict[str, Any]], Any, Any]:
    bundle_root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    manifest_path = bundle_root / config["dataset"]["train_manifest"]
    records = load_jsonl(manifest_path)
    for record in records:
        validate_split_record(record, "train")
    if limit is not None:
        records = records[:limit]
    return records, bundle_root, manifest_path


def sample_catalog(bundle_root, record: dict[str, Any]) -> list[ToolSpec]:
    return load_catalog_schemas(
        bundle_root,
        "train",
        record["context"].get("installed_apps", {}),
    )


def expected_tool_names(record: dict[str, Any]) -> list[str]:
    calls = record.get("label", {}).get("tool_calls", [])
    return list(
        dict.fromkeys(
            call["name"]
            for call in calls
            if isinstance(call, dict)
            and isinstance(call.get("name"), str)
            and call["name"] != "sys.ask_missing_info"
        )
    )

"""YAML configuration loading and project-relative path resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_config(config_path: str | Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    path = Path(config_path).resolve()
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load pipeline configuration") from exc
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    config["_project_root"] = str(path.parent.parent)
    for dotted_key, value in (overrides or {}).items():
        target = config
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return config


def configured_path(config: dict[str, Any], value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(config["_project_root"]) / path).resolve()

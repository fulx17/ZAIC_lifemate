"""Deterministic validation of tool arguments against catalog schemas."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from typing import Any

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _is_type(value: Any, expected: str | None) -> bool:
    return {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, (list, tuple)),
        "object": lambda item: isinstance(item, dict),
    }.get(expected, lambda _: True)(value)


def _format_valid(value: Any, fmt: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if fmt == "date":
            return bool(_DATE.fullmatch(value)) and date.fromisoformat(value).isoformat() == value
        if fmt == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "T" in value
        if fmt == "time":
            if not _TIME.fullmatch(value):
                return False
            time.fromisoformat(value)
            return True
    except ValueError:
        return False
    return True


def _matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    if schema.get("type") and not _is_type(value, schema["type"]):
        return False
    if schema.get("enum") and value not in schema["enum"]:
        return False
    if schema.get("format") and not _format_valid(value, schema["format"]):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return False
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            return False
    if isinstance(value, (list, tuple)) and isinstance(schema.get("items"), dict):
        if not all(_matches_schema(item, schema["items"]) for item in value):
            return False
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - properties.keys():
            return False
        if any(
            name in properties and not _matches_schema(item, properties[name])
            for name, item in value.items()
        ):
            return False
    if schema.get("anyOf") and not any(_matches_schema(value, branch) for branch in schema["anyOf"]):
        return False
    if schema.get("oneOf") and sum(_matches_schema(value, branch) for branch in schema["oneOf"]) != 1:
        return False
    return True


def validate_arguments(arguments: dict[str, Any], parameters: dict[str, Any]) -> list[str]:
    errors = [
        f"missing required argument: {name}"
        for name in parameters.get("required", [])
        if arguments.get(name) in (None, "", [], {})
    ]
    groups = parameters.get("x-one-of", [])
    if groups and not any(
        all(arguments.get(name) not in (None, "", [], {}) for name in group)
        for group in groups
    ):
        errors.append("one-of requirement not satisfied")
    for constraint in ("anyOf", "oneOf"):
        branches = parameters.get(constraint)
        if branches:
            matches = sum(_matches_schema(arguments, branch) for branch in branches)
            expected = matches > 0 if constraint == "anyOf" else matches == 1
            if not expected:
                errors.append(f"{constraint} requirement not satisfied")
    if parameters.get("additionalProperties") is False:
        unknown = set(arguments) - parameters.get("properties", {}).keys()
        if unknown:
            errors.append(f"unknown arguments: {sorted(unknown)}")
    for name, value in arguments.items():
        spec = parameters.get("properties", {}).get(name)
        if isinstance(spec, dict) and value not in (None, "", [], {}) and not _matches_schema(value, spec):
            errors.append(f"invalid value for {name}")
    return errors

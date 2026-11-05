"""Safe token-based reference resolution; never evaluates expressions."""

from __future__ import annotations

from typing import Any

from core.contracts import ArgumentReference


class BindingError(ValueError):
    def __init__(self, status: str, message: str, candidates: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.status = status
        self.candidates = candidates or []


def _read_path(value: Any, path: list[str | int]) -> Any:
    current = value
    for token in path:
        if isinstance(token, int) and isinstance(current, list) and 0 <= token < len(current):
            current = current[token]
        elif isinstance(token, str) and isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise BindingError("NOT_FOUND", f"reference path token {token!r} was not found")
    return current


def bind_reference(reference: ArgumentReference, observations: dict[str, Any]) -> Any:
    if reference.task_id not in observations:
        raise BindingError("MISSING", f"observation for task {reference.task_id!r} is unavailable")
    value = _read_path(observations[reference.task_id], reference.path)
    if isinstance(value, list):
        if reference.match is not None:
            value = [
                item
                for item in value
                if isinstance(item, dict)
                and all(item.get(key) == expected for key, expected in reference.match.items())
            ]
        if not value:
            raise BindingError("NOT_FOUND", "reference matched no result")
        if reference.require_unique and len(value) != 1:
            summaries = [
                {key: item[key] for key in ("id", "name", "title") if isinstance(item, dict) and key in item}
                for item in value
            ]
            raise BindingError("AMBIGUOUS", "reference matched more than one result", summaries)
        selected = value[0] if reference.require_unique else value
    else:
        selected = value
    if reference.require_unique:
        try:
            result = _read_path(selected, [reference.field])
        except BindingError as exc:
            raise BindingError("NOT_FOUND", f"reference field {reference.field!r} was not found") from exc
        if result in (None, ""):
            raise BindingError("MISSING", f"reference field {reference.field!r} is empty")
        return result
    if isinstance(selected, list):
        return [item.get(reference.field) for item in selected if isinstance(item, dict) and reference.field in item]
    return _read_path(selected, [reference.field])


def bind_value(value: Any, observations: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise BindingError("INVALID", "a $ref argument must contain only the $ref key")
            return bind_reference(ArgumentReference.model_validate(value["$ref"]), observations)
        return {key: bind_value(item, observations) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [bind_value(item, observations) for item in value]
    return value

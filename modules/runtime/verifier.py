"""Strict interpretation of tool responses without model-based re-planning."""

from __future__ import annotations

from typing import Any

from core.contracts import ToolResult


def verify_tool_result(
    value: Any,
    *,
    is_write: bool,
    arguments: dict[str, Any] | None = None,
    state_changed: bool = False,
) -> ToolResult:
    if not isinstance(value, dict):
        return ToolResult(ok=False, data={}, error="tool returned a non-object result", effect_status="UNKNOWN")
    if value.get("ok") is False:
        return ToolResult(
            ok=False,
            data=value,
            error=str(value.get("error", "tool reported failure")),
            effect_status="NOT_APPLIED" if is_write else "UNKNOWN",
        )
    if value.get("done") is False:
        return ToolResult(
            ok=False,
            data=value,
            error=str(value.get("message", "requested effect was not completed")),
            effect_status="NOT_APPLIED" if is_write else "UNKNOWN",
        )
    if "effect_status" in value and value["effect_status"] in {"CONFIRMED", "NOT_APPLIED", "UNKNOWN"}:
        effect_status = value["effect_status"]
    elif not is_write:
        effect_status = "UNKNOWN"
    elif value.get("done") is True or state_changed:
        effect_status = "CONFIRMED"
    else:
        expected = arguments or {}
        returned_item = value.get("item") or value.get("message")
        if isinstance(returned_item, dict):
            checked = {
                ("id" if key == "event_id" else key): item
                for key, item in expected.items()
                if key in returned_item or (key == "event_id" and "id" in returned_item)
            }
            if checked and all(returned_item.get(key) == item for key, item in checked.items()):
                effect_status = "CONFIRMED"
            else:
                return ToolResult(
                    ok=False,
                    data=value,
                    error="write result did not verify the requested fields",
                    effect_status="UNKNOWN",
                )
        else:
            return ToolResult(
                ok=False,
                data=value,
                error="write effect was not confirmed",
                effect_status="UNKNOWN",
            )
    return ToolResult(ok=True, data=value, effect_status=effect_status)

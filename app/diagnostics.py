"""Runtime diagnostics without exposing labels or raw environment state."""

from __future__ import annotations

from typing import Any


def summarize_sample(sample: Any) -> dict[str, Any]:
    return {
        "id": sample.id,
        "audio": sample.audio,
        "installed_apps": sorted(sample.context.installed_apps),
        "history_length": len(sample.history),
    }

"""Competition output formatting and JSONL serialization."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from core.contracts import AgentResult


def submission_record(result: AgentResult) -> dict:
    return {
        "id": result.id,
        "tool_calls": [{"name": call.name, "arguments": call.arguments} for call in result.tool_calls],
        "state_hash": result.state_hash,
    }


def write_submission(path: str | Path, results: Iterable[AgentResult]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(submission_record(result), ensure_ascii=False) + "\n")

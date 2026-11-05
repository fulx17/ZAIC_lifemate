"""Offline ordered-tool-call comparison; labels never enter inference components."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.dataset_io import discover_bundle_root, load_jsonl
from core.config import configured_path, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a submission against train labels offline")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--submission", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    manifest = root / config["dataset"]["train_manifest"]
    labels = {row["id"]: row["label"] for row in load_jsonl(manifest)}
    predictions = {}
    with Path(args.submission).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                predictions[row["id"]] = row
    compared = matches = 0
    for sample_id, prediction in predictions.items():
        if sample_id not in labels:
            continue
        compared += 1
        expected = labels[sample_id].get("tool_calls", [])
        actual = prediction.get("tool_calls", [])
        matches += expected == actual
    print(
        json.dumps(
            {
                "evaluated_offline": True,
                "compared": compared,
                "ordered_tool_call_exact_matches": matches,
                "exact_match_rate": matches / compared if compared else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

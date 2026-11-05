"""Create a seeded train-only validation ID split without exposing labels to inference."""

from __future__ import annotations

import argparse
import json
import random

from app.dataset_io import discover_bundle_root, load_jsonl
from core.config import configured_path, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist a deterministic train/validation ID split")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--output", default="outputs/train_validation_ids.json")
    args = parser.parse_args()
    if not 0 < args.validation_fraction < 1:
        parser.error("--validation-fraction must be between 0 and 1")
    config = load_config(args.config)
    root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    records = load_jsonl(root / config["dataset"]["train_manifest"])
    ids = [record["id"] for record in records]
    random.Random(args.seed).shuffle(ids)
    validation_size = max(1, round(len(ids) * args.validation_fraction))
    payload = {
        "seed": args.seed,
        "validation_fraction": args.validation_fraction,
        "train_ids": sorted(ids[validation_size:]),
        "validation_ids": sorted(ids[:validation_size]),
    }
    output = configured_path(config, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Persisted {len(payload['train_ids'])} train IDs and "
        f"{len(payload['validation_ids'])} validation IDs to {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

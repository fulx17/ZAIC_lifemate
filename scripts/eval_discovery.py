"""Offline train-only tool Recall@K and full-chain recall evaluation."""

from __future__ import annotations

import argparse
import json

from core.config import load_config
from core.contracts import AgentRequest
from modules.discovery.service import DiscoveryService
from scripts._eval_common import expected_tool_names, load_train_records, sample_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    config = load_config(args.config)
    records, bundle_root, _ = load_train_records(config, args.limit)
    discovery_settings = config.get("discovery", {})
    discovery = DiscoveryService(
        top_k=discovery_settings.get("initial_top_k", config.get("modules", {}).get("discovery_top_k", 8)),
        recovery_top_k=discovery_settings.get("recovery_top_k", 5),
    )
    recalled = expected_count = complete_chains = evaluated = candidate_total = 0
    for record in records:
        expected = expected_tool_names(record)
        if not expected:
            continue
        catalog = sample_catalog(bundle_root, record)
        request = AgentRequest(
            sample_id=record["id"],
            transcript=record["audio_text"],
            context=record["context"],
            history=record.get("history", []),
        )
        candidates = discovery.retrieve(request, catalog)
        candidate_names = {tool.name for tool in candidates}
        expected_count += len(expected)
        recalled += sum(name in candidate_names for name in expected)
        complete_chains += set(expected) <= candidate_names
        candidate_total += len(candidates)
        evaluated += 1
    print(
        json.dumps(
            {
                "split": "train",
                "samples": evaluated,
                "tool_recall_at_k": recalled / expected_count if expected_count else None,
                "full_chain_recall": complete_chains / evaluated if evaluated else None,
                "average_candidates": candidate_total / evaluated if evaluated else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline planner evaluation using train transcripts and oracle candidate tools."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

from app.build_services import build_llm
from core.config import load_config
from core.contracts import AgentRequest
from core.llm import BudgetedLLMClient
from modules.planner.service import PlanInvalidError, SingleShotPlanner
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
    raw_llm = build_llm(config)
    budget = BudgetedLLMClient(raw_llm, max_calls=1)
    planner = SingleShotPlanner(
        budget,
        max_new_tokens=config.get("models", {}).get("llm", {}).get("max_new_tokens", {}).get("plan", 900),
    )
    valid = exact_tool_sets = call_violations = elapsed = 0
    for record in records:
        catalog = {tool.name: tool for tool in sample_catalog(bundle_root, record)}
        expected = expected_tool_names(record)
        oracle_candidates = [catalog[name] for name in expected if name in catalog]
        request = AgentRequest(
            sample_id=record["id"],
            transcript=record["audio_text"],
            context=record["context"],
            history=record.get("history", []),
        )
        budget.reset()
        started = perf_counter()
        try:
            plan = planner.generate_plan(request, oracle_candidates)
        except PlanInvalidError:
            plan = None
        elapsed += perf_counter() - started
        call_violations += budget.calls_used != 1
        if plan is not None:
            valid += 1
            predicted = {task.tool for task in plan.tasks}
            exact_tool_sets += predicted == set(expected)
    samples = len(records)
    print(
        json.dumps(
            {
                "split": "train",
                "samples": samples,
                "valid_plan_rate": valid / samples if samples else None,
                "exact_tool_set_rate": exact_tool_sets / samples if samples else None,
                "average_latency_seconds": elapsed / samples if samples else None,
                "planner_call_budget_violations": call_violations,
                "gold_task_plans": None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run mock/local inference for a split manifest."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

from app.audit import print_dataset_summary, print_sample_summary
from app.dataset_io import discover_bundle_root, iterate_samples, load_train_reference_transcripts
from app.environment import MockEnvironment, OfficialEnvironment, load_catalog_schemas
from app.pipeline import Pipeline
from core.config import configured_path, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LifeMate inference over a split")
    parser.add_argument("--config", default="configs/mock.yaml")
    parser.add_argument("--split", choices=["train", "public_test"], default="train")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", default="outputs/submission.jsonl")
    parser.add_argument("--input-mode", choices=["audio", "transcript_reference"], default="audio")
    parser.add_argument("--adapter", choices=["mock", "official"])
    parser.add_argument("--audit-level", choices=["off", "flow", "debug", "full"])
    parser.add_argument("--audit-console", choices=["off", "summary", "flow"])
    parser.add_argument("--audit-dir")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.input_mode == "transcript_reference" and args.split != "train":
        parser.error("--input-mode transcript_reference is available only for --split train")
    config = load_config(args.config)
    run_settings = config.setdefault("run", {})
    if args.audit_level is not None:
        run_settings["audit_level"] = args.audit_level
    elif "audit_level" not in run_settings:
        run_settings["audit_level"] = "debug" if run_settings.get("audit_enabled", False) else "off"
    run_settings["audit_console"] = "flow" if args.audit_console == "flow" else "off"
    if args.audit_dir is not None:
        run_settings["audit_dir"] = args.audit_dir
    if args.adapter:
        config.setdefault("environment", {})["adapter"] = args.adapter
    bundle_root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    manifest = bundle_root / config["dataset"][f"{args.split}_manifest"]
    reference_transcripts = (
        load_train_reference_transcripts(manifest) if args.input_mode == "transcript_reference" else {}
    )
    pipeline = Pipeline(config)
    results = []
    for loaded in iterate_samples(bundle_root, args.split, args.limit):
        if config.get("environment", {}).get("adapter", "mock") == "official":
            environment = OfficialEnvironment(bundle_root, args.split, loaded.sample.id)
        else:
            schemas = load_catalog_schemas(bundle_root, args.split, loaded.sample.context.installed_apps)
            environment = MockEnvironment(schemas)
        started = perf_counter()
        result = pipeline.run(
            loaded.sample,
            loaded.audio_path,
            environment,
            transcript_reference=reference_transcripts.get(loaded.sample.id),
        )
        elapsed = perf_counter() - started
        results.append(result)
        print_sample_summary(loaded.sample.id, result, elapsed)
    print_dataset_summary(results)
    from app.competition_io import write_submission

    write_submission(configured_path(config, args.output), results)
    print(
        json.dumps(
            {
                "split": args.split,
                "input_mode": args.input_mode,
                "processed": len(results),
                "output": args.output,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

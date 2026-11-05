"""Read-only, offline introspection of the supplied LifeMate zaic_tools kit."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from app.dataset_io import discover_bundle_root
from core.config import configured_path, load_config


def _api_symbols(path: Path) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            result[node.name] = [
                child.name for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.setdefault("functions", []).append(node.name)
    return result


def inspect_split(bundle_root: Path, split: str) -> dict[str, Any]:
    split_dir = bundle_root / split
    package_dir = split_dir / "zaic_tools"
    catalog_path = split_dir / f"{split}_tools_catalog.json"
    environment_dir = split_dir / f"{split}_environment"
    if not package_dir.is_dir() or not catalog_path.is_file() or not environment_dir.is_dir():
        return {
            "split": split,
            "available": False,
            "package": package_dir.exists(),
            "catalog": catalog_path.exists(),
            "environment": environment_dir.exists(),
        }
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    sample_dirs = sorted(path for path in environment_dir.iterdir() if (path / "state.json").is_file())
    sample_id = sample_dirs[0].name if sample_dirs else None
    state_summary = None
    if sample_id:
        state = json.loads((environment_dir / sample_id / "state.json").read_text(encoding="utf-8"))
        state_summary = {
            "sample_id": sample_id,
            "top_level_keys": sorted(state),
            "installed_tools": state.get("_meta", {}).get("tools", []),
        }
    return {
        "split": split,
        "available": True,
        "package": str(package_dir),
        "catalog_schema_version": catalog.get("schema_version"),
        "apps": [{"id": app.get("id"), "tool_count": len(app.get("tools", []))} for app in catalog.get("apps", [])],
        "tool_count": sum(len(app.get("tools", [])) for app in catalog.get("apps", [])),
        "environment_sample_count": len(sample_dirs),
        "representative_state": state_summary,
        "apis": {
            name: _api_symbols(package_dir / name)
            for name in ("__init__.py", "executor.py", "validate.py", "__main__.py", "utils.py")
            if (package_dir / name).is_file()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect local zaic_tools files without running tools")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--split", choices=["train", "public_test", "both"], default="both")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    splits = ("train", "public_test") if args.split == "both" else (args.split,)
    report = {
        "bundle_root": str(root),
        "splits": [inspect_split(root, split) for split in splits],
        "network_requests": 0,
        "state_mutations": 0,
    }
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fast local configuration and dataset sanity checks."""

from __future__ import annotations

import argparse

from app.dataset_io import discover_bundle_root
from core.config import configured_path, load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/mock.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    root = discover_bundle_root(configured_path(config, config["dataset"]["bundle_root"]))
    for split in ("train", "public_test"):
        manifest = root / config["dataset"][f"{split}_manifest"]
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
    print(f"Configuration and both manifests are available under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

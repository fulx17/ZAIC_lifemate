"""Explicit development-only model snapshot downloader; never called by inference."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Download an explicitly pinned model snapshot for development")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True, help="Pinned commit/revision; floating revisions are not accepted")
    parser.add_argument("--local-dir", required=True)
    args = parser.parse_args()
    if len(args.revision) < 7 or args.revision.casefold() in {"main", "master", "latest"}:
        parser.error("--revision must be a pinned commit-like identifier, not a floating branch")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Install huggingface_hub separately to use this development-only command") from exc
    target = Path(args.local_dir).resolve()
    snapshot_download(repo_id=args.repo_id, revision=args.revision, local_dir=str(target))
    print(f"Downloaded {args.repo_id}@{args.revision} to {target}; verify license and competition approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

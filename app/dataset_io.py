"""Safe JSONL dataset loading with split-aware inference sanitization."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from core.contracts import RuntimeSample


@dataclass(frozen=True)
class LoadedSample:
    sample: RuntimeSample
    manifest_path: Path
    audio_path: Path


def discover_bundle_root(path: str | Path) -> Path:
    configured = Path(path).resolve()
    candidates = [configured, configured / configured.name]
    for candidate in candidates:
        if (candidate / "train" / "train.jsonl").is_file() and (
            candidate / "public_test" / "public_test.jsonl"
        ).is_file():
            return candidate
    raise FileNotFoundError(f"Could not locate nested LifeMate bundle root under {configured}")


def load_jsonl(manifest_path: str | Path) -> list[dict[str, Any]]:
    path = Path(manifest_path)
    if path.name.casefold() == "sample_submission.jsonl":
        raise ValueError("sample_submission.jsonl is output examples, not an input manifest")
    if not path.is_file():
        raise FileNotFoundError(path)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("id"), str)
                or not isinstance(record.get("audio"), str)
            ):
                raise ValueError(f"{path}:{line_number}: each record requires string id and audio fields")
            if record["id"] in seen:
                raise ValueError(f"{path}:{line_number}: duplicate sample id {record['id']!r}")
            if not isinstance(record.get("context"), dict):
                raise ValueError(f"{path}:{line_number}: context must be an object")
            seen.add(record["id"])
            records.append(record)
    return records


def resolve_audio_path(jsonl_path: str | Path, audio_field: str) -> Path:
    base = Path(jsonl_path).resolve().parent
    normalized = audio_field.replace("\\", "/")
    relative = Path(normalized)
    windows_relative = PureWindowsPath(audio_field)
    if relative.is_absolute() or windows_relative.is_absolute() or windows_relative.drive or ".." in relative.parts:
        raise ValueError("Unsafe audio path in manifest")
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("Audio path escapes JSONL directory")
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def validate_split_record(record: dict[str, Any], split: str) -> None:
    if split == "train":
        if "audio_text" not in record or "label" not in record:
            raise ValueError("train records require audio_text and label for offline evaluation")
    elif split == "public_test":
        if "audio_text" in record or "label" in record:
            raise ValueError("public_test records must not contain audio_text or label")
    else:
        raise ValueError(f"Unsupported split: {split!r}")


def to_runtime_sample(record: dict[str, Any]) -> RuntimeSample:
    """Create an inference-safe object without audio_text or label fields."""
    return RuntimeSample(
        id=record["id"],
        audio=record["audio"],
        context=record["context"],
        history=record.get("history", []),
    )


def get_sample_by_id(manifest_path: str | Path, sample_id: str, split: str) -> LoadedSample:
    path = Path(manifest_path).resolve()
    for record in load_jsonl(path):
        validate_split_record(record, split)
        if record["id"] == sample_id:
            sample = to_runtime_sample(record)
            return LoadedSample(sample=sample, manifest_path=path, audio_path=resolve_audio_path(path, sample.audio))
    raise KeyError(f"Sample {sample_id!r} not found in {path}")


def get_train_reference_transcript(manifest_path: str | Path, sample_id: str) -> str:
    """Load only a train sample's reference transcript for explicit module testing."""
    for record in load_jsonl(manifest_path):
        validate_split_record(record, "train")
        if record["id"] == sample_id:
            transcript = record.get("audio_text")
            if not isinstance(transcript, str) or not transcript.strip():
                raise ValueError(f"Train sample {sample_id!r} has no usable audio_text")
            return transcript
    raise KeyError(f"Train sample {sample_id!r} not found in {manifest_path}")


def load_train_reference_transcripts(manifest_path: str | Path) -> dict[str, str]:
    """Load train reference text keyed by ID; labels are not returned to callers."""
    transcripts: dict[str, str] = {}
    for record in load_jsonl(manifest_path):
        validate_split_record(record, "train")
        transcript = record.get("audio_text")
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError(f"Train sample {record['id']!r} has no usable audio_text")
        transcripts[record["id"]] = transcript
    return transcripts


def iterate_samples(bundle_root: str | Path, split: str, limit: int | None = None) -> Iterator[LoadedSample]:
    root = discover_bundle_root(bundle_root)
    manifest = root / split / f"{split}.jsonl"
    records = load_jsonl(manifest)
    count = 0
    for record in records:
        validate_split_record(record, split)
        sample = to_runtime_sample(record)
        yield LoadedSample(sample=sample, manifest_path=manifest, audio_path=resolve_audio_path(manifest, sample.audio))
        count += 1
        if limit is not None and count >= limit:
            break

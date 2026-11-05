"""Offline train-only ASR WER/CER evaluation against audio_text."""

from __future__ import annotations

import argparse
import json
import re

from app.dataset_io import resolve_audio_path
from core.config import configured_path, load_config
from modules.asr.mock import MockASR
from modules.asr.pho_whisper import PhoWhisperASR
from scripts._eval_common import load_train_records


def _edit_distance(reference: list[str], prediction: list[str]) -> int:
    previous = list(range(len(prediction) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def _load_asr(config):
    impl = config.get("modules", {}).get("asr_impl", "mock")
    if impl == "mock":
        return MockASR()
    if impl != "pho_whisper":
        raise ValueError(f"Unknown ASR implementation: {impl}")
    settings = config.get("models", {}).get("asr", {})
    local_path = settings.get("local_path")
    if not local_path:
        raise ValueError("models.asr.local_path is required for ASR evaluation")
    return PhoWhisperASR(
        str(configured_path(config, local_path)),
        device=settings.get("device"),
        torch_dtype=settings.get("torch_dtype"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    config = load_config(args.config)
    records, _, manifest_path = load_train_records(config, args.limit)
    asr = _load_asr(config)
    word_errors = word_count = char_errors = char_count = samples = 0
    for record in records:
        audio_path = resolve_audio_path(manifest_path, record["audio"])
        prediction = asr.transcribe(str(audio_path)).text.casefold()
        reference = re.sub(r"\s+", " ", record["audio_text"].strip()).casefold()
        predicted_words = prediction.split()
        reference_words = reference.split()
        word_errors += _edit_distance(reference_words, predicted_words)
        word_count += len(reference_words)
        normalized_prediction = re.sub(r"\s+", "", prediction)
        normalized_reference = re.sub(r"\s+", "", reference)
        char_errors += _edit_distance(list(normalized_reference), list(normalized_prediction))
        char_count += len(normalized_reference)
        samples += 1
    print(
        json.dumps(
            {
                "split": "train",
                "samples": samples,
                "wer": word_errors / word_count if word_count else None,
                "cer": char_errors / char_count if char_count else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

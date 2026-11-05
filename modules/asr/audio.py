"""Minimal audio input checks shared by ASR implementations."""

from pathlib import Path


def validate_audio_path(audio_path: str) -> Path:
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return path

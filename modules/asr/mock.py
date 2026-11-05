"""No-weight ASR adapter for deterministic tests and pipeline smoke runs."""

from __future__ import annotations

from core.contracts import Transcript
from modules.asr.audio import validate_audio_path
from modules.asr.service import normalize_transcript


class MockASR:
    def __init__(self, transcripts: dict[str, str] | None = None, default_text: str = ""):
        self.transcripts = transcripts or {}
        self.default_text = default_text

    def transcribe(self, audio_path: str) -> Transcript:
        path = validate_audio_path(audio_path)
        text = self.transcripts.get(path.stem, self.default_text)
        return normalize_transcript(text)

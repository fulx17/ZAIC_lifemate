"""ASR service contract helpers."""

from core.contracts import Transcript


def normalize_transcript(text: str) -> Transcript:
    normalized = " ".join(text.strip().split())
    return Transcript(text=normalized, language="vi", confidence=None)

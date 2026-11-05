"""Lazy local Transformers adapter for PhoWhisper."""

from __future__ import annotations

from typing import Any

from core.contracts import Transcript
from core.errors import ModelUnavailableError
from modules.asr.audio import validate_audio_path
from modules.asr.service import normalize_transcript


class PhoWhisperASR:
    def __init__(
        self,
        model_path: str,
        *,
        device: str | int | None = None,
        torch_dtype: str | None = None,
    ):
        self.model_path = model_path
        self.device = device
        self.torch_dtype = torch_dtype
        self._pipeline: Any = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        from pathlib import Path

        if not Path(self.model_path).exists():
            raise ModelUnavailableError(
                "ASR_MODEL_NOT_FOUND", f"Local PhoWhisper path does not exist: {self.model_path}"
            )
        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise ModelUnavailableError(
                "ASR_DEPENDENCY_MISSING", "Install the local-model extra to use PhoWhisper."
            ) from exc
        options: dict[str, Any] = {
            "model": self.model_path,
            "model_kwargs": {"local_files_only": True},
        }
        if self.device is not None:
            options["device"] = self.device
        if self.torch_dtype is not None:
            dtype = getattr(torch, self.torch_dtype, None)
            if not isinstance(dtype, torch.dtype):
                raise ValueError(f"Unsupported ASR torch dtype: {self.torch_dtype!r}")
            options["torch_dtype"] = dtype
        self._pipeline = pipeline("automatic-speech-recognition", **options)

    def transcribe(self, audio_path: str) -> Transcript:
        path = validate_audio_path(audio_path)
        self._load()
        import soundfile

        audio, sampling_rate = soundfile.read(str(path), dtype="float32", always_2d=False)
        result = self._pipeline(
            {"raw": audio, "sampling_rate": sampling_rate},
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
        return normalize_transcript(str(result.get("text", "")))

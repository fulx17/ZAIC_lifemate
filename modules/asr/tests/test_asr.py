import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from modules.asr.mock import MockASR
from modules.asr.pho_whisper import PhoWhisperASR


def test_mock_asr_uses_configured_transcript(tmp_path: Path) -> None:
    audio = tmp_path / "request.wav"
    audio.write_bytes(b"fixture")
    assert MockASR({"request": "  Xin chào \n"}).transcribe(str(audio)).text == "Xin chào"


def test_mock_asr_rejects_missing_audio(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        MockASR().transcribe(str(tmp_path / "missing.wav"))


def test_mock_asr_rejects_empty_audio(tmp_path: Path) -> None:
    audio = tmp_path / "empty.wav"
    audio.touch()
    with pytest.raises(ValueError, match="empty"):
        MockASR().transcribe(str(audio))


def test_phowhisper_decodes_wav_without_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    soundfile = pytest.importorskip("soundfile")
    model_path = tmp_path / "model"
    model_path.mkdir()
    audio_path = tmp_path / "request.wav"
    soundfile.write(audio_path, np.zeros(16000, dtype=np.float32), 16000)
    observed: dict = {}

    def create_pipeline(task, **options):
        observed["task"] = task
        observed["options"] = options

        def transcribe(payload, **kwargs):
            observed["payload"] = payload
            observed["call_kwargs"] = kwargs
            return {"text": "  Xin chào  "}

        return transcribe

    transformers = ModuleType("transformers")
    transformers.pipeline = create_pipeline
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    result = PhoWhisperASR(str(model_path), device=0, torch_dtype="float16").transcribe(str(audio_path))

    assert result.text == "Xin chào"
    assert observed["task"] == "automatic-speech-recognition"
    assert observed["options"]["device"] == 0
    assert observed["options"]["model_kwargs"]["local_files_only"] is True
    assert observed["payload"]["sampling_rate"] == 16000
    assert observed["payload"]["raw"].shape == (16000,)
    assert observed["call_kwargs"]["generate_kwargs"] == {"language": "vi", "task": "transcribe"}

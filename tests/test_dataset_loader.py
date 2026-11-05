from pathlib import Path

import pytest

from app.dataset_io import (
    discover_bundle_root,
    get_sample_by_id,
    get_train_reference_transcript,
    load_jsonl,
    load_train_reference_transcripts,
    resolve_audio_path,
    to_runtime_sample,
    validate_split_record,
)


def _record(sample_id: str = "sample") -> dict:
    return {
        "id": sample_id,
        "audio": "audio/sample.wav",
        "context": {"installed_apps": {}},
        "history": [],
        "audio_text": "private reference",
        "label": {"tool_calls": []},
    }


def test_nested_bundle_root_ignores_metadata_directory(tmp_path: Path) -> None:
    outer = tmp_path / "train+public_test"
    nested = outer / "train+public_test"
    (nested / "train").mkdir(parents=True)
    (nested / "public_test").mkdir()
    (outer / "__MACOSX").mkdir()
    (nested / "train" / "train.jsonl").touch()
    (nested / "public_test" / "public_test.jsonl").touch()
    assert discover_bundle_root(outer) == nested.resolve()


def test_split_schema_differences_are_enforced() -> None:
    train = _record()
    public = {key: value for key, value in train.items() if key not in {"audio_text", "label"}}
    validate_split_record(train, "train")
    validate_split_record(public, "public_test")
    with pytest.raises(ValueError, match="must not contain"):
        validate_split_record(train, "public_test")


def test_wav_path_resolves_relative_to_manifest_parent(tmp_path: Path) -> None:
    manifest = tmp_path / "train" / "train.jsonl"
    wav = tmp_path / "train" / "audio" / "sample.wav"
    wav.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    wav.touch()
    assert resolve_audio_path(manifest, "audio/sample.wav") == wav.resolve()
    assert resolve_audio_path(manifest, r"audio\sample.wav") == wav.resolve()


def test_missing_wav_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_audio_path(tmp_path / "train.jsonl", "audio/missing.wav")


@pytest.mark.parametrize("audio", ["../secret.wav", r"..\secret.wav", "C:\\secret.wav"])
def test_malicious_audio_paths_are_rejected(tmp_path: Path, audio: str) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        resolve_audio_path(tmp_path / "train.jsonl", audio)


def test_sample_submission_is_rejected_as_input(tmp_path: Path) -> None:
    path = tmp_path / "sample_submission.jsonl"
    path.write_text('{"id":"x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not an input"):
        load_jsonl(path)


def test_runtime_sample_excludes_labels_and_reference_transcript() -> None:
    sample = to_runtime_sample(_record())
    assert not hasattr(sample, "label")
    assert not hasattr(sample, "audio_text")
    assert sample.id == "sample"


def test_reference_transcript_loader_returns_text_without_labels(tmp_path: Path) -> None:
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        (
            '{"id":"sample","audio":"audio/sample.wav","context":{},'
            '"audio_text":"reference text","label":{"secret":true}}\n'
        ),
        encoding="utf-8",
    )

    assert get_train_reference_transcript(manifest, "sample") == "reference text"
    assert load_train_reference_transcripts(manifest) == {"sample": "reference text"}


def test_reference_transcript_loader_rejects_non_train_split(tmp_path: Path) -> None:
    manifest = tmp_path / "public_test.jsonl"
    manifest.write_text(
        '{"id":"sample","audio":"audio/sample.wav","context":{},"audio_text":"reference text"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="train records require"):
        get_train_reference_transcript(manifest, "sample")


def test_actual_train_and_public_manifests_resolve_audio_without_leaking_labels() -> None:
    root = Path(__file__).resolve().parents[1] / "train+public_test" / "train+public_test"
    if not (root / "train" / "train.jsonl").is_file():
        pytest.skip("local dataset bundle is not present")
    train = get_sample_by_id(root / "train" / "train.jsonl", "train_0001", "train")
    public = get_sample_by_id(root / "public_test" / "public_test.jsonl", "public_0002", "public_test")
    assert train.audio_path.is_file() and public.audio_path.is_file()
    assert not hasattr(train.sample, "audio_text") and not hasattr(train.sample, "label")

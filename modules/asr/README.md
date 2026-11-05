# ASR

`MockASR` and `PhoWhisperASR` implement `transcribe(audio_path)`. The real adapter loads only a
local Transformers snapshot and validates the input file before inference.

Run the independent tests with `python -m pytest modules/asr/tests -q`.

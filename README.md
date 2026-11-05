# LifeMate V2

LifeMate runs an offline-capable, per-sample assistant pipeline with five clear module owners:
`asr`, `discovery`, `planner`, `resolver`, and `runtime`. The full target and acceptance cases are
described in [`docs/LifeMate_V2_Team_Plan_Detailed.md`](docs/LifeMate_V2_Team_Plan_Detailed.md).

Hướng dẫn cài đặt, các mode, CLI options, audit và vai trò của từng thư mục nằm trong
[Sổ tay sử dụng và phát triển (tiếng Việt)](docs/handbook_vi.md).

## Run and test

```powershell
python -m pip install -e ".[dev]"
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/rainy_reschedule.json
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/missing_contact.json
python -m app.run_one --config configs/mock.yaml --split public_test --id public_0002
python -m scripts.eval_discovery --config configs/mock.yaml --limit 20
python -m scripts.eval_resolver
python -m scripts.eval_runtime
python -m pytest -q
ruff check .
```

The mock mode needs no model weights or network access. Its rule-based planner is intentionally
limited to smoke-test cases; it is not a quality benchmark. For local inference, install the
`local-models` extra, set local PhoWhisper and Qwen snapshot paths in `configs/baseline.yaml`, then
run:

```powershell
python -m app.run_one --config configs/baseline.yaml --split public_test --id public_0002 --audit-level flow
```

The Qwen planner makes one non-repairing JSON call per sample. Discovery, Resolver, and Runtime do
not call a model. Local model loading uses local files only; inference does not download weights or
call external model services.

Offline train evaluators are available via `scripts.eval_asr`, `scripts.eval_discovery`, and
`scripts.eval_planner`. Planner evaluation requires local Qwen weights and uses oracle candidates;
there is no gold TaskPlan, so it reports plan validity and tool-set match rather than task-sequence
accuracy. Resolver and Runtime evaluators run fixed test fixtures because no verified gold benchmark
is present for those outputs.

## Architecture and data boundaries

- `modules/asr`: WAV to normalized transcript; MockASR and PhoWhisper adapters.
- `modules/discovery`: deterministic retrieval from the sample's actual allowed catalog; retrieval
  never grants permission to call a tool.
- `modules/planner`: one Qwen call producing immutable schema-v2 goals, tasks, dependencies,
  conditions, and typed `$ref`s.
- `modules/resolver`: deterministic reference binding and schema checks; no LLM or environment calls.
- `modules/runtime`: bounded dependency scheduler, tri-state guards, verification, missing-info
  protocol, and audit events; no semantic replanning.
- `app/`: composition, safe dataset loading, official/mock environment adapters, CLI, audit render,
  and competition serialization.
- `core/`: shared schema-v2 contracts and module protocols.

Every inference sample is sanitized to `RuntimeSample`; `label` and `audio_text` are excluded.
`transcript_reference` is an explicit train-only development option. The original bundle and
`lifemate_analysis_full` are not modified.

`OfficialEnvironment` is the only source of official tool calls and `state_hash`. Submission lines
contain exactly `id`, `tool_calls`, and `state_hash`; audit and internal status are not submitted.
Mock hashes are test-only.

## Audit

`run_one` writes compact `outputs/audit/<sample>.flow.txt` by default. `--audit-level debug` adds
allowlisted `*.events.jsonl` metadata (tool and field names, statuses, and counts); it excludes
transcripts, prompts, argument values, and raw tool results.
`run_dataset` defaults to audit off so it writes one summary line per sample.

```powershell
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/rainy_reschedule.json --audit-level flow
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/rainy_reschedule.json --audit-level debug
python -m app.run_one --config configs/baseline.yaml --split public_test --id public_0002 --audit-level full
```

Use `--audit-level full` for local diagnosis: the JSONL includes the ASR transcript, generated plan,
resolved arguments, and raw tool results. These can contain private information; keep the file local
and use `flow` or `debug` for ordinary runs. Full details are not printed to the console.

Official competition rules for checkpoints, licensing, model limits, and hardware still need
verification before packaging. The mock path and local kit adapter tests are not a model-quality or
competition-score claim.

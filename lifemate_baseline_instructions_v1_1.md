# LIFEMATE BASELINE — IMPLEMENTATION INSTRUCTIONS FOR CODING AGENT

**Version:** 1.1 — 2026-10-29 (verified local dataset structure)  
**Language:** Vietnamese-first (identifiers and code in English)  
**Deliverable:** A **working, testable, modular Python repository**, not just diagrams or empty interfaces.  
**Development strategy:** Prompt engineering first; no fine-tuning in baseline.  
**Models:** `vinai/PhoWhisper-small` (default ASR implementation; configurable PhoWhisper variant) and **one shared instance** of `Qwen/Qwen3-4B` (LLM for perception, planning and tool grounding). No other learned model by default.

> **How to use this document:** Give the entire document to the coding agent as the primary implementation specification. Follow sections **0 → 15** in order. Implement with mocks before running the real models. Inspect the provided local `zaic_tools` implementation before designing the official adapter; never invent SDK methods.

---

## 0. Work order, non-negotiable requirements, and scope

### 0.1 Required outcome

Implement a complete single-request execution flow:

```text
Input sample (audio, runtime context, history, installed tools)
    → ASR (PhoWhisper)
    → Input Perception (Qwen3-4B → structured intents)
    → Planner/Controller (Qwen3-4B → goal + dynamic task graph)
    → Tool Manager (tool retrieval → argument grounding → validation → execute)
    → Observer/AWM (normalize results → facts → task/goal evaluation)
    → Controller loop (expand/discover/repair/continue/stop)
    → Competition output adapter (ordered tool_calls + state_hash)
```

All 5 modules MUST have independently executable mock/demo tests. The end-to-end smoke test MUST run without model weights, internet, or an official simulator using deterministic mocks. Real-model and official-environment adapters must be swappable using configuration.

### 0.2 Non-negotiable engineering rules

1. **Exactly five independently owned module folders**: `asr`, `perception`, `planner_controller`, `tool_manager`, `observer_awm`. Put individual `experiments/` inside each folder.
2. **Shared contracts in `core/`**, with Pydantic v2 types and versioned schemas. Modules may import `core` but **must not import one another directly**. `app/pipeline.py` wires dependencies together.
3. **Only one Qwen3-4B instance** is loaded per process; Perception, Planner, and Tool Manager receive the same `LLMClient` object. Never initialize three separate Qwen models.
4. **Controller is pure Python**, not an LLM. It is the only writer of the task graph. Observer/AWM is the only writer of facts/memory. Planner returns proposals, not direct state mutations.
5. **No runtime access to gold labels** (`label.tool_calls`, `label.tool_results`, `label.final_state`). These may be used by offline training/evaluation code only.
6. **No third-party LLM APIs** during final inference. Prefer local model files and an in-process backend. A local endpoint is optional for development, but final Docker must run without external network access.
7. **Never invent tool names, entity IDs, arguments, state hashes, environment interfaces, or unavailable data.** Always consult schemas returned by the environment.
8. **Never blindly retry state-changing calls** (payments, messages, orders, calendar modifications) when the previous effect is uncertain.
9. **Keep every sample isolated**: new AWM, task graph, tool-call trace, and environment session for each request. Do not leak state across samples.
10. Keep a **strict maximum budget** for LLM calls, plan patches, graph nodes, execution steps and time. On exhaustion, stop safely and return a valid output using the actual official adapter.
11. Use `ruff`/`pytest`; include type hints and structured errors. Avoid heavy agent frameworks and vector DBs in baseline.
12. **Inspect the supplied local LifeMate kit first** (`train/zaic_tools`, `public_test/zaic_tools`, README, catalogs, environment state). Treat its documented API/code as the source of truth for invocation signatures, state hashes, tool schemas and validation. Use `OfficialEnvironmentAdapter` stubs only for methods that remain genuinely undocumented or uncallable after inspection; mocks must still run.

### 0.3 Critical compatibility checks before deployment

- Confirm the **LifeMate** total parameter/model limits and runtime budget against its own current Rules. `Qwen3-4B` is approximately 4.0B parameters, and PhoWhisper adds more parameters. Do **not** assume an exact 4.0B *combined* cap would allow both; the user-proposed combination is **provisional until checked**.
- Verify the approved model weight release dates, licences, inference hardware and packaging policy against official Rules.
- The competition output examples include `tool_calls` and `state_hash`, plus special no-action/missing-information behavior. Verify the EXACT meaning and invocation of `state_hash`, special actions and result formatting by reading the supplied `zaic_tools` README, executor and validator before coding them. Do not assume example API names match local kit.
- Do not load remote model weights at runtime. For final submission, resolve models to local paths and verify offline startup.

**Authoritative references (for humans and coding agent):**
- LifeMate description: https://challenge.zalo.ai/portal/lifemate
- PhoWhisper: https://huggingface.co/vinai/PhoWhisper-small
- Qwen3-4B: https://huggingface.co/Qwen/Qwen3-4B
- Source design supplied by team: *Thành phần bạn hỏi.docx*, 53 pages.

---

## 0.4 VERIFIED dataset layout and loader instructions (read this BEFORE implementing repository code)

This section is grounded in the team's `dataset_structure_report.txt`, generated on Windows for the extracted LifeMate bundle. **The report is a filesystem inventory, not a dump of tool schemas or environment APIs.** The coding agent running on the user's machine MUST inspect actual source files before writing the official adapter.

### 0.4.1 Exact paths on the team's machine

Working directory (current project root):

```text
C:\contest\ZAIC2026\
└── train+public_test\                   # Outer extraction folder
    ├── __MACOSX\                        # Ignore extracted macOS metadata
    └── train+public_test\               # TRUE BUNDLE ROOT
        ├── README.md
        ├── VERSION
        ├── train\
        │   ├── train.jsonl               # 1,545 lines/samples
        │   ├── audio\
        │   │   └── train_0001\train_0001.wav
        │   └── zaic_tools\              # Contains README and kit package
        └── public_test\
            ├── public_test.jsonl         # 634 lines/samples
            ├── sample_submission.jsonl   # 3 illustrative records, NOT train data
            ├── public_test_tools_catalog.json
            ├── audio\
            │   └── public_0002\public_0002.wav
            ├── public_test_environment\
            │   └── public_0002\state.json
            └── zaic_tools\
                ├── README.md
                ├── executor.py
                ├── validate.py
                ├── utils.py
                ├── __init__.py
                └── __main__.py
```

**IMPORTANT:** Only the example files and paths shown above were explicitly listed in the report; other files exist and must be inspected in situ. Do not assume the absence of tools/state files from a truncated tree listing. The report counts **22,885 files, 8,739 directories, ~1.055 GB** over the whole outer extraction, including `__MACOSX` and non-sample metadata. It also counts 13,938 `.wav` files **across the tree**, which is NOT a verified count of distinct train/public-test samples. Counts for train/public-test JSONL above are exact report line counts (not yet independent validation of ID uniqueness or JSON parsing for every line).

### 0.4.2 Machine-independent configuration

Do NOT hard-code `C:\contest\ZAIC2026` inside modules. Add to `configs/baseline.yaml` (and support CLI overrides):

```yaml
dataset:
  bundle_root: ./train+public_test/train+public_test
  train_manifest: train/train.jsonl
  public_test_manifest: public_test/public_test.jsonl
  train_split_dir: train
  public_test_split_dir: public_test
  sample_submission: public_test/sample_submission.jsonl
  public_test_tool_catalog: public_test/public_test_tools_catalog.json
  public_test_environment: public_test/public_test_environment
  exclude_metadata_dirs: [__MACOSX]
```

All relative config paths above are relative to the repo/project working directory or `bundle_root` as appropriate; **document one consistent resolution rule** and allow an absolute override for Docker/other machines. Resolve using `pathlib.Path`, not string concatenation or Windows-only separators.

### 0.4.3 JSONL schema and AUDIO RESOLUTION RULE (verified)

- `train/train.jsonl`: 1,545 samples; first record fields: `id`, `audio`, `audio_text`, `context`, `history`, `label`.
- `public_test/public_test.jsonl`: 634 samples; first record fields: `id`, `audio`, `context`, `history`. It does **not** show `audio_text` or `label`.
- `public_test/sample_submission.jsonl`: 3 example records; fields `id`, `tool_calls`, `state_hash`; **submission examples are not input samples**.
- The `audio` value is a relative path like `audio/train_0001/train_0001.wav` or `audio/public_0002/public_0002.wav`.
- The inventory explicitly checked: **audio exists relative to the JSONL's own parent directory = True** for both train and public test. Audio does **not** resolve relative to the OUTER dataset root.

Canonical loader algorithm:

```python
from pathlib import Path

def resolve_audio_path(jsonl_path: Path, audio_field: str) -> Path:
    # JSONL uses '/' regardless of Windows/Unix; support both slash styles safely.
    relative = Path(audio_field.replace('\\', '/'))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe audio path in manifest')
    base = jsonl_path.resolve().parent
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError('Audio path escapes JSONL directory')
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved
```

Implement `app/dataset_io.py` containing `load_jsonl(manifest_path)`, `resolve_audio_path`, `get_sample_by_id`, `iterate_samples(split)`, and split-specific validation. **One manifest record = one sample**. Never infer the sample count by counting `.wav` files. Do not recursively read all `.json` files as samples: environment/state JSON has a distinct purpose.

### 0.4.4 Train / public-test isolation and evaluation

- Train: `audio_text` is a **reference transcript for ASR evaluation**, and `label` is for offline evaluation/supervision ONLY. Never feed either into the real audio-inference pipeline; provide a deliberately named `--input-mode transcript_reference` for debugging if desired, disabled in competition inference.
- Public test: use **audio and public context** for inference; never synthesize missing labels or use public-test outputs to train/tune models. The public test package includes environment state; treat it as **environment initialization through the provided kit**, not as a shortcut to gold outcomes.
- Derive a fixed, seeded train/validation split **from `train.jsonl` only** and persist chosen IDs to `outputs/` (ignored by Git). Keep whole-sample isolation for facts/graph/environment per run.
- Strip any `label`, `audio_text` and evaluation-only fields from `RuntimeSample` given to inference in audio mode. Add tests checking this invariant.
- For evaluation, use documented helpers under `zaic_tools` and actual train labels without passing gold responses to Agent modules.

### 0.4.5 Inspect and reuse provided kit BEFORE implementing executor

The report CONFIRMS the existence of `train/zaic_tools/README.md`, `public_test/zaic_tools/README.md`, `public_test/zaic_tools/executor.py`, `validate.py`, `utils.py`, `__main__.py`, `public_test_tools_catalog.json` and per-public-sample `public_test_environment/<id>/state.json`. **We have not inspected the CONTENTS of those files**, so do NOT assume their method signatures, state-mutation policy, official tool names or exact state-hash API.

Mandatory discovery workflow for the coding agent on the user's machine:

1. Read `bundle_root/README.md`, both `zaic_tools/README.md` files, and `VERSION`.
2. Inspect `zaic_tools/executor.py`, `validate.py`, `__main__.py` and relevant `apps` packages; identify official invocation, catalog loading, state initialization, execution trace, and state-hash handling.
3. Inspect `public_test_tools_catalog.json` and **one** representative `public_test_environment/<id>/state.json` schema. Treat state files as immutable inputs; do not patch/simulate oracle results.
4. Confirm whether train has a corresponding environment/catalog, and discover it from existing files. **Do not invent paths.**
5. Document exact kit commands/APIs with citations to file paths/lines in `docs/environment_mapping.md`. Implement adapter thinly over these local APIs, reuse their validator/executor instead of recreating the execution semantics.
6. Run a read-only introspection smoke test first, then a state-changing tool only inside an isolated copy/sandbox of a permitted train-derived test environment. Do not modify the provided dataset directory.
7. Where kit method names truly cannot be established, isolate a `NotImplementedError` with a specific TODO; this must NOT block the deterministic `MockEnvironment` tests.

The default source of truth for *which tools can actually execute* must be the **actual per-sample provided environment + installed-app/tool catalog**, not an invented universal list. Never assume sample-state files are gold final states.

### 0.4.6 Dataset loader & kit-specific acceptance tests

Add `tests/test_dataset_loader.py` with tests for nested bundle root, both split manifests, train-vs-public schema differences, JSONL-relative WAV lookup, missing WAV, malicious `../` path, ignoring `__MACOSX`, `sample_submission.jsonl` rejection as an input, and labels excluded from inference. Add a kit introspection script `scripts/inspect_kit.py` that reports discovered callable interfaces and catalogs without modifying state. It must work WITHOUT downloading models or making network requests.

When the data is accessible locally, demonstrate at least:

```powershell
python -m app.run_one --config configs/mock.yaml --split train --id train_0001
python -m app.run_one --config configs/mock.yaml --split public_test --id public_0002
python -m app.run_dataset --config configs/mock.yaml --split train --limit 10
python -m scripts.inspect_kit --config configs/baseline.yaml
```

The CLI arguments are **interfaces that the coding agent must implement**, not claims that these scripts already exist. First make mock runs work while loading REAL manifest/context/audio paths; then switch LLM/ASR and environment adapters independently. If a sample's environment is not provided, report this clearly and use an isolated deterministic mock; never fabricate a kit response.


## 1. Ownership and repository tree

```text
lifemate-baseline/
├── README.md                       # setup / quickstart / contracts / team guide
├── AGENTS.md                       # copy of this instruction for coding assistants
├── pyproject.toml                  # editable install, dependencies, pytest, ruff
├── .gitignore
├── .env.example                    # no secrets
├── configs/
│   ├── baseline.yaml               # model paths, budgets, adapters, prompts
│   ├── mock.yaml
│   └── experiments/               # experiment overrides only
├── core/                           # SHARED, CONTRACT-FIRST (jointly reviewed)
│   ├── __init__.py
│   ├── contracts.py                 # Pydantic I/O models and enums
│   ├── interfaces.py                # Protocol/ABC interfaces
│   ├── errors.py
│   ├── references.py                # safe typed fact paths
│   ├── json_utils.py                # LLM JSON parse & schema validation
│   ├── llm.py                       # ONE reusable Qwen backend + mock client
│   ├── config.py
│   └── events.py                    # event taxonomy, trace records
├── modules/
│   ├── asr/                         # OWNER 1
│   │   ├── __init__.py
│   │   ├── service.py
│   │   ├── pho_whisper.py
│   │   ├── audio.py
│   │   ├── mock.py
│   │   ├── tests/
│   │   └── experiments/            # owner-local scripts and configs
│   ├── perception/                  # OWNER 2
│   │   ├── service.py
│   │   ├── prompts/parse_intents.txt
│   │   ├── validators.py
│   │   ├── mock.py
│   │   ├── tests/
│   │   └── experiments/
│   ├── planner_controller/          # OWNER 3 / INTEGRATION LEAD
│   │   ├── planner.py
│   │   ├── controller.py
│   │   ├── scheduler.py
│   │   ├── guards.py
│   │   ├── graph_store.py
│   │   ├── patch_validator.py
│   │   ├── prompts/
│   │   │   ├── build_plan.txt
│   │   │   ├── expand_task.txt
│   │   │   └── repair_plan.txt
│   │   ├── mock.py
│   │   ├── tests/
│   │   └── experiments/
│   ├── tool_manager/                # OWNER 4
│   │   ├── service.py
│   │   ├── registry.py
│   │   ├── retriever.py
│   │   ├── selector.py
│   │   ├── grounder.py
│   │   ├── validator.py
│   │   ├── executor.py
│   │   ├── prompts/select_ground.txt
│   │   ├── mock.py
│   │   ├── tests/
│   │   └── experiments/
│   └── observer_awm/                # OWNER 5
│       ├── observer.py
│       ├── awm.py
│       ├── fact_extractors.py
│       ├── evaluators.py
│       ├── issues.py
│       ├── mock.py
│       ├── tests/
│       └── experiments/
├── app/                              # integration, thin adapters only
│   ├── pipeline.py
│   ├── dataset_io.py                # verified JSONL loading and audio resolution
│   ├── environment.py                # EnvProtocol; MockEnv & OfficialEnv adapters
│   ├── competition_io.py             # official input/output serialization
│   ├── build_services.py             # dependency injection / module factories
│   ├── run_one.py
│   ├── run_dataset.py
│   └── diagnostics.py
├── tests/
│   ├── fixtures/                     # synthetic scenarios, no gold leaked
│   │   ├── rainy_reschedule.json
│   │   ├── corrected_intent.json
│   │   ├── transfer_derived_amount.json
│   │   ├── missing_contact.json
│   │   ├── unsupported_request.json
│   │   └── uncertain_action.json
│   ├── test_contracts.py
│   ├── test_dataset_loader.py
│   ├── test_graph_invariants.py
│   ├── test_pipeline_mock.py
│   └── test_competition_adapter.py
├── scripts/
│   ├── sanity_check.py
│   ├── inspect_kit.py               # inspect supplied local zaic_tools APIs
│   ├── evaluate_train.py
│   └── download_models.py           # development-time ONLY, never at inference
├── docs/
│   ├── architecture.md
│   ├── dataset_layout.md
│   ├── contracts.md
│   ├── environment_mapping.md
│   └── team_workflow.md
└── outputs/                          # gitignored traces, analysis, submissions
```

**Folder ownership rule:** Each member edits their module directory and local experiments freely. Changes to `core/contracts.py`, `core/interfaces.py`, `app/pipeline.py` or competition adapters require a team review because they affect all five modules. Experiments must **not** mutate production code or rely on uncommitted local hacks.

Recommended experiment interface: `configs/experiments/<name>.yaml` selects the module implementation by a factory key (e.g. `perception_impl=prompt_v2`), not by ad hoc edits of the pipeline.

---

## 2. Exactly one source of truth per data type

| Data | Sole authoritative owner | Readers | Mutations |
|---|---|---|---|
| Raw request & structured intent | Perception output, stored immutably in AWM | Planner/Observer | Never silently rewrite user intent |
| `GoalSpec` and `TaskGraph` | Planner proposals; **Controller's GraphStore** applies patches | Controller/Observer/Tool Manager | Controller only |
| Task lifecycle status | GraphStore controlled by Controller | All via snapshot | Controller only, based on verdicts |
| `facts`, `entities`, `issues`, `execution_log` | AWM Manager | All via snapshot | AWM only |
| Tool availability/schema | Environment's installed apps + ToolRegistry | Tool Manager/Planner | Environment/adapter only |
| Tool side effects | Official environment | Observer through tool results | Executor via SDK only |
| Final tool-call trace | Environment adapter / execution recorder | Competition formatter | Append after actual execution only |

**Do not duplicate mutable task statuses in both TaskGraph and AWM.** `MemorySnapshot` may contain a **read-only view** of current graph states; Controller's GraphStore remains canonical. For testability, every call receives immutable snapshots (deep copy/Pydantic frozen objects or copies).

---

## 3. Shared JSON contracts — implement first

Implement these as Pydantic models in `core/contracts.py`. Use `Literal`/`Enum` for types; all IDs are strings. The JSON below is illustrative; fields with `null` and `[]` must be supported.

### 3.1 InputEnvelope and Transcript

```json
{
  "id": "train_0001",
  "audio_path": "audio/train_0001/train_0001.wav",
  "context": {
    "current_time": "2026-11-28T07:10:00+07:00",
    "timezone": "Asia/Ho_Chi_Minh",
    "location": {"lat": 16.0544, "lng": 108.2022},
    "user_profile": {"city": "Đà Nẵng"},
    "history": [],
    "installed_apps": {"weather": {"tools": ["weather.get_forecast"]}}
  }
}
```

```json
{"text": "Nếu mai mưa thì dời chạy bộ muộn 1 tiếng, nhắn Sếp Dũng giờ mới; không mưa thì thôi.", "language": "vi", "confidence": null}
```

Only approved input and context fields may enter inference. `label` is never in `InputEnvelope`.

### 3.2 StructuredIntent (Perception output)

Keep **exactly four top-level semantic groups**: `intents`, `conditions`, `relations`, `constraints` (plus optional metadata only for version and source span if needed).

```json
{
  "intents": [
    {"id": "i1", "name": "reschedule_event", "slots": {"event": "chạy bộ", "shift_minutes": 60}, "condition_id": "c1", "condition_value": true},
    {"id": "i2", "name": "send_message", "slots": {"recipient": "Sếp Dũng", "content": "giờ chạy bộ mới"}, "condition_id": "c1", "condition_value": true}
  ],
  "conditions": [{"id": "c1", "expression": "ngày mai có mưa"}],
  "relations": [{"from": "i2", "to": "i1", "type": "uses_result"}],
  "constraints": [{"type": "no_action", "condition_id": "c1", "condition_value": false}]
}
```

Requirements: return **only currently active intents** after self-corrections; never invent entity IDs, exact amounts, or unsupported tools; unresolved values can remain natural-language strings. `relations[].type` starts with `after | uses_result`, extend via reviewed contract changes only. Conditional ID references must exist. `condition_value` must be boolean or null. For compound conditions, preserve the original expression; Planner may parse an expression tree later.

### 3.3 GoalSpec / Guard / TaskGraph

Represent conditional goals with explicit `when` and verifiable criteria. A `guard` is a **predicate over facts**, NOT a dependency; guard evaluation is tri-state `TRUE/FALSE/UNKNOWN`.

```json
{
  "graph_id": "plan_0001",
  "version": 1,
  "goals": [
    {"id": "g_reschedule", "description": "Dời chạy bộ +60 phút nếu mưa", "when": {"fact": "weather.tomorrow.rain", "op": "eq", "value": true}, "success_criteria": [{"fact": "updated_event.start", "op": "exists"}]},
    {"id": "g_notify", "description": "Nhắn giờ mới cho Sếp Dũng nếu mưa", "when": {"fact": "weather.tomorrow.rain", "op": "eq", "value": true}, "success_criteria": [{"fact": "sent_message.contact_id", "op": "exists"}]}
  ],
  "nodes": {
    "t_weather": {
      "id": "t_weather", "type": "DISCOVERY", "description": "Check tomorrow forecast", "parent_id": null,
      "depends_on": [], "guard": null, "inputs": {"date": "2026-11-29"},
      "produces": ["weather.tomorrow.rain"], "success_criteria": [], "status": "PENDING"
    },
    "t_reschedule": {
      "id": "t_reschedule", "type": "ABSTRACT", "description": "Dời lịch chạy bộ +60 phút", "parent_id": null,
      "depends_on": ["t_weather"], "guard": {"fact": "weather.tomorrow.rain", "op": "eq", "value": true},
      "inputs": {"event_name": "chạy bộ", "shift_minutes": 60},
      "produces": ["updated_event"], "success_criteria": [], "status": "PENDING"
    },
    "t_notify": {
      "id": "t_notify", "type": "ABSTRACT", "description": "Thông báo giờ mới", "parent_id": null,
      "depends_on": ["t_reschedule"], "guard": {"fact": "weather.tomorrow.rain", "op": "eq", "value": true},
      "inputs": {"recipient": "Sếp Dũng", "content": "giờ mới"},
      "produces": ["sent_message"], "success_criteria": [], "status": "PENDING"
    }
  }
}
```

Task `type`: `ABSTRACT | DISCOVERY | ACTION | COMPUTE`. Task `status`: `PENDING | BLOCKED | READY | RUNNING | EXPANDED | DONE | FAILED | SKIPPED`. `depends_on` must reference existing nodes, with no cycles. `parent_id` is hierarchical expansion, not an execution dependency by itself.

**Important handling of expanded parents:**
- `EXPANDED` is nonterminal; do not execute the parent directly.
- Child tasks inherit the effective guard and external dependencies of their parent, unless Planner specifies an explicit narrower guard. The GraphStore performs this inheritance deterministically, not the LLM.
- Parent becomes `DONE` only when the expanded child's success condition is verified, with all required child tasks resolved.
- A dependent task (`t_notify`) becomes runnable only after `t_reschedule` is `DONE`, never while it is merely `EXPANDED`.
- Child failure can fail/block its parent. Child `SKIPPED` under a valid false guard must not be treated as failed.

**Fact references** should use typed selectors, e.g.:

```json
{"$ref": "fact", "key": "running_event", "path": ["id"]}
```

Disallow arbitrary Python expressions in references. A computation (e.g. `+60 minutes`) is a `COMPUTE` task with a known operator implemented in Python, not untrusted `eval()`.

### 3.4 AgentWorkingMemory and provenance

```json
{
  "session_id": "train_0001", "revision": 3,
  "request": {"intents": [], "conditions": [], "relations": [], "constraints": []},
  "context": {"current_time": "2026-11-28T07:10:00+07:00", "timezone": "Asia/Ho_Chi_Minh"},
  "facts": {
    "weather.tomorrow.rain": {
      "value": true,
      "status": "VERIFIED",
      "source": {"type": "tool_result", "task_id": "t_weather", "execution_id": "exec_001"}
    }
  },
  "goal_state": {"g_reschedule": {"status": "UNSATISFIED", "evidence": []}},
  "execution_log": [{"id": "exec_001", "task_id": "t_weather", "tool": "weather.get_forecast", "status": "EXECUTED"}],
  "issues": []
}
```

Each fact should have source/provenance and verifiability. Distinguish **not observed**, `UNKNOWN`, `NOT_FOUND`, `FALSE`, and tool error. Do not overwrite prior significant state without retaining evidence. Use `get_snapshot(task_id)` to supply only relevant facts to a prompt.

### 3.5 ToolFeedback, ToolExecutionResult, PlanPatch and Verdict

```json
{
  "task_id": "t_sms",
  "status": "MISSING_ARGUMENTS",
  "selected_tool": "sms.send",
  "missing": [{"argument": "contact_id", "required_fact": "boss_contact.id", "known": "Sếp Dũng"}]
}
```

```json
{
  "task_id": "t_weather",
  "status": "EXECUTED",
  "tool_call": {"name": "weather.get_forecast", "arguments": {"date": "2026-11-29"}},
  "raw_result": {"ok": true, "forecast": [{"date": "2026-11-29", "rain": true}]},
  "execution_id": "exec_001"
}
```

```json
{
  "base_version": 1,
  "operations": [
    {"op": "ADD_TASK", "task": {"id": "t_contact", "type": "DISCOVERY", "description": "Find contact Sếp Dũng", "parent_id": null, "depends_on": [], "guard": null, "inputs": {"query": "Sếp Dũng"}, "produces": ["boss_contact"], "success_criteria": [], "status": "PENDING"}},
    {"op": "ADD_DEPENDENCY", "task_id": "t_sms", "depends_on": "t_contact"}
  ]
}
```

PlanPatch allowed operations: `ADD_TASK`, `ADD_DEPENDENCY`, `EXPAND_TASK`, `UPDATE_TASK`, `SKIP_TASK`. Controller validates existence, acyclicity, parent-child inheritance and no changes to already-effected `DONE` tasks before applying.

`ToolFeedback.status`: `EXECUTED | MISSING_ARGUMENTS | INVALID_ARGUMENTS | TOOL_NOT_FOUND | AMBIGUOUS_TOOL | EXECUTION_ERROR | UNCERTAIN_EFFECT`.

`TaskVerdict.status`: `DONE | UNSATISFIED | UNKNOWN | FAILED`.

`GoalVerdict.status`: `SATISFIED | UNSATISFIED | UNKNOWN | UNRECOVERABLE`.

Use explicit semantic issue codes (`MISSING_FACT`, `ENTITY_NOT_FOUND`, `ENTITY_AMBIGUOUS`, `RESULT_MISMATCH`, `UNCERTAIN_EFFECT`, `GOAL_BLOCKED`). Preserve the raw tool result in trace, but avoid pushing large raw JSON into the LLM prompt.

---

## 4. Interfaces that all members must implement

Create the following Protocols in `core/interfaces.py` and corresponding concrete implementations under their owners:

```python
class ASRModule(Protocol):
    def transcribe(self, audio_path: str) -> Transcript: ...

class InputPerception(Protocol):
    def perceive(self, transcript: Transcript, runtime_context: dict, history: list) -> StructuredIntent: ...

class PlanBuilder(Protocol):
    def build_plan(self, request: StructuredIntent, memory: MemorySnapshot) -> TaskGraph: ...
    def expand_task(self, task: TaskNode, memory: MemorySnapshot, feedback: dict | None = None) -> PlanPatch: ...
    def repair_plan(self, graph: TaskGraph, memory: MemorySnapshot, feedback: dict) -> PlanPatch: ...

class ToolManager(Protocol):
    def prepare(self, task: TaskNode, memory: MemorySnapshot, available_tools: list) -> PreparedToolCall | ToolFeedback: ...
    def execute(self, prepared: PreparedToolCall) -> ToolExecutionResult: ...
    def run(self, task: TaskNode, memory: MemorySnapshot, available_tools: list) -> ToolExecutionResult | ToolFeedback: ...

class Observer(Protocol):
    def process(self, result: ToolExecutionResult, task: TaskNode, memory: MemorySnapshot) -> ObservationFeedback: ...
    def evaluate_task(self, task: TaskNode, memory: MemorySnapshot) -> TaskVerdict: ...
    def evaluate_goal(self, goals: list[GoalSpec], graph: TaskGraph, memory: MemorySnapshot) -> GoalVerdict: ...

class AWMManager(Protocol):
    def initialize(self, request: StructuredIntent, context: dict) -> None: ...
    def apply_update(self, update: MemoryUpdate) -> None: ...
    def get_fact(self, key: str) -> Fact | None: ...
    def get_snapshot(self, task_id: str | None = None) -> MemorySnapshot: ...

class Environment(Protocol):
    def list_available_tools(self) -> list[ToolSchema]: ...
    def call_tool(self, name: str, arguments: dict) -> dict: ...
    def get_state_hash(self) -> str: ...
```

`Environment` protocol above is **our internal abstraction**, not a claim about official SDK method signatures. The official adapter must translate to real kit APIs. The competition output adapter must return the official required JSON keys and order, including state hash obtained from the official environment.

---

## 5. Model backend: one Qwen3-4B + PhoWhisper

### 5.1 Shared Qwen LLMClient

Implement `core/llm.py` as `LLMClient.generate_json(prompt_name, payload, response_model, settings)`:
- Load Qwen once via `transformers` (`Qwen/Qwen3-4B` or configured local snapshot).
- Use `tokenizer.apply_chat_template` with `enable_thinking=False` by default for compact JSON tasks; optional `enable_thinking=True` **only for planner repair or difficult decomposition** if profiling justifies it.
- Use controlled max output tokens per step (e.g. perception 512, planner build 900, repair 700, tool grounding 384); these are **initial tunable budgets**, not performance guarantees.
- Use schema-aware decoding when available; otherwise parse JSON, validate with Pydantic, do **one bounded format-repair** attempt, then return an explicit structured error.
- Never interpret `<think>...</think>` as JSON payload or allow reasoning text into output. With non-thinking mode, no think block is expected; still handle model output defensively.
- Cache the model/tokenizer in one singleton/factory per process, with reference passed to three modules.
- Provide `MockLLMClient` with deterministic fixture mappings so tests never need weights.
- Set decoding params in configuration; include random seed; do not assume greedy is best for Qwen3. Preserve reproducibility by keeping prompts, model versions and settings logged.

### 5.2 PhoWhisper ASR

- Default checkpoint: `vinai/PhoWhisper-small`, *subject to actual parameter and speed limits*. Keep the variant configurable.
- Read mono audio, resample only as model requires, transcribe with local `transformers` ASR pipeline, return `Transcript(text, language='vi', confidence=None)`.
- Only light text normalization (whitespace, punctuation); **do not change numbers, names, negation or user intent**.
- For `asr=mock`, load a fixture transcript; for `asr=pho_whisper`, load real local weights.
- ASR owner adds optional WER/CER, latency and real-time factor evaluation using allowed training/validation data.

### 5.3 Download/offline policy

Provide a **separate preparation script** to download models during development and a `local_files_only=True` production mode. Do not download at import time or during contest inference. Document the precise dependency versions, checkpoint commit IDs and licences in `README.md`.

---

## 6. Module 1 — ASR (owner 1)

**Input:** `audio_path` or an audio fixture. **Output:** `Transcript`.

Substeps: audio loader → preprocessing → PhoWhisper inference → safe transcript normalization → output validator.

Tests: file missing/empty; sample rate differences; Vietnamese date/name/negation preservation (do not promise recognition accuracy from mocks); mock audio path; no torch/model load for mock tests.

Definition of done: a working `ASRModule` with both `mock` and PhoWhisper implementations, a demo command and tests.

---

## 7. Module 2 — Input Perception (owner 2)

**Input:** `Transcript`, `current_time`, `timezone`, relevant user profile and history. **Do not feed full tool schemas, tool results or gold labels into this prompt.**

**Output:** `StructuredIntent` containing four groups: `intents + slots`, `conditions`, `relations`, `constraints`.

One LLM prompt for baseline:

```text
You are a Vietnamese voice-request semantic parser.
Output ONLY JSON matching the StructuredIntent schema.
Extract final ACTIVE intents after self-corrections; ignore cancelled intents.
Preserve conditions, negations, no-action constraints, and relations between intents.
Extract literal slots and normalized simple units only if unambiguous.
If a value requires app lookup, leave it unresolved as original text.
Do NOT choose tools, create task graphs, invent IDs/dates/money, or execute anything.
```

Pass **2–3 small few-shot examples**: (1) rainy conditional reschedule, (2) 'à thôi' cancellation, (3) multi-intent financial request. Keep user content isolated as data, not instructions to the parser. Validate JSON and ID references using Pydantic.

Tests: multiple intents; self-correction; negation; guard false; relative time preserved; incomplete slot; nonsense ASR output; no tool hallucination.

Definition of done: parse mocked transcripts to valid, faithful `StructuredIntent`; each example passes deterministic assertion tests.

---

## 8. Module 3 — Planner + Controller (owner 3)

### 8.1 Planner responsibilities and prompts

`build_plan()` receives StructuredIntent + relevant MemorySnapshot and emits `GoalSpec + TaskGraph` (or a TaskGraph containing goal specs). It creates **logical tasks, not necessarily tool calls**. `expand_task()` produces a `PlanPatch` with children when a task is too abstract. `repair_plan()` produces a `PlanPatch` when feedback demands new discovery/repair/replan. Never rewrite historical executed tasks.

Prompts are separate:
- `build_plan.txt`: "Generate a minimal DAG of logical tasks with dependencies and conditional guards. Do not invent tool outputs or IDs. Preserve user intent and no-op branches."
- `expand_task.txt`: "Expand ONE abstract task into smallest executable discovery/action/compute tasks, preserving requirements and order."
- `repair_plan.txt`: "Given blocker, current facts and graph, propose the SMALLEST allowed PlanPatch. Do not duplicate discovery requests or revisit confirmed effects."

### 8.2 Graph and task loop

- `GraphStore` owns and versions the single authoritative graph.
- `Scheduler` finds next **progressable** node (not a FIFO queue). Node can be an `ABSTRACT` ready for expansion or atomic with satisfied dependencies and a true guard.
- `GuardEvaluator` handles `TRUE/FALSE/UNKNOWN` and `all/any/not` expressions where supported. FALSE → `SKIPPED`; UNKNOWN → `BLOCKED` and require its provider task if one exists. Do not convert UNKNOWN to false.
- A BLOCKED task must **not spin**. Continue with another runnable task; if none, trigger repair/blocked handling once, then stop on no progress.
- For atomic tasks invoke `ToolManager.run()` for `DISCOVERY/ACTION`; `COMPUTE` uses a small trusted deterministic operator registry (e.g. time addition, simple arithmetic, format message), **not arbitrary generated code**.
- For tool feedback `MISSING_ARGUMENTS`, check AWM, then existing provider tasks, then ask Planner for discovery. Never create duplicate search tasks for identical fact and predicate.
- `EXPAND_TASK` patch sets parent to `EXPANDED`, adds children, creates relationships and guards; children contribute completion evidence to parent.
- After execution, always call Observer, apply AWM update, then handle TaskVerdict and GoalVerdict.
- Replan **only** if an actual blocker/failure/changed observation requires it; not after routine success.

### 8.3 Controller pseudocode (required semantics)

```python
def run_one(request: StructuredIntent, context: dict, env: Environment) -> AgentResult:
    awm.initialize(request, context)
    graph = graph_store.initialize(planner.build_plan(request, awm.get_snapshot()))

    for step in range(config.max_agent_steps):
        snapshot = awm.get_snapshot()
        verdict = observer.evaluate_goal(graph.goals, graph.snapshot(), snapshot)
        if verdict.status == "SATISFIED":
            break
        if verdict.status == "UNRECOVERABLE":
            break

        decision = scheduler.next_progressable(graph.snapshot(), snapshot)
        if decision is None:
            # No spin: attempt bounded unblock/repair once, else stop safely.
            if not try_unblock_or_repair(...):
                break
            continue

        task = decision.task
        if decision.kind == "EXPAND":
            graph_store.apply_validated_patch(planner.expand_task(task, snapshot))
            continue

        result = execute_atomic_or_compute(task, snapshot, env)
        if result.status == "MISSING_ARGUMENTS":
            handle_missing_via_existing_fact_or_provider_or_patch(result)
            continue
        if result.status in PREPARATION_ERRORS:
            handle_bounded_preparation_repair(result)
            continue

        feedback = observer.process(result, task, awm.get_snapshot())
        awm.apply_update(feedback.memory_update)
        graph_store.apply_task_verdict(feedback.task_verdict)
        handle_bounded_failure_or_replan(feedback)

    # Always serialize actual executed tool calls, obtain env state hash from official adapter.
    return output_adapter.finalize(env, execution_recorder)
```

This pseudocode is behavioral, not a literal drop-in code block. Implement the helpers with explicit bounded logic and tests; do **not** leave them as `...` in the final baseline.

### 8.4 Limits (defaults, configurable)

Start with `max_agent_steps=24`, `max_plan_nodes=36`, `max_expand_depth=4`, `max_replans_per_task=2`, `max_json_repair=1`, `max_tool_prepare_repair=2`; use actual benchmark latency to tune. Track a `progress_signature` (graph version, completed task IDs, facts revision, unresolved issues) to detect no-progress cycles.

Definition of done: supports conditional no-op, dynamic discovery, guarded dependencies, expanded parents, verified completion, bounded retry and valid final serialization in mock E2E tests.

---

## 9. Module 4 — Tool Retriever / Manager (owner 4)

### 9.1 Flow

`TaskSpec + MemorySnapshot + installed tools → retrieve candidates → select tool → ground arguments → validate schema → execute → ToolExecutionResult/ToolFeedback`.

**Registry:** indexed by exact real tool name and official JSON schema; only enable tools listed under the sample's `installed_apps` (and any official system tools). Do not infer available tools from examples only.

**Retriever:** start simple keyword/capability matching over descriptions; Top-K about 3–5. No embedding model is required or permitted by default (keeps parameter budget simple). If a task maps to exactly one capability confidently, choose directly. Otherwise prompt Qwen to select from candidate exact tool names.

**Grounder:** resolve values in this order: (1) literal supplied slots, (2) typed AWM references, (3) deterministic normalization (dates/currency/durations), (4) bounded LLM semantic mapping or message formatting. Never hallucinate IDs or balances.

**Validator:** validate required arguments, types, enums, dates, allowed app, unresolved references, restrictions, ambiguous entities and unexpected fields. Distinguish missing information from wrong formatting. No tool call on failed validation.

**Executor:** delegate real effects to the environment adapter, return raw result + tool name + arguments + execution ID. Append to public tool-call recorder **only when the call actually occurred**; avoid appending failed preparation attempts.

### 9.2 Missing arguments protocol

If `sms.send` needs `contact_id` and only name `Sếp Dũng` is available, return:

```json
{"task_id": "t_sms", "status": "MISSING_ARGUMENTS", "selected_tool": "sms.send", "missing": [{"argument": "contact_id", "required_fact": "boss_contact.id", "known": "Sếp Dũng"}]}
```

Controller checks fact / existing discovery provider; if absent, Planner creates `DISCOVERY` task using `contacts.search`. Tool Manager never inserts graph nodes itself.

### 9.3 Execution outcomes

- `EXECUTED` means a call was executed, **not** that a logical task succeeded.
- `EXECUTION_ERROR` means tool reported definite error; classify before retry.
- `UNCERTAIN_EFFECT` means the side effect is unknown; **do not retry state-changing tools** until verified through an allowed read tool, or safely stop.
- `TOOL_NOT_FOUND` means unavailable capability; reconsider alternative or final out-of-scope.

Definition of done: correct installed-tool filter, schema validation, typed references, dynamic discovery feedback, safe action retry, working mock and official adapter interface.

---

## 10. Module 5 — Observer + AWM (owner 5)

### 10.1 Flow

`ToolExecutionResult → Observation Parser → facts/entities + provenance → AWM Update → Task Evaluator → Goal Evaluator → feedback to Controller`.

Prefer deterministic extraction from structured tool results; use Qwen only for semantic ambiguity if necessary. AWM uses a Python dict/Pydantic; no vector DB or embedding model.

**Fact extraction:** e.g. `weather.get_forecast` with `rain=true` produces `weather.tomorrow.rain`. `calendar.list_events` produces a structured collection or resolved `running_event` after entity selection; `calendar.update_event` produces `updated_event` only when supported by the tool response/evidence. Preserve original and updated event information separately.

**Memory API:** `initialize`, `apply_update`, `get_fact`, `get_entity`, `get_snapshot(task_id)`, `get_execution_history`. Each fact has source execution ID and verification status.

**Task evaluator:** checks predicates, not just `ok=true`; distinguish `DONE`, `UNSATISFIED`, `UNKNOWN`, `FAILED`. If a mutation result cannot establish requested state, report `UNKNOWN` so Controller can consider a read-only verification task (if supported) rather than inventing success.

**Goal evaluator:** considers conditional active branch only; all required active criteria satisfied → `SATISFIED`; otherwise `UNSATISFIED`, `UNKNOWN`, or `UNRECOVERABLE`. If weather is false and no action is required, successfully skipping side-effect tasks may satisfy the request. Must not treat skipped branch as failure.

**Issue detector:** return issue codes, evidence and suggestions (`DISCOVER`, `REPAIR`, `REPLAN`, `STOP`), but do not call tools/Planner or mutate the graph.

Definition of done: provenance, separate unknown/not_found/false, task & goal evaluation, branch-aware no-op, focused snapshots and no shared state leakage across samples.

---

## 11. Dynamic planning: exact task decisions

| Situation | Controller action | Owner |
|---|---|---|
| Branch guard `UNKNOWN` | Wait for or request its provider task; no action yet | Scheduler/Planner |
| Dependency pending | `BLOCKED`; run other progressable task | Scheduler |
| Guard `FALSE` | `SKIPPED`; propagate to dependent branch where applicable | Scheduler |
| `ABSTRACT` | `expand_task`; apply validated patch | Planner → GraphStore |
| Atomic, args resolvable | Tool selection, grounding, validation, execution | Tool Manager |
| Missing args, fact in AWM | Retry preparation with resolved fact | Tool Manager |
| Missing args, provider task exists | Add/reuse dependency, wait | Controller |
| Missing args, no provider | Add `DISCOVERY` task using patch | Planner |
| Successful execution | Observer normalizes, records, verifies; next task | Observer/Controller |
| Recoverable invalid args | One bounded local repair | Tool Manager |
| Execution mismatch | Evaluate evidence; bounded patch/replan | Observer → Controller → Planner |
| Effect uncertain after mutation | Read-only verify if possible; no blind retry | Controller/Observer |
| Goal verified | Stop and serialize trace | Controller |
| Unsupported request | No app call; `tool_calls=[]` when official contract requires | Output adapter |
| Required missing info cannot be obtained | Use official `sys.ask_missing_info` protocol if applicable | Planner/Tool Manager → Output adapter |
| Budget exhausted/deadlock | Stop safely with valid output and diagnostic trace | Controller |

**Important:** `sys.ask_missing_info` is a **real special interaction in the official LifeMate description**, not a generic error string. The code must use the exact schema exposed by the official kit, never guess arguments for it. An out-of-scope request differs from missing info: the former uses empty tool calls, the latter may require a valid system tool call.

---

## 12. Worked end-to-end scenario: conditional update + notification

Input: *"Nếu mai mưa thì dời chạy bộ muộn 1 tiếng, nhắn Sếp Dũng giờ mới; không mưa thì thôi."*

1. PhoWhisper transcribes audio.
2. Perception returns two active intents (reschedule, notify) with `condition_id=c1`; relation `notify uses_result reschedule`; no-action constraint for false branch.
3. Planner creates GoalSpec and DAG with `t_weather`, abstract `t_reschedule`, abstract `t_notify`; latter two guarded on rain=true.
4. Tool Manager calls `weather.get_forecast` for correct relative date. Observer records weather fact with provenance.
5. If false: scheduler skips guarded tasks, Goal Evaluator checks no-action branch and exits with **no state-changing calls**.
6. If true: Planner expands `t_reschedule` into `calendar.list_events` → deterministic time shift +60min → `calendar.update_event`.
7. Observer stores original event `evt_01` and after update `updated_event`; task completion is evidenced.
8. For `t_notify`, Tool Manager lacks `contact_id`: emits missing fact report. Planner adds/reuses a contact discovery task (`contacts.search`) and dependency.
9. Observer stores `boss_contact.id`; Tool Manager resolves contact and formats SMS using **verified updated time**, calls `sms.send`.
10. Observer verifies result; evaluates active goals; Controller stops. Execution recorder captures the actual **ordered** tool calls. Official adapter retrieves actual final `state_hash`.

**Second scenario: self-correction**: *"Nếu mai mưa thì hủy lịch đá bóng... À mà thôi, cứ để lịch đó, chỉ cần xem giúp mai có mưa không."* Perception MUST omit cancelled calendar action; plan contains only read-only forecast request; no calendar mutation.

**Third scenario: derived financial argument**: *"Nạp 50 nghìn cho Bác Ba và chuyển ví cho Cô Mai số tiền điện tháng này."* The amount for transfer is unknown initially; require bill lookup and contact resolution. Never transfer with guessed amount, beneficiary or ID.

---

## 13. Test matrix and acceptance criteria (MANDATORY)

Implement tests in each module and one mock end-to-end suite. **Use synthetic fixtures** so no official environment is required for local smoke tests.

| Test | Expected behavior |
|---|---|
| A. Simple one-step action | One correct tool, valid args and final trace |
| B. Conditional true | Discovery forecast → guarded actions with correct order |
| C. Conditional false | No side effects; guarded tasks skipped; goal satisfied |
| D. Self-correction | Cancelled action absent from intent/plan/trace |
| E. Missing contact ID | `MISSING_ARGUMENTS` → one discovery task → action; no fake IDs |
| F. Dynamic amount lookup | Amount obtained from tool fact; never guessed |
| G. Already-resolved fact | No duplicate discovery; reuse AWM fact |
| H. Existing provider | Wait for provider instead of adding another search task |
| I. Tool missing from installed apps | Not called; alternative or out-of-scope behavior |
| J. Malformed LLM JSON | One bounded repair, then explicit error; no silent coercion |
| K. Invalid graph patch | Reject ID collision, cycles, invalid refs, DONE mutation |
| L. Parent expansion | Parent `EXPANDED` until children verified; dependents wait |
| M. Task result `ok=true` but no proof | `UNKNOWN` not automatically DONE |
| N. Uncertain side effect | No blind duplicate payment/message |
| O. Stale/unresolvable fact | Bounded repair; never infinite discovery loop |
| P. Multiple sequential samples | No cross-sample memory/model prompt pollution |
| Q. Final formatting | Ordered actual calls, real state_hash via adapter, proper id |
| R. Runtime no-network | Mock and offline real-model smoke test do not fetch remote assets |

**Minimum practical acceptance gate:**

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/rainy_reschedule.json
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/corrected_intent.json
```

Commands must be implemented and documented. If running on Windows, use `python` for entrypoints as above; avoid shell-specific hacks in code. Optional real-model smoke test should be behind an explicit switch so CI never loads multi-GB weights.

**Runtime logs (per sample):** request ID, model settings, ASR text, structured intents, graph versions, selected tasks, retrieved tools, resolved arguments (with secret redaction in shared logs), validator outcomes, tool call & observation, AWM fact revisions, goal verdict, final status, token counts and latency. Write JSONL traces under `outputs/` (gitignored).

**Evaluation:** use allowed training data and train-derived validation splits. When labels are present, evaluate ordered tool-call match, final-state correctness via supplied evaluator, per-module intent/slot correctness, end-to-end success, ASR WER/CER and latency. Do not pass gold traces into inference. Do not train on public/private test.

---

## 14. Development phases and ownership (implement in this order)

### Phase A — Contract-first skeleton, no GPUs (INTEGRATION LEAD + everyone)

1. Inspect actual dataset layout and the supplied `zaic_tools` kit per section 0.4; record discovered interfaces before designing official adapters. Create tree, `pyproject.toml`, README, default config.
2. Implement Pydantic contracts, reference resolver, `LLMClient` protocol and mock implementations.
3. Implement the dataset JSONL/audio loader and Environment abstraction, plus a deterministic `MockEnvironment` for at least 3 cases. Base the real adapter on inspected local `zaic_tools`, never on guessed APIs.
4. Implement `app/pipeline.py`, dependency injection and output adapter; all modules initially mock.
5. `pytest -q` must pass before any heavy model work.

### Phase B — Five owners work in parallel

1. ASR owner: PhoWhisper adapter, audio tests, mock fallback.
2. Perception owner: Qwen prompt + JSON schema, cancellation/conditional tests.
3. Planner/Controller owner: scheduler, graph patcher, guards, bounded task loop, prompts.
4. Tool Manager owner: installed-tool registry, selection, ground/validate/execute, mock environment binding.
5. Observer/AWM owner: fact extraction, memory snapshots, goal evaluation, issue detector.

**Integration check:** each member provides `README` in their folder, at least one runnable demo, unit tests and a mock implementation interchangeable with the real one.

### Phase C — Real local model integration

1. Prepare model weights on a development machine. Record exact snapshots and permissions.
2. Load **one shared** Qwen3-4B instance; plug into all three LLM-using services.
3. Plug in PhoWhisper; first compare transcript-mode vs audio-mode results to isolate ASR errors.
4. Test on a small, legal validation set; inspect tool-call traces and graph/memory updates.
5. Optimize call count, prompts, max new tokens, repetition handling, device placement and caching.

### Phase D — Official kit integration and submission

1. Implement/activate the official adapter against the **supplied local** `zaic_tools` package after inspecting its README, executor, validator, catalog and state handling. Use mocks only for genuinely unavailable operations.
2. Confirm available tool schemas, `sys.ask_missing_info`, state hash and submission JSONL contract.
3. Verify zero network calls and no weight downloads in submitted runtime.
4. Benchmark on allowed data; honor official parameter/time/compute constraints.
5. Create official Docker entrypoint and README with model declarations and exact commands, only after inspecting actual submission guidance.

---

## 15. Coding-agent execution checklist and final report

The coding agent MUST:

- [ ] Build the full repository tree and working files; **do not stop at pseudocode or empty stubs** except official adapter methods genuinely unsupported by the inspected local kit.
- [ ] Inspect the local extracted dataset and `zaic_tools` package, implement the JSONL/audio loader, document verified kit interfaces, and test both sample splits.
- [ ] Implement all contracts with clear validation errors and tests.
- [ ] Implement deterministic mock LLM/ASR/environment plus a working E2E controller loop.
- [ ] Add real PhoWhisper and Qwen3-4B adapters, lazy-loaded and configurable via local paths.
- [ ] Keep one shared LLM, not one model instance per module.
- [ ] Implement structured prompts and JSON parsing/repair for Perception, build/expand/repair planning, tool selection/grounding.
- [ ] Correctly distinguish dependency, guard and parent-child decomposition.
- [ ] Implement dynamic discovery, PlanPatch validation, no-progress detection and bounded loops.
- [ ] Implement provenance-aware AWM, task success verification, conditional goal evaluation.
- [ ] Respect installed tool schema and missing-info/out-of-scope behavior.
- [ ] Include actual execution log, official adapter placeholder and no fake `state_hash`.
- [ ] Make per-module experiments isolated and swappable by configuration.
- [ ] Run tests, report output, file tree and limitations transparently.

### Required final response from the coding agent

1. Summarize the files created and the five module entrypoints.
2. Show actual commands to install, run tests, run mock pipeline and run local-model pipeline.
3. Report which tests passed/failed with evidence; no invented success claims.
4. List any remaining unknown kit APIs after **inspecting the supplied source** as blockers only for the affected adapter methods, not for the mock baseline.
5. Describe how each teammate changes their module implementation through config, without modifying others.

### Do not overbuild

No distributed message broker, event streaming infrastructure, service mesh, vector database, multi-agent debate, heavy orchestration framework or learned embeddings in V1. A single Python process, well-typed contracts and a deterministic Controller are sufficient. Keep interfaces stable so module owners can experiment later.

---

## Appendix — suggested baseline config

```yaml
run:
  mode: mock                     # mock | local
  seed: 42
  max_agent_steps: 24
  max_plan_nodes: 36
  max_expand_depth: 4
  max_replans_per_task: 2
  max_json_repair: 1
  max_tool_prepare_repair: 2
  save_traces: true

models:
  asr:
    impl: pho_whisper            # mock in configs/mock.yaml
    checkpoint: vinai/PhoWhisper-small
    local_path: null            # required for strict offline runtime
  llm:
    impl: qwen3_4b               # mock in configs/mock.yaml
    checkpoint: Qwen/Qwen3-4B
    local_path: null            # required for strict offline runtime
    thinking_default: false
    context_limit: 8192
    max_new_tokens:
      perception: 512
      build_plan: 900
      expand_task: 700
      repair_plan: 700
      select_ground: 384

modules:
  asr_impl: pho_whisper
  perception_impl: prompt_v1
  planner_impl: prompt_v1
  tool_manager_impl: hybrid_v1
  observer_impl: rule_v1

dataset:
  bundle_root: ./train+public_test/train+public_test
  train_manifest: train/train.jsonl
  public_test_manifest: public_test/public_test.jsonl
  sample_submission: public_test/sample_submission.jsonl
  public_test_tool_catalog: public_test/public_test_tools_catalog.json
  public_test_environment: public_test/public_test_environment

environment:
  adapter: mock                 # mock | official
  enforce_installed_tools: true
  allow_unverified_retries: false
```

These are *starting engineering defaults*, not confirmed competition limits. The real LifeMate Rule/Submission Guidance governs final deployment.

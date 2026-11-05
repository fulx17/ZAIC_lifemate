# LifeMate V2 — Sổ tay cài đặt, chạy và phát triển

Tài liệu này hướng dẫn thành viên mới cài môi trường, chạy mock hoặc model local, audit một mẫu,
chạy dataset/evaluator, và tìm đúng mã nguồn để sửa. Lệnh ví dụ dùng PowerShell và chạy từ thư mục
gốc repo, ví dụ `C:\contest\ZAIC2026`.

## 1. LifeMate đang chạy theo kiến trúc nào?

Đường đi chính của một mẫu:

```text
manifest + audio + runtime context
    → ASR (audio thành transcript)
    → Discovery (chọn candidate từ tool catalog được phép)
    → Planner (tạo một TaskPlan; baseline gọi Qwen tối đa một lần)
    → Runtime (lập lịch, gọi Resolver, validate và thực thi tool)
    → Environment (mock hoặc simulator zaic_tools)
    → kết quả + audit
```

Năm module hiện tại là `asr`, `discovery`, `planner`, `resolver`, `runtime`. Đây là tên và layout
đang có trong code, không phải tên module của baseline V1 cũ. `app/` lắp các module và điều khiển
chạy; `core/` chứa contracts dùng chung. Discovery, Resolver và Runtime là deterministic, không gọi
Qwen. PhoWhisper là model ASR riêng; Qwen chỉ lập kế hoạch.

## 2. Cài đặt môi trường

### 2.1 Cài dependencies để phát triển/test mock

Mở PowerShell tại repo:

```powershell
Set-Location C:\contest\ZAIC2026
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

`pyproject.toml` yêu cầu Python từ 3.10 trở lên. Extra `dev` cài pytest và Ruff. Nếu PowerShell
chặn activate script, có thể bỏ qua bước activate và gọi trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m app.run_one --help
```

Kiểm tra repository:

```powershell
python -m scripts.sanity_check --config configs/mock.yaml
python -m pytest -q
ruff check .
```

### 2.2 Chuẩn bị chạy PhoWhisper và Qwen local

Cần internet ở bước tải weights, đủ dung lượng đĩa cho cả hai snapshot và môi trường Python/PyTorch
phù hợp với CUDA trên máy. Trước tiên cài dependencies inference:

```powershell
python -m pip install -e ".[dev,local-models]"
```

Script tải weights dùng riêng `huggingface_hub`; cài package này trong đúng virtualenv:

```powershell
python -m pip install huggingface_hub
```

Tải đúng snapshot đã pin trong `configs/baseline.yaml` (revision là commit ID, không dùng nhánh
`main` để tránh weights thay đổi ngoài ý muốn):

```powershell
python -m scripts.download_models `
  --repo-id vinai/PhoWhisper-medium `
  --revision 55a7e3eb6c906de891f8f06a107754427dd3be79 `
  --local-dir C:\models\PhoWhisper-medium

python -m scripts.download_models `
  --repo-id Qwen/Qwen3-4B-Instruct-2507 `
  --revision cdbee75f17c01a7cc42f958dc650907174af0554 `
  --local-dir C:\models\Qwen3-4B-Instruct-2507
```

Nếu Hugging Face yêu cầu xác thực cho repository nào, đăng nhập theo quy trình Hugging Face của
nhóm trước khi tải; không ghi token vào YAML, source code hoặc Git. Các lệnh trên chỉ chuẩn bị
weights trên máy phát triển, không chạy trong inference.

Kiểm tra thư mục đã được tạo:

```powershell
Test-Path C:\models\PhoWhisper-medium
Test-Path C:\models\Qwen3-4B-Instruct-2507
```

Mở [configs/baseline.yaml](../configs/baseline.yaml) và đặt `models.asr.local_path` cùng
`models.llm.local_path` khớp thư mục vừa tải. Ví dụ nếu giữ nguyên lệnh trên, các giá trị đã đúng:

```yaml
models:
  asr:
    local_path: "C:/models/PhoWhisper-medium"
  llm:
    local_path: "C:/models/Qwen3-4B-Instruct-2507"
```

Không đổi `checkpoint`/`revision` sang model khác mà chưa kiểm tra tương thích, license và luật thi.
Baseline mẫu đặt ASR `pho_whisper` trên `device: 0`/`float16`, Qwen quantization `4bit`, Planner
`qwen_single_shot`, Environment `official`.

Qwen 4-bit yêu cầu CUDA theo code hiện tại; model và tokenizer được tải với
`local_files_only=True`. Nếu thiếu weights, thiếu package hoặc GPU không đáp ứng yêu cầu, chương
trình báo lỗi thay vì tự tải model hay tự đổi sang mock. Sau khi tải xong, inference đọc snapshot
local và không cần internet. Không cần tải model để chạy mock/tests.

Có thể kiểm tra kit cục bộ theo chế độ chỉ đọc:

```powershell
python -m scripts.inspect_kit --config configs/baseline.yaml --split both
```

`scripts.download_models` là tiện ích tải snapshot trong khâu chuẩn bị, không chạy trong inference.
Nếu máy đích offline, tải snapshot trên máy có mạng trước rồi chuyển cả thư mục snapshot an toàn
sang máy đó và cập nhật `local_path`.

## 3. Chọn mode đúng

“Model” và “environment adapter” là hai lựa chọn riêng. Model tạo transcript/kế hoạch; environment
là nơi tool được validate và thực thi.

| Cấu hình | ASR / Planner | Environment | Mục đích |
|---|---|---|---|
| `configs/mock.yaml` | MockASR + MockPlanner | MockEnvironment | Smoke test, fixture, không cần model weights |
| `configs/baseline.yaml` | PhoWhisper local + Qwen local | OfficialEnvironment của kit | Chạy inference với model local trên simulator/kit của sample |

`--adapter mock|official` ghi đè environment trong YAML; nó **không** tự chuyển model. Vì vậy lệnh
với `baseline.yaml` vẫn dùng model local, dù adapter được ghi đè. Fixture của `run_one` luôn tạo
MockEnvironment và truyền transcript fixture; fixture chỉ hợp lệ khi `run.mode` là `mock`.

`OfficialEnvironment` dùng bộ giả lập/công cụ `zaic_tools` đi kèm dataset, không phải kết nối đến
ứng dụng thật của người dùng hay dịch vụ bên ngoài. Dù vậy, khi chạy trên sample thật, nó thực thi
tool trong trạng thái simulator và tạo tool-call trace/state hash. Luôn phân biệt điều này với
mock tests và không xem một lần chạy là bằng chứng về chất lượng model.

## 4. Chạy một mẫu

### 4.1 Smoke test nhanh, không có weights

Fixture là dữ liệu tổng hợp nằm trong `tests/fixtures/`, chạy cùng MockASR/MockPlanner:

```powershell
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/rainy_reschedule.json
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/missing_contact.json
python -m app.run_one --config configs/mock.yaml --fixture tests/fixtures/unsupported_request.json
```

MockPlanner chỉ hỗ trợ một số tình huống smoke test. Ví dụ `rainy_reschedule` hiện chỉ thực hiện
đọc dự báo thời tiết; không khẳng định nó hoàn thành cả chuỗi dời lịch và gửi tin nhắn.

Chạy một ID từ manifest bằng mock:

```powershell
python -m app.run_one --config configs/mock.yaml --split public_test --id public_0002
```

Lệnh này đọc audio/context/catalog thật của sample nhưng dùng implementations mock; nó không phải
đánh giá model.

### 4.2 Chạy baseline với model local thật

```powershell
python -m app.run_one --config configs/baseline.yaml --split public_test --id public_0002
```

Đây là audio mode mặc định: PhoWhisper nhận dạng file WAV, Qwen tạo plan trong một planning call,
rồi Runtime thực thi qua adapter `official` của kit. Lệnh cần dataset, weights và dependencies
local-models đã sẵn sàng.

Muốn dùng Qwen thật nhưng bỏ qua ASR để cô lập kiểm tra planner, có thể dùng transcript tham chiếu
của **train**:

```powershell
python -m app.run_one --config configs/baseline.yaml --split train --id train_0001 --input-mode transcript_reference
```

Chế độ này lấy `audio_text` train thay cho ASR, chỉ dùng offline trên train; không áp dụng cho
`public_test` và không được dùng như kết quả ASR.

### 4.3 Chạy nhiều mẫu và ghi submission

Bắt đầu bằng số lượng nhỏ:

```powershell
python -m app.run_dataset --config configs/mock.yaml --split train --limit 10 --output outputs/mock_train_10.jsonl
```

Chạy baseline local trên một phần public test:

```powershell
python -m app.run_dataset --config configs/baseline.yaml --split public_test --limit 10 --output outputs/baseline_public_10.jsonl
```

Bỏ `--limit` sẽ chạy cả split, có thể lâu và tốn tài nguyên. Chỉ bỏ giới hạn khi đã kiểm tra model,
adapter, output path và thời gian chạy. Submission mỗi dòng chỉ chứa `id`, `tool_calls`,
`state_hash`; status, trace và audit không nằm trong submission. `run_dataset` mặc định tắt audit
file để tránh tạo nhiều log.

## 5. CLI và tham số

Xem help của entrypoint bất cứ lúc nào:

```powershell
python -m app.run_one --help
python -m app.run_dataset --help
python -m scripts.eval_asr --help
```

### `python -m app.run_one`

| Tham số | Ý nghĩa |
|---|---|
| `--config PATH` | YAML cấu hình; mặc định `configs/mock.yaml`. |
| `--split train\|public_test` | Split manifest; mặc định `public_test`. |
| `--id ID` | ID cần chạy; bắt buộc nếu không truyền `--fixture`. |
| `--fixture PATH` | Chạy fixture tổng hợp; chỉ dùng với cấu hình mock. |
| `--adapter mock\|official` | Ghi đè environment adapter trong YAML. |
| `--input-mode audio\|transcript_reference` | ASR từ WAV (mặc định) hoặc transcript tham chiếu train. |
| `--audit-level off\|flow\|debug\|full` | Tắt, flow gọn, metadata an toàn, hoặc chi tiết đầy đủ vào file. |
| `--audit-console off\|summary\|flow` | Tắt console, in một dòng, hoặc in flow gọn. |
| `--audit-dir PATH` | Thư mục lưu file audit; mặc định `outputs/audit`. |
| `--include-trace` | Thêm trace nội bộ vào JSON kết quả in ra stdout; mặc định trace bị lược khỏi JSON đó. |

Không kết hợp `--fixture` với `--input-mode transcript_reference`. `transcript_reference` chỉ hợp
lệ cho `--split train`.

### `python -m app.run_dataset`

| Tham số | Ý nghĩa |
|---|---|
| `--config PATH` | Cấu hình; mặc định `configs/mock.yaml`. |
| `--split train\|public_test` | Split; mặc định `train`. |
| `--limit N` | Chạy tối đa N sample; nếu có, N phải lớn hơn 0. |
| `--output PATH` | Submission JSONL; mặc định `outputs/submission.jsonl`. |
| `--input-mode audio\|transcript_reference` | Transcript từ ASR hoặc tham chiếu train. |
| `--adapter mock\|official` | Ghi đè adapter trong YAML. |
| `--audit-level ...` | Các mức audit như `run_one`; mặc định của dataset là `off`. |
| `--audit-console off\|summary\|flow` | `run_dataset` chỉ bật console flow khi chọn `flow`; bình thường in summary từng sample và tổng kết. |
| `--audit-dir PATH` | Thư mục audit nếu bật audit. |

Với cấu hình dữ liệu tùy chỉnh, kiểm tra loader và manifest paths trước khi chạy dataset: vòng lặp
`iterate_samples` hiện dùng quy ước manifest `<bundle>/<split>/<split>.jsonl`.

## 6. Audit, trace và kết quả

### Mức audit

| Mức | File | Nội dung |
|---|---|---|
| `off` | Không tạo audit | Dùng khi chạy batch nếu không cần kiểm tra từng bước. |
| `flow` | `<id>.flow.txt` | Luồng ngắn: Discovery, plan, bind, tool, trạng thái cuối. |
| `debug` | Flow + `<id>.events.jsonl` | Metadata allowlist như tool/field names, statuses, counts; không có transcript hay giá trị args. |
| `full` | Flow + `<id>.events.jsonl` | Transcript ASR, plan Qwen, arguments đã resolve, tool results và kết quả cuối. |

`run_one` mặc định dùng `flow` và in một dòng summary nếu không truyền cờ audit; `run_dataset` mặc
định `off`. Nếu bật `debug` hoặc `full`, logger vẫn ghi file flow cùng event JSONL.

Ví dụ baseline với full audit:

```powershell
python -m app.run_one --config configs/baseline.yaml --split public_test --id public_0002 --audit-level full --audit-console flow --include-trace
```

Mở `outputs/audit/public_0002.events.jsonl`. Những event hữu ích gồm `transcript_ready`,
`discovery_completed`, `plan_generated`, `argument_resolution_detail`, `tool_call_detail`,
`tool_result_detail`, `execution_finished` và `pipeline_completed`. Flow tóm tắt hiện trên terminal;
`full` details không được in ra console.

`full` có thể lưu tên, địa chỉ, nội dung tin nhắn, thông tin thanh toán hoặc dữ liệu trả về từ tool.
Chỉ bật khi cần debug local; không commit/chia sẻ file. `--include-trace` là trace Runtime trong
JSON stdout, khác với file audit. Dữ liệu gửi cho cuộc thi vẫn được lọc riêng qua competition
adapter.

## 7. Cấu hình model/dataset

Hai YAML mẫu là điểm bắt đầu:

- [configs/mock.yaml](../configs/mock.yaml): `run.mode: mock`, model/ASR/planner mock, adapter mock,
  không cần weights.
- [configs/baseline.yaml](../configs/baseline.yaml): `run.mode: local`, PhoWhisper + Qwen local,
  planner single-shot, adapter official.

Các nhóm cấu hình:

- `run`: seed, giới hạn execution/LLM/time, trace và audit.
- `models.asr`: implementation, checkpoint/revision, local path, device/dtype.
- `models.llm`: implementation, local path, quantization và giới hạn sinh JSON.
- `modules`: implementation từng module và `discovery_top_k`.
- `dataset`: bundle root, manifest, catalog/environment paths.
- `environment`: adapter và chính sách tool.

Không phải mọi key nằm trong YAML mẫu đều hiện đang được đọc bởi runtime. Trước khi dựa vào một
tham số, tìm key trong code hoặc hỏi `python -m app.run_one --help`; đừng coi cấu hình mẫu như
schema đã được validate đầy đủ. Ví dụ, hard cap Qwen hiện được đặt ở một call/sample.

Config path được nạp từ file YAML; các đường dẫn tương đối của dataset được resolve theo project
root. Snapshot model trong `baseline.yaml` hiện dùng đường dẫn tuyệt đối trên máy phát triển, nên
thành viên khác phải cập nhật `local_path` của máy mình.

## 8. Các thư mục và file nguồn quan trọng

### Root

| Đường dẫn | Vai trò |
|---|---|
| [README.md](../README.md) | Giới thiệu và quick start ngắn. |
| [AGENTS.md](../AGENTS.md) | Entry point cho coding agent, giữ dữ liệu và module boundaries. |
| [lifemate_baseline_instructions_v1_1.md](../lifemate_baseline_instructions_v1_1.md) | Baseline/invariant lịch sử; một số tên module trong đó thuộc kiến trúc V1. |
| [pyproject.toml](../pyproject.toml) | Python requirement, dependencies/extras, pytest và Ruff config. |

Kiến trúc code đang chạy dùng năm ownership areas V2 như liệt kê ở trên và trong
[team technical plan](LifeMate_V2_Team_Plan_Detailed.md); đừng tạo lại các V1 folders chỉ vì chúng
còn được liệt kê trong baseline instruction cũ.

### `app/` — composition và entrypoints

- `run_one.py`: CLI cho một sample/fixture; nạp config, sample, adapter rồi gọi Pipeline.
- `run_dataset.py`: CLI batch; gọi pipeline cho mỗi sample và ghi submission JSONL.
- `pipeline.py`: thứ tự ASR → Discovery → Planner → Runtime, audit và internal trace.
- `build_services.py`: lắp implementations từ YAML; tạo/reuse Qwen client và budget một call.
- `dataset_io.py`: tìm bundle, đọc JSONL/audio, kiểm tra split và loại label/audio_text khỏi inference.
- `environment.py`: `MockEnvironment`, `OfficialEnvironment`, nạp schema/catalog từ kit.
- `competition_io.py`: serialize submission với đúng key/thứ tự tool calls.
- `audit.py`: ghi flow text và event JSONL theo mức audit.
- `diagnostics.py`: tiện ích chẩn đoán cấu hình/môi trường.

### `core/` — contracts và shared helpers

- `contracts.py`: Pydantic schema v2 cho request, tool, plan, reference, resolution, event, result.
- `interfaces.py`: Protocol giữa pipeline, module, environment và LLM client.
- `llm.py`: LocalQwenClient, MockLLMClient và wrapper giới hạn số lần gọi.
- `config.py`: YAML loader và resolve đường dẫn theo project root.
- `json_utils.py`: trích JSON từ output model và validate qua Pydantic.
- `errors.py`: kiểu lỗi pipeline/model/budget có code rõ ràng.

Đổi `core/contracts.py`, `core/interfaces.py` hoặc adapter/output chung có ảnh hưởng cả nhóm; trao
đổi với các owner trước khi đổi contract.

### `modules/` — năm ownership areas

| Module | Các file chính | Trách nhiệm |
|---|---|---|
| `modules/asr/` | `pho_whisper.py`, `mock.py`, `audio.py`, `service.py` | Kiểm tra WAV, nhận dạng PhoWhisper local hoặc transcript mock, chuẩn hóa transcript nhẹ. |
| `modules/discovery/` | `service.py`, `retriever.py`, `registry.py` | Keyword/capability retrieval từ catalog đúng sample; closure chỉ thêm tool nếu tool đó có trong catalog. Retrieval không cấp quyền mới. |
| `modules/planner/` | `service.py`, `prompts/plan.txt` | MockPlanner cho smoke test; SingleShotPlanner dùng Qwen một lần để trả TaskPlan schema v2. |
| `modules/resolver/` | `service.py`, `bindings.py`, `entity_matcher.py` | Bind typed `$ref`, dò entity duy nhất, validate arguments theo JSON Schema subset; không gọi model/tool. |
| `modules/runtime/` | `engine.py`, `scheduler.py`, `state.py`, `verifier.py` | Scheduler dependency/condition, gọi resolver/environment, xác minh kết quả, quản lý state/event trong sample. Không semantic replan. |

Mỗi module có `tests/`; ASR cũng có `experiments/`. Thêm implementation/test vào đúng module owner.
Module không nên import implementation trực tiếp từ module khác; giao tiếp qua `core` contracts.

### `configs/`, `scripts/`, `tests/`, `docs/`, `outputs/` và dataset

- `configs/`: YAML baseline/mock; `configs/experiments/` để đặt override thử nghiệm, không sửa production
  chỉ để thử một tham số.
- `scripts/`: CLI tiện ích/evaluation: `sanity_check`, `inspect_kit`, `make_train_split`,
  `eval_asr`, `eval_discovery`, `eval_planner`, `eval_resolver`, `eval_runtime`, `evaluate_train`,
  `download_models`. File `_eval_common.py` là helper nội bộ, không phải entrypoint.
- `tests/`: contract, data loading, environment, adapter và pipeline tests. `tests/fixtures/` là
  sample tổng hợp để thử offline.
- `docs/`: plan modular V2 và hướng dẫn phát triển/dự án.
- `outputs/`: audit, traces, evaluation và submissions sinh ra; không phải source, thường được
  `.gitignore` loại khỏi version control.
- `train+public_test/`: bundle dữ liệu, manifest, audio, environment state, tool catalog và
  `zaic_tools`. Giữ nguyên, không chỉnh sửa thủ công.
- `lifemate_analysis_full/`: bộ phân tích/dữ liệu phân tích đã có; giữ nguyên.

## 9. Evaluator và lệnh phát triển

Chạy checks trước khi gửi thay đổi:

```powershell
python -m pytest -q
ruff check .
```

Test một module:

```powershell
python -m pytest modules/asr/tests -q
python -m pytest modules/discovery/tests -q
python -m pytest modules/planner/tests -q
python -m pytest modules/resolver/tests -q
python -m pytest modules/runtime/tests -q
```

Evaluator:

```powershell
python -m scripts.eval_asr --config configs/baseline.yaml --limit 20
python -m scripts.eval_discovery --config configs/baseline.yaml --limit 20
python -m scripts.eval_planner --config configs/baseline.yaml --limit 10
python -m scripts.eval_resolver
python -m scripts.eval_runtime
```

Tham số các script tiện ích:

| Lệnh | Tham số chính | Dùng khi |
|---|---|---|
| `python -m scripts.sanity_check` | `--config` (mặc định mock) | Kiểm tra cấu hình và sự tồn tại của hai manifest. |
| `python -m scripts.inspect_kit` | `--config`, `--split train\|public_test\|both` (mặc định both) | In thông tin kit/catalog cục bộ; chỉ introspection. |
| `python -m scripts.make_train_split` | `--config`, `--seed` (42), `--validation-fraction` (0.1), `--output` | Tạo danh sách ID train/validation; fraction phải nằm trong (0, 1). |
| `python -m scripts.eval_asr` | `--config`, `--limit` | WER/CER trên audio và transcript tham chiếu train. |
| `python -m scripts.eval_discovery` | `--config`, `--limit` | Recall@K/full-chain recall trên train. |
| `python -m scripts.eval_planner` | `--config`, `--limit` | Kiểm tra plan model trên train; cần Qwen local. |
| `python -m scripts.eval_resolver` | Không có option riêng | Chạy resolver fixture tests. |
| `python -m scripts.eval_runtime` | Không có option riêng | Chạy runtime/integration fixture tests. |
| `python -m scripts.evaluate_train` | `--config`, `--submission` (bắt buộc) | So sánh submission với labels train, dùng offline. |
| `python -m scripts.download_models` | `--repo-id`, `--revision`, `--local-dir` (đều bắt buộc) | Tải snapshot trong khâu chuẩn bị; cần `huggingface_hub` cài riêng. |

ASR/Discovery/Planner evaluators dùng dữ liệu train offline; giới hạn sample khi smoke test. Planner
evaluator dùng candidate oracle và không có gold TaskPlan, nên không phải đo độ chính xác chuỗi
task. Resolver/Runtime evaluators là các fixture tests cố định. `scripts.evaluate_train` so sánh
submission với label train, chỉ dùng cho đánh giá offline:

```powershell
python -m scripts.evaluate_train --config configs/baseline.yaml --submission outputs/submission.jsonl
```

Tạo danh sách train/validation ID có seed:

```powershell
python -m scripts.make_train_split --config configs/baseline.yaml --seed 42 --validation-fraction 0.1 --output outputs/train_validation_ids.json
```

## 10. Ranh giới dữ liệu và an toàn khi phát triển

- Không để `label` hoặc `audio_text` lọt vào inference bình thường. `transcript_reference` là ngoại
  lệ offline/train có chủ đích.
- Chỉ dùng tool schema/catalog của environment sample; không tự đoán tool hoặc ID.
- TaskPlan bất biến sau validate; references là typed paths, không dùng `eval`.
- Khi write tool có effect không chắc chắn, không gọi lại mù quáng.
- Tool calls và `state_hash` chính thức phải đến từ `OfficialEnvironment`/kit; không dùng mock hash
  làm kết quả thi.
- Không chạy lệnh `download_models` trong lúc inference; không tải weights từ internet khi chạy.
- Không commit audit full, model weights, secrets, output submissions hay dataset.

## 11. Khắc phục lỗi thường gặp

| Triệu chứng | Kiểm tra / cách xử lý |
|---|---|
| `ASR_MODEL_NOT_FOUND` hoặc `MODEL_NOT_FOUND` | Sửa `models.asr.local_path`/`models.llm.local_path` trong baseline YAML; đường dẫn phải trỏ đến snapshot local. |
| `*_DEPENDENCY_MISSING` | Cài `python -m pip install -e ".[dev,local-models]"` trong đúng virtualenv. |
| Qwen báo 4-bit cần CUDA | `baseline.yaml` bật `quantization: 4bit`; xác nhận CUDA/GPU phù hợp. Không tự chuyển cấu hình sang mock nếu cần kết quả model thật. |
| `PLAN_INVALID` | Mở full audit để xem `plan_generated` nếu plan được tạo; kiểm tra candidate tool, schema, dependency/ref và prompt. Planner không chạy lần sửa thứ hai. |
| Không tìm thấy sample/audio | Xác nhận bundle root, split đúng, ID tồn tại; `sanity_check` và loader sẽ báo nếu manifest/WAV thiếu. |
| Không thấy `events.jsonl` | Chọn `--audit-level debug` hoặc `full`; `flow` chỉ sinh `.flow.txt`, `off` không ghi audit. |
| Public test từ chối transcript reference | Đây là giới hạn có chủ ý: chỉ train được phép dùng `--input-mode transcript_reference`. |
| Fixture không chạy với baseline | Fixture truyền transcript override và cố ý chỉ dùng ở `run.mode: mock`; dùng `--split`/`--id` với model thật. |
| Dataset chạy quá lâu | Dùng `--limit 1` hoặc `--limit 10` trước, kiểm tra output/audit rồi mới chạy cả split. |

## 12. Tài liệu tham chiếu

- [README quick start](../README.md)
- [V2 team technical plan](LifeMate_V2_Team_Plan_Detailed.md) — architecture and module responsibilities.
- [Baseline implementation instructions](../lifemate_baseline_instructions_v1_1.md) — tài liệu V1 cũ, đọc cùng lưu ý về kiến trúc hiện tại ở mục 8.

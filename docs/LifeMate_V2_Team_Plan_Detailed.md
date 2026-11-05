# LifeMate V2 — Team Plan kỹ thuật: 5 module, baseline, thí nghiệm và phối hợp

> **Mục đích:** Tài liệu làm việc chung cho 5 thành viên và coding agent: hiểu pipeline, nắm rõ mỗi module chịu trách nhiệm gì, baseline xử lý thế nào, những lỗi cần chủ động kiểm thử, và hướng cải tiến **độc lập, đo lường được**.
>
> **Trạng thái:** **Đặc tả kiến trúc V2 đã thống nhất**, **chưa phải kiểm toán code as-built**. Người dùng cho biết repo đã refactor nhưng chưa cung cấp source sau refactor trong lượt này. Những tên file/API bên dưới là **hợp đồng mục tiêu và vị trí kỳ vọng**; cần đối chiếu `core/contracts.py`, `modules/*`, `app/pipeline.py`, config thực tế trước khi ghi nhận là “đã implement”. Phần **§15 – As-built verification** dùng cho việc này.
>
> **Nguồn căn cứ:** mô tả repo V1.1 do nhóm cung cấp; kiến trúc V2 chốt trong trao đổi; file `train.jsonl` đã cung cấp (1.545 mẫu). Các ví dụ tool và argument thực tế được phân biệt với JSON/DSL minh họa.
>
> **Phạm vi baseline:** **ASR → Tool Discovery → Qwen 4B sinh TaskPlan trong 1 inference → Runtime điều phối Resolver + Environment + Verifier → Submission/Audit.** Không tạo NLU Agent/Perception Agent/Observer Agent riêng; không gọi lại Qwen trong vòng thực thi baseline.

---

## 0. Tóm tắt để 5 thành viên hiểu cùng một kiến trúc

| Người | Module độc lập | Câu hỏi nghiên cứu duy nhất | Input → Output | Baseline đề xuất |
|---|---|---|---|---|
| **N1** | `asr` | **Người dùng thực sự nói gì?** | WAV → `Transcript` | PhoWhisper-medium + chuẩn hóa an toàn |
| **N2** | `discovery` | **Những tool nào Qwen cần biết để lập plan?** | Request + allowed catalog → candidate `ToolSpec[]` | capability map + keyword ranking + resolver closure |
| **N3** | `planner` | **Yêu cầu ấy biến thành những task/quan hệ nào?** | Request + candidates → `TaskPlan` | Qwen3-4B-Instruct-2507; một lần sinh JSON |
| **N4** | `resolver` | **Arguments cuối cùng của task lấy từ đâu, đã đủ và đúng chưa?** | Task + observations + ToolSpec + context → `READY`/`Issue` | typed bindings + temporal/location resolution + schema validation |
| **N5** | `runtime` | **Thực thi đúng thứ tự, điều kiện, an toàn và kết luận ra sao?** | TaskPlan + Resolver + Environment → `RunResult` | state machine + scheduler + verifier + audit flow |

**Ba điều tuyệt đối không nhầm:**

1. **5 module ≠ 5 LLM calls.** Chỉ N3 gọi Qwen để sinh plan; M1 chạy ASR model riêng. N2/N4/N5 chạy logic bằng code.
2. **Single-shot planning ≠ biết tương lai.** Qwen có thể sinh đầy đủ *logic* từ đầu, nhưng **không biết `event_id`, `contact_id`, số dư hay thời gian của event cho đến khi tool trả về**. Những giá trị đó phải được biểu diễn bằng tham chiếu/biểu thức và được N4 resolve lúc chạy.
3. **Một JSON ngôn ngữ chung ≠ mọi module được phép sửa JSON.** N3 sở hữu `TaskPlan` ban đầu; N5 sở hữu `ExecutionState`; N4 chỉ trả resolved arguments hoặc issues. Không để N2/N3/N4 tự mutate state runtime.

### Quyết định baseline cần đóng băng

- **Một Qwen planning call/request** (trừ request kết thúc trước planner, ví dụ ASR thất bại). Không có LLM tool selector, LLM validator, LLM repair ngầm; mọi thí nghiệm nhiều calls phải chạy thành một *experiment variant* tách biệt.
- **Không đoán ID hoặc output tool tương lai.** Dùng typed `$ref`/expression; nếu chưa đủ cơ sở phải blocked/ask, không chọn bản ghi `[0]` bừa.
- **Authoritative tools** lấy từ `Environment` theo sample, split và `installed_apps`. Retrieval chỉ thu hẹp candidate, không nới quyền.
- **Không đọc `audio_text`/`label` tại runtime inference.** Dùng làm oracle cho train-only evaluation. Không đọc `tool_results` tương lai để giúp Qwen sinh plan.
- **Không đổi submission:** `{ "id", "tool_calls", "state_hash" }` theo adapter chính thức. Official hash do kit cung cấp; mock hash không dùng nộp.
- **Giữ khả năng audit theo flow, mặc định ngắn**, debug raw là tùy chọn có redaction.

---

## 1. Những gì dataset kiểm chứng được và chưa kiểm chứng được

`train.jsonl` có **1.545 mẫu**. Trong tất cả các mẫu đã kiểm tra, `context` có các trường `current_time`, `timezone`, `location`, `user_profile`, `installed_apps`; `history` có thể chứa nhiều lượt user/assistant cùng tool calls/results cũ. `label` chứa `tool_calls`, `tool_results`, `final_state`.

**Hai hệ quả quan trọng:**

- `current_time` là **thời điểm trong mẫu**, không phải thời điểm đồng hồ máy đang chạy. Với `train_0001`, `current_time = 2026-11-28T07:10:00+07:00`, nên **“mai” = 2026-11-29**. Đây là phép grounding có thể kiểm chứng bằng code.
- `label.tool_calls` là **trace thực thi cho một trạng thái environment cụ thể**, **không phải gold TaskPlan độc lập**. Muốn đánh giá goal/dependency/condition/binding phải tạo thêm fixtures/annotations đã kiểm tra. Không tự gán mọi quan hệ dependency theo vị trí xuất hiện của tool calls.

Ví dụ từ dữ liệu:

| Mẫu | Đặc điểm | Rủi ro thiết kế |
|---|---|---|
| `train_0001` | “Nếu mai mưa…” → `weather.get_forecast` → tìm lịch → dời 1h → tìm liên hệ → nhắn | Conditions, timezone, `$ref`, thay đổi thời gian, side-effect order |
| `train_0048` | “Gọi cho Lan” → `contacts.search` có **hai** Lan → `sys.ask_missing_info` | Ambiguity khác missing; không tự chọn người đầu tiên |
| `train_0068` | Đặt báo thức sáng mai **và** gọi Minh; search có hai Minh | Multi-goal partial completion; không chặn goal độc lập đã đủ thông tin |
| `train_0121` | Trả hóa đơn đến hạn trong 5 ngày, loại trừ hóa đơn >500k | Filter theo thời gian và số tiền; nhiều action từ một read result |

**Giới hạn dataset:** trace label chủ yếu cho biết những tool calls đã xảy ra trong tình huống cụ thể; dữ liệu gốc không tự cho ta mọi outcome lỗi, retry hay counterfactual branch. Khi tạo fault injection, phải đánh dấu rõ **synthetic evaluation**, không nhầm là nhãn thật.

---

## 2. Pipeline hiện tại theo hợp đồng V2

```text
              JSONL sample + WAV + context + history
                             │
                             ▼
                     app/dataset_io.py
                   (runtime fields only)
                             │
                             ▼
                    M1. ASR / PhoWhisper
                      Transcript + metadata
                             │
                             ▼
                  M2. Discovery / Retrieval  ◄── Environment allowed ToolSpec[]
                     candidate tool cards
                             │
                             ▼
              M3. Qwen Single-shot Planner (1 call)
       understand transcript/context/history → goals/tasks/tools
       refs/expressions + dependencies + conditions + no-op
                             │
                             ▼
                 validate TaskPlan schema/graph
                             │
                             ▼
          ┌────────── M5. Runtime & ExecutionState ──────────┐
          │  scheduler: ready task / guard TRUE-FALSE-UNKNOWN │
          │                       │                           │
          │                       ▼                           │
          │             M4. Argument Resolver                 │
          │          literal / $ref / time / location         │
          │              / schema / ambiguity                 │
          │           ┌───────────┴───────────┐               │
          │        READY                ISSUE/EXPLORE         │
          │           │                      │                │
          │    validate → tool call      add safe explore /    │
          │           │                 NEEDS_USER / BLOCKED  │
          │       observation                 │                │
          │           │                      │                │
          │   verify → state update → audit events → loop     │
          └───────────────────────────────────────────────────┘
                             │
                             ▼
            RunResult + official tool trace/state_hash
                             │
                             ▼
                 submission JSONL + readable audit
```

**Một điểm kỹ thuật:** M4 **không** đứng sau M3 như một bước một lần rồi thôi. M5 gọi M4 **trước từng tool call**; observations từ task trước trở thành inputs cho những task sau.

### 2.1. End-to-end API mong muốn

```python
# Sơ đồ interface, KHÔNG khẳng định tên hàm as-built.
def run_sample(sample, services):
    transcript = services.asr.transcribe(sample.audio)
    req = AgentRequest(
        sample_id=sample.id,
        transcript=transcript.text,
        context=sample.context,
        history=sample.history,
    )
    allowed_catalog = services.environment.list_tools()  # per sample/session
    candidates = services.discovery.retrieve(req, allowed_catalog)
    plan = services.planner.generate_plan(req, candidates)  # Qwen x1
    plan = validate_plan(plan, allowed_catalog)
    result = services.runtime.execute_plan(
        plan=plan,
        request=req,
        resolver=services.resolver,
        environment=services.environment,
        catalog=allowed_catalog,
    )
    return services.competition_io.serialize(sample.id, result)
```

**Ranh giới data:** `AgentRequest` dùng chung, không tạo `StructuredIntent` rồi `GoalSpec` rồi `TaskGraph` như các schema liên tục bị chuyển đổi trong V1.1. `TaskPlan` của Qwen và `ExecutionState` runtime khác vai trò nhưng dùng **cùng task IDs/field semantics**.

---

## 3. Contracts chuẩn — quy định tối thiểu để 5 người không phụ thuộc code nhau

> **Quan trọng:** Sau refactor đã có thể tồn tại contracts tương đương. Hãy **reuse type/cú pháp đã có** nếu đáp ứng ràng buộc; không tự tạo nhiều dialect `$ref`, `$from`, `$shift`, `$add_minutes` cạnh tranh.

| Contract | Trường cốt lõi | Producer → Consumer |
|---|---|---|
| `AgentRequest` | `sample_id`, `transcript`, `context`, `history` | app/M1 → M2/M3/M4 |
| `ToolSpec` | `name`, `description`, `input_schema`, optional outputs/metadata | Environment → M2/M3/M4/M5 |
| `TaskPlan` | `schema_version`, `goals[]`, `tasks[]` | M3 → M5 |
| `Task` | `id`, `goal_id`, `tool`, `arguments`, `depends_on`, `when?` | M3 → M5/M4 |
| `ResolutionResult` | `READY(arguments)` hoặc `Issue(code, field, details, explore?)` | M4 → M5 |
| `ToolResult` | `tool_name`, execution response, status/error | Environment → M5 |
| `ExecutionState` | task statuses, observations, issues, attempts, trace | M5 only |
| `RunResult` | final status, tool calls, audit summary, official state hash ref | M5 → app |

> Python `Protocol` cho các module là public API; không phải lý do để tạo thêm 5 abstract base classes. Input/output có thể dùng Pydantic v2 hoặc dataclass theo code hiện hữu, miễn JSON/schema được kiểm chứng.

### 3.1. TaskPlan minh họa: gọi cho bác Ba

```json
{
  "schema_version": "2.0",
  "goals": [{"id": "g1", "description": "Gọi bác Ba"}],
  "tasks": [
    {
      "id": "t1", "goal_id": "g1", "tool": "contacts.search",
      "arguments": {"query": "bác Ba"},
      "depends_on": [], "when": null
    },
    {
      "id": "t2", "goal_id": "g1", "tool": "phone.call",
      "arguments": {
        "contact_id": {
          "$ref": {
            "task_id": "t1", "path": ["contacts"],
            "match": {"name": "bác Ba"}, "field": "id",
            "require_unique": true
          }
        }
      },
      "depends_on": ["t1"], "when": null
    }
  ]
}
```

**Đây là JSON minh họa DSL nội bộ, không phải argument hợp lệ để truyền nguyên xi vào `zaic_tools`.** M4 phải thay `$ref` bằng ID thực trước khi M5 gọi `phone.call`. Nếu có nhiều người “bác Ba” phù hợp: `AMBIGUOUS`, không mặc định phần tử `[0]`.

### 3.2. Điều kiện và giá trị chưa biết

- `depends_on`: task đợi các task trước hoàn thành; là **ordering/data dependency**, không tự thay thế logic `when`.
- `when`: điều kiện Boolean trên observation (ví dụ `rain == true`); Runtime dùng logic **TRUE/FALSE/UNKNOWN**. FALSE → `SKIPPED`, UNKNOWN → `WAIT/BLOCKED`, tuyệt đối không coi UNKNOWN là FALSE.
- `$ref`: binding tới kết quả task/field đã có; phải check ref tồn tại, đúng type, chọn duy nhất nếu cần.
- **Temporal expression:** Qwen biểu diễn ý nghĩa “ngày mai 7 giờ sáng” hoặc “dời 60 phút”; M4 tính từ `context.current_time`, `context.timezone`, giá trị lịch thật.
- **Location expression:** Qwen biểu diễn “ở đây”, “nhà tôi”, “gần X” là tham chiếu; M4 dùng context/observations có thẩm quyền để tạo tọa độ/địa chỉ; không tự đặt location.

### 3.3. Một ví dụ time grounding (mỗi người phải hiểu)

**Input thực tế của `train_0001`:**

```json
{
  "audio_text": "Nếu mai mưa thì dời chạy bộ muộn 1 tiếng, nhắn Sếp Dũng giờ mới; không mưa thì thôi.",
  "context": {
    "current_time": "2026-11-28T07:10:00+07:00",
    "timezone": "Asia/Ho_Chi_Minh"
  }
}
```

**Trách nhiệm M3:** Hiểu “mai” = **ngày lịch kế tiếp** so với `context.current_time`, liên hệ với argument của `weather.get_forecast`; hiểu “dời muộn 1 tiếng” = shift giờ của event tìm được, không phải “09:00” mặc định; chỉ nhắn sau khi cập nhật lịch thành công.

**Ví dụ semantic expression trong TaskPlan:**

```json
{
  "tool": "weather.get_forecast",
  "arguments": {
    "date": {"$time": {"base": "context.current_time", "calendar_days": 1, "format": "date"}}
  }
}
```

**Trách nhiệm M4:** từ `2026-11-28T07:10:00+07:00` cùng `Asia/Ho_Chi_Minh` tính `date = "2026-11-29"`; nếu cập nhật lịch, đọc `event.start/end` rồi shift 60 phút. **Trách nhiệm M5:** chỉ thực thi nhánh sửa lịch khi dự báo xác định là mưa và đúng dependency.

Nên tách 3 khái niệm thời gian trong schema:

| Câu nói | Loại | Nghĩa |
|---|---|---|
| “ngày mai” | `calendar_day_offset(+1)` | Ngày lịch kế tiếp theo local timezone |
| “sau 24 giờ” | `duration(24h)` | Khoảng thời gian trôi qua |
| “dời lịch muộn 1 giờ” | `shift(event_time,+60m)` | Phép biến đổi trên thời gian event chưa biết |

Không thay các expression mơ hồ thành timestamp chắc chắn; giữ `UNRESOLVED` và yêu cầu thông tin nếu không đủ context.

### 3.4. Contract invariants bắt buộc

1. Task IDs/goal IDs duy nhất; mọi `goal_id`, `depends_on`, `$ref`, `when` trỏ tới ID hợp lệ; graph không có cycle.
2. M3 chỉ sử dụng tools trong candidates; M5 chỉ gọi tools có schema trong **allowed_catalog**. Không có chuyện Qwen tự đặt tool mới.
3. M3 không sinh `status`, `result`, `attempts`, `state_hash` vào plan.
4. M4 không gọi tool; M5 là **single writer** của ExecutionState và single caller của Environment.
5. M4 validate `anyOf`/alternative fields (ví dụ một tool có thể nhận `contact_id` **hoặc** `phone_number`) chứ không áp dụng `required` đơn giản sai.
6. `ToolResult.ok == true` là bằng chứng tool báo thành công, **không tự động** chứng minh mọi goal đã đạt.
7. Request output không được rò `audio_text`/`label` train ngoài evaluation mode.
8. Nếu tool state-changing timeout chưa rõ đã thực thi hay chưa: **UNCERTAIN**, không tự retry mù.

---

## 4. Phân công quyền sở hữu repo và quy tắc PR

### 4.1. Layout kỳ vọng (giữ tên hiện có nếu refactor đã tương đương)

```text
LifeMate/
├── app/                         # composition root, CLI, dataset, kit adapter, submission, audit renderer
│   ├── pipeline.py
│   ├── build_services.py
│   ├── dataset_io.py
│   ├── environment.py
│   ├── competition_io.py
│   ├── audit.py
│   ├── run_one.py
│   └── run_dataset.py
├── core/                        # stable shared contracts/interfaces, config/errors/model adapter
│   ├── contracts.py
│   ├── interfaces.py
│   ├── llm.py
│   └── errors.py
├── modules/
│   ├── asr/                     # N1
│   ├── discovery/               # N2
│   ├── planner/                 # N3
│   ├── resolver/                # N4
│   └── runtime/                 # N5
├── configs/
│   ├── baseline.yaml
│   └── experiments/{asr,discovery,planner,resolver,runtime}/
├── scripts/
│   ├── eval_asr.py
│   ├── eval_discovery.py
│   ├── eval_planner.py
│   ├── eval_resolver.py
│   └── eval_runtime.py
├── tests/fixtures/             # curated, versioned, no future leakage into input
├── docs/
└── outputs/{audits,evaluations,submissions}/
```

**Sở hữu:**

- **N1**: chỉ `modules/asr/**`, `configs/experiments/asr/**`, `scripts/eval_asr.py` và unit tests của ASR.
- **N2**: chỉ `modules/discovery/**`, experiments/eval tương ứng.
- **N3**: chỉ `modules/planner/**`, prompt/model experiments và eval tương ứng.
- **N4**: chỉ `modules/resolver/**`, experiments/eval tương ứng.
- **N5**: `modules/runtime/**`, `app/pipeline.py`, `app/audit.py`, `tests/test_integration.py`; quản lý tích hợp.
- **Shared:** `core/contracts.py`, `core/interfaces.py`, `app/environment.py`, `app/competition_io.py`, `app/dataset_io.py` cần review chéo, **không sửa âm thầm**.

**Không import implementation chéo:** `modules/runtime` nhận một `Resolver` protocol instance; không import trực tiếp `modules/resolver/bindings.py`. `app/build_services.py` nối các implementations. `core` không import `modules`.

### 4.2. Thay đổi contract cần quy trình ngắn

1. Người đề xuất mở PR nhỏ: **vì sao contract hiện tại không diễn đạt được case nào**, ví dụ `DURATION` vs `CALENDAR_DATE`.
2. Đưa mẫu input/output và ít nhất một test trước khi đổi schema.
3. N3, N4, N5 review nếu thay Task/Binding; N1/N2 review phần mình ảnh hưởng.
4. Sau merge, cập nhật version/schema snapshot và integration fixture; không viết 2 dialect song song mãi.

### 4.3. Định nghĩa module độc lập

Một module được coi là độc lập khi `pytest modules/<name>/tests` chạy được **không tải model khác hoặc environment thật**, có fake inputs/outputs riêng, và thay implementation không buộc sửa internal code của module khác.

---

## 5. N1 — ASR: nhận dạng và giữ nguyên ngữ nghĩa người dùng

### 5.1. Nhiệm vụ nguyên tử

**Audio → Transcript**. Không suy ra tasks, tools, goals. Câu nói có từ phủ định, tên riêng, số tiền hay thời gian phải được nhận chính xác; không tự ý “sửa” ý nghĩa bằng hallucination.

**Public API:** `transcribe(audio_path) -> Transcript(text, optional confidence/timing)`.

**Baseline:** PhoWhisper-medium từ đường dẫn local, audio validation, whitespace normalization; mock ASR phục vụ fixtures. Cấu hình model/weights thực tế cần kiểm tra trong repo sau refactor.

### 5.2. Các lỗi thường gặp và xử lý

| Failure mode | Ví dụ | Hướng xử lý |
|---|---|---|
| Phủ định bị bỏ | “không mưa thì thôi” mất chữ “không” | critical-token error set, thử decoding và prompt ASR nếu model hỗ trợ |
| Số sai | “năm trăm nghìn” → “năm mươi nghìn” | đánh giá số/đơn vị độc lập với WER; không tự đoán ở hậu xử lý |
| Tên riêng sai | “Sếp Dũng” → “sếp đúng” | domain hotwords/contextual biasing nếu engine hỗ trợ, không thêm tên giả |
| Câu tự sửa | “đặt 7 giờ… à không, 8 giờ” | bảo toàn thứ tự và phần đính chính |
| Audio noise/khẩu ngữ | “ờ à, gọi cho Lan nhé” | khảo sát audio preprocessing/decoding |

### 5.3. Thí nghiệm độc lập (ưu tiên)

1. **A0:** Baseline PhoWhisper + current decoding.
2. **A1:** So sánh beam size/temperature và cách normalize số, ngày giờ nhưng **không làm mất nghĩa**.
3. **A2:** Thử model khác / post-processing tên riêng dựa vào *đầu vào được phép*.
4. **A3:** Downstream-aware evaluation: số lượng lỗi ASR dẫn tới đổi tool/action dù WER không cao.

**Metric:** WER/CER; **critical slot accuracy** cho `negation`, `time`, `amount`, `recipient`, `location`; latency. Tránh chỉ tối ưu WER trung bình.

**Standalone test:** WAV + `audio_text` train oracle để chấm offline. Public test không có transcript vàng, không dùng để chấm WER giả.

**Deliverables N1:** README kỹ thuật, config experiments, script eval, bảng A0/A1/A2, 10–20 ca ASR lỗi có nguyên nhân và phương án sửa.

**Ngoài phạm vi:** parse intent, thời gian chuẩn hóa ISO, contact resolution, plan.

---

## 6. N2 — Tool Discovery: giới hạn không gian công cụ trước khi Qwen lập plan

### 6.1. Nhiệm vụ nguyên tử

**Request + per-sample allowed catalog → candidate tool cards (ranked).** Discovery không tự sinh task, không đưa arguments cuối cùng và không chạy LLM selector.

**Public API:** `retrieve(request, allowed_catalog) -> ToolCandidates`.

**Baseline:** reuse capability map + keyword overlap từ hệ thống cũ, Top-K có cấu hình (khởi đầu thử `K=8`, **không coi 8 là tối ưu**); bổ sung **resolver closure** cho các tool hỗ trợ lẫn nhau.

Ví dụ `phone.call` cần liên hệ nhưng request chỉ nói tên → nên đưa cả `contacts.search` vào tool cards **nếu** session có hai tools đó. Với “nếu mai mưa thì dời lịch rồi nhắn” → phải đủ weather, calendar, contact, SMS tools, không chỉ top-1 khớp từ khóa.

### 6.2. Thuật toán baseline cụ thể

```python
def retrieve(request, allowed):
    # permitted names always come from this sample's environment
    score = lexical_and_capability_scores(request.transcript, allowed)
    ranked = stable_sort_by_score(score)
    selected = ranked[:K]
    selected = append_allowed_resolver_dependencies(selected, allowed)
    return deduplicate_preserving_order(selected)
```

`append_allowed_resolver_dependencies` không biến tools không cài thành tools được phép. Không include tất cả 146 tool schemas trong một prompt. Tool cards nên ưu tiên tên, mục đích, required/alternative arguments, output fields cần để bind và hint resolver.

### 6.3. Lỗi có thể gặp

| Lỗi | Nguyên nhân | Kiểm thử |
|---|---|---|
| **Recall thấp** | “gọi bác Ba” chỉ lấy `phone.call`, bỏ `contacts.search` | full-chain tool recall |
| **Đồng nghĩa tiếng Việt** | “nhắn” vs `sms.send`/`chat_ott.send_message` | paraphrase queries |
| **Candidate phình** | closure thêm quá nhiều tool phụ | avg candidates, latency, precision |
| **Tool không được cài** | retrieval dùng global catalog thay vì session | 100% allowlist invariant |
| **Thiếu schema semantics** | chỉ gửi tool name nên Qwen bịa fields | tool cards include input schema compact |
| **Tool mới trong public test** | chỉ hardcode train mapping | fallback lexical matching; split-aware tests |

### 6.4. Hướng cải tiến có thể thử (tách biến số)

- **D1 — BM25** trên descriptions + argument docs, so với keyword overlap.
- **D2 — Dense retrieval** với sentence embeddings đa ngôn ngữ/Vietnamese, đo Recall@K.
- **D3 — Hybrid** lexical+dense, rank fusion đơn giản; tránh cross-encoder nếu latency chưa cho phép.
- **D4 — Query expansion/capability routing** (không LLM call): pattern rules nhằm giữ các action phụ thuộc (lookup, read-before-write).
- **D5 — Adaptive K** theo độ phức tạp yêu cầu, kèm hạn mức tokens tool cards.

**Benchmark:** input là `audio_text` vàng + catalog theo sample, nhãn `label.tool_calls` làm oracle tool-set offline; đo **Recall@K** và **Full-chain Recall**. Một tool chỉ xuất hiện trong label không nhất thiết có từ tương ứng trong transcript — chính điều này kiểm tra được closure.

**Không đo:** độ chính xác Qwen sinh plan (thuộc N3). N2 phải báo cáo riêng tỷ lệ candidate-set có đủ tools trước khi thử end-to-end.

**Deliverables N2:** deterministic retriever, file capability/hints, standalone evaluator, top misses và confusion pairs, bảng Recall@K/avg candidate count.

---

## 7. N3 — Planner: Qwen hiểu toàn bộ semantic request, không làm thay phép tính/tool lookup

### 7.1. Định nghĩa đúng bài toán

Một lần inference Qwen phải chuyển `transcript + context + history + candidate tool cards` thành **TaskPlan có thể thực thi về mặt logic**:

- **Hiểu transcript:** ngôn ngữ tiếng Việt, lời đính chính, phủ định, tham chiếu ngữ cảnh.
- **Goal coverage:** không bỏ sót yêu cầu; phân biệt action và no-op.
- **Task composition:** tạo đủ bước lookup/read/compute/action khi biết trước từ ngữ nghĩa.
- **Tool selection:** dùng tool chính xác trong candidate set.
- **Dependency/condition:** tạo cạnh phụ thuộc và nhánh chỉ kích hoạt khi thỏa điều kiện.
- **Arguments:** literal đã biết, **symbolic references** với dữ liệu chỉ có sau tool, expression thời gian/địa điểm.

**Qwen KHÔNG:** gọi tool, đoán ID, xác minh `ok`, tính lịch tuyệt đối bằng tưởng tượng, ghi runtime status, semantic replan sau tool output trong baseline.

### 7.2. Baseline inference

**Model tham chiếu theo config V1.1:** `Qwen3-4B-Instruct-2507` (kiểm chứng model name/path/precision thực tế). Một prompt có 5 khối:

1. **Instruction:** chỉ sinh TaskPlan JSON, không narrative.
2. **Request:** transcript gốc và context/history *liên quan* (giữ `current_time/timezone`, installed tools, profile/location nếu được phép).
3. **Tool cards:** tên/tool parameters/output summary từ N2.
4. **Task patterns:** Direct, Lookup→Action, Read→Modify, Conditional, Multi-goal, Reference/No-op.
5. **Schema + constraints:** `TaskPlan` shape, typed refs/time expressions, uniqueness, allowed tools, no hallucinated results.

```python
# Baseline: one call, not parse-intent + plan + select-tool.
plan_json = qwen.generate_one_json(prompt, taskplan_schema)
plan = TaskPlan.model_validate(plan_json)
validate_semantics_and_references(plan, allowed_candidates)
```

Nếu inference stack hỗ trợ constrained JSON Schema output, ưu tiên thử để giảm invalid JSON. Constrained decoding **không chứng minh plan đúng logic**; semantic validators và benchmarks vẫn cần.

### 7.3. Semantic vs deterministic grounding — phải phân chia chính xác

| Câu nói | N3 phải hiểu/sinh | N4/M5 làm sau đó |
|---|---|---|
| “mai” | relative day `+1` so với `context.current_time` | N4 tính ngày ISO theo `timezone` |
| “6 giờ sáng mai” | local time 06:00 + tomorrow | N4 tính aware datetime, format cho tool |
| “dời muộn 1 tiếng” | shift 60m của event start/end | N4 dùng event thật và shift bằng datetime |
| “đây”, “gần tôi” | semantic reference `current_location` | N4 lấy tọa độ từ context, validate |
| “về nhà” | reference `home` | N4 tìm từ context/profile/tool có thẩm quyền; thiếu thì issue |
| “cái sớm nhất” | chọn earliest **trong tập liên quan** | N4 filter/sort tool results/history nếu có tập rõ |
| “Lan” | semantic target name=Lan, không tự chọn ID | N4 resolve unique hoặc AMBIGUOUS |
| “không mưa thì thôi” | guard/no-op branch | M5 skip toàn bộ side-effects khi false |

### 7.4. Các vấn đề khó và cách khống chế

| Vấn đề | Nguyên nhân | Giải pháp baseline | Hướng thử nghiệm |
|---|---|---|---|
| **Cognitive overload** | model 4B gánh nhiều khái niệm | grammar nhỏ, tool cards ngắn, task templates | template-conditioned prompt, SFT |
| **Goal omission** | nhiều yêu cầu trong một câu | `goals[]` tường minh, test multi-goal | few-shot hard multi-intent |
| **Wrong dependency** | hai task gần nhau nhưng không phụ thuộc | chỉ thêm dependency vì dữ liệu/guard/causality | kiểm thử edge-level precision/recall |
| **Wrong condition** | “nếu… thì”, “trừ khi”, “không thì…” | typed `when` + tri-state runtime | condition-specific datasets |
| **Time errors** | model tự cộng ngày/giờ | symbolic `$time`, `$shift`, N4 compute | compare symbolic vs direct timestamp |
| **Hallucinated IDs** | Qwen sinh luôn `evt_01`, `c_08` | forbid IDs không có trong context/history; typed refs | SFT consistency checks |
| **Context pollution** | history dài, thông tin cũ | chọn history liên quan, state snapshot ngắn | context ablation/selection |
| **Invalid JSON** | model output không theo contract | Pydantic + constrained decoding nếu có | guided decoding vs prompt-only |
| **No-op sai** | user tự hủy yêu cầu | explicit no-action goal/result | special negative/correction cases |

### 7.5. Kế hoạch nghiên cứu N3 có thể chứng minh hiệu quả

- **P0:** Zero-shot unified prompt + JSON validation, freeze model and test set.
- **P1:** Few-shot/task templates, chỉ thay prompt, so sánh với P0.
- **P2:** Constrained schema decoding nếu server local hỗ trợ; log parsing errors và semantics errors riêng.
- **P3:** **LoRA/QLoRA SFT** trên các mẫu TaskPlan được annotate/verified từ trace; không huấn luyện bằng `future tool_results` như input initial planning.
- **P4:** Structured data augmentation: paraphrase, ngày tương đối, phủ định, nhiều goals, ambiguity và multi-branch — phải kiểm chứng nhãn.
- **P5 (ngoài baseline):** So sánh single-shot với một recovery call có kiểm soát; ghi rõ biến thể, **không trộn** vào baseline chung.

**Gold labels:** train chỉ có `tool_calls`/`tool_results`, không có sẵn đồ thị task vàng. N3 cần lập một tập nhỏ (~50–150 case, tùy nhân lực) gán nhãn/kiểm tra graph, condition, refs; lưu version và tiêu chí annotation. Không đánh giá dependency bằng việc đoán từ thứ tự tool trace.

**Metric:** JSON-valid %, Plan-valid %, Goal Coverage, Task/tool recall, edge-level dependency F1, Condition accuracy, reference syntax/correctness, executable plan rate, latency/tokens, **one Qwen call invariant**.

**Deliverables N3:** prompt versioned, baseline configs/model revision, schema-valid tests, hard-case suite, benchmark per-subskill, báo cáo zero/few-shot/SFT (nếu làm).

---

## 8. N4 — Argument Resolver: nơi context/time/location và output tool thành arguments cuối cùng

### 8.1. Nhiệm vụ nguyên tử

**Input:** `Task + ToolSpec + Request.context/history + prior observations`.

**Output:** `ResolutionResult = READY(fully_validated_arguments) | ISSUE(code, field, evidence, explore_suggestion?)`.

N4 **không tự gọi tools, không mutate RuntimeState, không cần LLM**. Khi thiếu thông tin có thể truy xuất, trả `ExploreSuggestion` chứa tool & query dự kiến; chỉ M5 thêm và thực thi explore task.

### 8.2. Baseline deterministic algorithm

```python
def resolve(task, observations, spec, request):
    args = deep_copy(task.arguments)
    args = resolve_context_refs(args, request.context, request.history)
    args = resolve_task_refs(args, observations)       # require unique when needed
    args = resolve_time_expressions(args, request.context)
    args = resolve_location_expressions(args, request.context)
    issues = validate_against_tool_schema(args, spec.input_schema)
    if issues:
        return classify_issue_and_suggest_explore(issues, task, spec)
    return Ready(arguments=args)
```

**Schema semantics:** phải xử lý `anyOf`/`oneOf`/optional/required/type/enum khi toolkit dùng; `phone.call` có thể hợp lệ với `contact_id` **hoặc** `phone_number` tùy schema kit. Không tự ép search contact khi đã có số trực tiếp hợp lệ.

### 8.3. Bộ phép toán baseline nên giữ nhỏ

- **Literal:** chuỗi/số/bool biết từ user/context.
- **`$context`:** tham chiếu field ngữ cảnh đã cho, ví dụ `location.lat`.
- **`$ref`:** tham chiếu output của task đã hoàn thành, có `match`/`require_unique` nếu cần.
- **`$time`:** relative calendar date/local clock → datetime/date theo timezone.
- **`$shift`:** tăng/giảm `timedelta` đối với datetime event thật.

Các operator trên là **tập khái niệm đề xuất**; nếu code V2 có grammar tương đương, không thay chỉ vì khác tên. **Không dùng `eval`** để execute expressions từ LLM.

### 8.4. Missing/ambiguous/not-found và explore task

| Tình trạng | N4 phát hiện | Kết quả gửi M5 | Hành vi M5 |
|---|---|---|---|
| `MISSING` | required arg trống; user chưa cung cấp | `Issue(field, missing)` | hỏi user nếu không có resolver |
| `NEEDS_EXPLORE` | thiếu field có source tool hợp lệ | `ExploreSuggestion(tool,args,bind_to)` | thêm task, dedup + budget + retry resolve |
| `AMBIGUOUS` | >1 entity thỏa constraints | `Issue(candidates, ambiguity)` | hỏi user / tìm thêm bằng chứng hợp lệ |
| `NOT_FOUND` | query tool không trả record phù hợp | `Issue(not_found)` | search khác nếu có quy tắc an toàn, ngược lại dừng |
| `INVALID` | sai schema/type/enum | `Issue(invalid)` | sửa deterministic nếu an toàn, ngược lại blocked |
| `STALE` | reference trỏ observation không còn hợp lệ | `Issue(stale)` | refresh/read lại nếu công cụ có sẵn |

**Không “khám phá vô hạn”:** N4 phải kèm `reason` và `suggested_explore` có thể audit; M5 dedup theo `(tool,args,target_field)` và giới hạn số lần, tránh gọi `contacts.search` lặp cùng query không có dữ liệu mới.

### 8.5. Lỗi nghiên cứu cốt lõi

1. **Time:** `tomorrow` tương đối với *context*, không máy; local-calendar vs elapsed duration; không tự thêm buổi sáng/tối khi mơ hồ; format đúng tool.
2. **Location:** `ở đây` lấy `context.location`; `nhà` không tương đương vị trí hiện tại; tọa độ không được tự bịa; query geocoding chỉ khi tool được phép.
3. **Entity resolution:** contact/event có nhiều candidate; exact ID/quan hệ/context evidence mạnh hơn matching tên đơn thuần; không chọn candidate đầu tiên.
4. **History grounding:** “cái còn lại”, “lịch đó” phải xác định referent từ các lượt hội thoại và trạng thái mới nhất, không lấy dữ liệu stale vô điều kiện.
5. **Schema:** một số tools có alternative arguments; name/type/range phải đúng đúng schema của từng split.
6. **Partial data:** output có `ok=true` nhưng thiếu `contacts` hoặc thiếu `id`; cần `INVALID_RESULT`, không coi thành công.

### 8.6. Thí nghiệm độc lập

- **R0:** typed binding + simple exact matching + datetime aware normalization.
- **R1:** ranking entity theo explicit relationship, timestamp, user context, chỉ auto-select nếu đủ unique/evidence.
- **R2:** resolver hints/parameter-provider graph (argument → tool output), đo giảm missing.
- **R3:** temporal coverage tests: next day, weeks, crossing month/year, shifts, timezone (đặc biệt DST ở vùng khác Việt Nam).
- **R4:** schema validation depth: `anyOf`, nested objects, alternative fields; đánh giá invalid tool call rate.

**Metric:** argument exact match, binding success, ambiguity detection precision/recall, unsafe auto-selection count (phải ~0), temporal conversion exact match, explore redundancy, median resolve latency.

**Deliverables N4:** một DSL reference duy nhất + tests, temporal/location utilities, issue taxonomy, resolver hints (nếu cần), standalone fixtures, báo cáo lỗi có root cause.

---

## 9. N5 — Execution Runtime: scheduler, safety, verification, audit

### 9.1. Nhiệm vụ nguyên tử

**Input:** validated `TaskPlan` + per-sample environment + resolver + request context.

**Output:** `RunResult` gồm task/goal statuses, real executed `ToolCallTrace`, issues, audit events; adapter official lấy hash thật.

N5 quản lý *vòng lặp deterministic*, **không làm semantic planning** và không gọi Qwen trong baseline.

### 9.2. State machine

| Status | Nghĩa | Transition cơ bản |
|---|---|---|
| `PENDING` | Chưa chạy | → READY / SKIPPED / BLOCKED |
| `READY` | dependencies OK, condition TRUE, args có thể resolve | → RUNNING |
| `RUNNING` | đang thực thi | → DONE / FAILED / UNCERTAIN |
| `DONE` | postcondition xác minh hợp lệ | terminal |
| `SKIPPED` | nhánh condition FALSE hợp lệ | terminal |
| `BLOCKED` | thiếu dữ liệu, ambiguity, dependency chưa thể hoàn thành | → PENDING khi có explore/user data; hoặc terminal blocked |
| `FAILED` | lỗi xác định, không thể hoàn thành | terminal hoặc recovery policy an toàn |
| `UNCERTAIN` | state-changing call không rõ đã thực thi | terminal/pending reconciliation; không retry mù |

`when` phải được tính theo ba giá trị: `TRUE`, `FALSE`, `UNKNOWN`. TRUE chạy; FALSE skip; UNKNOWN phải chờ/block và ghi evidence cần bổ sung.

### 9.3. Runtime loop (pseudocode)

```python
while within_budgets(state):
    task = scheduler.next_progressable(state)
    if task is None:
        return finalize_goals_or_blockers(state)

    guard = evaluate_when(task.when, state.observations)
    if guard is FALSE:
        state.mark_skipped(task); audit.emit("TASK_SKIPPED", task)
        continue
    if guard is UNKNOWN:
        state.block(task, "GUARD_UNKNOWN")
        continue

    resolution = resolver.resolve(task, state.observations, tool_spec(task), request)
    if resolution.needs_explore:
        state.add_internal_task_if_safe(resolution.suggestion)
        continue
    if not resolution.ready:
        state.block(task, resolution.issue)
        continue

    result = environment.execute(task.tool, resolution.arguments)
    verdict = verifier.check(task, resolution.arguments, result)
    state.record(task, result, verdict)
    audit.emit_tool_and_verdict(task, result, verdict)

return finalize_run(state)
```

**Engineering requirements:** scheduler phải đảm bảo progress; chống explore loop; bảo toàn thứ tự tool calls thật; mỗi state-changing action có idempotency/reconciliation hoặc không retry khi uncertain. Không có tool calls giả do logger tạo ra.

### 9.4. Verification thực sự là gì?

- **Layer 1:** execution response/status; tool call có được kit chấp nhận?
- **Layer 2:** tool result schema hợp lệ; field quan trọng có tồn tại?
- **Layer 3:** postcondition có thể xác minh: đúng event ID, thời gian, đúng người nhận, amount, payment status… nếu evidence có đủ.
- **Layer 4:** goal-level aggregation theo branch. Ví dụ `weather.rain=false` và các actions skipped có thể là **goal SUCCESS** vì user nói “không mưa thì thôi”. Không coi mỗi `SKIPPED` là failure.

**Không cần “Observer LLM”**. Khi điều kiện semantic không thể kiểm chứng bằng rule và không được gọi lại Qwen, trả trạng thái `UNVERIFIED/BLOCKED` rõ ràng, không tuyên bố success giả.

### 9.5. Recovery policy gọn, an toàn

| Lỗi | Hành động baseline |
|---|---|
| Tool result `ok=false` / schema invalid | mark failed + issue, không tiếp tục task phụ thuộc sai |
| Query rỗng | M4 trả `NOT_FOUND`, chỉ retry query khác nếu có đủ evidence |
| Duplicate contact/event | `NEEDS_USER`/`BLOCKED`, không auto-select |
| Guard UNKNOWN | block/need-explore, không chạy side effect |
| Read-only tool timeout | có thể retry giới hạn theo policy |
| State-changing timeout | `UNCERTAIN`, không tự gửi/chuyển tiền lần nữa |
| Invalid TaskPlan | reject trước tool đầu tiên, audit lý do |
| Không có task khả thi | kết thúc `PARTIAL/NEEDS_USER/FAILED`, không loop vô hạn |

### 9.6. Hướng cải tiến có tính thí nghiệm

- **E0:** deterministic scheduler theo dependency và task order, guard tri-state.
- **E1:** postcondition rules theo tool families; đo false-success/false-failure.
- **E2:** safe recovery + reconciliation cho read-only/state-changing (khi API kit cho phép).
- **E3:** tối ưu loop và budgets, dedup explore, giảm calls thừa.
- **E4:** flow audit/trace replayer để tái hiện mọi state transition từ events.

**Metric:** execution correctness trên fixed gold plans, dependency/guard violation rate (mục tiêu 0), goal completion, unnecessary tool calls, unsafe duplicate side effects (mục tiêu 0), recovery success, median wall-clock latency.

**Deliverables N5:** engine/state/scheduler/verifier tests; E2E wiring; audit renderer + JSONL events; regression submission/official adapter tests; báo cáo scenario thành công & thất bại.

---

## 10. Chạy xuyên suốt một case — ai xử lý từng quyết định?

### Case A: `train_0001` — Nếu mai mưa thì dời lịch chạy bộ 1 giờ rồi nhắn

| Bước | Module | Trách nhiệm cụ thể | Ví dụ evidence/output |
|---|---|---|---|
| 1 | N1 | Transcript đúng cả “nếu…”, “không mưa thì thôi” | raw text |
| 2 | N2 | Cung cấp weather, calendar, contacts, sms candidates | allowlisted ToolSpecs |
| 3 | N3 | Sinh 1 plan: weather → (rain true) list events → update → search contact → send, refs + condition | TaskPlan (không có `evt_01`/`c_08` bịa) |
| 4 | N4 | `tomorrow` + `context.current_time` → `2026-11-29` | weather args đã ground |
| 5 | N5 | Gọi `weather.get_forecast` | observation rain=true |
| 6 | N5 | Chỉ mở nhánh mưa | guard TRUE |
| 7 | N5/N4 | List events; chọn chạy bộ theo title/date; shift start/end 60m | `evt_01`: 08:00→09:00, 09:00→10:00 |
| 8 | N5 | Update event; kiểm tra đã update | verified result |
| 9 | N5/N4 | Search “Sếp Dũng”; bind unique contact | `c_08` nếu kết quả thật vậy |
| 10 | N5 | Send SMS với giờ mới, verify | đúng recipient/content |
| 11 | N5 | Aggregate goal, emit audit/trace/hash | success hoặc issue thực tế |

**Cách tách các biến thể test:**

- Rain **FALSE** → các task cập nhật/nhắn **SKIPPED**, không gửi tin.
- Weather thiếu field `rain` → **UNKNOWN**, không tự suy ra từ `condition` text khi rule không hỗ trợ.
- Nhiều event “chạy bộ” → **AMBIGUOUS**.
- Calendar update failed → **không gửi** SMS giả rằng đã dời.
- Contacts trả hai “Sếp Dũng” → hỏi rõ, không chọn đầu.

### Case B: `train_0048` — Hai liên hệ tên Lan

1. N3 sinh `contacts.search("Lan") → phone.call(contact_id=$ref...)`.
2. N5 gọi contacts search; N4 nhận hai candidates không phân biệt được bằng yêu cầu/context.
3. N4 trả `AMBIGUOUS(contact_id, candidates=[...])`; N5 không gọi `phone.call`.
4. Nếu kit cho phép `sys.ask_missing_info`, N5 dùng bridge chính thức đúng schema; nếu không, phản ánh `NEEDS_USER`/`BLOCKED` theo protocol thực tế. **Không tự tạo tool call có tên `sys.ask_missing_info` khi schema session không cho phép.**
5. Flow audit phải ghi rõ: *chưa gọi điện vì sao*.

### Case C: “Nhắc tôi chạy bộ lúc 7 giờ sáng mai”

- N3: sinh symbolic date `tomorrow` + local time `07:00`, không tự bắt buộc tính ISO trong model.
- N4: lấy ngày local từ `context.current_time` + timezone rồi sinh timestamp đúng format của tool.
- N5: verify args trước khi gọi tool; audit cả **raw phrase → resolved timestamp**.

### Case D: “Gần nhà” và “ở đây”

- N3: “ở đây” → reference `current_location`, “nhà” → `home_location` (hai referent khác nhau).
- N4: lấy location hiện tại từ context, còn “nhà” cần nguồn định danh riêng; nếu không có thì MISSING/EXPLORE/ASK.
- N5: không cho maps/ride_hailing chạy với tọa độ bịa.

### Case E: `train_0121` — Lọc hóa đơn trước thanh toán

- N3: hiểu bộ lọc `(due_date within 5 local calendar days) AND (amount <= 500000) AND (unpaid)` và source=`bank`; không quyết định bill IDs trước `list_bills`.
- N4: evaluate biểu thức filter/sort đối với `bill_payment.list_bills` observations, tạo binding cho đúng các hóa đơn.
- N5: chỉ chạy `bill_payment.pay` cho tập đã xác định, không trả hóa đơn vượt ngưỡng; bảo vệ tránh thanh toán trùng.
- **Thiết kế phải chốt:** nếu plan DSL chỉ hỗ trợ một task đơn lẻ với một `bill_id`, case này có thể yêu cầu *foreach over filtered results* hoặc *runtime expansion* có giới hạn. Đây là **năng lực thực sự cần trong dataset**, nhưng không nên thêm tổng quát “workflow language” quá phức tạp; chỉ implement operator loop có scope và budget nếu đã có test chứng minh cần.

---

## 11. Audit flow: nhìn được request, task, quyết định, evidence, issue

### 11.1. Mặc định console: ngắn và diễn giải được

```text
LIFEMATE  train_0001  [single-shot Qwen]
USER    "Nếu mai mưa thì dời chạy bộ muộn 1 tiếng..."
ASR     ok
TOOLS   6 candidates (weather / calendar / contacts / sms)
PLAN    1 goal | 5 tasks | valid | qwen_calls=1

T1  weather.get_forecast(date=2026-11-29)
    ARG    "mai" + context.current_time → 2026-11-29
    RESULT ok  rain=true
T2  calendar.list_events()
    RESULT ok  events=2
T3  calendar.update_event(event_id=evt_01, start=09:00, end=10:00)
    BIND   event_id,start,end ← T2 (shift +60m)
    RESULT ok  verified
T4  contacts.search(query="Sếp Dũng")
    RESULT ok  contacts=1
T5  sms.send(contact_id=c_08, content=...)
    BIND   contact_id ← T4
    RESULT ok  verified
FINAL SUCCESS | done=5 skipped=0 blocked=0 | tool_calls=5 qwen_calls=1
```

**Chỉ in khi có:** condition evaluation, binding provenance, explore injection, blocker/issue, postcondition failure. Không dump full prompts, user profiles, raw tool outputs.

### 11.2. Machine audit: JSONL, 1 event / dòng

```json
{"sample_id":"train_0001","seq":1,"type":"PLAN_CREATED","summary":"5 tasks, 1 goal, valid","qwen_calls":1}
{"sample_id":"train_0001","seq":2,"type":"ARG_BOUND","task_id":"t1","field":"date","source":"context.current_time","value_preview":"2026-11-29"}
{"sample_id":"train_0001","seq":3,"type":"TOOL_EXECUTED","task_id":"t1","tool":"weather.get_forecast","status":"ok","result_summary":"rain=true"}
{"sample_id":"train_0001","seq":4,"type":"CONDITION_EVALUATED","task_id":"t2","result":"TRUE","evidence":"t1.forecast[0].rain"}
```

Event keys tối thiểu: `sample_id`, `seq`, `type`, `task_id?`, `tool?`, `status?`, `summary?`, `issue_code?`, `duration_ms?`, `evidence_ref?`. Tránh payload khổng lồ; `raw` chỉ có khi debug explicit và phải redaction các dữ liệu nhạy cảm.

**N5** sở hữu event schema/renderer. N1/N2/N3/N4 chỉ cấp *summary metadata* vào interface đã thống nhất; không tự in nhiều JSON khác nhau.

### 11.3. Audit cần phân biệt ba loại lỗi

- **Upstream error:** transcript sai → N1, thiếu tool trong candidates → N2, TaskPlan thiếu action/guard → N3.
- **Grounding error:** task logic đúng nhưng ID/time/location/args sai → N4.
- **Execution error:** arguments đúng nhưng scheduler thực thi sai nhánh, retry trùng, verifier đánh giá sai → N5.

Mỗi event lỗi phải chỉ ra `module`, `task_id`, `reason`, `evidence`, `next_action` (nếu có). Đây là nền tảng debugging theo flow, không phải raw dump theo object.

---

## 12. Benchmark độc lập và integration — không đánh giá nhầm đóng góp

### 12.1. Hai loại benchmark phải giữ riêng

| Module | **Oracle benchmark** (cô lập module) | **End-to-end** (dữ liệu thật qua pipeline) |
|---|---|---|
| N1 ASR | WAV + transcript vàng | ảnh hưởng lên task/tool accuracy |
| N2 Discovery | `audio_text` vàng + allowed catalog + labels tool-set offline | kết quả retrieval từ transcript ASR |
| N3 Planner | `audio_text` vàng + **gold/oracle tool cards** (chỉ offline) + manually verified plan labels | tool candidates do N2 dự đoán |
| N4 Resolver | Gold task + fixture observations + ToolSpec | Qwen plan thật + real tool outputs |
| N5 Runtime | Fixed validated plan + fake/official-compatible env + resolver stub/real | cả pipeline đã tích hợp |

**Không leak:** gold tools/transcript/labels chỉ nằm trong evaluator. Trong inference thật, M3 không thấy `label`, và không thấy future tool results. Tách train/validation theo sample ID; với synthetic variants cần chống near-duplicate paraphrase giữa train/val.

### 12.2. Metric definitions (để mọi người tính giống nhau)

- **WER/CER:** lỗi phiên âm so với `audio_text` oracle; thêm critical-slot error để không che khuất lỗi “không”.
- **Discovery Recall@K:** `|gold_tools ∩ retrieved| / |gold_tools|`; **Full-chain Recall:** tỷ lệ samples có *tất cả* tool cần trong candidates. Với empty gold tool-set, thống nhất quy tắc no-op riêng.
- **Plan validity:** đúng schema, refs, dependency acyclic, allowed tools, recognized expressions.
- **Tool set/sequence match:** so với `label.tool_calls` khi chạy replay tình huống được gán; không dùng sequence match thay thế goal correctness cho mọi branch.
- **Dependency/condition accuracy:** đối chiếu trên small verified annotation set, không suy từ tool-call order.
- **Resolver exact arguments:** trên fixtures đã có ground truth; temporal exact match và ambiguity safety được báo cáo riêng.
- **Runtime correctness:** được chấm với fixed plans; phân biệt plan sai từ upstream và runtime execution sai.
- **Safety metrics:** invalid/unauthorized calls, wrong-recipient calls, condition violations, duplicate side-effect calls. Các số này phải được báo cáo riêng dù total success cao.

### 12.3. Mỗi experiment report cần 1 bảng chuẩn

| Field | Ghi gì |
|---|---|
| `experiment_id` | Mã duy nhất: `M3_fewshot_v2` |
| `owner` | N1–N5 |
| `baseline_commit / candidate_commit` | commit hash để reproduce |
| `dataset_split / sample_ids` | version/seed, không đổi để so sánh |
| `single_changed_variable` | thứ duy nhất được thay |
| `oracle_metric_before/after` | metrics riêng module |
| `E2E_metric_before/after` | khi tích hợp |
| `latency / memory / tool_calls / tokens` | chi phí thực |
| `failure_cases` | sample IDs + root causes |
| `decision` | adopt / reject / investigate |

### 12.4. Chiến lược thí nghiệm ít tốn công nhất

1. **Freeze baseline** và chạy E2E/mock/replay trên một tập validation đã khóa.
2. Mỗi người xây **oracle harness** riêng và lưu outputs dưới `outputs/evaluations/<module>/`.
3. Mỗi experiment **thay một thứ** (prompt, retriever, parser, policy…).
4. Nếu module metric tăng, chạy cùng integration tests; nếu E2E giảm thì phân tích audit theo `task_id`.
5. Không merge tối ưu chỉ nhờ vài ví dụ đẹp; cần bằng chứng trên tập validation và kiểm tra regression/safety.

---

## 13. Roadmap cải tiến có thứ tự ưu tiên (không mở rộng kiến trúc sớm)

**P0 — Sửa tính đúng trước:** schema, allowlist, no-leakage, condition FALSE/UNKNOWN, time grounding từ context, ambiguity, no duplicate side effect. Bất kỳ lỗi nào ở đây là blocker.

**P1 — Tăng coverage của baseline:**

- N1: critical entities trong ASR.
- N2: Tool Full-chain Recall.
- N3: Goal/Task completeness + condition/dependency + symbolic args.
- N4: time/location/entity resolution chính xác; resolver issue tốt.
- N5: trace/verification/stop rules.

**P2 — Tối ưu chất lượng theo nghiên cứu:**

- N2: BM25/hybrid/dense nếu vượt lexical rõ rệt.
- N3: few-shot + constrained decoding → LoRA/SFT nếu có đủ validated plans.
- N4: evidence-based entity ranking và argument-provider graph.
- N5: safe recovery policies + minimal audit summaries.
- N1: model/decoding tuning có đo downstream.

**Để sau khi baseline đủ tốt:** multi-shot semantic replanning, các LLM chuyên biệt, vector database, long-term memory, generic workflow DSL lớn, multi-agent orchestration. Những thứ này chỉ thêm khi baseline metrics và failure analysis chứng minh cần.

---

## 14. Bộ test bắt buộc và tiêu chí nghiệm thu nhóm

### 14.1. Test matrix (ít nhất)

| ID | Ca | Module chủ yếu | Expected |
|---|---|---|---|
| T01 | Direct alarm | N3/N5 | Đúng tool, args, 1 Qwen call |
| T02 | “ngày mai” qua cuối tháng/năm | N3/N4 | Đúng date so với context, không dựa clock máy |
| T03 | “sau 24 giờ” vs “ngày mai giờ này” | N3/N4 | Hai nghĩa khác nhau khi phù hợp timezone |
| T04 | “gọi bác Ba” chưa có contact ID | N3/N4 | Lookup/binding, không hallucinate ID |
| T05 | Hai contacts trùng tên (train_0048) | N4/N5 | AMBIGUOUS; không gọi người bừa |
| T06 | Conditional rain=true (train_0001) | N3/N5 | Update và notify theo thứ tự |
| T07 | Conditional rain=false | N3/N5 | Skip mutation/SMS; không false failure |
| T08 | Conditional result thiếu `rain` | N4/N5 | UNKNOWN, không side effect |
| T09 | Calendar update fails | N5 | Không gửi lời nhắn xác nhận thay đổi |
| T10 | Multi-goal báo thức + gọi | N3/N5 | Goal độc lập thành công vẫn giữ khi goal kia blocked |
| T11 | “cái sớm nhất”, “cái còn lại” trong history | N3/N4 | đúng referent, chống stale |
| T12 | Bill filtering >500k (train_0121) | N3/N4/N5 | chỉ pay đúng bills, không lặp |
| T13 | Request không có allowed tool | N2/N3/N5 | không gọi tool bịa |
| T14 | Invalid plan/cycle/unknown ref | N3/N5 | reject trước tool đầu tiên |
| T15 | Tool timeout read-only | N5 | retry có giới hạn nếu cho phép |
| T16 | Tool timeout state-changing | N5 | UNCERTAIN, không retry mù |
| T17 | Location “ở đây” vs “nhà” | N3/N4 | không đánh đồng, không bịa tọa độ |
| T18 | No-op / user self-correction | N1/N3/N5 | không chạy hành động bị hủy |
| T19 | `sys.ask_missing_info` chính thức | N4/N5/app | theo đúng API kit, không phát call giả |
| T20 | Submission official-compatible | N5/app | đúng 3 khóa, trace thật, hash official |

### 14.2. Definition of Done theo thành viên

- **N1 done:** chạy oracle WER/CER + critical ASR suite; outputs đúng `Transcript` contract; không sửa semantic plan.
- **N2 done:** recall report + strict allowlist tests; không dùng LLM; candidates/ToolCards phù hợp schema.
- **N3 done:** TaskPlan valid, goals/tasks/condition refs đủ trên verified cases, Qwen call counter =1; không execute tool.
- **N4 done:** references/time/location/args tính đúng; issue taxonomy đầy đủ; ambiguous không auto-select; không gọi tool.
- **N5 done:** fixed-plan E2E đúng state machine; tool execution, verifier, audit, submission đạt tests; không gọi Qwen.
- **Team done:** mock/fixture/test passes; official compatibility được xác minh riêng trong sandbox/kit theo rules; audit timeline cho thấy rõ luồng một sample.

---

## 15. Checklist “as-built”: cần agent rà lại repo **đã refactor** trước khi công bố tài liệu

> Đây là checklist xác minh, **không** mặc định rằng code thực tế đã làm đủ mọi điểm.

- [ ] Ghi lại commit baseline, version Python, model/checkpoint, quantization, flags.
- [ ] Xác nhận 5 module và đúng public method signatures; nếu tên khác nhưng semantics khớp, **cập nhật tài liệu**, không ép đổi tên vô ích.
- [ ] Xác nhận số Qwen calls thực tế mỗi request; có JSON repair / hidden model calls không?
- [ ] Xác nhận Discovery dùng allowed catalog theo sample và output candidate tool cards đúng hợp đồng.
- [ ] Xác nhận TaskPlan và ExecutionState tách quyền sở hữu, DSL `$ref`/time/location dùng một grammar.
- [ ] Xác nhận Temporal Resolver dùng `context.current_time` và `timezone`, **không** đồng hồ hệ thống.
- [ ] Xác nhận conditional tri-state; guard UNKNOWN không tự false.
- [ ] Xác nhận M4 không gọi tool; M5 là module duy nhất execute và mutate state.
- [ ] Xác nhận Resolver support alternative argument schema và detected ambiguity.
- [ ] Xác nhận explore injection chống loop/duplicate và không tự biến thành semantic replanning.
- [ ] Xác nhận `sys.ask_missing_info` theo `zaic_tools` kit **thực tế** của split; ghi rõ đó là internal action hay permitted tool call.
- [ ] Xác nhận không leak `audio_text`, `label`, future results vào inference.
- [ ] Xác nhận `app/competition_io.py` giữ `id/tool_calls/state_hash`, official hash từ kit.
- [ ] Xác nhận audit console ngắn, debug JSONL riêng và không lộ dữ liệu nhạy cảm mặc định.
- [ ] Chạy `pytest -q`, `ruff check .`, fixture end-to-end; log kết quả **thực**, không copy số test pass từ tài liệu cũ.

**Yêu cầu coding agent sau verification:** cập nhật `docs/team_roles_baseline_experiments.md` bằng **tên file/hàm/config as-built**, đánh dấu từng gap `IMPLEMENTED / PARTIAL / MISSING`; nếu phát hiện khác biệt quan trọng, sửa doc hoặc tạo issue cụ thể kèm file:line và testcase. **Không tự thêm kiến trúc mới khi chưa được nhóm duyệt.**

---

## 16. Tài liệu tham khảo cho từng hướng (tham khảo kỹ thuật, không phải thành phần bắt buộc)

| Chủ đề | Tham khảo | Ứng dụng dự kiến |
|---|---|---|
| Qwen 4B instruct | [Qwen3-4B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | N3: xác nhận model, prompt/template, inference setup |
| Structured JSON decoding | [vLLM Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/) | N3: JSON-schema guided output **nếu dùng vLLM**, không giả định Transformers hiện hỗ trợ giống hệt |
| PEFT/LoRA | [Hugging Face PEFT](https://huggingface.co/docs/transformers/peft) | N3: SFT với adapters nếu có verified TaskPlan labels |
| Retrieve/rerank | [Sentence Transformers Retrieve & Re-Rank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) | N2: embedding/hybrid tool discovery |
| Aware timezone | [Python `zoneinfo`](https://docs.python.org/3/library/zoneinfo.html) | N4: tính lịch địa phương, DST/fold đúng |
| JSON Schema | [JSON Schema specification](https://json-schema.org/specification) | N4/N5: alternative args và output validation |
| Typed models | [Pydantic documentation](https://docs.pydantic.dev/latest/) | core: kiểm tra contracts và schema |

**Thứ tự ưu tiên:** sửa lỗi thiết kế/grounding trước, rồi benchmark từng module, cuối cùng mới quyết định cần SFT, embedding hay inference bổ sung. Bất kỳ kỹ thuật tham khảo nào cũng cần đo lợi ích so với độ trễ, token và tài nguyên GPU của baseline.

---

## Phụ lục A. Template thí nghiệm (copy cho mỗi người)

```markdown
# Mx Experiment: <short-title>
- Owner:
- Baseline commit / Variant commit:
- Dataset/fixture version + split:
- Research question:
- Single change:
- Model/checkpoint/parameters (nếu có):
- Oracle metric baseline → variant:
- E2E metric baseline → variant:
- Latency/tokens/memory/tool calls:
- Regression/safety failures:
- Top 5 error sample IDs + root cause:
- Decision: adopt/reject/further investigation
```

## Phụ lục B. Template issue từ Resolver/Runtime

```json
{
  "task_id": "t2",
  "issue": {
    "code": "AMBIGUOUS",
    "field": "contact_id",
    "source": "contacts.search",
    "evidence": {"candidate_count": 2},
    "suggested_action": "ASK_USER"
  }
}
```

Không nhồi full contact list với số điện thoại vào console audit; raw details (nếu lưu) cần permission và redaction.

## Phụ lục C. Yêu cầu ngắn giao cho coding agent để đồng bộ doc với repo thực tế

> Đọc `LifeMate_V2_Team_Plan_Detailed.md`, inspect repo V2 hiện tại. **Chỉ đối chiếu**, không tự refactor nếu chưa được yêu cầu. Với từng module M1–M5, xác nhận file thật, public interface, thuật toán đang chạy, test/eval commands, những gap so với đặc tả. Cập nhật phần “As-built verification” với bằng chứng file:line, gắn trạng thái IMPLEMENTED/PARTIAL/MISSING. Giữ baseline đúng một Qwen planning inference, không thay official environment/submission, không tự tạo thêm module/LLM calls. Báo cáo gọn các contract mismatch và đề xuất PR nhỏ để sửa.

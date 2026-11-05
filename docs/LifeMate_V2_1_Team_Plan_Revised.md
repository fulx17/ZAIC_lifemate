# LifeMate V2.1 — Team Plan
## Pipeline tổng quan · Vai trò 5 thành viên · Baseline · Failure modes · Hướng cải tiến

> **Mục đích:** Tài liệu chung để mỗi thành viên hiểu hệ thống đang được thiết kế vận hành ra sao, phần mình chịu trách nhiệm, những lỗi có thể gặp và hướng nghiên cứu/cải thiện. Không phải tài liệu refactor, phân sprint hay checklist giao việc.
>
> **Phạm vi chính xác:** Mô tả **baseline/kiến trúc V2.1 đã thống nhất** (single-shot initial planning + optional issue-triggered repair). Nhóm đã refactor V2, nhưng chưa có source V2.1 sau khi bổ sung adaptive repair để đối chiếu; vì vậy những phần mô tả cơ chế recovery là **thiết kế mục tiêu**, không mặc nhiên là tính năng đã chạy. Các ví dụ `$context`, `$time`, `$need`, `$ref` là *biểu thức logic minh họa*; dùng cú pháp DSL thực đã thống nhất trong repo, không gửi nguyên các biểu thức này cho tool API.

---

# 1. Tổng quan hệ thống

## 1.1. Bài toán LifeMate

**Input:** audio tiếng Việt + `context` (thời gian tham chiếu, timezone, location, profile, installed apps) + `history` nếu có.

**Mục tiêu:** hiểu yêu cầu của người dùng, tìm các công cụ được phép, lập và thực thi đúng các tác vụ; truy xuất thêm thông tin khi cần; không tự điền dữ kiện không có căn cứ; và trả kết quả khớp ý định ban đầu.

**Output cuộc thi:** `{id, tool_calls, state_hash}`. Các `tool_calls`, side effects và `state_hash` phải dựa vào môi trường tool chính thức, không tự dựng.

Hai kiểu thành công phải tách biệt:

- **Execution success:** tool API trả thành công (`ok=true`, `booked`, `sent`...).
- **Goal satisfaction:** kết quả thỏa **đúng yêu cầu**, bao gồm người nhận, thời gian, địa điểm, điều kiện và các giới hạn.

Một tool call thành công nhưng đặt xe sai địa điểm vẫn là thất bại ở cấp user goal.

## 1.2. Pipeline V2.1

```text
Audio + context + history
       |
       v
[N1 — ASR]                      Audio -> transcript
       |
       v
[N2 — Initial Tool Discovery]   Transcript + allowed ToolSpecs -> candidates
       |
       v
[N3 — Qwen Initial Planner]     Goals + complete logical TaskPlan
       |                         (1 initial LLM call)
       v
+----------------------- [N5 — Runtime] ---------------------------+
| Validate plan / maintain state / choose executable task           |
|                                                                   |
|             [N4 — Argument Resolver]                               |
|                 |                                                 |
|     +-----------+-------------+                                   |
|     |                         |                                   |
|   READY                BLOCKED / InformationNeed                  |
|     |                         |                                   |
| Execute allowed tool            v                                  |
|     |             [N2 — Retrieve for InformationNeed]             |
| Observe/verify                 | candidates                       |
|     |                          v                                  |
|     |             [N3 — Qwen Repair / Discovery Plan]             |
|     |             PlanPatch | ASK_USER | STOP                     |
|     |                          |                                  |
|     |                   N5 validate/apply patch                   |
|     +--------------------------+----------------------------------|
|                             repeat only if useful                |
+-------------------------------------------------------------------+
       |
       v
RunResult + audit -> official submission
```

**Quy tắc vận hành:**

1. N3 sinh **initial plan một lần**. Đây là kế hoạch logic có thể chứa tham chiếu tới context, kết quả tool trong tương lai hoặc thông tin còn thiếu.
2. N5 chạy những task thỏa dependency và guard; trước mỗi action, N4 phải resolve và kiểm tra arguments.
3. Khi N4 trả **InformationNeed**, N5 *không tự nghĩ ra* nên dùng tool gì. N5 gọi **N2** lấy candidate provider, rồi **N3** quyết định `EXPLORE`, `ASK_USER` hoặc `STOP`, và sinh PlanPatch khi cần.
4. N5 chỉ áp dụng patch hợp lệ, kiểm soát số lượt repair, tránh lặp vô hạn và trùng side effect.
5. **Không phải issue nào cũng cần gọi Qwen lần hai:** thiếu một ID đã có trong observation, cộng thời gian, format dữ liệu và các phép biến đổi xác định được do N4 giải quyết bằng code.

Hai chế độ nên được giữ để so sánh: `strict_single_shot` (1 Qwen call, không repair) và `adaptive_on_issue` (1 initial call + repair khi có issue, giới hạn bằng config; mốc xuất phát đề xuất tối đa 1 repair call). Không biến repair thành bước mặc định sau mọi tool call.

## 1.3. Ranh giới trách nhiệm — ai quyết định điều gì?

| Câu hỏi | Chủ sở hữu | Không thuộc trách nhiệm của họ |
|---|---|---|
| Audio nói gì? | **N1 ASR** | Tự tạo task hoặc định ngày từ lời nói |
| Có tool nào phù hợp với hành động hoặc nhu cầu thông tin? | **N2 Discovery** | Quyết định thực thi, tự tạo PlanPatch |
| Người dùng muốn gì; cần task nào; liên hệ giữa chúng; khi thiếu cần khám phá gì? | **N3 Planner** | Thực thi tool, tự bịa ID/địa chỉ/giờ |
| Argument nào đã đủ căn cứ; còn thiếu gì; giá trị được resolve thế nào? | **N4 Resolver** | Tự chọn chiến lược gọi `calendar.list_events` bằng suy đoán |
| Khi nào chạy, block, recover, hỏi, dừng; có đạt goal không? | **N5 Runtime** | Tự thực hiện semantic planning để chọn provider |

**Phân biệt đặc biệt quan trọng:**

- `InformationNeed`: **N4** mô tả *cần biết gì*.
- `ToolCandidates`: **N2** xếp hạng *công cụ nào có thể cung cấp điều đó*.
- `PlanPatch`: **N3** quyết định *thử công cụ nào, lấy gì, gắn kết quả vào task nào, hay hỏi/dừng*.
- `ExecutionState`: **N5** quyết định *có được phép chạy patch/action không, và lưu bằng chứng nào*.

## 1.4. Cách data đi qua hệ thống

| Dữ liệu | Sinh ra bởi | Dùng ở | Ghi nhớ |
|---|---|---|---|
| Transcript | N1 | N2, N3; đối chiếu semantic | ASR có thể sai, không phải nguồn truth tuyệt đối |
| Allowed ToolSpecs | Environment | N2, N3, N4, N5 | Chỉ các tools thực sự được phép cho sample |
| `TaskPlan` | N3 | N4, N5 | Goals, tasks, dependencies, guards, value expressions; **không** chứa trạng thái thực thi |
| Tool observations | Environment/N5 | N4, N3 khi repair | Chỉ xuất hiện **sau** execution, có provenance |
| `InformationNeed` | N4 | N2, N3, N5 | Field thiếu, precision cần, constraints, nguồn đã thử |
| `PlanPatch / ASK_USER / STOP` | N3 | N5 | Patch tối thiểu, không sửa task đã hoàn thành |
| `ResolutionResult` | N4 | N5 | `READY` hoặc issues; READY phải đúng *cả schema lẫn grounding* |
| `ExecutionState`, `RunResult` | N5 | Pipeline/output | Single writer cho trạng thái, audit và kết luận |

**Ví dụ semantics:** user nói “mai”, N3 hiểu đây là *ngày lịch địa phương tiếp theo* và gắn vào argument; N4 dùng **`context.current_time` + `timezone`** tính ngày thực. User nói “công ty”, N3 xác định referent là *workplace*; N4 lấy `user_profile.work_address`. User nói “đi khám răng”, N3 nhận ra *mục đích*, không được khẳng định đó là địa chỉ đến.

---

# 2. N1 — ASR: Audio → Transcript

## 2.1. Nhiệm vụ và trách nhiệm

**Câu hỏi N1 chịu trách nhiệm:** *Người dùng thực sự nói gì?*

- Nhận audio và trả transcript tiếng Việt chính xác, ưu tiên giữ nguyên phủ định, tên riêng, con số, giờ/ngày, đơn vị, quan hệ và câu tự sửa.
- Chịu trách nhiệm tiền xử lý audio và decoding trong phạm vi ASR, đo chất lượng recognition và độ trễ.
- Không suy luận user intent, không chọn tool, không tự chuyển “ngày mai” thành ISO timestamp; chuyện này thuộc N3/N4.

## 2.2. Cách baseline hoạt động

```text
Audio path -> audio load/normalize -> PhoWhisper-medium
           -> decode -> transcript -> downstream
```

Baseline đã được định hướng là PhoWhisper-medium. Các hyperparameters, weights và preprocessing chính xác cần dựa trên implementation thực tế. N1 có thể xuất thêm confidence/segments nếu backend hỗ trợ, nhưng không ép N2–N5 phụ thuộc vào metadata chưa đáng tin cậy.

## 2.3. Failure modes N1 cần chịu trách nhiệm

| Failure | Ví dụ | Hậu quả |
|---|---|---|
| Sai từ chức năng | “**từ** công ty” → “**thử** công ty” | N3 hiểu sai nguồn/đích |
| Mất phủ định/điều kiện | “**không** mưa thì thôi” → bỏ “không” | Thực hiện action trái điều kiện |
| Sai số/đơn vị | 500 nghìn → 50 nghìn | Chuyển/chi sai tiền |
| Sai tên riêng | “Sếp Dũng” → tên khác | Nhắn/gọi sai người |
| Bỏ lời tự sửa | “7 giờ… à không, 8 giờ” | Dùng giá trị cũ |
| Nhiễu/giọng vùng miền | Mất một mệnh đề | N3 bỏ goal hoặc task |

Không coi transcript đọc được trôi chảy là “đã đúng”; các lỗi nhỏ ở từ quan trọng có thể gây sai cả workflow.

## 2.4. Hướng phát triển/cải thiện

| Hướng | Ý tưởng | Tác dụng cần kiểm chứng |
|---|---|---|
| **A1 — Decoding tuning** | Beam search/temperature/threshold nếu backend hỗ trợ | Giảm WER/CER, đổi latency ra sao |
| **A2 — Critical-entity-aware analysis** | Đánh giá riêng negation, date/time, amount, name | Giảm lỗi có hậu quả hành động, không chỉ lỗi ký tự |
| **A3 — Audio preprocessing** | Chuẩn hóa sample rate, lọc nhiễu thận trọng | Cải thiện noisy samples |
| **A4 — Model comparison** | Các checkpoint PhoWhisper/ASR khác trong ngân sách GPU | Chọn tradeoff độ chính xác–tốc độ |
| **A5 — Context-aware recognition (thử nghiệm)** | Hotwords/context hints nếu backend và cuộc thi cho phép | Cải thiện tên riêng; tránh biến hint thành hallucination |

**Thước đo chính:** WER, CER, critical-slot accuracy (phủ định/số/thời gian/tên), ASR latency. Test độc lập bằng audio và transcript tham chiếu của train **chỉ trong offline evaluation**; không dùng `audio_text` gold khi inference.

---

# 3. N2 — Tool Discovery: Tool retrieval cho action và information need

## 3.1. Nhiệm vụ và trách nhiệm

**Câu hỏi N2 chịu trách nhiệm:** *Những tool nào có khả năng giúp thực hiện action hoặc tìm thông tin còn thiếu?*

N2 có **hai ngữ cảnh sử dụng**:

- **Initial retrieval:** từ transcript/context lấy các tool có khả năng thực hiện yêu cầu chính và các prerequisite rõ ràng (ví dụ `contacts.search` trước `phone.call` khi cần `contact_id`).
- **Recovery retrieval:** từ `InformationNeed` của N4 tìm các **information providers** như `calendar.list_events`, `reminders.list`, `contacts.search`, không phụ thuộc việc tên tool có xuất hiện trong câu nói ban đầu.

N2 **chỉ xếp hạng ứng viên, cung cấp mô tả, schema và capability**. N2 không tự tạo task; không phải cứ retrieve `calendar.list_events` là Runtime phải gọi nó. Quyết định chọn chiến lược thuộc N3.

## 3.2. Cách baseline hoạt động

```text
                  +--> initial request / transcript -----------+
Allowed ToolSpecs |                                            +--> capability mapping
                  +--> InformationNeed + known constraints ----+    + keyword scoring
                                                                    + allowed-tool filter
                                                                    + dependency/resolver closure
                                                                    + Top-K candidates
```

Baseline: capability mapping + keyword scoring, Top-K (ví dụ Top-8 ở initial), có mở rộng những tool prerequisite/resolver phù hợp. Khi recovery phải tìm trong **toàn bộ tool được phép**, không chỉ 8 ứng viên từ lượt đầu. Tool metadata có thể mô tả `could_provide`, `side_effect`, input/output schema **nếu có nguồn đáng tin cậy**; không suy diễn một field mà API không công bố.

## 3.3. Failure modes N2 cần chịu trách nhiệm

| Failure | Nguyên nhân | Tác động |
|---|---|---|
| Recall thiếu provider | Query chỉ dựa trên lời user “đặt xe”, không có “calendar” | N3 không có tool để tìm lịch khám |
| Candidate nhiễu | Top-K lấy nhiều smart-home/banking cho booking | Tăng token/context noise, nguy cơ Qwen chọn sai |
| Không hiểu tool chain | Chỉ đưa `phone.call`, thiếu `contacts.search` | Task không resolve được `contact_id` |
| Tool ngoài allowlist | Registry dùng catalog toàn hệ thống | Plan gọi tool không được phép |
| Sai khả năng tool | Tự ghi `could_provide=location` dù API không hỗ trợ | N3 tạo explore plan vô ích |
| Lặp provider đã thử | Không lưu attempted tool/query/issue | Runtime mắc recovery loop |
| Không tìm được gì nhưng vẫn trả tool bất kỳ | Không cho phép `[]` | Tạo false hope và wasted calls |

## 3.4. Hướng phát triển/cải thiện

| Hướng | Ý tưởng | Tác dụng cần kiểm chứng |
|---|---|---|
| **D1 — BM25** | Index tên, mô tả, input/output schema, capability | Recall@K/precision tốt hơn keyword overlap? |
| **D2 — Dense embeddings** | Embedding tiếng Việt/multilingual cho implicit needs | Hiểu “địa chỉ đi khám răng” → calendar mà không có từ khóa? |
| **D3 — Hybrid retrieval** | Kết hợp lexical + dense, RRF/rerank | Bền vững với cả exact tool terms và paraphrase |
| **D4 — Provider/capability graph** | `information_type → tool providers → prerequisite` | Tìm nguồn dữ liệu theo field cần lấy, không theo action |
| **D5 — Query expansion** | Mở rộng InformationNeed bằng entity, date, required precision | Giảm missing provider ở recovery |
| **D6 — Adaptive Top-K** | Confidence/coverage threshold, token budget | Giảm irrelevant tools mà vẫn đủ recall |

**Thước đo chính:** initial Tool Recall@K, **Recovery Provider Recall@K**, full-chain recall, candidate noise/precision, retrieval latency, allowlist violations. Mẫu đánh giá N2 cần cả requests bình thường và `InformationNeed` độc lập; nhãn tool-call train **không tự động** là gold nhãn provider cho recovery.

---

# 4. N3 — Qwen Planner: Semantic understanding, initial plan và adaptive replanning

## 4.1. Nhiệm vụ và trách nhiệm

**Câu hỏi N3 chịu trách nhiệm:** *User muốn đạt goal nào; những task nào cần tạo; quan hệ logic ra sao; khi thiếu dữ liệu nên làm gì?*

N3 là **nơi ra quyết định semantic** của LifeMate, không phải tool executor. Nó chịu trách nhiệm:

- Đọc transcript **cùng context và history** để hiểu ý định, constraints, các câu điều kiện, phủ định, quan hệ và tự sửa.
- Biến ý định thành goals, tasks, selected tool, dependency, `when`/guards, argument expressions có thể được N4 resolve sau.
- Phân biệt `literal` đã biết, tham chiếu `context`, tham chiếu `tool result` trong tương lai, thời gian tương đối, entity và dữ kiện chưa có.
- Khi nhận issues + candidates trong recovery, quyết định **EXPLORE / ASK_USER / STOP** và sinh **minimal PlanPatch** nếu cần explore/sửa plan.

N3 **không** tự gọi tools; không tự tính hết time arithmetic; không tự chọn contact ID/địa chỉ không có bằng chứng; không sửa task đã thực thi.

## 4.2. Cách baseline hoạt động

**Initial planning:**

```text
Transcript + relevant context/history
+ candidate ToolSpecs (N2)
+ TaskPlan schema + planning patterns
       |
       v
Qwen3-4B-Instruct-2507 (một lượt initial)
       |
       v
TaskPlan(goals, tasks, tool names, dependencies, guards, value expressions)
```

**Recovery planning:**

```text
Original request + compact execution state + prior observations
+ N4 Issue / InformationNeed
+ N2 recovery candidates + attempted history
       |
       v
Qwen repair (chỉ khi issue cần semantic decision)
       |
       v
PlanPatch | ASK_USER | STOP
```

Ví dụ “nếu mai mưa thì dời lịch chạy bộ một giờ và nhắn Sếp Dũng” đòi hỏi N3 biểu diễn đủ chuỗi *weather check → guarded calendar lookup/update → contact lookup/send*, trong đó thời gian được dịch từ context hoặc dữ liệu calendar theo N4. Qwen có thể sinh toàn bộ cấu trúc logic từ initial call, nhưng **không thể biết trước event ID hoặc forecast thật**.

## 4.3. Failure modes N3 cần chịu trách nhiệm

| Failure | Ví dụ | Hậu quả |
|---|---|---|
| **Goal omission** | User yêu cầu dời lịch **và** nhắn; plan chỉ có dời lịch | Bỏ sót hành động dù graph hợp lệ |
| **Task omission/wrong tool** | Có mục tiêu cần read trước action nhưng chỉ sinh action | Không có dữ liệu để thực thi đúng |
| **Wrong dependencies/guards** | Nhắn Sếp Dũng ngay cả khi không mưa | Side effect trái điều kiện |
| **Argument hallucination** | “Chiều nay” → tự chọn 14:00; payment=`ewallet` không nguồn | Tool call có vẻ hợp lệ nhưng sai yêu cầu |
| **Confuse task vs information acquisition** | Không phân biệt đặt xe với việc tìm địa chỉ phòng khám | Không sinh discovery strategy khi cần |
| **Bad repair strategy** | Thiếu giờ user phải quyết định nhưng vẫn gọi calendar vô hạn | Wasted calls/loop |
| **Unsafe patch** | Patch gọi lại transfer hoặc sửa task DONE | Trùng side effect hoặc đổi kế hoạch đã thực thi |
| **Broken output** | JSON sai schema, tool không allowed, dangling refs | Không thể execute |
| **Under-reasoning** | Kế hoạch đúng cú pháp nhưng chưa đầy đủ ý định | Không có issue để Runtime kích hoạt repair |

Lưu ý: N4 có thể phát hiện một số lỗi grounding nhưng **không thể luôn phát hiện goal bị N3 bỏ sót**. Nếu model bỏ cả goal lẫn task, chỉ rule-based graph validation không đủ để biết. Đây là hướng nghiên cứu semantic coverage riêng của N3.

## 4.4. Hướng phát triển/cải thiện

| Hướng | Ý tưởng | Tác dụng cần kiểm chứng |
|---|---|---|
| **P1 — Structured/constrained decoding** | Enforce TaskPlan/PlanPatch JSON syntax | Giảm malformed output, không đảm bảo semantic accuracy |
| **P2 — Planning patterns** | Direct, lookup→action, read→modify, conditional, multi-goal | Giảm thiếu dependency, giúp Qwen 4B nhất quán |
| **P3 — Goal/effect coverage mapping** | Liên kết span yêu cầu → goals → expected effects → tasks | Phát hiện goal/task omission tốt hơn |
| **P4 — Issue-conditioned repair** | Sinh patch tối thiểu từ issue + state + tool candidates | Tăng recovery success, ít phá plan cũ |
| **P5 — Explore/Ask/Stop policy** | Học/quy tắc khi nào tìm thêm, hỏi user, dừng | Giảm unnecessary tools và hallucinations |
| **P6 — LoRA/SFT** | Train TaskPlan và issue→patch trên nhãn đã kiểm chứng | Cải thiện semantic planning hơn chỉ prompt engineering |
| **P7 — Hard-case augmentation** | Conditions, ambiguous references, paraphrase, temporal constraints | Tăng generalization và robustness |
| **P8 — Optional semantic verifier** | Extra verifier pass cho ca có rủi ro/complexity cao | Bắt omission; so sánh accuracy với latency/cost |

**Thước đo chính:** goal/task coverage, correct tools, dependency/condition accuracy, argument-expression accuracy, executable-plan rate, patch validity, repair success, Qwen calls, latency. Dữ liệu train có tool-call traces nhưng **không có nhãn gold TaskPlan/PlanPatch trực tiếp**; muốn SFT phải xây nhãn có kiểm chứng, không leakage tool results tương lai vào initial plan.

---

# 5. N4 — Argument Resolver: Grounding + phát hiện thông tin thiếu

## 5.1. Nhiệm vụ và trách nhiệm

**Câu hỏi N4 chịu trách nhiệm:** *Các arguments này có đủ căn cứ để gọi tool đúng và an toàn chưa? Nếu chưa, chính xác cần biết gì?*

N4 sở hữu:

1. **Schema validation:** fields, types, required, enum, các nhánh `anyOf/oneOf` theo schema thực.
2. **Reference binding:** context/path refs; outputs từ tool observations; chọn entity dựa trên constraints và uniqueness.
3. **Temporal resolver:** biểu thức “mai”, “chiều nay”, “sau 24 giờ”, “lùi lịch một giờ” → giá trị thời gian khi đủ precision.
4. **Spatial resolver:** “ở đây”, “nhà”, “công ty”, “địa điểm lịch hẹn” → dữ liệu location từ context/observations.
5. **Provenance & semantic readiness:** phân biệt giá trị thực sự từ user/context/tool/default hợp lệ với giả định do LLM tự điền.
6. **Information-gap detection:** trả `InformationNeed` có field, constraints, required precision và known evidence cho N2/N3.

N4 **không** sinh discovery plan, không trực tiếp chọn `calendar.list_events`, không gọi Qwen và không gọi tool.

## 5.2. Cách baseline hoạt động

```text
Task argument expressions + tool schema
+ context + observations
       |
       v
Evaluate references / time / location / entity
       |
       v
Validate types + constraints + provenance + precision
       |
       +--> READY(grounded tool arguments)
       |
       +--> BLOCKED(Issue[] + InformationNeed[])
```

Ví dụ time grounding:

- Context: `2026-11-16T11:30:00+07:00`, timezone `Asia/Ho_Chi_Minh`.
- “**chiều nay**” → ngày `2026-11-16`, period `afternoon`, **không đủ exact pickup time** nếu tool đòi chính xác giờ.
- “**ngày mai**” → `2026-11-17` theo lịch địa phương.
- “**sau 24 giờ**” → cộng duration 24 giờ từ `current_time`, không mặc định đồng nghĩa với “ngày mai”.

Ví dụ location grounding:

- “**từ công ty**” → `user_profile.work_address` nếu referent nhất quán.
- “**ở đây**” → `context.location`, nếu có và được phép dùng.
- “**đi khám răng**” → *mục đích chuyến đi*, **không phải** địa chỉ; cần `InformationNeed(LOCATION)`.

**`READY` không có nghĩa chỉ đủ key và đúng string type.** Nếu pickup/dropoff/payment/schedule_time chưa có nguồn đáng tin cậy hoặc chưa đủ precision, N4 phải báo issue, trừ khi actual tool schema cho phép bỏ field hoặc có default được xác nhận.

## 5.3. Failure modes N4 cần chịu trách nhiệm

| Failure | Ví dụ | Hậu quả |
|---|---|---|
| **False READY** | `dropoff="khám răng"` được accept như địa chỉ đầy đủ | Booked nhưng sai đích |
| **False MISSING** | `phone.call` cho phép `phone_number` nhưng N4 bắt `contact_id` | Thêm lookup thừa |
| Sai context grounding | “công ty” không lấy `work_address` | Truy vấn thiếu/sai địa chỉ |
| Sai temporal precision | “chiều nay” được nâng thành 14:00 | Hành động sai thời gian |
| Sai local date/timezone | Dùng audit time/system clock thay sample time | “ngày mai” lệch ngày |
| Sai entity selection | Hai liên hệ tên Lan → lấy `[0]` | Gọi nhầm người |
| Lỗi provenance | Qwen sinh `ewallet`, N4 coi là mặc định | Thanh toán bằng phương thức không được user chọn |
| InformationNeed mơ hồ | “need more info” không có field/constraints | N2 không biết retrieve gì |
| Repeated unresolved need | Không ghi nguồn đã thử | Recovery lặp |

## 5.4. Hướng phát triển/cải thiện

| Hướng | Ý tưởng | Tác dụng cần kiểm chứng |
|---|---|---|
| **R1 — Provenance-aware resolution** | Bắt buộc mỗi critical arg có evidence/source | Giảm unsafe READY |
| **R2 — Temporal DSL/parser** | Relative date vs duration, calendar shifts, timezone-aware arithmetic | Giảm lỗi ngày giờ |
| **R3 — Spatial/context grounding** | Alias `here/home/work`, georeference, profile/time constraints | Đúng địa điểm và không phát minh tọa độ |
| **R4 — Entity matching** | Filter theo role/date/number, confidence, ambiguity threshold | Không auto-pick sai ID |
| **R5 — Semantic readiness** | Kiểm tra precision/consistency theo từng field/action | Bắt dữ liệu có string nhưng không đủ ý nghĩa |
| **R6 — Structured InformationNeed** | Field/kind/question/constraints/attempt history | N2 tìm nguồn tốt hơn |
| **R7 — Schema completeness** | Support nested schema, alternatives, documented defaults | Giảm false blockers và invalid tool calls |

**Thước đo chính:** argument binding accuracy, false READY rate, false MISSING rate, time/location exact-match, ambiguity detection, InformationNeed quality. Có thể đánh giá N4 độc lập bằng TaskPlan/context/tool-result fixtures, không cần chạy Qwen hay ASR.

---

# 6. N5 — Execution Runtime: Điều phối, bảo vệ side effects, kiểm chứng goal

## 6.1. Nhiệm vụ và trách nhiệm

**Câu hỏi N5 chịu trách nhiệm:** *Task nào có thể chạy, khi nào phải recover, và hệ thống đã thực sự đạt goal chưa?*

- Quản lý single source of truth cho task/goal states, dependency graph, guards, observations và audit.
- Scheduler chọn task hợp lệ; evaluate `when` theo **TRUE / FALSE / UNKNOWN**.
- Gọi N4 trước khi execute; với `READY`, validate allowed tool và gọi environment thật.
- Với issue chưa thể giải bằng code, điều phối **N2 retrieve_for_need → N3 repair_plan**; validate/apply PlanPatch.
- Giới hạn số repair/tool calls, ngăn repeated no-progress và duplicate side effects.
- Kiểm tra postconditions/goal evidence, không coi `tool.ok=true` là auto `SATISFIED`.
- Lưu structured audit để truy nguyên quyết định; submit đúng trace/hash official.

N5 **không** tự quyết định rằng “missing dental appointment location ⇒ nên call calendar”; đó là quyết định semantic của N3, dựa trên candidates N2.

## 6.2. Cách baseline hoạt động

```text
TaskPlan -> validate graph / init ExecutionState
         -> pick task (deps satisfied, guard TRUE)
         -> N4.resolve
              READY     -> safe tool call -> observation -> verification
              BLOCKED   -> deterministic fix? -> yes: resolve again
                         -> no: N2 recovery retrieval -> N3 repair
                                 -> validate PlanPatch / ASK / STOP
                                 -> apply patch or block
         -> continue until goals resolved or no progress/budget exhausted
```

Các trạng thái quan trọng: `PENDING`, `READY`, `RUNNING`, `DONE`, `SKIPPED`, `BLOCKED`, `FAILED`, `UNCERTAIN`. Chỉ N5 cập nhật chúng.

- Guard **FALSE** → skip side effect. Guard **UNKNOWN** → không được hiểu là FALSE hoặc cho action chạy.
- Không sửa task đã `DONE`, `RUNNING` hoặc `UNCERTAIN` thông qua PlanPatch.
- Với timeout của action tạo side effect (đặt xe, chuyển tiền, gửi tin), trạng thái có thể là **UNCERTAIN**; phải đối soát bằng công cụ read-only được phép nếu có, không retry mù.
- Nếu một goal fail nhưng goal độc lập khác thành công, cần bảo toàn partial success và trace.

## 6.3. Failure modes N5 cần chịu trách nhiệm

| Failure | Ví dụ | Hậu quả |
|---|---|---|
| **Premature SATISFIED** | Tool book trả `ok=true`, nhưng dropoff không đúng | Báo hoàn thành giả |
| Wrong guard | `UNKNOWN` được xem là TRUE | Thực hiện action khi chưa có evidence |
| Wrong dependency | Task notification chạy trước cập nhật lịch | Tin nhắn sai giờ |
| Recovery không kích hoạt | N4 đã emit need nhưng N5 chỉ block | Không có cơ hội explore |
| Recovery loop | Lặp `calendar.list_events` cùng query không có dữ liệu mới | Tốn tool calls/latency |
| Unsafe PlanPatch | Sửa task DONE/cho tool ngoài allowlist | Sai trạng thái/hành động |
| Duplicate side effect | Retry `ride_hailing.book` sau timeout | Đặt trùng xe |
| Lost tool observation | Không lưu ID/status/evidence | N4 không bind được, goal verdict không có căn cứ |
| Audit sai thứ tự | `tool_result_detail` ghi trước `tool_started` | Khó debug nguyên nhân |
| Global failure sai | Một nhánh blocked làm bỏ những goal độc lập có thể làm | Kém completion |

## 6.4. Hướng phát triển/cải thiện

| Hướng | Ý tưởng | Tác dụng cần kiểm chứng |
|---|---|---|
| **E1 — Robust DAG scheduler** | Dependencies, tri-state guards, valid task transitions | Tránh chạy task sai thứ tự |
| **E2 — Issue-triggered orchestration** | Chỉ gọi N2/N3 khi code không thể resolve; giới hạn budget | Tăng recovery mà giữ cost ổn |
| **E3 — Safe patch validation** | Versioning, atomic application, immutability DONE/UNCERTAIN | Không phá plan/state |
| **E4 — Postcondition verification** | Effect evidence, constraints, status distinction | Giảm false `SATISFIED` |
| **E5 — Idempotence/reconciliation** | Detect uncertain state, read-only verify before retry | Tránh duplicate booking/transfer/send |
| **E6 — Recovery stop policy** | Attempt history, no-progress detection, budget | Không lặp vô hạn |
| **E7 — Flow audit** | Event timeline chuẩn `PLAN→BIND→TOOL→OBSERVE→REPAIR` | Định vị lỗi giữa N2/N3/N4/N5 |

**Thước đo chính:** correct execution, recovery success, false-success rate, duplicate side-effect rate, tool/LLM calls, P50/P95 latency, correct stop/block/ask decisions. Có thể kiểm N5 bằng plan cố định và fake environment để tách lỗi Runtime khỏi lỗi N3.

---

# 7. Ví dụ end-to-end: tại sao cần cả N2, N3, N4, N5?

## 7.1. `public_0002` — Đặt xe đi khám răng

**Transcript gần đúng:** “Đặt xe 4 chỗ từ công ty đi khám răng chiều nay, đặt ngay bây giờ nhé.”

**Context của sample:** `current_time=2026-11-16T11:30:00+07:00`, `timezone=Asia/Ho_Chi_Minh`, `work_address=Tòa nhà Blue Pearl, Quận 7, TP.HCM`, `history=[]`. Audit cũ đã cho thấy model sinh booking lúc `2026-11-16T14:00+07:00` và `payment=ewallet` mà chưa có evidence rõ; Resolver trả `READY` và tool accepted. Đó là *technical success*, không chứng minh *goal correctness*.

| Bước | Module | Kết quả đúng về mặt trách nhiệm |
|---|---|---|
| 1 | N1 | Nhận transcript, giữ “từ công ty”, “chiều nay”, “đặt ngay” |
| 2 | N2 initial | Retrieve `ride_hailing.book` và các tool prerequisite thực sự liên quan |
| 3 | N3 initial | Goal đặt xe; `pickup=work_ref`, `dropoff=unknown clinic`, `time=today afternoon`, `vehicle=car4`; không tự đặt 14:00 hoặc ewallet |
| 4 | N4 | `pickup` từ `work_address`; `dropoff` chưa có địa chỉ; giờ đón chưa xác định nếu required; tạo `InformationNeed` |
| 5 | N2 recovery | Có thể đề xuất `calendar.list_events`/`reminders.list` **nếu có trong allowed ToolSpecs** và có khả năng cung cấp lịch khám |
| 6 | N3 repair | Chọn thử calendar, hoặc hỏi user nếu không có nguồn hợp lý; sinh minimal PlanPatch |
| 7 | N5 | Validate patch, execute read-only lookup, record result; N4 resolve lại; chỉ book khi đủ thông tin |

**Ranh giới ngữ nghĩa:** lịch khám lúc 15:00, nếu tìm được, **không tự chứng minh** giờ đón xe là 14:00. “Đặt ngay bây giờ” cũng không tự chứng minh “xe đón ngay”. Phương thức thanh toán chỉ được điền nếu user/context/tool schema thực sự cho phép. Nếu API cho phép omission/default thì không cần hỏi vô ích.

## 7.2. `train_0001` — Conditional workflow và time grounding

**Yêu cầu:** “Nếu mai mưa thì dời chạy bộ muộn 1 tiếng, nhắn Sếp Dũng giờ mới; không mưa thì thôi.”

| Thành viên | Điều cần xử lý |
|---|---|
| N1 | Giữ “nếu”, “không mưa thì thôi”, “muộn 1 tiếng” |
| N2 | Có tool thời tiết, đọc/update lịch, tìm contact, gửi thông báo nếu được cài/cho phép |
| N3 | Biểu diễn guard `rain_tomorrow`, branch no-op, dependency: event lookup → update → notify |
| N4 | “Mai” dựa theo `context.current_time`; bind event ID/contact ID từ tool; cộng đúng +60 phút cho start/end |
| N5 | Chỉ update khi forecast đủ bằng chứng rain=true; nếu false thì skip; notify chỉ khi update đúng |

Ca này minh họa rằng **one initial planning call có thể mô tả một chuỗi có điều kiện**, nhưng giá trị kết quả dự báo và ID phải chờ execution. Nếu plan bỏ mất việc “nhắn Sếp Dũng”, N3 phải cải thiện semantic coverage; N4 không thể tự suy ra task hoàn toàn bị bỏ sót từ một graph thiếu goal.

---

# 8. Tóm tắt định hướng cải tiến của 5 thành viên

| Người | Ưu tiên đầu tiên | Nghiên cứu sâu tiếp theo | Lỗi muốn giảm |
|---|---|---|---|
| **N1 ASR** | Critical words/entities + WER/CER | Decoding, context hints, model comparison | Sai transcription dẫn tới sai action |
| **N2 Discovery** | InformationNeed retrieval + provider recall | Provider graph, BM25/dense/hybrid | Thiếu source hoặc quá nhiều tool nhiễu |
| **N3 Planner** | Schema-guided plans + goal coverage + issue→patch | Task patterns, LoRA SFT, semantic verifier | Plan thiếu task, sai guard, repair kém |
| **N4 Resolver** | Strict readiness/provenance, time/location | Entity matching, information-gap precision | False READY và tự lấp arguments |
| **N5 Runtime** | Recovery orchestration + goal verification | Safe patch, idempotency, adaptive budget | Premature SATISFIED, loops, duplicate effects |

**Nguyên tắc chung:** Không cố giải một lỗi bằng cách đẩy toàn bộ trí thông minh vào Qwen hay bằng cách hardcode quá nhiều heuristic trong Runtime. N3 chịu trách nhiệm semantic decisions, N2 cung cấp tool capabilities, N4 xác minh tính đầy đủ/đúng của dữ liệu, N5 giữ tính an toàn và tiến độ thực thi. Ranh giới rõ thì mới biết thí nghiệm của từng người cải thiện phần nào.

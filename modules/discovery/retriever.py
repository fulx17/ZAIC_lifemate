"""Hybrid lexical, schema-graph, and capability-based tool retrieval for N2 Discovery."""

from __future__ import annotations

import math
import re
from typing import Any

from core.contracts import AgentRequest, InformationNeed, ToolCandidate, ToolSpec
from modules.discovery.capabilities import (
    ACTION_VERB_TRIGGERS,
    ANAPHORA_MARKERS,
    APP_KEYWORDS,
    NEED_CAPABILITIES,
    STATIC_CLOSURE,
    TOOL_CAPABILITY_TERMS,
    build_schema_closure,
    extract_tool_schema_terms,
    has_any_phrase,
    has_phrase,
    infer_tool_app,
    infer_tool_kind,
    normalize_text,
    pad_tokens,
    split_self_correction,
    tokenize,
)

# Vietnamese & English function/stop words that should not trigger false-positive tool matches on their own.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "cho", "tôi", "mình", "em", "anh", "chị", "nhé", "nha", "với", "giúp", "hộ",
        "của", "trong", "ngoài", "trên", "dưới", "theo", "vào", "ra", "lên", "xuống",
        "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười",
        "các", "những", "mọi", "tất", "cả", "này", "đó", "kia", "ấy", "nào", "đâu",
        "khi", "nếu", "thì", "mà", "và", "hoặc", "hay", "nhưng", "rồi", "xong",
        "được", "không", "chưa", "đang", "sẽ", "đã", "vừa", "mới", "cần", "muốn",
        "lúc", "giờ", "ngày", "tháng", "năm", "hôm", "nay", "mai", "qua", "sáng",
        "trưa", "chiều", "tối", "đêm", "phút", "giây", "từ", "đến", "tới", "ở", "tại",
        "là", "có", "bị", "bằng", "về", "đi", "làm", "xem", "tra", "kiểm", "thử",
        "the", "a", "an", "to", "for", "of", "in", "on", "at", "by", "with", "from", "or", "and",
    }
)

# Only strip English stop-words and ultra-generic system boilerplate words from schema tokens.
# Keep Vietnamese domain/action nouns & verbs intact so natural descriptions and parameter schemas match unseen apps!
_GENERIC_SCHEMA_WORDS: frozenset[str] = frozenset(
    {
        "thông", "tin", "chi", "tiết", "người", "dùng", "hệ", "thống",
        "dịch", "vụ", "kết", "quả", "dữ", "liệu", "theo", "mã", "tên",
    }
)

_HONORIFIC_RECIPIENT_HINTS: tuple[str, ...] = (
    "sếp", "bố", "mẹ", "ba", "má", "vợ", "chồng", "con", "cô giáo", "thầy",
    "bác", "chú", "cô", "dì", "cậu", "mợ", "ông", "bà", "bạn", "đồng nghiệp", "khách hàng",
)

_EVENT_SCHEDULE_HINTS: tuple[str, ...] = (
    "lịch", "họp", "khám", "hẹn", "sự kiện", "buổi", "ca", "chạy bộ", "đá bóng", "sinh nhật",
)


class ToolRetriever:
    def __init__(self, top_k: int = 8, recovery_top_k: int | None = None):
        if top_k < 1 or (recovery_top_k is not None and recovery_top_k < 1):
            raise ValueError("retrieval limits must be positive")
        self.top_k = top_k
        self.recovery_top_k = recovery_top_k or top_k

    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]:
        """Rank and select candidate tools from the sample's allowed catalog, expanding required lookup closures."""
        allowed_tools = [tool for tool in catalog if tool.name != "sys.ask_missing_info"]
        if not allowed_tools:
            return []

        by_name = {tool.name: tool for tool in allowed_tools}
        closure = build_schema_closure(allowed_tools)

        full_query, post_corr_query = split_self_correction(request.transcript)

        # Extract history context: if the last assistant turn was a clarification question (no real tools executed),
        # merge the pending user turn + clarification question directly into the active query!
        pending_query, history_text, history_apps, history_tools = self._extract_history_signals(request.history)
        if pending_query:
            full_query = f"{pending_query} {full_query}".strip()

        raw_tokens = tokenize(full_query)
        content_tokens = {t for t in raw_tokens if t not in _STOP_WORDS and len(t) > 1}
        post_corr_tokens = {t for t in tokenize(post_corr_query) if t not in _STOP_WORDS and len(t) > 1}

        padded_query = pad_tokens(full_query)
        padded_post_corr = pad_tokens(post_corr_query) if post_corr_query else ""
        padded_history = pad_tokens(history_text) if history_text else ""

        is_followup = (
            bool(pending_query)
            or len(content_tokens) <= 6
            or has_any_phrase(padded_query, ANAPHORA_MARKERS)
        )
        history_tokens = {t for t in tokenize(history_text) if t not in _STOP_WORDS and len(t) > 1}

        # Compute inverse document frequency (IDF) across current sample catalog
        doc_tokens_map: dict[str, set[str]] = {}
        enum_terms_map: dict[str, list[str]] = {}
        df_counts: dict[str, int] = {}
        for tool in allowed_tools:
            searchable, enum_terms = extract_tool_schema_terms(tool)
            tokens = {
                t
                for t in tokenize(searchable)
                if t not in _STOP_WORDS and t not in _GENERIC_SCHEMA_WORDS and len(t) > 1
            }
            doc_tokens_map[tool.name] = tokens
            enum_terms_map[tool.name] = enum_terms
            for tok in tokens:
                df_counts[tok] = df_counts.get(tok, 0) + 1

        n_docs = max(len(allowed_tools), 1)

        scored: list[tuple[float, str, ToolSpec]] = []
        app_best_score: dict[str, float] = {}

        for tool in allowed_tools:
            app = infer_tool_app(tool)
            tool_tokens = doc_tokens_map[tool.name]
            score = 0.0

            # 1. IDF-weighted lexical overlap on content words
            for tok in content_tokens & tool_tokens:
                idf = 1.0 + math.log((n_docs + 1.0) / (df_counts.get(tok, 1) + 0.5))
                score += idf
                if tok in post_corr_tokens:
                    score += 0.75 * idf

            # 2. Tool-specific capability phrase matching (token-boundary aware)
            tool_terms = TOOL_CAPABILITY_TERMS.get(tool.name, set())
            for term in tool_terms:
                if has_phrase(padded_query, term):
                    weight = 3.5 if " " in term else 2.2
                    if padded_post_corr and has_phrase(padded_post_corr, term):
                        weight *= 1.35
                    score += weight

            # 3. App-level semantic phrase & keyword matching (token-boundary aware)
            app_terms = APP_KEYWORDS.get(app, set())
            app_matched = 0.0
            for term in app_terms:
                if has_phrase(padded_query, term):
                    w = 2.8 if " " in term else 1.8
                    if padded_post_corr and has_phrase(padded_post_corr, term):
                        w *= 1.25
                    app_matched = max(app_matched, w) + 0.35
            score += min(app_matched, 6.0)

            # 3b. Action-suffix alignment (distinguishes create/update/cancel/pay/send within an app)
            action_suffix = tool.name.split(".", 1)[-1].casefold()
            action_triggers = ACTION_VERB_TRIGGERS.get(action_suffix, ())
            if not action_triggers and "_" in action_suffix:
                action_triggers = ACTION_VERB_TRIGGERS.get(action_suffix.split("_", 1)[0], ())
            if action_triggers and (score > 0 or app in history_apps):
                for trig in action_triggers:
                    if has_phrase(padded_query, trig):
                        score += 2.4 if " " in trig else 1.6
                        break

            # 4. Schema enum value matching (e.g., ron95, sjc, car4)
            for enum_val in enum_terms_map[tool.name]:
                if len(enum_val) >= 2 and re.search(rf"\b{re.escape(enum_val)}\b", full_query):
                    score += 2.5

            # 5. History continuity signal (stronger when turn is short/anaphoric)
            if padded_history:
                hist_factor = 0.55 if is_followup else 0.22
                for term in tool_terms:
                    if has_phrase(padded_history, term):
                        score += hist_factor * 1.8
                for term in app_terms:
                    if has_phrase(padded_history, term):
                        score += hist_factor * 1.2
                        break
                for tok in history_tokens & tool_tokens:
                    score += hist_factor * 0.6
            if app in history_apps:
                score += 1.8 if is_followup else 0.5
            if tool.name in history_tools and is_followup:
                score += 1.0

            if score > 0:
                scored.append((score, tool.name, tool))
                if score > app_best_score.get(app, 0.0):
                    app_best_score[app] = score

        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored:
            return []

        # Small top_k mode (e.g., unit tests with top_k=1..3): strict top_k anchors + direct closure
        if self.top_k < 4:
            selected = {tool.name: tool for _, _, tool in scored[: self.top_k]}
            for name in tuple(selected):
                for related in STATIC_CLOSURE.get(name, closure.get(name, ())):
                    if related in by_name:
                        selected.setdefault(related, by_name[related])
            return list(selected.values())

        # Standard runtime mode (top_k >= 4):
        # Step A: App-diverse anchor selection so multi-app queries don't get crowded out by a single app's tools
        selected: dict[str, ToolSpec] = {}
        seen_apps: set[str] = set()
        for score, name, tool in scored:
            if len(selected) >= self.top_k:
                break
            app = infer_tool_app(tool)
            if app not in seen_apps and score >= 1.5:
                selected[name] = tool
                seen_apps.add(app)

        # Fill remaining anchor slots up to top_k by raw score
        for score, name, tool in scored:
            if len(selected) >= self.top_k:
                break
            if name not in selected and score >= 1.8:
                selected[name] = tool

        # Step B: For strongly matched apps, include closely scored sibling tools in the same app
        max_overall = scored[0][0]
        strong_app_threshold = max(2.8, max_overall * 0.28)
        for score, name, tool in scored:
            app = infer_tool_app(tool)
            if app_best_score.get(app, 0.0) >= strong_app_threshold and score >= max(2.2, app_best_score[app] * 0.45):
                selected.setdefault(name, tool)

        # Step C: Expand schema-driven & static prerequisite read closures (2-hop safe)
        for name in tuple(selected):
            for related in closure.get(name, ()):
                if related in by_name:
                    selected.setdefault(related, by_name[related])
                    for transitive in closure.get(related, ()):
                        if transitive in by_name:
                            selected.setdefault(transitive, by_name[transitive])

        # Step D: Contextual cross-app implicit providers (only when installed in catalog)
        self._add_contextual_implicit_providers(selected, by_name, full_query, history_text)

        return list(selected.values())

    def retrieve_for_need(
        self,
        need: InformationNeed,
        catalog: list[ToolSpec],
        history: list[str] | None = None,
    ) -> list[ToolCandidate]:
        """Find allowed read-only providers for an information gap without executing them."""
        tried = set(history or ()) | set(need.attempt_history or ())
        constraints_text = " ".join(f"{k} {v}" for k, v in (need.constraints or {}).items())
        evidence_text = " ".join(
            str(item.get("value", "")) for item in (need.known_evidence or []) if isinstance(item, dict)
        )
        raw_query = " ".join(
            [
                need.field or "",
                need.kind or "",
                need.question or "",
                need.why_not_ready or "",
                need.required_precision or "",
                constraints_text,
                evidence_text,
                *(need.capability_hints or ()),
            ]
        )
        query = normalize_text(raw_query)
        padded_query = pad_tokens(query)
        query_tokens = {t for t in tokenize(query) if t not in _STOP_WORDS and len(t) > 1}

        kind_map = NEED_CAPABILITIES.get(need.kind, {})
        preferred: dict[str, list[str]] = {}
        for capability, names in kind_map.items():
            if has_phrase(padded_query, capability) or capability in query:
                for name in names:
                    preferred.setdefault(name, []).append(f"need:{need.kind}:{capability}")

        # Fallback default providers by kind when query has generic wording
        default_by_kind: dict[str, tuple[str, ...]] = {
            "LOCATION": ("calendar.list_events", "reminders.list", "maps.search_place", "contacts.search"),
            "TIME": ("calendar.list_events", "reminders.list", "weather.get_forecast"),
            "ENTITY": ("contacts.search", "banking.list_beneficiaries", "chat_ott.list_chats"),
            "VALUE": ("bill_payment.list_bills", "ewallet.get_balance", "banking.get_balance"),
            "FACT": ("calendar.list_events", "weather.get_forecast", "reminders.list"),
            "ARGUMENT": ("contacts.search", "calendar.list_events", "reminders.list"),
        }

        ranked: list[tuple[int, str, ToolSpec, list[str]]] = []
        for tool in catalog:
            if infer_tool_kind(tool) != "read" or tool.name in tried or tool.name == "sys.ask_missing_info":
                continue

            app = infer_tool_app(tool)
            searchable, enum_terms = extract_tool_schema_terms(tool)
            tool_tokens = {
                t
                for t in tokenize(searchable)
                if t not in _STOP_WORDS and t not in _GENERIC_SCHEMA_WORDS and len(t) > 1
            }

            terms = TOOL_CAPABILITY_TERMS.get(tool.name, set()) | APP_KEYWORDS.get(app, set())
            matched_terms = sorted(term for term in terms if has_phrase(padded_query, term))
            overlap_tokens = sorted(query_tokens & tool_tokens)
            pref_reasons = preferred.get(tool.name, [])

            score = (
                len(overlap_tokens)
                + 3 * len(matched_terms)
                + (6 if pref_reasons else 0)
                + (2 if not preferred and tool.name in default_by_kind.get(need.kind, ()) and query_tokens else 0)
            )
            if score > 0:
                evidence = pref_reasons + matched_terms + overlap_tokens
                # Deduplicate evidence while preserving order
                dedup_evidence = list(dict.fromkeys(evidence))[:8]
                ranked.append((score, tool.name, tool, dedup_evidence))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [
            ToolCandidate(
                tool=tool,
                score=int(score),
                rank=rank,
                rationale=f"read-only provider for {need.kind} ({need.field})",
                provider_evidence=evidence,
            )
            for rank, (score, _, tool, evidence) in enumerate(ranked[: self.recovery_top_k], start=1)
        ]

    @staticmethod
    def _extract_history_signals(history: list[dict[str, Any]] | None) -> tuple[str, str, set[str], set[str]]:
        if not history:
            return "", "", set(), set()

        # Check if the last assistant turn was a clarification question (no action tools executed)
        pending_parts: list[str] = []
        if len(history) >= 2 and isinstance(history[-1], dict) and history[-1].get("role") == "assistant":
            last_calls = history[-1].get("tool_calls") or []
            real_calls = [
                c.get("name")
                for c in last_calls
                if isinstance(c, dict) and c.get("name") and c.get("name") != "sys.ask_missing_info"
            ]
            if not real_calls:
                for turn in history[-2:]:
                    if isinstance(turn, dict):
                        for key in ("audio_text", "text"):
                            val = turn.get(key)
                            if isinstance(val, str) and val.strip():
                                pending_parts.append(val)
                        for call in turn.get("tool_calls") or ():
                            if isinstance(call, dict) and call.get("name") == "sys.ask_missing_info":
                                tname = call.get("arguments", {}).get("tool_name")
                                if isinstance(tname, str) and tname:
                                    pending_parts.append(tname.replace(".", " ").replace("_", " "))

        recent = history[-6:]
        texts: list[str] = []
        apps: set[str] = set()
        tools: set[str] = set()
        for turn in recent:
            if not isinstance(turn, dict):
                continue
            for key in ("audio_text", "text"):
                val = turn.get(key)
                if isinstance(val, str) and val.strip():
                    texts.append(val)
            for call in turn.get("tool_calls") or ():
                if isinstance(call, dict) and isinstance(call.get("name"), str):
                    tname = call["name"]
                    if tname == "sys.ask_missing_info":
                        asked_tool = call.get("arguments", {}).get("tool_name")
                        if isinstance(asked_tool, str) and asked_tool:
                            tools.add(asked_tool)
                            if "." in asked_tool:
                                apps.add(asked_tool.split(".", 1)[0])
                    else:
                        tools.add(tname)
                        if "." in tname:
                            apps.add(tname.split(".", 1)[0])
        return normalize_text(" ".join(pending_parts)), normalize_text(" ".join(texts)), apps, tools

    @staticmethod
    def _add_contextual_implicit_providers(
        selected: dict[str, ToolSpec],
        by_name: dict[str, ToolSpec],
        full_query: str,
        history_text: str,
    ) -> None:
        combined = f"{full_query} {history_text}"
        padded_combined = pad_tokens(combined)
        selected_apps = {infer_tool_app(t) for t in selected.values()}

        # 1. Communication/transfer/calendar tools or recipient honorific -> contacts.search
        if "contacts.search" in by_name:
            needs_contact = bool(
                selected_apps & {"sms", "phone", "ewallet", "email", "chat_ott"}
                or has_any_phrase(padded_combined, _HONORIFIC_RECIPIENT_HINTS)
            )
            if needs_contact:
                selected.setdefault("contacts.search", by_name["contacts.search"])

        # 2. Ride/alarm/reminders/flights + event/appointment cues -> calendar.list_events
        if "calendar.list_events" in by_name:
            if selected_apps & {"ride_hailing", "alarm", "reminders", "sms", "chat_ott", "flights"} and has_any_phrase(
                padded_combined, (*_EVENT_SCHEDULE_HINTS, "workshop", "hội thảo")
            ):
                selected.setdefault("calendar.list_events", by_name["calendar.list_events"])
        if "video_meeting.list_meetings" in by_name and has_any_phrase(
            padded_combined, ("họp", "meeting", "online", "trực tuyến")
        ):
            selected.setdefault("video_meeting.list_meetings", by_name["video_meeting.list_meetings"])

        # 2b. Weather selected or weather/rain cues mentioned -> ensure weather.get_forecast
        if "weather.get_forecast" in by_name and (
            "weather" in selected_apps
            or has_any_phrase(padded_combined, ("mưa", "nắng", "thời tiết", "dự báo", "trời ráo"))
        ):
            selected.setdefault("weather.get_forecast", by_name["weather.get_forecast"])

        # 2c. Calendar adding/recording cues mentioned -> ensure calendar.create_event
        if "calendar.create_event" in by_name and has_any_phrase(
            padded_combined, ("vào lịch", "thêm lịch", "tạo lịch", "một lịch", "lên lịch", "ghi lịch", "chặn lịch")
        ):
            selected.setdefault("calendar.create_event", by_name["calendar.create_event"])

        # 3. Food delivery + group/chat cues -> chat_ott.list_chats & read_chat
        if "food_delivery" in selected_apps and has_any_phrase(
            padded_combined, ("nhóm", "mọi người", "chat", "tin nhắn")
        ):
            for cname in ("chat_ott.list_chats", "chat_ott.read_chat"):
                if cname in by_name:
                    selected.setdefault(cname, by_name[cname])

        # 4. Bill payment selected or bill terms mentioned -> list_bills & pay + ewallet/banking
        if "bill_payment" in selected_apps or has_any_phrase(
            padded_combined,
            ("hoá đơn", "hóa đơn", "tiền điện", "tiền nước", "tiền mạng", "tiền truyền hình", "học phí"),
        ):
            if "bill_payment.list_bills" in by_name:
                selected.setdefault("bill_payment.list_bills", by_name["bill_payment.list_bills"])
            if "bill_payment.pay" in by_name and has_any_phrase(
                padded_combined, ("trả", "đóng", "thanh toán", "nộp", "pay")
            ):
                selected.setdefault("bill_payment.pay", by_name["bill_payment.pay"])
            for bname in ("ewallet.get_balance", "banking.get_balance", "banking.list_beneficiaries"):
                if bname in by_name and has_any_phrase(
                    padded_combined, ("ví", "ngân hàng", "số dư", "đủ", "chuyển", "thanh toán", "trả")
                ):
                    selected.setdefault(bname, by_name[bname])

        # 5. Chat OTT selected or message verbs with chat_ott installed -> list_chats & send_message
        if ("chat_ott" in selected_apps or "chat_ott.send_message" in by_name) and has_any_phrase(
            padded_combined, ("nhắn", "gửi tin", "báo", "nhóm", "zalo", "ott")
        ):
            for cname in ("chat_ott.list_chats", "chat_ott.send_message"):
                if cname in by_name:
                    selected.setdefault(cname, by_name[cname])

        # 6. Food delivery + order/food cues -> list_restaurants, get_menu, place_order
        if "food_delivery" in selected_apps and has_any_phrase(
            padded_combined,
            ("đặt", "gọi", "mua", "giao", "suất", "phần", "tô", "bún", "phở", "cơm", "cháo", "trà sữa"),
        ):
            for fname in ("food_delivery.list_restaurants", "food_delivery.get_menu", "food_delivery.place_order"):
                if fname in by_name:
                    selected.setdefault(fname, by_name[fname])

        # 7. Door lock or home security + lock/door cues -> door_lock.list_locks & set_lock
        if selected_apps & {"door_lock", "home_security"} and has_any_phrase(
            padded_combined, ("khóa", "khoá", "cửa", "cổng")
        ):
            for dname in ("door_lock.list_locks", "door_lock.set_lock"):
                if dname in by_name:
                    selected.setdefault(dname, by_name[dname])

        # 8. Banking + transfer/payment cues -> get_balance, list_beneficiaries, transfer
        if "banking" in selected_apps and has_any_phrase(
            padded_combined, ("chuyển", "trích", "trả", "thanh toán", "đóng", "góp")
        ):
            for bname in ("banking.get_balance", "banking.list_beneficiaries", "banking.transfer"):
                if bname in by_name:
                    selected.setdefault(bname, by_name[bname])

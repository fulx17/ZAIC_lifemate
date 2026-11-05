"""Keyword retrieval with a small deterministic resolver-tool closure."""

from __future__ import annotations

import re

from core.contracts import AgentRequest, ToolSpec

_CAPABILITY_TERMS = {
    "weather.get_forecast": {"weather", "forecast", "rain", "mưa", "thời tiết", "dự báo"},
    "weather.get_current": {"weather", "current", "thời tiết", "hiện tại"},
    "calendar.list_events": {"calendar", "event", "schedule", "lịch", "sự kiện"},
    "calendar.update_event": {"calendar", "reschedule", "update", "dời", "đổi lịch", "sửa lịch"},
    "calendar.cancel_event": {"calendar", "cancel", "hủy", "xóa lịch"},
    "contacts.search": {"contact", "contacts", "recipient", "liên hệ", "người"},
    "sms.send": {"sms", "text", "message", "nhắn", "tin nhắn"},
    "chat_ott.send_message": {"chat", "message", "nhắn tin"},
    "phone.call": {"call", "phone", "gọi", "cuộc gọi"},
}
_CLOSURE = {
    "phone.call": ("contacts.search",),
    "sms.send": ("contacts.search",),
    "chat_ott.send_message": ("contacts.search",),
    "calendar.update_event": ("calendar.list_events",),
    "calendar.cancel_event": ("calendar.list_events",),
}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class ToolRetriever:
    def __init__(self, top_k: int = 8):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.top_k = top_k

    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]:
        by_name = {tool.name: tool for tool in catalog}
        query = request.transcript.casefold()
        context = " ".join(
            str(request.context.get(key, ""))
            for key in ("current_time", "timezone", "user_profile")
        ).casefold()
        query_tokens = set(_TOKEN.findall(f"{query} {context}"))
        scored: list[tuple[int, str, ToolSpec]] = []
        for tool in catalog:
            if tool.name == "sys.ask_missing_info":
                continue
            searchable = f"{tool.name} {tool.description}".casefold().replace(".", " ").replace("_", " ")
            tool_tokens = set(_TOKEN.findall(searchable))
            terms = _CAPABILITY_TERMS.get(tool.name, set())
            score = len(query_tokens & tool_tokens) + sum(2 for term in terms if term in query)
            if score:
                scored.append((score, tool.name, tool))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = {tool.name: tool for _, _, tool in scored[: self.top_k]}
        for name in tuple(selected):
            for related in _CLOSURE.get(name, ()):
                if related in by_name:
                    selected.setdefault(related, by_name[related])
        return list(selected.values())

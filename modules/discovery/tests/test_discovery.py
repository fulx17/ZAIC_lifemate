"""Comprehensive unit tests for N2 Tool Discovery & Capability-Based Recovery Retrieval."""

from __future__ import annotations

import pytest

from core.contracts import AgentRequest, InformationNeed, ToolSpec
from modules.discovery.registry import ToolRegistry
from modules.discovery.service import DiscoveryService


def test_retrieval_returns_only_allowlisted_tools_and_adds_safe_lookup_closure() -> None:
    catalog = [
        ToolSpec(name="sms.send", description="send message"),
        ToolSpec(name="contacts.search", description="search contacts"),
        ToolSpec(name="phone.call", description="call a contact"),
        ToolSpec(name="sys.ask_missing_info", description="report missing inputs", kind="meta"),
        ToolSpec(name="bank.transfer", description="transfer money"),
    ]
    request = AgentRequest(sample_id="s1", transcript="Nhắn cho Lan", context={})

    candidates = DiscoveryService(top_k=1).retrieve(request, catalog)

    names = {tool.name for tool in candidates}
    assert names == {"sms.send", "contacts.search"}
    assert "sys.ask_missing_info" not in names
    assert "bank.transfer" not in names


def test_retrieve_returns_empty_when_no_relevance_or_only_meta_tool() -> None:
    catalog = [
        ToolSpec(name="weather.get_forecast", description="Xem dự báo thời tiết", kind="read"),
        ToolSpec(name="sys.ask_missing_info", description="Hỏi thêm thông tin", kind="meta"),
    ]
    request = AgentRequest(sample_id="s_empty", transcript="xyz123 qwerty", context={})

    candidates = DiscoveryService(top_k=8).retrieve(request, catalog)
    assert candidates == []


def test_retrieve_ignores_user_profile_address_noise() -> None:
    """User profile addresses ('Số 12 Nhà Chung, Phòng 302') must not trigger smart_home tools."""
    catalog = [
        ToolSpec(name="weather.get_forecast", description="Dự báo thời tiết theo ngày", kind="read"),
        ToolSpec(name="smart_home.light_set", description="Bật tắt đèn trong nhà, phòng khách", kind="write"),
        ToolSpec(name="smart_home.get_status", description="Kiểm tra trạng thái thiết bị nhà", kind="read"),
    ]
    request = AgentRequest(
        sample_id="s_profile_noise",
        transcript="Mai trời có mưa không em?",
        context={
            "user_profile": {
                "home_address": "Số 15 phố Nhà Chung, Phòng 402, Quận Hoàn Kiếm",
                "work_address": "Tòa nhà Công nghệ, Thành phố Hà Nội",
            }
        },
    )

    candidates = DiscoveryService(top_k=4).retrieve(request, catalog)
    names = [t.name for t in candidates]
    assert "weather.get_forecast" in names
    assert "smart_home.light_set" not in names


def test_retrieve_multi_goal_cross_app_chain() -> None:
    """Multi-app conditional query (weather + calendar + ride_hailing + sms + contacts) retrieves full chain."""
    catalog = [
        ToolSpec(name="weather.get_forecast", description="Dự báo thời tiết", kind="read"),
        ToolSpec(name="calendar.list_events", description="Liệt kê sự kiện trong lịch", kind="read"),
        ToolSpec(name="calendar.cancel_event", description="Hủy sự kiện trong lịch", kind="write"),
        ToolSpec(name="contacts.search", description="Tìm người liên hệ trong danh bạ", kind="read"),
        ToolSpec(name="sms.send", description="Gửi tin nhắn SMS", kind="write"),
        ToolSpec(name="ride_hailing.book", description="Đặt chuyến xe", kind="write"),
        ToolSpec(name="music.play", description="Phát nhạc", kind="write"),
    ]
    request = AgentRequest(
        sample_id="train_0165_like",
        transcript=(
            "Mai nếu mưa thì huỷ cái lịch khám răng, nhắn SMS cho bố biết, "
            "không mưa thì gọi ô tô 4 chỗ từ nhà đến đó, đón trước giờ hẹn nửa tiếng."
        ),
        context={},
    )

    candidates = DiscoveryService(top_k=8).retrieve(request, catalog)
    names = {t.name for t in candidates}
    expected = {
        "weather.get_forecast",
        "calendar.list_events",
        "calendar.cancel_event",
        "contacts.search",
        "sms.send",
        "ride_hailing.book",
    }
    assert expected <= names
    assert "music.play" not in names


def test_retrieve_self_correction_boosts_post_correction_intent() -> None:
    """When user self-corrects ('à không...'), the revised target receives higher priority."""
    catalog = [
        ToolSpec(name="alarm.create", description="Tạo báo thức mới", kind="write"),
        ToolSpec(name="sms.send", description="Gửi tin nhắn SMS", kind="write"),
        ToolSpec(name="contacts.search", description="Tìm danh bạ", kind="read"),
    ]
    request = AgentRequest(
        sample_id="s_self_corr",
        transcript="Đặt báo thức 7 giờ... à không, nhắn tin SMS cho Lan nhé",
        context={},
    )

    candidates = DiscoveryService(top_k=1).retrieve(request, catalog)
    names = [t.name for t in candidates]
    assert names[0] == "sms.send"
    assert "contacts.search" in names


def test_retrieve_merges_pending_clarification_history_turn() -> None:
    """When the previous assistant turn asked a clarification question (tool_calls=[]), merge pending user intent."""
    catalog = [
        ToolSpec(name="bill_payment.list_bills", description="Danh sách hóa đơn", kind="read"),
        ToolSpec(name="bill_payment.pay", description="Thanh toán hóa đơn", kind="write"),
        ToolSpec(name="ewallet.get_balance", description="Số dư ví điện tử", kind="read"),
        ToolSpec(name="music.play", description="Phát nhạc", kind="write"),
    ]
    history = [
        {
            "role": "user",
            "audio_text": "Thanh toán hóa đơn tiền nước giúp chị nhé.",
        },
        {
            "role": "assistant",
            "text": "Chị muốn thanh toán bằng ví điện tử hay tài khoản ngân hàng ạ?",
            "tool_calls": [],
        },
    ]
    request = AgentRequest(
        sample_id="s_clarification_followup",
        transcript="Trả bằng ví điện tử đi em.",
        context={},
        history=history,
    )

    candidates = DiscoveryService(top_k=6).retrieve(request, catalog)
    names = {t.name for t in candidates}
    assert {"bill_payment.list_bills", "bill_payment.pay", "ewallet.get_balance"} <= names


def test_retrieve_dynamic_xref_schema_closure_on_unseen_app() -> None:
    """Unseen apps in public/private test must automatically pull prerequisite read tools via JSON Schema x-ref."""
    catalog = [
        ToolSpec(
            name="cinema_booking.search_shows",
            description="Tìm suất chiếu phim tại rạp",
            app="cinema_booking",
            kind="read",
            parameters={"type": "object", "properties": {"movie": {"type": "string"}}},
        ),
        ToolSpec(
            name="cinema_booking.reserve_seat",
            description="Đặt ghế xem phim",
            app="cinema_booking",
            kind="write",
            parameters={
                "type": "object",
                "properties": {
                    "show_id": {"type": "string", "x-ref": "cinema_booking.shows"},
                    "seat": {"type": "string"},
                },
            },
        ),
    ]
    request = AgentRequest(
        sample_id="s_unseen_app",
        transcript="Đặt ghế xem phim tối nay cho anh nhé",
        context={},
    )

    candidates = DiscoveryService(top_k=4).retrieve(request, catalog)
    names = {t.name for t in candidates}
    assert names == {"cinema_booking.reserve_seat", "cinema_booking.search_shows"}


def test_retrieve_for_need_location_finds_implicit_calendar_and_reminder_providers() -> None:
    """Section 3.3 Failure Mode 1: 'book ride to dental appointment' needs LOCATION from calendar/reminders."""
    catalog = [
        ToolSpec(name="ride_hailing.book", description="Đặt xe đến địa điểm", kind="write"),
        ToolSpec(name="calendar.list_events", description="Xem lịch sự kiện, cuộc hẹn", kind="read"),
        ToolSpec(name="reminders.list", description="Xem danh sách lời nhắc", kind="read"),
        ToolSpec(name="maps.search_place", description="Tìm địa điểm trên bản đồ", kind="read"),
        ToolSpec(name="sys.ask_missing_info", description="Hỏi thông tin thiếu", kind="meta"),
    ]
    need = InformationNeed(
        issue_id="iss_loc",
        task_id="task_ride",
        field="destination",
        kind="LOCATION",
        question="Địa chỉ phòng khám răng trong lịch hẹn là ở đâu?",
        why_not_ready="Chưa có địa điểm đến cho chuyến xe",
        capability_hints=["appointment", "khám"],
    )

    candidates = DiscoveryService(top_k=8, recovery_top_k=3).retrieve_for_need(need, catalog)
    cand_names = [c.tool.name for c in candidates]

    assert "calendar.list_events" in cand_names
    assert "reminders.list" in cand_names
    # Write and meta tools must NEVER be returned by retrieve_for_need
    assert "ride_hailing.book" not in cand_names
    assert "sys.ask_missing_info" not in cand_names
    assert all(c.rank == idx for idx, c in enumerate(candidates, start=1))


def test_retrieve_for_need_excludes_already_tried_tools_and_returns_empty_when_exhausted() -> None:
    """Section 3.3 Failure Mode 3 & 4: Do not return already-tried tools or random tools when exhausted."""
    catalog = [
        ToolSpec(name="contacts.search", description="Tìm danh bạ", kind="read"),
        ToolSpec(name="sms.send", description="Gửi tin nhắn", kind="write"),
    ]
    need = InformationNeed(
        issue_id="iss_ent",
        task_id="task_sms",
        field="recipient",
        kind="ENTITY",
        question="Tìm số điện thoại của Minh",
        capability_hints=["contact"],
        attempt_history=["contacts.search"],
    )

    candidates = DiscoveryService(top_k=8, recovery_top_k=3).retrieve_for_need(
        need, catalog, history=["contacts.search"]
    )
    assert candidates == []


def test_tool_registry_helpers_and_duplicate_validation() -> None:
    t1 = ToolSpec(name="alarm.list", description="Xem báo thức", app="alarm", kind="read")
    t2 = ToolSpec(name="alarm.create", description="Đặt báo thức", app="alarm", kind="write")
    t3 = ToolSpec(name="sys.ask_missing_info", description="Ask user", app="sys", kind="meta")

    reg = ToolRegistry([t1, t2, t3])
    assert reg.get("alarm.list") == t1
    assert len(reg.by_app("alarm")) == 2
    assert [t.name for t in reg.read_only_tools()] == ["alarm.list"]

    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([t1, t1])

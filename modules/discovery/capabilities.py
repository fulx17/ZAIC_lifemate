"""Domain capability lexicons, dialect normalization, and schema-driven dependency graphs for N2."""

from __future__ import annotations

import re
import unicodedata

from core.contracts import ToolSpec

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Self-correction markers in spoken Vietnamese: text after the marker carries the revised intent.
SELF_CORRECTION_PATTERNS: tuple[str, ...] = (
    "à không",
    "à mà thôi",
    "à nhầm",
    "nhầm rồi",
    "thôi khỏi",
    "khoan đã",
    "à quên",
    "đổi ý",
    "à thôi",
)

# Short/anaphoric markers indicating the current turn relies on recent conversation history.
ANAPHORA_MARKERS: tuple[str, ...] = (
    "đó",
    "này",
    "đấy",
    "ấy",
    "vừa nãy",
    "vừa rồi",
    "lúc nãy",
    "hồi nãy",
    "như trên",
    "như chị dặn",
    "như anh dặn",
    "như em nói",
    "như vừa nói",
    "cái còn lại",
    "cậu ấy",
    "anh ấy",
    "chị ấy",
    "bác ấy",
    "cô ấy",
    "chú ấy",
    "người đó",
    "bên đó",
    "quán đó",
    "chuyến đó",
    "đơn đó",
    "món đó",
    "hóa đơn đó",
    "cái đó",
    "hôm đấy",
    "bản đấy",
    "tập đó",
    "cửa đó",
    "tiếp",
    "luôn nhé",
    "giúp tôi nhé",
)

# Regional dialect & colloquial phrase expansions.
DIALECT_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("bữa ni", "hôm nay"),
    ("hôm ni", "hôm nay"),
    ("bữa nay", "hôm nay"),
    ("ngày mốt", "ngày kia"),
    ("bữa mai", "ngày mai"),
    ("mần răng", "làm sao"),
    ("hông", "không"),
    ("dùm", "giúp"),
    ("giùm", "giúp"),
    ("máy lạnh", "điều hoà điều hòa"),
    ("bắn tiền", "chuyển tiền chuyển khoản"),
    ("chuyển khoản", "chuyển tiền ngân hàng"),
    ("tiền điện", "hoá đơn hóa đơn điện"),
    ("trả điện", "thanh toán hoá đơn điện"),
    ("đóng điện", "thanh toán hoá đơn điện"),
    ("tiền nước", "hoá đơn hóa đơn nước"),
    ("trả nước", "thanh toán hoá đơn nước"),
    ("tiền mạng", "hoá đơn hóa đơn internet"),
    ("tiền nét", "hoá đơn hóa đơn internet"),
    ("tiền internet", "hoá đơn hóa đơn internet"),
    ("tiền truyền hình", "hoá đơn hóa đơn truyền hình"),
    ("tiền cáp", "hoá đơn hóa đơn truyền hình"),
    ("học phí", "hoá đơn hóa đơn học phí"),
    ("ơ-rô", "eur tỷ giá ngoại tệ"),
    ("ơ rô", "eur tỷ giá ngoại tệ"),
    ("đô bữa nay", "usd tỷ giá ngoại tệ"),
    ("đô dưới", "usd tỷ giá ngoại tệ"),
    ("mấy đô", "usd tỷ giá ngoại tệ"),
    ("phiếu giảm giá", "voucher ưu đãi loyalty"),
    ("cắt điện", "tin tức news"),
    ("cữ kháng sinh", "lịch thuốc uống thuốc medication"),
    ("kháng sinh", "lịch thuốc uống thuốc medication"),
    ("dầu mà còn", "giá xăng dầu fuel_price"),
    ("tổng cộng mấy cây", "tính biểu thức calculator"),
    ("cộng chung tiền", "tính biểu thức calculator"),
    ("gạch cái việc", "hoàn thành việc danh sách việc tasks"),
    ("gạch việc", "hoàn thành việc danh sách việc tasks"),
    ("ghi vào lịch", "tạo sự kiện lịch calendar"),
    ("ghi lịch", "tạo sự kiện lịch calendar"),
    ("chặn lịch", "tạo sự kiện lịch calendar"),
    ("ghi buổi khai giảng vào lịch", "tạo sự kiện lịch calendar"),
    ("bỏ hộ tớ", "xoá món danh sách mua sắm"),
    ("bỏ cái hẹn tắt", "xoá quy tắc tự động hoá"),
    ("bỏ luôn hẹn giờ", "xoá quy tắc tự động hoá"),
    ("xoá hết hẹn giờ", "xoá quy tắc tự động hoá"),
    ("xoá luôn hai cái hẹn", "xoá quy tắc tự động hoá"),
    ("cái bật đèn phòng khách bỏ đi", "xoá quy tắc tự động hoá"),
    ("cái tắt máy lạnh năm rưỡi sáng", "xoá quy tắc tự động hoá"),
    ("tắt cái máy dưới bếp", "danh sách thiết bị gia dụng appliances"),
    ("tắt cái máy đang chạy", "dừng thiết bị gia dụng appliances"),
    ("đám cưới", "sự kiện lịch calendar"),
    ("đám giỗ", "danh sách nhắc việc reminders"),
    ("gặp khách", "danh sách việc tasks"),
    ("demo cho khách", "cuộc họp trực tuyến video_meeting"),
    ("mỗi tờ trúng", "kết quả xổ số lottery"),
    ("kết quả đà nẵng", "kết quả xổ số lottery"),
    ("giảm còn phân nửa", "điều khiển phát nhạc âm lượng music"),
    ("học phí thằng bi mới đóng", "hoàn thành việc danh sách việc tasks"),
    ("gọi xe", "đặt xe đặt chuyến"),
    ("bắt xe", "đặt xe đặt chuyến"),
    ("book xe", "đặt xe đặt chuyến"),
    ("gọi ô tô", "đặt xe đặt chuyến"),
    ("kêu xe", "đặt xe đặt chuyến"),
    ("xe ôm", "đặt xe bike"),
    ("tắt chuông", "xoá báo thức tắt báo thức"),
    ("báo thức dậy", "báo thức"),
    ("gọi dậy", "báo thức"),
    ("ngủ thêm", "sửa báo thức báo thức"),
    ("nhắc tôi", "tạo nhắc việc nhắc nhở"),
    ("nhắc em", "tạo nhắc việc nhắc nhở"),
    ("nhắc anh", "tạo nhắc việc nhắc nhở"),
    ("nhắc chị", "tạo nhắc việc nhắc nhở"),
    ("nhắc mình", "tạo nhắc việc nhắc nhở"),
    ("đặt lịch", "tạo sự kiện lịch"),
)

# App-level Vietnamese & English semantic keywords (covers all 57 apps in train + public_test + general domains).
APP_KEYWORDS: dict[str, set[str]] = {
    "smart_home": {
        "nhà thông minh", "đèn", "bóng đèn", "quạt", "điều hoà", "điều hòa", "máy lạnh",
        "ổ cắm", "rèm", "rèm cửa", "công tắc", "ngữ cảnh", "phòng khách", "phòng ngủ",
        "phòng bếp", "tầng", "độ sáng", "nhiệt độ phòng", "đi ngủ", "ra khỏi nhà",
        "light", "fan", "climate", "switch", "scene",
    },
    "home_security": {
        "an ninh", "camera", "cam", "cảnh báo", "chống trộm", "bảo vệ", "cảm biến",
        "chuông báo", "security", "alert", "arm",
    },
    "door_lock": {
        "khoá cửa", "khóa cửa", "cửa chính", "cửa sau", "cửa cổng", "cổng phụ", "cửa gara",
        "cửa kho", "cửa đó", "khóa lại", "khoá lại", "mở cửa", "cửa đang mở", "cửa còn mở",
        "mã khách", "mã mở cửa", "lock", "door",
    },
    "robot_vacuum": {
        "robot", "hút bụi", "dọn nhà", "quét nhà", "lau nhà", "dọn phòng", "về dock", "vacuum",
    },
    "appliances": {
        "máy giặt", "lò vi sóng", "nồi cơm", "máy lọc không khí", "máy sấy", "máy rửa bát",
        "gia dụng", "chu trình giặt", "appliance",
    },
    "home_energy": {
        "điện năng", "điện tiêu thụ", "số điện", "kwh", "tiêu thụ điện", "ngưỡng điện", "energy",
    },
    "alarm": {
        "báo thức", "chuông báo thức", "đặt chuông", "hẹn giờ dậy", "gọi dậy", "ngủ thêm", "alarm",
    },
    "reminders": {
        "nhắc việc", "nhắc nhở", "nhắc tôi", "nhắc em", "nhắc anh", "nhắc chị", "nhắc mình",
        "lời nhắc", "đừng quên", "reminder", "reminders",
    },
    "calendar": {
        "lịch", "sự kiện", "cuộc hẹn", "lịch họp", "buổi họp", "lịch hẹn", "khám răng",
        "khám bệnh", "chạy bộ", "dời lịch", "đổi lịch", "huỷ lịch", "hủy lịch",
        "thêm vào lịch", "đặt một lịch", "calendar", "event",
    },
    "notes": {
        "ghi chú", "note", "notes", "sổ tay", "ghi lại", "viết ghi chú", "lưu cái ghi chú",
    },
    "tasks": {
        "việc cần làm", "danh sách việc", "task", "tasks", "todo", "công việc có hạn",
        "hoàn thành việc", "tạo việc", "tạo giúp em việc", "tạo cho anh một việc", "hạn tám giờ", "hạn",
    },
    "contacts": {
        "danh bạ", "liên hệ", "số điện thoại", "email của", "số của", "tìm số",
        "a còng", "chấm test", "chấm com", "contact", "contacts",
    },
    "phone": {
        "gọi điện", "gọi thoại", "cuộc gọi", "gọi cho", "nhấc máy", "gọi lại", "gọi luôn số", "phone", "call",
    },
    "sms": {
        "tin nhắn", "nhắn tin", "sms", "gửi tin", "nhắn cho", "gửi sms", "message", "text",
    },
    "chat_ott": {
        "ott", "zalo", "nhóm chat", "nhóm", "cuộc trò chuyện", "gửi vị trí", "gọi video",
        "gọi nhóm", "tin nhắn nhóm", "nhắn cho", "nhắn anh", "nhắn chị", "nhắn cô", "nhắn bác", "chat",
    },
    "email": {
        "email", "thư điện tử", "mail", "hộp thư", "thư nháp", "trả lời thư", "gửi thư", "lưu trữ email",
    },
    "video_meeting": {
        "họp trực tuyến", "phòng họp", "phòng họp online", "mở phòng họp", "tham gia họp",
        "meeting", "video call", "link họp",
    },
    "banking": {
        "ngân hàng", "tài khoản ngân hàng", "tài khoản thanh toán", "trích tài khoản",
        "chuyển khoản", "người thụ hưởng", "gửi tiết kiệm",
        "sổ tiết kiệm", "lịch sử giao dịch", "sao kê", "số dư tài khoản", "banking", "bank", "transfer",
    },
    "ewallet": {
        "ví điện tử", "ví", "số dư ví", "chuyển tiền ví", "nạp tiền điện thoại", "nạp thẻ điện thoại",
        "thanh toán qr", "quét mã qr", "mã qr", "ewallet", "topup",
    },
    "bill_payment": {
        "hoá đơn", "hóa đơn", "thanh toán hoá đơn", "thanh toán hóa đơn", "tiền điện", "tiền nước",
        "tiền internet", "tiền mạng", "truyền hình cáp", "học phí", "autopay", "tự động thanh toán", "bill",
    },
    "loyalty": {
        "điểm thưởng", "tích điểm", "voucher", "mã giảm giá", "ưu đãi", "đổi điểm",
        "thẻ thành viên", "loyalty", "redeem",
    },
    "stocks": {
        "chứng khoán", "cổ phiếu", "mã cổ phiếu", "danh mục đầu tư", "đặt lệnh mua",
        "đặt lệnh bán", "giá cổ phiếu", "chỉ số", "vnindex", "stocks", "stock",
    },
    "weather": {
        "thời tiết", "dự báo thời tiết", "mưa", "nắng", "nhiệt độ ngoài trời", "trời",
        "có mưa không", "đang mưa", "trời ráo", "weather", "forecast", "rain",
    },
    "gold_price": {
        "giá vàng", "vàng sjc", "vàng nhẫn", "vàng thế giới", "mua vàng", "gold",
    },
    "fuel_price": {
        "giá xăng", "xăng dầu", "ron95", "ron92", "dầu diesel", "xăng", "fuel",
    },
    "lottery": {
        "xổ số", "vé số", "kết quả xổ số", "kiến thiết", "dò vé số", "đài", "lottery",
    },
    "exchange_rate": {
        "tỷ giá", "ngoại tệ", "đổi tiền", "quy đổi tiền", "usd", "eur",
        "jpy", "đô la", "yên nhật", "bảng anh", "exchange",
    },
    "news": {
        "tin tức", "đọc báo", "tin nổi bật", "điểm tin", "bài báo", "thời sự", "thông báo mới nhất", "news",
    },
    "calculator": {
        "máy tính", "tính toán", "biểu thức", "quy đổi đơn vị", "đổi đơn vị", "tính giúp", "chia đều", "calculator",
    },
    "translator": {
        "dịch", "dịch thuật", "dịch sang", "tiếng anh", "tiếng việt", "tiếng nhật",
        "tiếng hàn", "tiếng trung", "tiếng pháp", "translate", "translator",
    },
    "maps": {
        "bản đồ", "chỉ đường", "đường đi", "tìm địa điểm", "quanh đây", "gần đây",
        "bao xa", "mất bao lâu", "lưu địa điểm", "maps", "route",
    },
    "food_delivery": {
        "đặt đồ ăn", "giao đồ ăn", "quán ăn", "nhà hàng", "thực đơn", "menu", "đặt món",
        "trà sữa", "cơm", "phở", "bún", "cháo", "gà rán", "pizza", "suất", "phần ăn", "food", "restaurant",
    },
    "grocery": {
        "đi chợ", "siêu thị", "thực phẩm", "rau", "thịt", "cá", "trứng", "sữa", "trái cây",
        "giỏ hàng đi chợ", "grocery",
    },
    "recipes": {
        "công thức", "nấu ăn", "cách nấu", "cách làm món", "nguyên liệu nấu", "khẩu phần",
        "recipe", "recipes",
    },
    "ride_hailing": {
        "đặt xe", "đặt chuyến", "gọi xe", "bắt xe", "xe 4 chỗ", "xe 7 chỗ", "xe máy",
        "báo giá xe", "huỷ chuyến", "hủy chuyến", "điểm đón", "điểm đến", "ride",
    },
    "public_transit": {
        "xe buýt", "buýt", "bus", "metro", "tàu điện", "tuyến xe", "trạm buýt",
        "chuyến tiếp theo", "nạp thẻ xe buýt", "transit",
    },
    "parking": {
        "đỗ xe", "gửi xe", "bãi đỗ", "chỗ đỗ xe", "bãi giữ xe", "phiên đỗ", "parking",
    },
    "flights": {
        "vé máy bay", "chuyến bay", "máy bay", "sân bay", "check in", "làm thủ tục bay",
        "hạng ghế", "flight", "flights",
    },
    "train_bus_tickets": {
        "vé tàu", "tàu hoả", "tàu hỏa", "xe khách", "vé xe khách", "liên tỉnh", "ga tàu", "bến xe",
    },
    "ecommerce": {
        "mua sắm", "sàn thương mại", "đặt hàng online", "đơn hàng", "trả hàng", "hoàn tiền",
        "thêm vào giỏ", "thanh toán giỏ hàng", "cod", "ecommerce",
    },
    "shopping_list": {
        "danh sách mua sắm", "danh sách cần mua", "đồ cần mua", "shopping list", "đánh dấu đã mua",
    },
    "package_tracking": {
        "vận đơn", "bưu kiện", "kiện hàng", "giao hàng", "bưu tá", "lấy hàng gửi đi",
        "theo dõi đơn", "tracking", "package",
    },
    "music": {
        "nghe nhạc", "phát nhạc", "bài hát", "bản nhạc", "mở bài", "mở bản", "lofi",
        "playlist", "danh sách phát", "tạm dừng nhạc", "chuyển bài", "âm lượng nhạc", "music", "track",
    },
    "tv": {
        "tivi", "tv", "truyền hình", "chuyển kênh", "kênh", "vtv", "htv", "lịch phát sóng",
        "ghi hình chương trình",
    },
    "podcast_radio": {
        "podcast", "radio", "sách nói", "tập podcast", "kênh podcast", "đăng ký kênh", "danh sách nghe sau",
    },
    "event_tickets": {
        "vé sự kiện", "vé ca nhạc", "vé kịch", "vé xem phim", "vé bóng đá", "vé thể thao",
        "triển lãm", "concert", "liveshow",
    },
    "medication": {
        "uống thuốc", "lịch thuốc", "nhắc thuốc", "thuốc", "viên thuốc", "đã uống thuốc", "medication",
    },
    "fitness": {
        "bước chân", "calo", "buổi tập", "tập thể dục", "tập yoga", "vận động", "mục tiêu bước", "workout", "fitness",
    },
    "habit_tracker": {
        "thói quen", "chuỗi ngày", "streak", "duy trì thói quen", "đánh dấu thói quen", "habit",
    },
    "pantry": {
        "tủ bếp", "tủ lạnh", "đồ trong bếp", "nguyên liệu trong bếp", "đã dùng hết", "pantry",
    },
    "learning": {
        "học tập", "khoá học", "khóa học", "bài học", "lịch học", "đăng ký học", "tiến độ học", "course",
    },
    "bike_rental": {
        "thuê xe đạp", "xe đạp công cộng", "trạm xe đạp", "mượn xe đạp", "bike rental",
    },
    "home_automation": {
        "tự động hoá", "tự động hóa", "quy tắc hẹn giờ", "quy tắc tự động", "mỗi ngày tự động",
        "tự bật", "tự tắt", "cài giờ tắt", "cài giờ bật", "tối nào cũng", "sáng nào cũng", "automation",
    },
    "household_chores": {
        "việc nhà", "phân công việc nhà", "giao việc nhà", "rửa bát", "đổ rác", "chores",
    },
    "library": {
        "thư viện", "mượn sách", "đặt giữ sách", "tìm sách", "cuốn sách", "tác giả", "library",
    },
    "subscriptions": {
        "gói đăng ký", "gói cước", "dịch vụ trả phí", "gia hạn", "huỷ gói", "hủy gói",
        "netflix", "spotify", "youtube premium", "subscription",
    },
}

# Generic action-suffix -> Vietnamese & English trigger words (generalizes to unseen apps).
ACTION_VERB_TRIGGERS: dict[str, tuple[str, ...]] = {
    "create": ("tạo", "đặt", "thêm", "lên lịch", "mở", "hẹn", "nhắc", "create", "new"),
    "create_event": ("tạo lịch", "thêm lịch", "tạo sự kiện", "đặt lịch", "lên lịch", "có hẹn", "buổi họp"),
    "create_draft": ("soạn", "nháp", "lưu nháp", "viết thư", "draft"),
    "create_rule": ("tạo quy tắc", "hẹn giờ tự động", "mỗi ngày", "hằng ngày", "tự động"),
    "add": ("thêm", "cho vào", "bổ sung", "add", "nhắc thuốc", "uống thuốc"),
    "add_to_cart": ("thêm vào giỏ", "cho vào giỏ", "bỏ vào giỏ", "mua"),
    "add_to_playlist": ("thêm vào playlist", "cho vào danh sách phát"),
    "append": ("thêm vào ghi chú", "ghi thêm", "bổ sung vào ghi chú", "append"),
    "book": ("đặt", "book", "mua vé", "gọi xe", "bắt xe", "gọi ô tô"),
    "place_order": ("đặt", "mua", "giao", "order"),
    "checkout": ("thanh toán giỏ", "đặt hàng", "chốt đơn", "checkout"),
    "reserve": ("đặt", "giữ", "thuê", "mượn", "reserve"),
    "enroll": ("đăng ký", "theo học", "ghi danh", "enroll"),
    "send": ("gửi", "nhắn", "báo", "send"),
    "send_message": ("nhắn", "gửi tin", "báo", "nhắn qua zalo", "nhắn zalo", "nhắn nhóm", "gửi vào nhóm"),
    "send_location": ("gửi vị trí", "chia sẻ vị trí", "định vị"),
    "reply": ("trả lời", "phản hồi", "hồi âm", "reply"),
    "call": ("gọi", "liên lạc", "call"),
    "pay": ("thanh toán", "trả", "đóng", "nộp", "pay"),
    "pay_qr": ("quét mã", "qr", "thanh toán qr"),
    "transfer": ("chuyển", "bắn tiền", "chuyển khoản", "transfer"),
    "topup_mobile": ("nạp tiền điện thoại", "nạp điện thoại", "nạp thẻ"),
    "topup_card": ("nạp thẻ", "nạp tiền thẻ"),
    "open_savings": ("tiết kiệm", "gửi tiết kiệm", "mở sổ"),
    "redeem": ("đổi điểm", "đổi quà", "đổi voucher", "redeem"),
    "update": ("sửa", "đổi", "dời", "lùi", "đẩy", "cập nhật", "chỉnh", "hoãn", "ngủ thêm", "update"),
    "update_event": ("dời", "lùi", "đẩy", "đổi lịch", "sửa lịch", "hoãn", "sớm hơn", "muộn hơn"),
    "reschedule_delivery": ("hẹn lại", "đổi giờ giao", "dời giờ giao"),
    "cancel": ("huỷ", "hủy", "bỏ", "cancel", "ngừng"),
    "cancel_event": ("huỷ", "hủy", "bỏ", "xoá lịch", "xóa lịch"),
    "cancel_order": ("huỷ đơn", "hủy đơn", "bỏ đơn"),
    "delete": ("xoá", "xóa", "huỷ", "hủy", "bỏ", "delete"),
    "delete_rule": ("xoá quy tắc", "xóa quy tắc", "huỷ quy tắc", "hủy quy tắc", "tắt quy tắc"),
    "remove": ("xoá", "xóa", "bỏ", "gỡ", "remove"),
    "archive": ("lưu trữ", "xoá email", "xóa email", "archive"),
    "complete": ("hoàn thành", "xong", "đánh dấu xong", "đã làm xong", "complete"),
    "check": ("đánh dấu đã mua", "đã mua"),
    "check_in": ("làm thủ tục", "check in", "checkin"),
    "check_ticket": ("dò vé", "kiểm tra vé số"),
    "log": ("đánh dấu", "ghi nhận", "đã thực hiện", "log"),
    "log_taken": ("đã uống", "uống thuốc rồi"),
    "log_workout": ("ghi buổi tập", "đã tập", "vừa tập"),
    "log_progress": ("ghi tiến độ", "học được"),
    "consume": ("đã dùng", "dùng hết", "lấy ra dùng"),
    "assign": ("giao việc", "phân công", "nhờ", "assign"),
    "set_lock": ("khoá", "khóa", "mở khoá", "mở khóa", "cửa"),
    "grant_guest_code": ("mã khách", "mã mở cửa", "cấp mã"),
    "light_set": ("đèn", "bật đèn", "tắt đèn", "độ sáng"),
    "fan_set": ("quạt", "bật quạt", "tắt quạt", "tốc độ quạt"),
    "climate_set": ("điều hoà", "điều hòa", "máy lạnh", "nhiệt độ"),
    "switch_set": ("ổ cắm", "rèm", "công tắc"),
    "scene_run": ("ngữ cảnh", "chế độ đi ngủ", "ra khỏi nhà"),
    "start": ("bắt đầu", "chạy", "dọn", "quét", "lau", "bật"),
    "start_cycle": ("giặt", "chạy máy", "bật máy", "nấu", "chu trình"),
    "stop": ("dừng", "tắt", "ngừng", "về dock"),
    "arm": ("chế độ bảo vệ", "bật chống trộm", "tắt bảo vệ", "an ninh"),
    "acknowledge_alert": ("đã xem cảnh báo", "tắt cảnh báo", "xác nhận cảnh báo"),
    "calculate": ("tính", "cộng", "trừ", "nhân", "chia", "bằng bao nhiêu", "phần trăm"),
    "convert_unit": ("đổi", "quy đổi", "sang km", "sang m", "sang kg", "sang độ", "pound", "inch", "mile"),
    "convert": ("quy đổi", "đổi sang", "bao nhiêu tiền việt", "usd sang", "sang vnd"),
    "get_rate": ("tỷ giá", "giá đô", "giá ngoại tệ", "usd", "eur", "jpy"),
    "translate": ("dịch", "tiếng anh", "tiếng nhật", "tiếng hàn", "tiếng trung", "tiếng pháp", "nói sao"),
    "get_route": ("chỉ đường", "đường đi", "bao xa", "mất bao lâu", "từ đây đến"),
    "search_place": ("tìm quán", "tìm địa điểm", "gần đây", "quanh đây", "ở đâu"),
    "save_place": ("lưu địa điểm", "đánh dấu địa điểm"),
    "save": ("lưu lại", "lưu bài", "lưu công thức", "đọc sau"),
    "play": ("phát", "mở nhạc", "bật nhạc", "nghe bài", "nghe playlist", "nghe tập"),
    "control": ("tạm dừng", "tiếp tục", "chuyển bài", "âm lượng", "to lên", "nhỏ xuống", "tắt tv", "bật tv"),
    "tune": ("chuyển kênh", "mở kênh", "bật kênh", "kênh"),
    "record": ("ghi hình", "thu lại chương trình"),
    "join": ("tham gia", "vào phòng họp", "vào họp"),
}

# Tool-specific high-precision trigger terms (extends the baseline's 9 tools to all major tools).
TOOL_CAPABILITY_TERMS: dict[str, set[str]] = {
    "weather.get_forecast": {
        "weather", "forecast", "rain", "mưa", "thời tiết", "dự báo", "nắng", "mai trời", "trời ráo",
    },
    "weather.get_current": {
        "weather", "current", "thời tiết", "hiện tại", "bây giờ trời",
        "nhiệt độ hiện tại", "đang mưa", "giờ mà đang mưa",
    },
    "calendar.list_events": {"calendar", "event", "schedule", "lịch", "sự kiện", "cuộc hẹn", "họp", "khám"},
    "calendar.create_event": {
        "tạo lịch", "thêm lịch", "tạo sự kiện", "đặt lịch hẹn", "lên lịch", "thêm cuộc hẹn",
        "thêm vào lịch", "đặt cho anh một lịch", "đặt cho chị một lịch", "đặt một lịch",
        "ghi lịch", "chặn lịch", "tạo lại",
    },
    "calendar.update_event": {
        "calendar", "reschedule", "update", "dời", "đổi lịch", "sửa lịch", "lùi lịch",
        "đẩy lịch", "lùi lại", "lùi sang", "đẩy muộn", "dời muộn", "dời sớm", "hoãn lịch", "sửa giờ",
    },
    "calendar.cancel_event": {
        "calendar", "cancel", "hủy", "huỷ", "xóa lịch", "xoá lịch", "huỷ sự kiện", "hủy lịch",
        "bỏ lịch", "bỏ cuộc họp", "bỏ cái họp", "huỷ họp", "hủy họp",
    },
    "contacts.search": {"contact", "contacts", "recipient", "liên hệ", "người", "danh bạ", "số của", "tìm số"},
    "contacts.get": {"chi tiết liên hệ", "thông tin liên hệ"},
    "contacts.update": {
        "sửa số", "cập nhật số", "cập nhật email", "sửa liên hệ", "đổi số điện thoại",
        "a còng", "chấm test", "chấm com", "sửa email",
    },
    "sms.send": {"sms", "text", "message", "nhắn", "tin nhắn", "gửi tin", "gửi sms", "nhắn sms"},
    "sms.read_recent": {"đọc tin nhắn", "tin nhắn gần đây", "xem tin nhắn sms"},
    "chat_ott.list_chats": {"danh sách nhóm", "cuộc trò chuyện", "nhóm chat", "tìm nhóm", "zalo", "ott"},
    "chat_ott.read_chat": {
        "đọc tin trong nhóm", "xem tin nhắn nhóm", "mọi người trong nhóm",
        "tin nhắn zalo", "đọc giúp anh nhóm", "đọc giúp chị nhóm",
    },
    "chat_ott.send_message": {
        "chat", "message", "nhắn", "nhắn tin", "nhắn vào nhóm", "gửi vào nhóm", "báo trong nhóm",
        "nhắn zalo", "nhắn qua zalo", "gửi zalo", "nhắn trên zalo", "nhắn ott", "gửi tin zalo",
        "nhắn cho", "nhắn anh", "nhắn chị", "nhắn cô", "nhắn bác",
    },
    "chat_ott.send_location": {"gửi vị trí", "chia sẻ vị trí"},
    "chat_ott.call": {"gọi nhóm", "gọi video", "gọi ott", "gọi zalo"},
    "phone.call": {"call", "phone", "gọi", "cuộc gọi", "gọi điện", "gọi thoại", "gọi luôn số"},
    "phone.recent_calls": {"cuộc gọi gần đây", "cuộc gọi nhỡ", "lịch sử cuộc gọi"},
    "alarm.list": {"danh sách báo thức", "xem báo thức", "báo thức nào"},
    "alarm.create": {"đặt báo thức", "tạo báo thức", "hẹn báo thức", "báo thức lúc", "gọi dậy", "báo thức thì đặt"},
    "alarm.update": {"sửa báo thức", "đổi giờ báo thức", "bật báo thức", "tắt báo thức", "ngủ thêm", "dời báo thức"},
    "alarm.delete": {"xoá báo thức", "xóa báo thức", "huỷ báo thức", "hủy báo thức", "bỏ báo thức"},
    "reminders.list": {"danh sách nhắc việc", "xem lời nhắc", "nhắc nhở nào"},
    "reminders.create": {
        "nhắc tôi", "nhắc em", "nhắc anh", "nhắc chị", "nhắc mình",
        "tạo nhắc việc", "nhắc nhở", "nhắc lúc", "đừng quên", "nhắc mang", "nhắc nạp",
    },
    "reminders.complete": {
        "hoàn thành nhắc việc", "xong nhắc việc", "đánh dấu xong lời nhắc", "nhắc học thì done", "done luôn",
    },
    "reminders.delete": {"xoá nhắc việc", "xóa nhắc việc", "huỷ lời nhắc", "hủy nhắc nhở"},
    "smart_home.get_status": {"trạng thái thiết bị", "kiểm tra đèn", "kiểm tra điều hòa", "phòng nào đang bật"},
    "smart_home.light_set": {"bật đèn", "tắt đèn", "đèn", "độ sáng", "chỉnh đèn", "giảm đèn"},
    "smart_home.fan_set": {"bật quạt", "tắt quạt", "quạt", "tốc độ quạt"},
    "smart_home.climate_set": {"điều hoà", "điều hòa", "máy lạnh", "nhiệt độ", "bật điều hòa", "tắt điều hòa"},
    "smart_home.switch_set": {"ổ cắm", "rèm", "công tắc", "mở rèm", "đóng rèm", "máy bơm", "bơm nước"},
    "smart_home.scene_run": {"ngữ cảnh", "chế độ đi ngủ", "chế độ ra khỏi nhà", "chế độ xem phim"},
    "home_automation.create_rule": {
        "tạo quy tắc", "hẹn giờ tự động", "tự bật", "tự tắt", "cài giờ tắt", "cài giờ bật",
        "tối nào cũng", "sáng nào cũng", "mỗi ngày tự động",
    },
    "home_automation.delete_rule": {
        "xoá quy tắc", "xóa quy tắc", "huỷ quy tắc", "hủy quy tắc",
        "xoá hết hẹn giờ", "xoá luôn hai cái hẹn", "bỏ cái hẹn",
    },
    "door_lock.set_lock": {
        "khoá cửa", "khóa cửa", "khóa lại", "khoá lại", "khóa ngay cửa", "khóa cái cổng", "mở cửa",
    },
    "tasks.add": {
        "thêm việc", "tạo việc", "tạo giúp em việc", "tạo cho anh một việc",
        "tạo cho chị một việc", "thêm cho mình việc",
    },
    "tasks.complete": {"hoàn thành việc", "đánh dấu xong việc", "gạch việc", "gạch cái việc"},
    "shopping_list.remove": {"xoá khỏi danh sách", "bỏ khỏi danh sách", "khỏi danh sách đi chợ", "bỏ bánh", "bỏ nón"},
    "news.headlines": {"tin nóng", "điểm tin", "tin nổi bật", "tin thể thao", "bản tin"},
    "email.read": {"đọc email", "đọc thư", "mở thư", "xem thư", "mở coi"},
    "podcast_radio.queue": {"danh sách chờ phát", "chờ phát", "hàng đợi phát"},
    "bill_payment.list_bills": {
        "hoá đơn", "hóa đơn", "tiền điện", "tiền nước", "tiền mạng",
        "tiền truyền hình", "internet", "học phí",
    },
    "bill_payment.pay": {
        "thanh toán hoá đơn", "thanh toán hóa đơn", "trả tiền điện", "trả điện", "đóng điện",
        "trả tiền nước", "đóng tiền điện", "đóng tiền nước", "trả tiền mạng", "đóng tiền mạng",
        "trả tiền truyền hình", "đóng tiền truyền hình", "đóng học phí", "trả giúp chị cái tiền",
        "trả bằng ví", "trả bằng ngân hàng", "trả qua ngân hàng",
    },
    "bill_payment.schedule_autopay": {"tự động thanh toán", "autopay"},
    "banking.get_balance": {"số dư ngân hàng", "số dư tài khoản", "tài khoản còn bao nhiêu"},
    "banking.list_beneficiaries": {"người thụ hưởng", "danh sách thụ hưởng"},
    "banking.list_transactions": {"lịch sử giao dịch", "giao dịch gần đây", "sao kê"},
    "banking.transfer": {
        "chuyển khoản", "chuyển tiền ngân hàng", "bank transfer", "chuyển dùm", "chuyển giúp",
        "trích tài khoản", "tài khoản thanh toán",
    },
    "banking.open_savings": {"gửi tiết kiệm", "mở sổ tiết kiệm", "tiết kiệm"},
    "ewallet.get_balance": {
        "số dư ví", "ví còn bao nhiêu", "kiểm tra ví", "nếu ví đủ", "ví không đủ", "ví thiếu",
    },
    "ewallet.transfer": {"chuyển tiền ví", "chuyển ví", "bắn tiền ví"},
    "ewallet.topup_mobile": {"nạp tiền điện thoại", "nạp thẻ", "nạp điện thoại"},
    "ewallet.pay_qr": {"thanh toán qr", "quét qr", "trả bằng qr"},
    "ride_hailing.get_quotes": {"báo giá xe", "giá cước xe", "kiểm tra giá xe"},
    "ride_hailing.book": {
        "đặt xe", "gọi xe", "bắt xe", "book xe", "xe 4 chỗ",
        "xe bốn chỗ", "xe 7 chỗ", "xe bảy chỗ", "gọi ô tô",
    },
    "ride_hailing.cancel": {"huỷ chuyến xe", "hủy chuyến xe", "huỷ xe", "hủy đặt xe"},
    "ride_hailing.get_ride": {"trạng thái chuyến xe", "xe đến đâu rồi"},
    "food_delivery.list_restaurants": {"tìm quán ăn", "danh sách quán", "nhà hàng quanh đây"},
    "food_delivery.get_menu": {"thực đơn", "menu quán", "xem món"},
    "food_delivery.place_order": {
        "đặt đồ ăn", "đặt món", "giao đồ ăn", "đặt trà sữa", "đặt cơm", "đặt phở", "đặt bún",
        "bún bò", "cháo gà", "hai suất", "một phần",
    },
    "food_delivery.cancel_order": {"huỷ đơn đồ ăn", "hủy đơn ăn"},
    "music.play": {"phát nhạc", "mở bài", "mở bản", "bật bài", "nghe bài", "play music"},
    "gold_price.get_price": {"giá vàng", "vàng sjc", "vàng nhẫn"},
    "fuel_price.get_price": {"giá xăng", "ron95", "ron92", "giá dầu"},
}

# Static domain prerequisite closure (augments dynamic x-ref schema inspection).
STATIC_CLOSURE: dict[str, tuple[str, ...]] = {
    "phone.call": ("contacts.search",),
    "sms.send": ("contacts.search",),
    "sms.read_recent": ("contacts.search",),
    "chat_ott.send_message": ("chat_ott.list_chats", "contacts.search"),
    "chat_ott.send_location": ("chat_ott.list_chats",),
    "chat_ott.call": ("chat_ott.list_chats",),
    "chat_ott.read_chat": ("chat_ott.list_chats",),
    "calendar.update_event": ("calendar.list_events",),
    "calendar.cancel_event": ("calendar.list_events",),
    "alarm.update": ("alarm.list",),
    "alarm.delete": ("alarm.list",),
    "reminders.complete": ("reminders.list",),
    "reminders.delete": ("reminders.list",),
    "smart_home.light_set": ("smart_home.get_status",),
    "smart_home.fan_set": ("smart_home.get_status",),
    "smart_home.climate_set": ("smart_home.get_status",),
    "smart_home.switch_set": ("smart_home.get_status",),
    "smart_home.scene_run": ("smart_home.get_status",),
    "home_automation.create_rule": ("smart_home.get_status", "home_automation.list_rules"),
    "home_automation.delete_rule": ("home_automation.list_rules",),
    "home_security.acknowledge_alert": ("home_security.list_alerts",),
    "door_lock.set_lock": ("door_lock.list_locks",),
    "door_lock.grant_guest_code": ("door_lock.list_locks",),
    "robot_vacuum.start": ("robot_vacuum.get_status",),
    "robot_vacuum.stop": ("robot_vacuum.get_status",),
    "appliances.start_cycle": ("appliances.list",),
    "appliances.stop": ("appliances.list",),
    "notes.append": ("notes.list",),
    "tasks.complete": ("tasks.list",),
    "contacts.get": ("contacts.search",),
    "contacts.update": ("contacts.search",),
    "email.read": ("email.list",),
    "email.reply": ("email.list", "email.read"),
    "email.archive": ("email.list",),
    "email.send": ("contacts.search",),
    "email.create_draft": ("contacts.search",),
    "video_meeting.join": ("video_meeting.list_meetings",),
    "banking.transfer": ("banking.get_balance", "banking.list_beneficiaries"),
    "banking.open_savings": ("banking.get_balance",),
    "banking.list_transactions": ("banking.get_balance",),
    "ewallet.transfer": ("contacts.search", "ewallet.get_balance"),
    "ewallet.topup_mobile": ("contacts.search", "ewallet.get_balance"),
    "ewallet.pay_qr": ("food_delivery.list_restaurants", "ewallet.get_balance"),
    "bill_payment.pay": ("bill_payment.list_bills",),
    "bill_payment.schedule_autopay": ("bill_payment.list_bills",),
    "loyalty.redeem": ("loyalty.get_points", "loyalty.list_vouchers"),
    "news.save": ("news.search", "news.headlines"),
    "maps.save_place": ("maps.search_place",),
    "food_delivery.get_menu": ("food_delivery.list_restaurants",),
    "food_delivery.place_order": ("food_delivery.list_restaurants", "food_delivery.get_menu"),
    "food_delivery.cancel_order": ("food_delivery.order_history",),
    "grocery.add_to_cart": ("grocery.search",),
    "grocery.checkout": ("grocery.search", "grocery.add_to_cart"),
    "recipes.get": ("recipes.search",),
    "recipes.save": ("recipes.search",),
    "ride_hailing.cancel": ("ride_hailing.get_ride",),
    "parking.reserve": ("parking.find",),
    "parking.end_session": ("parking.list_sessions",),
    "flights.book": ("flights.search",),
    "flights.cancel": ("flights.my_bookings",),
    "flights.check_in": ("flights.my_bookings",),
    "train_bus_tickets.book": ("train_bus_tickets.search",),
    "train_bus_tickets.cancel": ("train_bus_tickets.my_bookings",),
    "ecommerce.add_to_cart": ("ecommerce.search",),
    "ecommerce.checkout": ("ecommerce.search", "ecommerce.add_to_cart"),
    "ecommerce.cancel_order": ("ecommerce.order_status",),
    "ecommerce.request_return": ("ecommerce.order_status",),
    "shopping_list.remove": ("shopping_list.get",),
    "shopping_list.check": ("shopping_list.get",),
    "package_tracking.reschedule_delivery": ("package_tracking.track",),
    "music.play": ("music.list_tracks",),
    "music.add_to_playlist": ("music.list_tracks",),
    "tv.tune": ("tv.guide",),
    "tv.record": ("tv.guide",),
    "podcast_radio.play": ("podcast_radio.search",),
    "podcast_radio.subscribe": ("podcast_radio.search",),
    "podcast_radio.queue": ("podcast_radio.search",),
    "event_tickets.book": ("event_tickets.search",),
    "medication.log_taken": ("medication.list",),
    "medication.remove": ("medication.list",),
    "habit_tracker.log": ("habit_tracker.list_habits",),
    "pantry.consume": ("pantry.list_items",),
    "learning.enroll": ("learning.list_courses",),
    "learning.schedule_lesson": ("learning.list_courses",),
    "learning.log_progress": ("learning.list_courses",),
    "bike_rental.reserve": ("bike_rental.find_bikes",),
    "household_chores.assign": ("household_chores.list_chores",),
    "library.reserve": ("library.search",),
    "subscriptions.cancel": ("subscriptions.list",),
    "stocks.place_order": ("stocks.get_quote", "stocks.get_portfolio"),
}

# InformationNeed kind -> trigger keywords -> preferred read-only provider tools.
NEED_CAPABILITIES: dict[str, dict[str, tuple[str, ...]]] = {
    "LOCATION": {
        "appointment": ("calendar.list_events", "reminders.list"),
        "event": ("calendar.list_events", "event_tickets.search"),
        "meeting": ("calendar.list_events", "video_meeting.list_meetings"),
        "khám": ("calendar.list_events", "reminders.list"),
        "họp": ("calendar.list_events", "video_meeting.list_meetings"),
        "lịch": ("calendar.list_events", "reminders.list"),
        "hẹn": ("calendar.list_events", "reminders.list"),
        "contact": ("contacts.search", "contacts.get"),
        "place": ("maps.search_place", "maps.get_route"),
        "địa chỉ": ("calendar.list_events", "maps.search_place", "contacts.search", "notes.list"),
        "địa điểm": ("calendar.list_events", "maps.search_place", "reminders.list"),
        "pickup": ("calendar.list_events", "maps.search_place"),
        "dropoff": ("calendar.list_events", "reminders.list", "maps.search_place"),
        "destination": ("calendar.list_events", "maps.search_place", "reminders.list"),
        "origin": ("maps.search_place", "calendar.list_events"),
        "near": ("maps.search_place", "parking.find", "bike_rental.find_bikes"),
        "quán": ("food_delivery.list_restaurants", "maps.search_place"),
        "nhóm": ("chat_ott.list_chats", "chat_ott.read_chat"),
    },
    "TIME": {
        "appointment": ("calendar.list_events", "reminders.list"),
        "event": ("calendar.list_events", "event_tickets.search"),
        "schedule": ("calendar.list_events", "reminders.list", "alarm.list", "tv.guide"),
        "weather": ("weather.get_forecast", "weather.get_current"),
        "khám": ("calendar.list_events", "reminders.list"),
        "họp": ("calendar.list_events", "video_meeting.list_meetings"),
        "lịch": ("calendar.list_events", "reminders.list"),
        "hẹn": ("calendar.list_events", "reminders.list"),
        "time": ("calendar.list_events", "reminders.list", "alarm.list"),
        "start": ("calendar.list_events", "video_meeting.list_meetings"),
        "end": ("calendar.list_events",),
        "flight": ("flights.my_bookings", "flights.search"),
        "train": ("train_bus_tickets.my_bookings", "train_bus_tickets.search"),
        "bus": ("public_transit.next_departures", "train_bus_tickets.search"),
        "delivery": ("package_tracking.track", "food_delivery.order_history"),
        "medication": ("medication.list",),
        "thuốc": ("medication.list",),
    },
    "ENTITY": {
        "contact": ("contacts.search", "contacts.get", "banking.list_beneficiaries"),
        "recipient": ("contacts.search", "banking.list_beneficiaries", "chat_ott.list_chats"),
        "person": ("contacts.search", "household_chores.list_chores"),
        "người": ("contacts.search", "banking.list_beneficiaries", "chat_ott.list_chats"),
        "beneficiary": ("banking.list_beneficiaries", "contacts.search"),
        "account": ("banking.get_balance",),
        "chat": ("chat_ott.list_chats",),
        "nhóm": ("chat_ott.list_chats", "chat_ott.read_chat"),
        "device": ("smart_home.get_status", "appliances.list", "door_lock.list_locks"),
        "restaurant": ("food_delivery.list_restaurants",),
        "product": ("grocery.search", "ecommerce.search"),
        "book": ("library.search",),
        "course": ("learning.list_courses",),
    },
    "VALUE": {
        "amount": ("bill_payment.list_bills", "ewallet.get_balance", "banking.get_balance", "notes.list"),
        "price": ("gold_price.get_price", "fuel_price.get_price", "stocks.get_quote", "ride_hailing.get_quotes"),
        "balance": ("ewallet.get_balance", "banking.get_balance", "loyalty.get_points"),
        "bill": ("bill_payment.list_bills",),
        "hoá đơn": ("bill_payment.list_bills",),
        "hóa đơn": ("bill_payment.list_bills",),
        "payment": ("ewallet.get_balance", "banking.get_balance"),
        "quantity": ("chat_ott.read_chat", "pantry.list_items", "shopping_list.get", "household_chores.list_chores"),
        "rate": ("exchange_rate.get_rate", "exchange_rate.convert"),
    },
    "FACT": {
        "event": ("calendar.list_events",),
        "appointment": ("calendar.list_events", "reminders.list"),
        "weather": ("weather.get_forecast", "weather.get_current"),
        "rain": ("weather.get_forecast", "weather.get_current"),
        "mưa": ("weather.get_forecast", "weather.get_current"),
        "status": (
            "smart_home.get_status", "robot_vacuum.get_status",
            "package_tracking.track", "ecommerce.order_status",
        ),
        "alert": ("home_security.list_alerts",),
        "note": ("notes.list",),
        "message": ("sms.read_recent", "chat_ott.read_chat", "email.list"),
    },
    "ARGUMENT": {
        "contact": ("contacts.search",),
        "event": ("calendar.list_events",),
        "reminder": ("reminders.list",),
        "alarm": ("alarm.list",),
        "bill": ("bill_payment.list_bills",),
        "device": ("smart_home.get_status",),
        "note": ("notes.list",),
        "task": ("tasks.list",),
    },
}


def tokenize(text: str) -> list[str]:
    """Tokenize Unicode text into alphanumeric word tokens."""
    return _TOKEN_RE.findall(unicodedata.normalize("NFC", text or "").casefold())


def pad_tokens(text: str) -> str:
    """Return space-padded token sequence for exact word/phrase boundary matching."""
    tokens = tokenize(text)
    return f" {' '.join(tokens)} " if tokens else " "


def has_phrase(padded_text: str, phrase: str) -> bool:
    """Check whether a word or multi-word phrase appears on exact token boundaries."""
    clean = " ".join(tokenize(phrase))
    if not clean:
        return False
    return f" {clean} " in padded_text


def has_any_phrase(padded_text: str, phrases: tuple[str, ...] | set[str] | list[str]) -> bool:
    """Check whether any phrase in phrases appears on exact token boundaries in padded_text."""
    return any(has_phrase(padded_text, p) for p in phrases)


def normalize_text(text: str) -> str:
    """Normalize Unicode NFC and lowercase while expanding common dialect terms on word boundaries."""
    norm = unicodedata.normalize("NFC", text or "").casefold()
    padded = pad_tokens(norm)
    extra: list[str] = []
    for src, dst in DIALECT_EXPANSIONS:
        if has_phrase(padded, src):
            extra.append(dst)
    if extra:
        return f"{padded.strip()} {' '.join(extra)}"
    return padded.strip()


def split_self_correction(transcript: str) -> tuple[str, str]:
    """Return (full_normalized_text, post_correction_normalized_text)."""
    norm = normalize_text(transcript)
    raw_lower = unicodedata.normalize("NFC", transcript or "").casefold()
    for marker in SELF_CORRECTION_PATTERNS:
        idx = raw_lower.rfind(marker)
        if idx != -1:
            after = raw_lower[idx + len(marker) :].strip(" ,.;:!-")
            if len(after) >= 3:
                return norm, normalize_text(after)
    return norm, ""


def infer_tool_app(tool: ToolSpec) -> str:
    """Infer app identifier from ToolSpec.app or prefix of ToolSpec.name."""
    if tool.app:
        return tool.app
    return tool.name.split(".", 1)[0] if "." in tool.name else tool.name


def infer_tool_kind(tool: ToolSpec) -> str:
    """Infer whether a tool is read, write, or meta even if ToolSpec.kind is omitted."""
    if tool.kind in ("read", "write", "meta"):
        return tool.kind
    if tool.name == "sys.ask_missing_info":
        return "meta"
    action = tool.name.split(".", 1)[-1].casefold()
    read_prefixes = (
        "get", "list", "search", "read", "find", "check_ticket", "guide", "track",
        "headlines", "calculate", "convert", "translate", "my_bookings", "order_history",
        "order_status", "next_departures", "recent_calls",
    )
    if any(action == p or action.startswith(f"{p}_") for p in read_prefixes):
        return "read"
    return "write"


def build_schema_closure(catalog: list[ToolSpec]) -> dict[str, list[str]]:
    """Dynamically construct prerequisite read-tool closure from catalog schemas and static rules."""
    by_name = {tool.name: tool for tool in catalog}
    read_tools_by_app: dict[str, list[str]] = {}
    for tool in catalog:
        if infer_tool_kind(tool) == "read":
            app = infer_tool_app(tool)
            read_tools_by_app.setdefault(app, []).append(tool.name)

    closure: dict[str, list[str]] = {tool.name: [] for tool in catalog}

    for tool in catalog:
        if tool.name == "sys.ask_missing_info":
            continue
        prereqs: list[str] = []

        # 1. Static known domain prerequisites
        for candidate in STATIC_CLOSURE.get(tool.name, ()):
            if candidate in by_name and candidate not in prereqs:
                prereqs.append(candidate)

        # 2. Dynamic JSON Schema x-ref and parameter inspection
        params = tool.parameters if isinstance(tool.parameters, dict) else {}
        props = params.get("properties", {}) if isinstance(params.get("properties"), dict) else {}
        for pname, pspec in props.items():
            if not isinstance(pspec, dict):
                continue
            xref = pspec.get("x-ref")
            if isinstance(xref, str) and "." in xref:
                target_app, collection = xref.split(".", 1)
                app_reads = read_tools_by_app.get(target_app, [])
                matched_reads = [
                    r for r in app_reads if collection.rstrip("s") in r or collection in r
                ] or app_reads
                for r in matched_reads:
                    if r != tool.name and r not in prereqs:
                        prereqs.append(r)

            # Parameter name heuristics for schemas without explicit x-ref
            pname_low = pname.casefold()
            if pname_low in ("contact_id", "recipient", "recipient_id") and "contacts.search" in by_name:
                if "contacts.search" != tool.name and "contacts.search" not in prereqs:
                    prereqs.append("contacts.search")
            elif pname_low.endswith("_id"):
                app = infer_tool_app(tool)
                for r in read_tools_by_app.get(app, []):
                    if r != tool.name and r not in prereqs:
                        prereqs.append(r)

        # 3. Link app's primary read tools for stateful write operations
        if infer_tool_kind(tool) == "write":
            app = infer_tool_app(tool)
            action = tool.name.split(".", 1)[-1].casefold()
            needs_app_read = any(
                k in action
                for k in (
                    "update", "delete", "cancel", "complete", "remove", "assign",
                    "log", "reply", "archive", "reserve", "book", "play", "tune",
                    "record", "consume", "enroll", "schedule", "check", "set",
                    "start", "stop", "redeem", "checkout", "return", "append",
                )
            )
            if needs_app_read:
                for r in read_tools_by_app.get(app, []):
                    if r not in prereqs:
                        prereqs.append(r)

        closure[tool.name] = prereqs

    return closure


def extract_tool_schema_terms(tool: ToolSpec) -> tuple[str, list[str]]:
    """Extract searchable text and high-value tokens from a ToolSpec's name, description, and parameter schema."""
    parts: list[str] = [
        tool.name.replace(".", " ").replace("_", " "),
        tool.description or "",
    ]
    enum_terms: list[str] = []
    params = tool.parameters if isinstance(tool.parameters, dict) else {}
    props = params.get("properties", {}) if isinstance(params.get("properties"), dict) else {}
    for pname, pspec in props.items():
        parts.append(str(pname).replace("_", " "))
        if isinstance(pspec, dict):
            if pspec.get("description"):
                parts.append(str(pspec["description"]))
            if isinstance(pspec.get("enum"), list):
                for val in pspec["enum"]:
                    enum_terms.append(str(val).casefold())
                    parts.append(str(val))
    searchable = unicodedata.normalize("NFC", " ".join(parts)).casefold()
    return searchable, enum_terms

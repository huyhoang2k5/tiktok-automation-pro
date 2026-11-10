"""
core/logger.py
==============
Structured logger cho TikTok Automation Pro.

Format log: [HH:MM:SS] [ACCOUNT] [TASK] [STATUS] MESSAGE

Quy tắc bảo mật:
- KHÔNG log cookie, token, password, sessionid dù dưới bất kỳ hình thức nào.
- KHÔNG log nội dung request/response body chứa xác thực.
- Chỉ log thông tin hoạt động: username mục tiêu, trạng thái task, thông báo lỗi.
"""

from datetime import datetime
from typing import Callable, List, Optional


# HTML color map dùng trong GUI
_LEVEL_COLORS = {
    "INFO":    "#94a3b8",
    "SUCCESS": "#34d399",
    "WARNING": "#fbbf24",
    "ERROR":   "#f87171",
    "DEBUG":   "#64748b",
}

# Danh sách từ khoá nhạy cảm cần lọc khỏi log
_SENSITIVE_KEYWORDS = [
    "sessionid", "sid_tt", "sid_guard", "ttwid", "tt_csrf_token",
    "cookie", "token", "password", "passwd", "secret", "auth",
]


def _sanitize(msg: str) -> str:
    """
    Lọc bỏ thông tin nhạy cảm trước khi ghi log.
    Nếu message chứa từ khoá nhạy cảm kết hợp với dấu = hoặc :, thay thế giá trị bằng [REDACTED].
    """
    import re
    for kw in _SENSITIVE_KEYWORDS:
        # sessionid=abc123... -> sessionid=[REDACTED]
        msg = re.sub(
            rf"({re.escape(kw)})\s*[=:]\s*\S+",
            rf"\1=[REDACTED]",
            msg,
            flags=re.IGNORECASE
        )
    return msg


class LogRecord:
    """Một bản ghi log đơn lẻ."""
    __slots__ = ("timestamp", "level", "account", "task", "message")

    def __init__(self, level: str, account: str, task: str, message: str):
        self.timestamp = datetime.now().strftime("%H:%M:%S")
        self.level     = level.upper()
        self.account   = account or "-"
        self.task      = task or "-"
        self.message   = _sanitize(message)

    def to_plain(self) -> str:
        """Dạng text thuần: [HH:MM:SS] [ACCOUNT] [TASK] [STATUS] MESSAGE"""
        return f"[{self.timestamp}] [{self.account}] [{self.task}] [{self.level}] {self.message}"

    def to_html(self) -> str:
        """Dạng HTML màu sắc để hiển thị trong QTextEdit."""
        color = _LEVEL_COLORS.get(self.level, "#ffffff")
        ts_html  = f'<span style="color:#475569;">[{self.timestamp}]</span>'
        acc_html = f'<span style="color:#7dd3fc;">[{self.account}]</span>'
        task_html= f'<span style="color:#a78bfa;">[{self.task}]</span>'
        lvl_html = f'<b style="color:{color};">[{self.level}]</b>'
        msg_html = f'<span style="color:#e2e8f0;">{self.message}</span>'
        return f"{ts_html} {acc_html} {task_html} {lvl_html} {msg_html}"


class AutoLogger:
    """
    Logger tập trung với khả năng notify nhiều subscriber (GUI callbacks).

    Cách dùng trong worker:
        logger = AutoLogger(account_label="acc_001")
        logger.connect(lambda rec: self.log_signal.emit(rec.timestamp, rec.level, rec.to_html()))
        logger.info("follow_user", "Bắt đầu xử lý @tiktok")
        logger.success("follow_user", "Follow thành công")
    """

    def __init__(self, account: str = "", task_prefix: str = ""):
        self._account     = account
        self._task_prefix = task_prefix
        self._callbacks:  List[Callable[[LogRecord], None]] = []
        self._records:    List[LogRecord] = []

    def connect(self, callback: Callable[[LogRecord], None]) -> None:
        """Đăng ký callback nhận thông báo khi có log mới."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable[[LogRecord], None]) -> None:
        """Hủy đăng ký callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def set_account(self, account: str) -> None:
        self._account = account

    def _emit(self, level: str, task: str, message: str) -> LogRecord:
        full_task = f"{self._task_prefix}/{task}" if self._task_prefix and task else (task or self._task_prefix or "-")
        rec = LogRecord(level, self._account, full_task, message)
        self._records.append(rec)
        for cb in self._callbacks:
            try:
                cb(rec)
            except Exception:
                pass
        return rec

    def debug(self, task: str, message: str) -> LogRecord:
        return self._emit("DEBUG", task, message)

    def info(self, task: str, message: str) -> LogRecord:
        return self._emit("INFO", task, message)

    def success(self, task: str, message: str) -> LogRecord:
        return self._emit("SUCCESS", task, message)

    def warning(self, task: str, message: str) -> LogRecord:
        return self._emit("WARNING", task, message)

    def error(self, task: str, message: str) -> LogRecord:
        return self._emit("ERROR", task, message)

    def get_records(self, level_filter: Optional[str] = None) -> List[LogRecord]:
        """Lấy danh sách log, có thể lọc theo level."""
        if not level_filter:
            return list(self._records)
        lvl = level_filter.upper()
        return [r for r in self._records if r.level == lvl]

    def clear(self) -> None:
        self._records.clear()


# ── Convenience helper cho workers dùng signal-based emit ──────────────────

def make_worker_log_callback(
    emit_fn: Callable[[str, str, str], None],
    use_html: bool = True
) -> Callable[[LogRecord], None]:
    """
    Tạo callback từ AutoLogger.connect() để bridge sang QThread Signal.

    Args:
        emit_fn: lambda nhận (timestamp, level, message) — khớp với log_signal của workers
        use_html: True → gửi HTML; False → gửi plain text

    Dùng:
        logger.connect(make_worker_log_callback(self.log_signal.emit))
    """
    def _cb(rec: LogRecord):
        msg = rec.to_html() if use_html else rec.to_plain()
        emit_fn(rec.timestamp, rec.level, msg)
    return _cb

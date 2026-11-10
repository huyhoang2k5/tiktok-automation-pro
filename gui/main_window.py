import os
import sys
import json
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QTextEdit, QPushButton, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QSplitter, QGroupBox, QFileDialog, QMessageBox, QInputDialog,
    QTabWidget, QComboBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor

from core.browser_manager import BrowserManager
from core.worker_pool import TikTokAutomationWorker
from core.follow_worker import TikTokFollowWorker
from core.account_parser import parse_accounts_list, TikTokAccount
from gui.styles import DARK_STYLE


class LoginWorker(QThread):
    status_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, browser_manager: BrowserManager, parent=None):
        super().__init__(parent)
        self.browser_manager = browser_manager

    def run(self):
        try:
            ok = self.browser_manager.open_manual_login(
                status_callback=lambda msg: self.status_signal.emit(msg)
            )
            self.finished_signal.emit(ok)
        except Exception as e:
            self.status_signal.emit(f"Lỗi: {str(e)}")
            self.finished_signal.emit(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Automation Pro - Thả Tim Video & Follow Đa Tài Khoản")
        self.resize(1180, 780)
        self.setStyleSheet(DARK_STYLE)

        self.worker = None
        self.follow_worker = None
        self.login_worker = None
        self.browser_manager = BrowserManager()

        # ── Stats counters (cập nhật realtime từ workers) ──
        self._like_stats = {
            "liked_success": 0, "already_liked": 0,
            "blocked_by_tiktok": 0, "errors": 0,
        }
        self._follow_stats = {
            "followed_success": 0, "already_followed": 0,
            "blocked_by_tiktok": 0, "cookie_expired": 0, "errors": 0,
        }

        # ── Log records buffer cho log filter ──
        # Mỗi entry: {"ts": str, "level": str, "msg": str}
        self._log_records: list = []
        self._follow_log_records: list = []

        self._init_ui()
        self._load_config()
        self._check_account_status()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 12, 15, 12)
        main_layout.setSpacing(10)

        # === TOP HEADER ===
        header_layout = QHBoxLayout()
        title_label = QLabel("⚡ TIKTOK AUTOMATION PRO")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00d2ff; letter-spacing: 1px;")

        # Trạng thái tài khoản chính (dùng cho Tab 1 Like)
        self.lbl_auth_status = QLabel("🔴 Chưa đăng nhập")
        self.lbl_auth_status.setStyleSheet(
            "color: #ef4444; font-weight: bold; padding: 5px 12px; border-radius: 5px; background-color: #450a0a; border: 1px solid #dc2626;"
        )

        self.btn_cookie = QPushButton("🍪 Nhập Cookie")
        self.btn_cookie.setToolTip("Dán mã cookie/sessionid từ trình duyệt ngoài để đăng nhập ngay")
        self.btn_cookie.clicked.connect(self._handle_import_cookie)

        self.btn_login = QPushButton("🔑 Mở Chrome đăng nhập")
        self.btn_login.setObjectName("btn_login")
        self.btn_login.setToolTip("Mở Google Chrome thật với tính năng chống chặn để quét mã QR / đăng nhập")
        self.btn_login.clicked.connect(self._handle_manual_login)

        self.btn_check_auth = QPushButton("🔄 Kiểm tra")
        self.btn_check_auth.setToolTip("Làm mới trạng thái đăng nhập")
        self.btn_check_auth.clicked.connect(self._check_account_status)

        self.btn_logout = QPushButton("🚪 Đăng xuất")
        self.btn_logout.setToolTip("Xóa sạch phiên đăng nhập hiện tại để đăng nhập tài khoản khác")
        self.btn_logout.clicked.connect(self._handle_logout)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_auth_status)
        header_layout.addWidget(self.btn_cookie)
        header_layout.addWidget(self.btn_login)
        header_layout.addWidget(self.btn_check_auth)
        header_layout.addWidget(self.btn_logout)
        main_layout.addLayout(header_layout)

        # === TAB WIDGET ===
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget, 1)

        # Tab 1: Thả tim video
        like_widget = self._create_like_tab()
        self.tab_widget.addTab(like_widget, "💖 Tự Động Thả Tim Video (Auto Like)")

        # Tab 2: Follow hàng loạt / chéo acc
        follow_widget = self._create_follow_tab()
        self.tab_widget.addTab(follow_widget, "👥 Follow Hàng Loạt (Multi-Account Follow)")

    # =========================================================================
    # TAB 1: THẢ TIM VIDEO (AUTO LIKE)
    # =========================================================================
    def _create_like_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # --- Cột trái: Nhập liệu & Cài đặt Like ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(10)

        user_group = QGroupBox("Danh sách Username TikTok (Cần tim video)")
        user_layout = QVBoxLayout(user_group)
        self.txt_usernames = QPlainTextEdit()
        self.txt_usernames.setPlaceholderText(
            "Nhập mỗi username trên 1 dòng\n"
            "Ví dụ:\n"
            "@dangquochuy.dev\n"
            "username2\n"
            "https://www.tiktok.com/@username3"
        )
        user_layout.addWidget(self.txt_usernames)

        user_btn_layout = QHBoxLayout()
        btn_import_txt = QPushButton("📂 Nhập từ file .txt")
        btn_import_txt.clicked.connect(self._handle_import_txt)
        btn_clear_users = QPushButton("🗑️ Xóa danh sách")
        btn_clear_users.clicked.connect(self.txt_usernames.clear)
        user_btn_layout.addWidget(btn_import_txt)
        user_btn_layout.addWidget(btn_clear_users)
        user_layout.addLayout(user_btn_layout)
        left_layout.addWidget(user_group, 3)

        config_group = QGroupBox("Cài đặt vận hành Thả Tim")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)

        row_videos = QHBoxLayout()
        lbl_videos = QLabel("Số video cần tim / người:")
        self.spn_videos = QSpinBox()
        self.spn_videos.setRange(1, 200)
        self.spn_videos.setValue(5)
        row_videos.addWidget(lbl_videos)
        row_videos.addWidget(self.spn_videos)
        config_layout.addLayout(row_videos)

        row_concurrency = QHBoxLayout()
        lbl_concurrency = QLabel("Số luồng xử lý cùng lúc:")
        self.spn_concurrency = QSpinBox()
        self.spn_concurrency.setRange(1, 10)
        self.spn_concurrency.setValue(1)
        row_concurrency.addWidget(lbl_concurrency)
        row_concurrency.addWidget(self.spn_concurrency)
        config_layout.addLayout(row_concurrency)

        row_delay = QHBoxLayout()
        lbl_delay = QLabel("Delay giữa các thao tác (giây):")
        self.spn_delay_min = QSpinBox()
        self.spn_delay_min.setRange(1, 300)
        self.spn_delay_min.setValue(5)
        self.spn_delay_min.setPrefix("Min: ")
        self.spn_delay_max = QSpinBox()
        self.spn_delay_max.setRange(1, 300)
        self.spn_delay_max.setValue(10)
        self.spn_delay_max.setPrefix("Max: ")
        row_delay.addWidget(lbl_delay)
        row_delay.addWidget(self.spn_delay_min)
        row_delay.addWidget(self.spn_delay_max)
        config_layout.addLayout(row_delay)

        self.chk_headless = QCheckBox("⚡ Chế độ Request API Siêu Tốc (Chạy ẩn - Không tải video/ảnh)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setStyleSheet("color: #00d2ff; font-weight: bold;")
        config_layout.addWidget(self.chk_headless)
        left_layout.addWidget(config_group, 2)

        ctrl_group = QGroupBox("Điều khiển tiến trình")
        ctrl_layout = QHBoxLayout(ctrl_group)
        self.btn_start = QPushButton("▶ BẮT ĐẦU")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._handle_start)

        self.btn_pause = QPushButton("⏸ TẠM DỪNG")
        self.btn_pause.setObjectName("btn_pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._handle_pause)

        self.btn_stop = QPushButton("⏹ DỪNG LẠI")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._handle_stop)

        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_pause)
        ctrl_layout.addWidget(self.btn_stop)
        left_layout.addWidget(ctrl_group)

        splitter.addWidget(left_widget)

        # --- Cột phải: Bảng & Log Like ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(10)

        progress_box = QHBoxLayout()
        self.lbl_progress = QLabel("Tiến độ: 0 / 0 người")
        self.lbl_progress.setStyleSheet("font-weight: bold; color: #00d2ff;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_box.addWidget(self.lbl_progress)
        progress_box.addWidget(self.progress_bar, 1)
        right_layout.addLayout(progress_box)

        # ── Stats counter bar ──
        self.lbl_like_stats = QLabel("✅ Thành công: 0  |  ⏩ Đã có tim: 0  |  🚫 Bị giới hạn: 0  |  ❌ Lỗi khác: 0")
        self.lbl_like_stats.setStyleSheet(
            "color: #94a3b8; font-size: 11px; padding: 4px 8px; "
            "background-color: #1e293b; border-radius: 4px; border: 1px solid #334155;"
        )
        right_layout.addWidget(self.lbl_like_stats)

        table_group = QGroupBox("Bảng theo dõi tiến trình trực tiếp")
        table_layout = QVBoxLayout(table_group)
        self.table_status = QTableWidget()
        self.table_status.setColumnCount(5)
        self.table_status.setHorizontalHeaderLabels([
            "Thời gian", "Username", "Video ID", "Thao tác", "Trạng thái chi tiết"
        ])
        self.table_status.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_status.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_status.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_status.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_status.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_status.setAlternatingRowColors(True)
        table_layout.addWidget(self.table_status)
        right_layout.addWidget(table_group, 3)

        log_group = QGroupBox("Nhật ký hệ thống (Realtime Logs)")
        log_layout = QVBoxLayout(log_group)

        # Thanh lọc log
        log_filter_row = QHBoxLayout()
        lbl_filter = QLabel("Lọc:")
        lbl_filter.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.cmb_log_filter = QComboBox()
        self.cmb_log_filter.addItems(["Tất cả", "Thành công", "Thất bại / Lỗi", "Đang chạy", "Cảnh báo"])
        self.cmb_log_filter.setStyleSheet(
            "QComboBox { background-color: #1e293b; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
        )
        self.cmb_log_filter.currentIndexChanged.connect(self._apply_like_log_filter)
        log_filter_row.addWidget(lbl_filter)
        log_filter_row.addWidget(self.cmb_log_filter)
        log_filter_row.addStretch()
        log_layout.addLayout(log_filter_row)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #0d0f14; font-family: 'Consolas', monospace;")
        log_layout.addWidget(self.txt_log)

        log_btn_layout = QHBoxLayout()
        btn_clear_log = QPushButton("🧹 Xóa Log & Bảng")
        btn_clear_log.clicked.connect(self._clear_logs_and_table)
        btn_export_log = QPushButton("💾 Xuất file Log")
        btn_export_log.clicked.connect(self._export_log_file)
        log_btn_layout.addStretch()
        log_btn_layout.addWidget(btn_clear_log)
        log_btn_layout.addWidget(btn_export_log)
        log_layout.addLayout(log_btn_layout)
        right_layout.addWidget(log_group, 2)

        splitter.addWidget(right_widget)
        splitter.setSizes([400, 720])
        return container

    # =========================================================================
    # TAB 2: FOLLOW HÀNG LOẠT (MULTI-ACCOUNT FOLLOW)
    # =========================================================================
    def _create_follow_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # --- Cột trái: Nhập danh sách acc & Cấu hình Follow ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(10)

        acc_group = QGroupBox("Danh sách Tài khoản của bạn (Cookie / SessionID)")
        acc_layout = QVBoxLayout(acc_group)
        self.txt_follow_accounts = QPlainTextEdit()
        self.txt_follow_accounts.setPlaceholderText(
            "Nhập mỗi tài khoản trên 1 dòng. Hỗ trợ các định dạng:\n"
            "1. sessionid thuần: 757e930fca5d82098402...\n"
            "2. Chuỗi Cookie: sessionid=xxx; ttwid=yyy; ...\n"
            "3. Định dạng phân cách: user|pass|sessionid\n"
            "4. Định dạng kèm Proxy: sessionid|ip:port:user:pass"
        )
        self.txt_follow_accounts.textChanged.connect(self._update_follow_account_count)
        acc_layout.addWidget(self.txt_follow_accounts)

        acc_btn_layout = QHBoxLayout()
        self.lbl_follow_acc_count = QLabel("Đã nạp: 0 tài khoản")
        self.lbl_follow_acc_count.setStyleSheet("color: #00d2ff; font-weight: bold;")
        btn_import_acc = QPushButton("📂 Nhập từ file .txt")
        btn_import_acc.clicked.connect(self._handle_follow_import_txt)
        btn_clear_acc = QPushButton("🗑️ Xóa")
        btn_clear_acc.clicked.connect(self.txt_follow_accounts.clear)
        acc_btn_layout.addWidget(self.lbl_follow_acc_count)
        acc_btn_layout.addStretch()
        acc_btn_layout.addWidget(btn_import_acc)
        acc_btn_layout.addWidget(btn_clear_acc)
        acc_layout.addLayout(acc_btn_layout)

        lbl_cookie_tip = QLabel("💡 <i>Mẹo nick mượt: Dán trọn bộ Cookie trình duyệt (có ttwid, sid_guard, sessionid...) để TikTok nhận diện thiết bị thật 100%, không bị hỏi Captcha. Nếu chỉ dán sessionid thô, khi có Captcha bạn chỉ cần kéo thanh trượt trên Chrome 1 lần là xong!</i>")
        lbl_cookie_tip.setWordWrap(True)
        lbl_cookie_tip.setStyleSheet("color: #94a3b8; font-size: 11px; padding-top: 4px;")
        acc_layout.addWidget(lbl_cookie_tip)

        left_layout.addWidget(acc_group, 3)

        target_group = QGroupBox("Mục tiêu cần Follow (Target Username)")
        target_layout = QVBoxLayout(target_group)
        self.txt_follow_targets = QPlainTextEdit()
        self.txt_follow_targets.setMaximumHeight(85)
        self.txt_follow_targets.setPlaceholderText(
            "Nhập username TikTok cần nhận follow (mỗi người 1 dòng):\n"
            "@dangquochuy.dev\n"
            "username2"
        )
        target_layout.addWidget(self.txt_follow_targets)

        target_btn_layout = QHBoxLayout()
        btn_import_targets = QPushButton("📂 Nhập target từ file .txt")
        btn_import_targets.clicked.connect(self._handle_follow_import_targets_txt)
        btn_clear_targets = QPushButton("🗑️ Xóa")
        btn_clear_targets.clicked.connect(self.txt_follow_targets.clear)
        target_btn_layout.addStretch()
        target_btn_layout.addWidget(btn_import_targets)
        target_btn_layout.addWidget(btn_clear_targets)
        target_layout.addLayout(target_btn_layout)

        left_layout.addWidget(target_group, 1)

        follow_cfg_group = QGroupBox("Cài đặt vận hành Follow")
        follow_cfg_layout = QVBoxLayout(follow_cfg_group)
        follow_cfg_layout.setSpacing(8)

        row_f_concurrency = QHBoxLayout()
        lbl_f_concurrency = QLabel("Số luồng xử lý cùng lúc:")
        self.spn_follow_concurrency = QSpinBox()
        self.spn_follow_concurrency.setRange(1, 10)
        self.spn_follow_concurrency.setValue(1)
        row_f_concurrency.addWidget(lbl_f_concurrency)
        row_f_concurrency.addWidget(self.spn_follow_concurrency)
        follow_cfg_layout.addLayout(row_f_concurrency)

        row_f_delay = QHBoxLayout()
        lbl_f_delay = QLabel("Delay giữa các tài khoản (giây):")
        self.spn_follow_delay_min = QSpinBox()
        self.spn_follow_delay_min.setRange(1, 300)
        self.spn_follow_delay_min.setValue(8)
        self.spn_follow_delay_min.setPrefix("Min: ")
        self.spn_follow_delay_max = QSpinBox()
        self.spn_follow_delay_max.setRange(1, 300)
        self.spn_follow_delay_max.setValue(15)
        self.spn_follow_delay_max.setPrefix("Max: ")
        row_f_delay.addWidget(lbl_f_delay)
        row_f_delay.addWidget(self.spn_follow_delay_min)
        row_f_delay.addWidget(self.spn_follow_delay_max)
        follow_cfg_layout.addLayout(row_f_delay)

        self.chk_follow_headless = QCheckBox("⚡ Chạy ẩn (Headless - Không hiển thị cửa sổ Chrome)")
        self.chk_follow_headless.setChecked(False)
        self.chk_follow_headless.setStyleSheet("color: #94a3b8; font-weight: normal;")
        follow_cfg_layout.addWidget(self.chk_follow_headless)

        lbl_headless_tip = QLabel("💡 Khuyến nghị: KHÔNG tích chạy ẩn để bạn có thể nhìn thấy và kéo thanh trượt khi TikTok yêu cầu xác minh Captcha (Ghép hình/Xoay vòng).")
        lbl_headless_tip.setWordWrap(True)
        lbl_headless_tip.setStyleSheet("color: #38bdf8; font-size: 11px; padding: 2px 0 6px 0;")
        follow_cfg_layout.addWidget(lbl_headless_tip)
        left_layout.addWidget(follow_cfg_group, 2)

        follow_ctrl_group = QGroupBox("Điều khiển Follow")
        follow_ctrl_layout = QHBoxLayout(follow_ctrl_group)
        self.btn_follow_start = QPushButton("▶ BẮT ĐẦU FOLLOW")
        self.btn_follow_start.setObjectName("btn_start")
        self.btn_follow_start.clicked.connect(self._handle_follow_start)

        self.btn_follow_pause = QPushButton("⏸ TẠM DỪNG")
        self.btn_follow_pause.setObjectName("btn_pause")
        self.btn_follow_pause.setEnabled(False)
        self.btn_follow_pause.clicked.connect(self._handle_follow_pause)

        self.btn_follow_stop = QPushButton("⏹ DỪNG LẠI")
        self.btn_follow_stop.setObjectName("btn_stop")
        self.btn_follow_stop.setEnabled(False)
        self.btn_follow_stop.clicked.connect(self._handle_follow_stop)

        follow_ctrl_layout.addWidget(self.btn_follow_start)
        follow_ctrl_layout.addWidget(self.btn_follow_pause)
        follow_ctrl_layout.addWidget(self.btn_follow_stop)
        left_layout.addWidget(follow_ctrl_group)

        splitter.addWidget(left_widget)

        # --- Cột phải: Bảng & Log Follow ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(10)

        follow_progress_box = QHBoxLayout()
        self.lbl_follow_progress = QLabel("Tiến độ: 0 / 0 tài khoản")
        self.lbl_follow_progress.setStyleSheet("font-weight: bold; color: #00d2ff;")
        self.follow_progress_bar = QProgressBar()
        self.follow_progress_bar.setValue(0)
        follow_progress_box.addWidget(self.lbl_follow_progress)
        follow_progress_box.addWidget(self.follow_progress_bar, 1)
        right_layout.addLayout(follow_progress_box)

        # ── Stats counter bar ──
        self.lbl_follow_stats = QLabel(
            "✅ Follow mới: 0  |  ⏩ Đã follow: 0  |  🚫 Bị block: 0  |  🔑 Cookie lỗi: 0  |  ❌ Lỗi khác: 0"
        )
        self.lbl_follow_stats.setStyleSheet(
            "color: #94a3b8; font-size: 11px; padding: 4px 8px; "
            "background-color: #1e293b; border-radius: 4px; border: 1px solid #334155;"
        )
        right_layout.addWidget(self.lbl_follow_stats)

        follow_table_group = QGroupBox("Bảng theo dõi tiến trình Follow trực tiếp")
        follow_table_layout = QVBoxLayout(follow_table_group)
        self.table_follow_status = QTableWidget()
        self.table_follow_status.setColumnCount(5)
        self.table_follow_status.setHorizontalHeaderLabels([
            "Thời gian", "Tài khoản thực hiện", "Mục tiêu (Target)", "Thao tác", "Trạng thái chi tiết"
        ])
        self.table_follow_status.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_follow_status.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_follow_status.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_follow_status.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_follow_status.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_follow_status.setAlternatingRowColors(True)
        follow_table_layout.addWidget(self.table_follow_status)
        right_layout.addWidget(follow_table_group, 3)

        follow_log_group = QGroupBox("Nhật ký Follow (Realtime Logs)")
        follow_log_layout = QVBoxLayout(follow_log_group)

        # Thanh lọc log Follow
        follow_filter_row = QHBoxLayout()
        lbl_follow_filter = QLabel("Lọc:")
        lbl_follow_filter.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.cmb_follow_log_filter = QComboBox()
        self.cmb_follow_log_filter.addItems(["Tất cả", "Thành công", "Thất bại / Lỗi", "Bị block", "Session lỗi"])
        self.cmb_follow_log_filter.setStyleSheet(
            "QComboBox { background-color: #1e293b; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
        )
        self.cmb_follow_log_filter.currentIndexChanged.connect(self._apply_follow_log_filter)
        follow_filter_row.addWidget(lbl_follow_filter)
        follow_filter_row.addWidget(self.cmb_follow_log_filter)
        follow_filter_row.addStretch()
        follow_log_layout.addLayout(follow_filter_row)

        self.txt_follow_log = QTextEdit()
        self.txt_follow_log.setReadOnly(True)
        self.txt_follow_log.setStyleSheet("background-color: #0d0f14; font-family: 'Consolas', monospace;")
        follow_log_layout.addWidget(self.txt_follow_log)

        follow_log_btn_layout = QHBoxLayout()
        btn_clear_follow_log = QPushButton("🧹 Xóa Log & Bảng")
        btn_clear_follow_log.clicked.connect(self._clear_follow_logs_and_table)
        btn_export_follow_log = QPushButton("💾 Xuất file Log")
        btn_export_follow_log.clicked.connect(self._export_follow_log_file)
        follow_log_btn_layout.addStretch()
        follow_log_btn_layout.addWidget(btn_clear_follow_log)
        follow_log_btn_layout.addWidget(btn_export_follow_log)
        follow_log_layout.addLayout(follow_log_btn_layout)
        right_layout.addWidget(follow_log_group, 2)

        splitter.addWidget(right_widget)
        splitter.setSizes([430, 750])
        return container

    # =========================================================================
    # XỬ LÝ AUTH & ĐĂNG NHẬP
    # =========================================================================
    def _check_account_status(self):
        """Kiểm tra trạng thái đăng nhập nhanh qua SQLite."""
        is_logged = self.browser_manager.check_login_status()
        self._update_auth_ui(is_logged)

    def _update_auth_ui(self, is_logged: bool):
        if is_logged:
            self.lbl_auth_status.setText("🟢 Đã đăng nhập TikTok")
            self.lbl_auth_status.setStyleSheet(
                "color: #10b981; font-weight: bold; padding: 5px 12px; border-radius: 5px; "
                "background-color: #064e3b; border: 1px solid #059669;"
            )
            self._append_log("SUCCESS", "Hệ thống đã nhận diện phiên đăng nhập TikTok thành công!")
        else:
            self.lbl_auth_status.setText("🔴 Chưa đăng nhập")
            self.lbl_auth_status.setStyleSheet(
                "color: #ef4444; font-weight: bold; padding: 5px 12px; border-radius: 5px; "
                "background-color: #450a0a; border: 1px solid #dc2626;"
            )

    def _handle_import_cookie(self):
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Nhập Cookie TikTok",
            "Dán mã Cookie (hoặc sessionid) của bạn vào ô bên dưới:\n"
            "(Hỗ trợ JSON, chuỗi 'sessionid=xxx; ...' hoặc chỉ mã sessionid)"
        )
        if ok and text.strip():
            success, msg = self.browser_manager.import_cookies(text)
            if success:
                QMessageBox.information(self, "Thành công", msg)
                self._check_account_status()
            else:
                QMessageBox.warning(self, "Lỗi Cookie", msg)

    def _handle_logout(self):
        reply = QMessageBox.question(
            self,
            "Xác nhận đăng xuất",
            "Bạn có chắc muốn xóa phiên đăng nhập hiện tại không?\n(Cookie lưu trên máy sẽ được dọn dẹp sạch sẽ)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.browser_manager.clear_session()
            self._check_account_status()
            self._append_log("INFO", "Đã đăng xuất và xóa sạch cookie phiên làm việc cũ.")
            QMessageBox.information(self, "Đã đăng xuất", "Đã xóa phiên đăng nhập cũ thành công! Bây giờ bạn có thể bấm 'Mở Chrome đăng nhập' để quét mã QR mới.")

    def _handle_manual_login(self):
        if self.login_worker and self.login_worker.isRunning():
            QMessageBox.information(self, "Thông báo", "Cửa sổ đăng nhập đang mở, vui lòng thao tác trên Chrome.")
            return

        self._append_log("INFO", "Đang khởi động Google Chrome để bạn quét mã QR đăng nhập...")
        self.btn_login.setEnabled(False)
        self.btn_login.setText("⏳ Đang mở Chrome...")

        self.login_worker = LoginWorker(self.browser_manager)
        self.login_worker.status_signal.connect(lambda msg: self._append_log("INFO", msg))
        self.login_worker.finished_signal.connect(self._on_login_finished)
        self.login_worker.start()

    def _on_login_finished(self, success: bool):
        self.btn_login.setEnabled(True)
        self.btn_login.setText("🔑 Mở Chrome đăng nhập")
        self._check_account_status()
        if success:
            QMessageBox.information(self, "Đăng nhập thành công", "🎉 Phiên đăng nhập TikTok đã được lưu an toàn vào hệ thống!")
        else:
            self._append_log("WARNING", "Cửa sổ Chrome đã đóng mà chưa hoàn tất đăng nhập.")

    # =========================================================================
    # XỬ LÝ TIẾN TRÌNH THẢ TIM (TAB 1)
    # =========================================================================
    def _handle_import_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file danh sách Username", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.txt_usernames.setPlainText(content)
                self._append_log("SUCCESS", f"Đã nạp danh sách từ file: {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi đọc file", f"Không thể đọc file: {str(e)}")

    def _handle_start(self):
        raw_text = self.txt_usernames.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập ít nhất 1 username TikTok!")
            return

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            QMessageBox.warning(self, "Thiếu thông tin", "Không tìm thấy username hợp lệ nào!")
            return

        if not self.browser_manager.check_login_status():
            reply = QMessageBox.question(
                self,
                "Chưa đăng nhập",
                "Hệ thống phát hiện bạn CHƯA đăng nhập TikTok.\n"
                "Bạn có muốn tiếp tục chạy không? (Có thể bị TikTok chặn không cho like)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ TẠM DỪNG")
        self.btn_stop.setEnabled(True)

        self.table_status.setRowCount(0)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText(f"Tiến độ: 0 / {len(lines)} người")

        # Reset stats + log buffer
        self._like_stats = {"liked_success": 0, "already_liked": 0, "blocked_by_tiktok": 0, "errors": 0}
        self._log_records = []
        self._update_like_stats_label()

        self.worker = TikTokAutomationWorker(
            usernames=lines,
            videos_per_user=self.spn_videos.value(),
            concurrency=self.spn_concurrency.value(),
            min_delay=self.spn_delay_min.value(),
            max_delay=self.spn_delay_max.value(),
            headless=self.chk_headless.isChecked(),
        )

        self.worker.log_signal.connect(self._on_worker_log)
        self.worker.status_signal.connect(self._on_worker_status)
        self.worker.progress_signal.connect(self._on_worker_progress)
        self.worker.stats_signal.connect(self._on_like_stats_update)
        self.worker.finished_signal.connect(self._on_worker_finished)

        self.worker.start()
        self._append_log("INFO", f"Khởi động tiến trình xử lý {len(lines)} username...")

    def _handle_pause(self):
        if not self.worker:
            return
        if not self.worker._is_paused:
            self.worker.pause()
            self.btn_pause.setText("▶ TIẾP TỤC")
        else:
            self.worker.resume()
            self.btn_pause.setText("⏸ TẠM DỪNG")

    def _handle_stop(self):
        if not self.worker:
            return
        reply = QMessageBox.question(
            self, "Xác nhận dừng", "Bạn có chắc chắn muốn dừng toàn bộ tiến trình không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_stop.setEnabled(False)
            self.worker.stop()

    def _on_worker_log(self, timestamp: str, level: str, msg: str):
        self._append_log(level, msg, timestamp)

    def _on_worker_status(self, username: str, video_id: str, action: str, status_msg: str, code: str):
        self._add_or_update_table_status(username, video_id, action, status_msg, code)

    def _on_worker_progress(self, current: int, total: int):
        self.lbl_progress.setText(f"Tiến độ: {current} / {total} người")
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)

    def _on_worker_finished(self, stats: dict):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸ TẠM DỪNG")

        if stats.get("status") == "COMPLETED":
            QMessageBox.information(
                self,
                "Hoàn thành",
                f"Quá trình thả tim đã hoàn tất!\n"
                f"- Số người đã xử lý: {stats.get('processed_users', 0)}\n"
                f"- Số video đã thả tim: {stats.get('liked_success', 0)}\n"
                f"- Số video đã tim trước: {stats.get('already_liked', 0)}\n"
                f"- Lỗi: {stats.get('errors', 0)}"
            )
        elif stats.get("status") == "STOPPED":
            QMessageBox.warning(self, "Đã dừng", "Tiến trình đã được dừng lại theo yêu cầu.")

    def _add_or_update_table_status(self, username: str, video_id: str, action: str, status_msg: str, code: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        row = self.table_status.rowCount()
        self.table_status.insertRow(row)

        item_time = QTableWidgetItem(now_str)
        item_user = QTableWidgetItem(f"@{username}")
        item_vid = QTableWidgetItem(video_id)
        item_act = QTableWidgetItem(action)
        item_status = QTableWidgetItem(status_msg)

        color_map = {
            "SUCCESS": QColor("#10b981"),
            "WARNING": QColor("#f59e0b"),
            "ERROR": QColor("#ef4444"),
            "PROCESSING": QColor("#00d2ff"),
            "PENDING": QColor("#94a3b8"),
        }
        color = color_map.get(code, QColor("#e2e8f0"))
        item_status.setForeground(color)

        self.table_status.setItem(row, 0, item_time)
        self.table_status.setItem(row, 1, item_user)
        self.table_status.setItem(row, 2, item_vid)
        self.table_status.setItem(row, 3, item_act)
        self.table_status.setItem(row, 4, item_status)
        self.table_status.scrollToBottom()

    def _append_log(self, level: str, msg: str, ts: str = None):
        if not ts:
            ts = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO":    "#94a3b8",
            "SUCCESS": "#34d399",
            "WARNING": "#fbbf24",
            "ERROR":   "#f87171",
        }
        color = colors.get(level, "#ffffff")
        html_msg = (
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<b style="color:{color};">[{level}]</b> '
            f'<span style="color:#e2e8f0;">{msg}</span>'
        )
        # Lưu vào buffer để filter có thể rebuild
        self._log_records.append({"ts": ts, "level": level, "msg": msg, "html": html_msg})

        # Chỉ hiển thị nếu vượt qua filter hiện tại
        if self._should_show_like_log(level):
            self.txt_log.append(html_msg)

    def _should_show_like_log(self, level: str) -> bool:
        """Kiểm tra xem log entry có vượt qua filter hiện tại không."""
        idx = self.cmb_log_filter.currentIndex() if hasattr(self, "cmb_log_filter") else 0
        if idx == 0:  # Tất cả
            return True
        elif idx == 1:  # Thành công
            return level == "SUCCESS"
        elif idx == 2:  # Thất bại / Lỗi
            return level == "ERROR"
        elif idx == 3:  # Đang chạy
            return level == "INFO"
        elif idx == 4:  # Cảnh báo
            return level == "WARNING"
        return True

    def _apply_like_log_filter(self):
        """Rebuild log display theo filter đã chọn."""
        self.txt_log.clear()
        for rec in self._log_records:
            if self._should_show_like_log(rec["level"]):
                self.txt_log.append(rec["html"])

    def _update_like_stats_label(self):
        s = self._like_stats
        self.lbl_like_stats.setText(
            f"✅ Thành công: {s.get('liked_success', 0)}  |  "
            f"⏩ Đã có tim: {s.get('already_liked', 0)}  |  "
            f"🚫 Bị giới hạn: {s.get('blocked_by_tiktok', 0)}  |  "
            f"❌ Lỗi khác: {s.get('errors', 0)}"
        )

    def _on_like_stats_update(self, stats: dict):
        """Nhận stats realtime từ worker và cập nhật stats bar."""
        self._like_stats.update(stats)
        self._update_like_stats_label()

    def _clear_logs_and_table(self):
        self.txt_log.clear()
        self._log_records = []
        self.table_status.setRowCount(0)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("Tiến độ: 0 / 0 người")
        self._like_stats = {"liked_success": 0, "already_liked": 0, "blocked_by_tiktok": 0, "errors": 0}
        self._update_like_stats_label()

    def _export_log_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Lưu file nhật ký", "tiktok_autolike_log.txt", "Text Files (*.txt)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.txt_log.toPlainText())
                QMessageBox.information(self, "Thành công", f"Đã xuất nhật ký ra {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể xuất file: {str(e)}")

    # =========================================================================
    # XỬ LÝ TIẾN TRÌNH FOLLOW HÀNG LOẠT (TAB 2)
    # =========================================================================
    def _update_follow_account_count(self):
        raw = self.txt_follow_accounts.toPlainText().strip()
        if not raw:
            self.lbl_follow_acc_count.setText("Đã nạp: 0 tài khoản")
            return
        accs = parse_accounts_list(raw)
        self.lbl_follow_acc_count.setText(f"Đã nạp: {len(accs)} tài khoản hợp lệ")

    def _handle_follow_import_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file danh sách tài khoản", "", "Text Files (*.txt);;JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            content = None
            for enc in ["utf-8-sig", "utf-8", "cp1258", "cp1252", "latin1"]:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as ex:
                    QMessageBox.critical(self, "Lỗi đọc file", f"Không thể đọc file: {str(ex)}")
                    return

            if content is None:
                QMessageBox.critical(self, "Lỗi đọc file", "Không thể đọc định dạng mã hóa của file này!")
                return

            self.txt_follow_accounts.setPlainText(content)
            accs = parse_accounts_list(content)
            self._append_follow_log(
                "SUCCESS",
                f"Đã nạp {len(accs)} tài khoản hợp lệ từ file: {os.path.basename(file_path)}"
            )
            self.lbl_follow_acc_count.setText(f"Đã nạp: {len(accs)} tài khoản hợp lệ")

    def _handle_follow_import_targets_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file danh sách mục tiêu (Usernames)", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            content = None
            for enc in ["utf-8-sig", "utf-8", "cp1258", "cp1252", "latin1"]:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as ex:
                    QMessageBox.critical(self, "Lỗi đọc file", f"Không thể đọc file: {str(ex)}")
                    return

            if content is not None:
                self.txt_follow_targets.setPlainText(content)
                lines = [l.strip() for l in content.splitlines() if l.strip()]
                self._append_follow_log(
                    "SUCCESS",
                    f"Đã nạp {len(lines)} username mục tiêu từ file: {os.path.basename(file_path)}"
                )

    def _handle_follow_start(self):
        raw_accs = self.txt_follow_accounts.toPlainText().strip()
        raw_targets = self.txt_follow_targets.toPlainText().strip()

        if not raw_accs:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập danh sách tài khoản (Cookie/sessionid)!")
            return

        accounts = parse_accounts_list(raw_accs)
        if not accounts:
            QMessageBox.warning(self, "Lỗi tài khoản", "Không tìm thấy tài khoản/cookie hợp lệ nào trong danh sách!")
            return

        if not raw_targets:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập ít nhất 1 username mục tiêu cần follow!")
            return

        targets = [line.strip() for line in raw_targets.splitlines() if line.strip()]

        self.btn_follow_start.setEnabled(False)
        self.btn_follow_pause.setEnabled(True)
        self.btn_follow_pause.setText("⏸ TẠM DỪNG")
        self.btn_follow_stop.setEnabled(True)

        self.table_follow_status.setRowCount(0)
        self.follow_progress_bar.setValue(0)
        self.lbl_follow_progress.setText(f"Tiến độ: 0 / {len(accounts)} tài khoản")

        # Reset stats + log buffer
        self._follow_stats = {
            "followed_success": 0, "already_followed": 0,
            "blocked_by_tiktok": 0, "cookie_expired": 0, "errors": 0,
        }
        self._follow_log_records = []
        self._update_follow_stats_label()

        self.follow_worker = TikTokFollowWorker(
            accounts=accounts,
            targets=targets,
            concurrency=self.spn_follow_concurrency.value(),
            min_delay=self.spn_follow_delay_min.value(),
            max_delay=self.spn_follow_delay_max.value(),
            headless=self.chk_follow_headless.isChecked(),
        )

        self.follow_worker.log_signal.connect(self._on_follow_worker_log)
        self.follow_worker.status_signal.connect(self._on_follow_worker_status)
        self.follow_worker.progress_signal.connect(self._on_follow_worker_progress)
        self.follow_worker.stats_signal.connect(self._on_follow_stats_update)
        self.follow_worker.finished_signal.connect(self._on_follow_worker_finished)

        self.follow_worker.start()
        self._append_follow_log(
            "INFO",
            f"Bắt đầu quy trình Follow: {len(accounts)} tài khoản → {len(targets)} mục tiêu. "
            f"Luồng: {self.spn_follow_concurrency.value()}."
        )

    def _handle_follow_pause(self):
        if not self.follow_worker:
            return
        if not self.follow_worker._is_paused:
            self.follow_worker.pause()
            self.btn_follow_pause.setText("▶ TIẾP TỤC")
        else:
            self.follow_worker.resume()
            self.btn_follow_pause.setText("⏸ TẠM DỪNG")

    def _handle_follow_stop(self):
        if not self.follow_worker:
            return
        reply = QMessageBox.question(
            self, "Xác nhận dừng", "Bạn có chắc chắn muốn dừng toàn bộ tiến trình Follow không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_follow_stop.setEnabled(False)
            self.follow_worker.stop()

    def _on_follow_worker_log(self, timestamp: str, level: str, msg: str):
        self._append_follow_log(level, msg, timestamp)

    def _on_follow_worker_status(self, timestamp: str, acc_label: str, target: str, action: str, status_msg: str, code: str):
        row = self.table_follow_status.rowCount()
        self.table_follow_status.insertRow(row)

        item_time = QTableWidgetItem(timestamp)
        item_acc = QTableWidgetItem(acc_label)
        item_target = QTableWidgetItem(target)
        item_act = QTableWidgetItem(action)
        item_status = QTableWidgetItem(status_msg)

        color_map = {
            "SUCCESS": QColor("#10b981"),
            "WARNING": QColor("#f59e0b"),
            "ERROR": QColor("#ef4444"),
            "PROCESSING": QColor("#00d2ff"),
            "PENDING": QColor("#94a3b8"),
        }
        color = color_map.get(code, QColor("#e2e8f0"))
        item_status.setForeground(color)

        self.table_follow_status.setItem(row, 0, item_time)
        self.table_follow_status.setItem(row, 1, item_acc)
        self.table_follow_status.setItem(row, 2, item_target)
        self.table_follow_status.setItem(row, 3, item_act)
        self.table_follow_status.setItem(row, 4, item_status)
        self.table_follow_status.scrollToBottom()

    def _on_follow_worker_progress(self, current: int, total: int):
        self.lbl_follow_progress.setText(f"Tiến độ: {current} / {total} tài khoản")
        if total > 0:
            pct = int((current / total) * 100)
            self.follow_progress_bar.setValue(pct)

    def _on_follow_worker_finished(self, stats: dict):
        self.btn_follow_start.setEnabled(True)
        self.btn_follow_pause.setEnabled(False)
        self.btn_follow_stop.setEnabled(False)
        self.btn_follow_pause.setText("⏸ TẠM DỪNG")

        if stats.get("status") == "COMPLETED":
            QMessageBox.information(
                self,
                "Hoàn thành Follow",
                f"Quá trình Follow hàng loạt đã hoàn tất!\n"
                f"- Số tài khoản đã xử lý: {stats.get('processed_accounts', 0)}\n"
                f"- Follow mới thành công: {stats.get('followed_success', 0)}\n"
                f"- Đã follow từ trước: {stats.get('already_followed', 0)}\n"
                f"- Bị TikTok giới hạn (Action Block): {stats.get('blocked_by_tiktok', 0)}\n"
                f"- Cookie hết hạn/bị thu hồi: {stats.get('cookie_expired', 0)}\n"
                f"- Lỗi kết nối khác: {stats.get('errors', 0)}"
            )
        elif stats.get("status") == "STOPPED":
            QMessageBox.warning(self, "Đã dừng", "Tiến trình Follow đã dừng lại theo yêu cầu.")

    def _append_follow_log(self, level: str, msg: str, ts: str = None):
        if not ts:
            ts = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO":    "#94a3b8",
            "SUCCESS": "#34d399",
            "WARNING": "#fbbf24",
            "ERROR":   "#f87171",
        }
        color = colors.get(level, "#ffffff")
        html_msg = (
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<b style="color:{color};">[{level}]</b> '
            f'<span style="color:#e2e8f0;">{msg}</span>'
        )
        self._follow_log_records.append({"ts": ts, "level": level, "msg": msg, "html": html_msg})

        if self._should_show_follow_log(level, msg):
            self.txt_follow_log.append(html_msg)

    def _should_show_follow_log(self, level: str, msg: str = "") -> bool:
        idx = self.cmb_follow_log_filter.currentIndex() if hasattr(self, "cmb_follow_log_filter") else 0
        if idx == 0:  # Tất cả
            return True
        elif idx == 1:  # Thành công
            return level == "SUCCESS"
        elif idx == 2:  # Thất bại / Lỗi
            return level == "ERROR"
        elif idx == 3:  # Bị block
            return "BLOCKED" in msg.upper() or "block" in msg.lower() or "giới hạn" in msg.lower()
        elif idx == 4:  # Session lỗi
            return "cookie" in msg.lower() or "session" in msg.lower() or "COOKIE_EXPIRED" in msg
        return True

    def _apply_follow_log_filter(self):
        self.txt_follow_log.clear()
        for rec in self._follow_log_records:
            if self._should_show_follow_log(rec["level"], rec["msg"]):
                self.txt_follow_log.append(rec["html"])

    def _update_follow_stats_label(self):
        s = self._follow_stats
        self.lbl_follow_stats.setText(
            f"✅ Follow mới: {s.get('followed_success', 0)}  |  "
            f"⏩ Đã follow: {s.get('already_followed', 0)}  |  "
            f"🚫 Bị block: {s.get('blocked_by_tiktok', 0)}  |  "
            f"🔑 Cookie lỗi: {s.get('cookie_expired', 0)}  |  "
            f"❌ Lỗi khác: {s.get('errors', 0)}"
        )

    def _on_follow_stats_update(self, stats: dict):
        self._follow_stats.update(stats)
        self._update_follow_stats_label()

    def _clear_follow_logs_and_table(self):
        self.txt_follow_log.clear()
        self._follow_log_records = []
        self.table_follow_status.setRowCount(0)
        self.follow_progress_bar.setValue(0)
        self.lbl_follow_progress.setText("Tiến độ: 0 / 0 tài khoản")
        self._follow_stats = {
            "followed_success": 0, "already_followed": 0,
            "blocked_by_tiktok": 0, "cookie_expired": 0, "errors": 0,
        }
        self._update_follow_stats_label()

    def _export_follow_log_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Lưu nhật ký Follow", "tiktok_follow_log.txt", "Text Files (*.txt)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.txt_follow_log.toPlainText())
                QMessageBox.information(self, "Thành công", f"Đã xuất nhật ký Follow ra {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể xuất file: {str(e)}")

    # =========================================================================
    # LƯU & TẢI CẤU HÌNH (CONFIG)
    # =========================================================================
    def _get_config_path(self):
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "config.json")

    def _load_config(self):
        cfg_path = self._get_config_path()
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                # Tab 1 config
                self.spn_videos.setValue(cfg.get("videos_per_user", 5))
                self.spn_concurrency.setValue(cfg.get("concurrency", 1))
                self.spn_delay_min.setValue(cfg.get("min_delay", 5))
                self.spn_delay_max.setValue(cfg.get("max_delay", 10))
                self.chk_headless.setChecked(cfg.get("headless", False))
                recent_users = cfg.get("recent_users", "")
                if recent_users:
                    self.txt_usernames.setPlainText(recent_users)

                # Tab 2 config
                self.spn_follow_concurrency.setValue(cfg.get("follow_concurrency", 1))
                self.spn_follow_delay_min.setValue(cfg.get("follow_min_delay", 5))
                self.spn_follow_delay_max.setValue(cfg.get("follow_max_delay", 10))
                self.chk_follow_headless.setChecked(cfg.get("follow_headless", False))
                recent_targets = cfg.get("recent_targets", "")
                if recent_targets:
                    self.txt_follow_targets.setPlainText(recent_targets)
            except Exception:
                pass

    def _save_config(self):
        cfg_path = self._get_config_path()
        cfg = {
            # Tab 1 config
            "videos_per_user": self.spn_videos.value(),
            "concurrency": self.spn_concurrency.value(),
            "min_delay": self.spn_delay_min.value(),
            "max_delay": self.spn_delay_max.value(),
            "headless": self.chk_headless.isChecked(),
            "recent_users": self.txt_usernames.toPlainText().strip(),

            # Tab 2 config
            "follow_concurrency": self.spn_follow_concurrency.value(),
            "follow_min_delay": self.spn_follow_delay_min.value(),
            "follow_max_delay": self.spn_follow_delay_max.value(),
            "follow_headless": self.chk_follow_headless.isChecked(),
            "recent_targets": self.txt_follow_targets.toPlainText().strip(),
        }
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_config()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        if self.follow_worker and self.follow_worker.isRunning():
            self.follow_worker.stop()
            self.follow_worker.wait(2000)
        event.accept()

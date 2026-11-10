import os
import sys
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Tuple, List, Dict
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright, BrowserContext

DEFAULT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--start-maximized",
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
]

IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def purge_waf_tokens(profile_dir: str):
    """
    Xóa sạch cookie độc hại do tường lửa Akamai của TikTok gài lại để chặn 403.
    """
    cookie_paths = [
        os.path.join(profile_dir, "Default", "Network", "Cookies"),
        os.path.join(profile_dir, "Network", "Cookies")
    ]
    for cp in cookie_paths:
        if os.path.exists(cp):
            try:
                conn = sqlite3.connect(cp)
                conn.execute(
                    "DELETE FROM cookies WHERE name IN ('_waftokenid', 'ak_bmsc', 'bm_sz', 'bm_sv', 'bm_mi')"
                )
                conn.commit()
                conn.close()
            except Exception:
                pass


def get_chrome_channel():
    """Kiểm tra xem Google Chrome hoặc Microsoft Edge chính chủ có tồn tại trên máy không."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            return "chrome"

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
    ]
    for p in edge_paths:
        if os.path.exists(p):
            return "msedge"

    return None


class BrowserManager:
    def __init__(self, profile_dir: str = None):
        if profile_dir is None:
            if getattr(sys, "frozen", False):
                base_dir = Path(sys.executable).resolve().parent
            else:
                base_dir = Path(__file__).resolve().parent.parent
            profile_dir = str(base_dir / "browser_profile")
        self.profile_dir = os.path.abspath(profile_dir)
        os.makedirs(self.profile_dir, exist_ok=True)
        self.channel = get_chrome_channel()

    def check_login_status(self) -> bool:
        """Kiểm tra xem profile hiện tại đã có cookie đăng nhập TikTok (sessionid) hay chưa."""
        # 1. Kiểm tra session_info.json được lưu khi đăng nhập thành công
        info_file = os.path.join(self.profile_dir, "session_info.json")
        if os.path.exists(info_file):
            try:
                with open(info_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("logged_in"):
                        return True
            except Exception:
                pass

        # 2. Kiểm tra database SQLite Cookies của Chrome
        purge_waf_tokens(self.profile_dir)
        cookie_paths = [
            os.path.join(self.profile_dir, "Default", "Network", "Cookies"),
            os.path.join(self.profile_dir, "Network", "Cookies")
        ]
        for cp in cookie_paths:
            if os.path.exists(cp):
                try:
                    temp_db = os.path.join(os.environ.get("TEMP", "."), "temp_chk_cookie.db")
                    shutil.copyfile(cp, temp_db)
                    conn = sqlite3.connect(temp_db)
                    c = conn.cursor()
                    c.execute("SELECT name FROM cookies WHERE name IN ('sessionid', 'sessionid_ss', 'sid_tt')")
                    row = c.fetchone()
                    conn.close()
                    try:
                        os.remove(temp_db)
                    except Exception:
                        pass
                    if row:
                        return True
                except Exception:
                    pass

        # 3. Fallback: Kiểm tra qua Playwright context
        try:
            with sync_playwright() as p:
                kwargs = {
                    "user_data_dir": self.profile_dir,
                    "headless": True,
                    "args": DEFAULT_ARGS,
                    "ignore_default_args": IGNORE_DEFAULT_ARGS,
                    "timeout": 5000
                }
                if self.channel:
                    kwargs["channel"] = self.channel

                context = p.chromium.launch_persistent_context(**kwargs)
                context.clear_cookies(name="_waftokenid")
                cookies = context.cookies()
                context.close()

                has_session = any(
                    c.get("name") in ["sessionid", "sessionid_ss", "sid_tt"]
                    for c in cookies
                )
                if has_session:
                    try:
                        with open(info_file, "w", encoding="utf-8") as f:
                            json.dump({"logged_in": True}, f)
                    except Exception:
                        pass
                return has_session
        except Exception:
            return False

    def import_cookies(self, raw_input: str) -> Tuple[bool, str]:
        raw_input = raw_input.strip()
        if not raw_input:
            return False, "Chuỗi cookie trống!"

        from core.account_parser import extract_cookies_and_session
        parsed_cookies, sessionid = extract_cookies_and_session(raw_input)

        if not parsed_cookies or not sessionid:
            return False, "Không tìm thấy sessionid hợp lệ trong chuỗi cookie đã nhập!"

        try:
            self._kill_profile_processes()
            purge_waf_tokens(self.profile_dir)
            with sync_playwright() as p:
                kwargs = {
                    "user_data_dir": self.profile_dir,
                    "headless": True,
                    "args": DEFAULT_ARGS,
                    "ignore_default_args": IGNORE_DEFAULT_ARGS
                }
                if self.channel:
                    kwargs["channel"] = self.channel

                context = p.chromium.launch_persistent_context(**kwargs)
                context.clear_cookies(name="_waftokenid")

                # Nếu cookie người dùng nhập chưa có ttwid (chỉ có sessionid thô),
                # vào trang Explore như khách để TikTok cấp ttwid cho thiết bị trước!
                has_ttwid = any(c.get("name") == "ttwid" for c in parsed_cookies)
                page = context.new_page()
                if not has_ttwid:
                    try:
                        page.goto("https://www.tiktok.com/explore", wait_until="domcontentloaded", timeout=15000)
                        import time
                        time.sleep(1.5)
                    except Exception:
                        pass

                context.add_cookies(parsed_cookies)

                # Mở trang explore nhẹ để Chromium Network Service flush cookie xuống đĩa
                try:
                    page.goto("https://www.tiktok.com/explore", wait_until="commit", timeout=8000)
                    import time
                    time.sleep(1.0)
                except Exception:
                    pass

                context.close()

            # Ghi nhớ trạng thái phiên làm việc để hiển thị ngay lập tức trên UI
            info_file = os.path.join(self.profile_dir, "session_info.json")
            try:
                with open(info_file, "w", encoding="utf-8") as f:
                    json.dump({"logged_in": True, "sessionid": sessionid[:8] + "..."}, f)
            except Exception:
                pass

            return True, f"Đã lưu thành công {len(parsed_cookies)} cookie vào hệ thống! Tài khoản đã sẵn sàng."
        except Exception as ex:
            return False, f"Lỗi khi lưu cookie vào trình duyệt: {str(ex)}"

    def _kill_profile_processes(self):
        """Đóng mọi tiến trình Chrome đang sử dụng profile_dir này để tránh khóa file."""
        try:
            import psutil
            abs_prof = os.path.abspath(self.profile_dir).lower()
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                        cmdline = proc.info.get('cmdline') or []
                        if any(abs_prof in str(c).lower() for c in cmdline):
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    def clear_session(self) -> bool:
        """
        Xóa sạch toàn bộ cookie và phiên làm việc trong browser_profile để đăng xuất an toàn,
        đưa profile về trạng thái sạch 100% (tránh lỗi TicketGuard, Captcha và xung đột mã QR).
        """
        self._kill_profile_processes()
        import time
        time.sleep(0.5)

        if os.path.exists(self.profile_dir):
            try:
                shutil.rmtree(self.profile_dir, ignore_errors=True)
            except Exception:
                pass

        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir, exist_ok=True)
        else:
            for sub in ["Default", "Network", "Local Storage", "IndexedDB", "Service Worker", "Sessions"]:
                p = os.path.join(self.profile_dir, sub)
                if os.path.exists(p):
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass

        # Xóa file session_info.json
        info_file = os.path.join(self.profile_dir, "session_info.json")
        if os.path.exists(info_file):
            try:
                os.remove(info_file)
            except Exception:
                pass

        return True

    def open_manual_login(self, status_callback=None) -> bool:
        # Nếu chưa có phiên đăng nhập hợp lệ, reset profile để mở Chrome với môi trường sạch 100%
        # Điều này loại bỏ các token lỗi TicketGuard, Captcha cũ và đảm bảo mã QR hoàn toàn mới, quét không bị lỗi.
        if not self.check_login_status():
            self.clear_session()
        else:
            purge_waf_tokens(self.profile_dir)

        with sync_playwright() as p:
            kwargs = {
                "user_data_dir": self.profile_dir,
                "headless": False,
                "args": DEFAULT_ARGS,
                "ignore_default_args": IGNORE_DEFAULT_ARGS,
                "no_viewport": True,
                "locale": "vi-VN"
            }
            if self.channel:
                kwargs["channel"] = self.channel

            context = p.chromium.launch_persistent_context(**kwargs)
            context.clear_cookies(name="_waftokenid")

            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")

            login_success = False

            while True:
                try:
                    if not context.pages or page.is_closed():
                        break

                    curr_url = page.url or ""
                    
                    # 1. Phát hiện chuyển hướng thành công ra khỏi trang login
                    is_redirected = ("/login" not in curr_url) and any(
                        kw in curr_url for kw in ["tiktok.com/@", "tiktok.com/foryou", "tiktok.com/explore", "tiktok.com/following"]
                    )

                    # 2. Phát hiện avatar hoặc icon hồ sơ tài khoản hiển thị trên trang
                    has_avatar = False
                    has_login_btn = True
                    try:
                        avatar_el = page.query_selector('a[data-e2e="profile-icon"], [data-e2e="profile-icon"], header img[class*="Avatar"]')
                        has_avatar = avatar_el is not None
                        login_btn_el = page.query_selector('button[id*="header-login-button"], [data-e2e="top-login-button"]')
                        has_login_btn = login_btn_el is not None
                    except Exception:
                        pass

                    cookies = context.cookies()
                    has_session = any(
                        c.get("name") in ["sessionid", "sessionid_ss", "sid_tt"]
                        for c in cookies
                    )

                    # Khi máy chủ TikTok đã cấp sessionid (hoặc xuất hiện avatar/chuyển trang)
                    if has_session or ((has_avatar and not has_login_btn) or is_redirected):
                        if not login_success:
                            login_success = True
                            if status_callback:
                                status_callback("🎉 ĐÃ ĐĂNG NHẬP THÀNH CÔNG! Đã phát hiện tài khoản trên TikTok.")

                    page.wait_for_timeout(1000)
                except Exception:
                    break

            try:
                context.clear_cookies(name="_waftokenid")
                context.close()
            except Exception:
                pass

            purge_waf_tokens(self.profile_dir)

            if login_success:
                info_file = os.path.join(self.profile_dir, "session_info.json")
                try:
                    with open(info_file, "w", encoding="utf-8") as f:
                        json.dump({"logged_in": True, "type": "qr_manual"}, f)
                except Exception:
                    pass

            return login_success or self.check_login_status()

    async def create_async_context(self, playwright_instance, headless: bool = False) -> BrowserContext:
        """
        Khởi tạo persistent context, tự động triệt tiêu cookie _waftokenid gây lỗi 403
        và vô hiệu hóa bộ đếm thời gian tự động hủy like (rollback timer) của TikTok desktop.
        """
        purge_waf_tokens(self.profile_dir)
        kwargs = {
            "user_data_dir": self.profile_dir,
            "headless": headless,
            "args": DEFAULT_ARGS,
            "ignore_default_args": IGNORE_DEFAULT_ARGS,
            "viewport": {"width": 1280, "height": 850},
            "locale": "vi-VN"
        }
        if self.channel:
            kwargs["channel"] = self.channel

        context = await playwright_instance.chromium.launch_persistent_context(**kwargs)

        # Chống lỗi TikTok desktop web tự động hủy tim sau 3 giây (3000ms rollback timer)
        await context.add_init_script("""
            const origSetTimeout = window.setTimeout;
            window.setTimeout = function(fn, delay, ...args) {
                if (delay === 3000 || delay === 3e3) {
                    const fnStr = typeof fn === 'function' ? fn.toString() : String(fn);
                    if (fnStr.includes('setLike') || fnStr.includes('liked:m')) {
                        return -1;
                    }
                }
                return origSetTimeout.call(this, fn, delay, ...args);
            };
        """)

        return context


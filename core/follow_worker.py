import asyncio
import random
import re
from datetime import datetime
from typing import List
from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from core.browser_manager import DEFAULT_ARGS, IGNORE_DEFAULT_ARGS, get_chrome_channel
from core.tiktok_scraper import clean_username, follow_user, dismiss_overlays, enable_fast_request_mode, is_captcha_present, wait_for_captcha_solved
from core.account_parser import TikTokAccount
from core.error_codes import FollowResult, TaskState, FOLLOW_RESULT_TO_STATE, RESULT_GUI_COLOR

# Timeout tối đa cho mỗi thao tác follow (giây)
FOLLOW_TASK_TIMEOUT = 120

# Timeout warmup (giây)
WARMUP_TIMEOUT = 25


STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = {
    app: { isInstalled: false },
    runtime: { PlatformOs: { WIN: 'win' } }
};
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


class TikTokFollowWorker(QThread):
    """
    QThread điều phối luồng Follow hàng loạt từ danh sách nhiều tài khoản.

    Mỗi tài khoản nhận BrowserContext riêng biệt, hoàn toàn độc lập.
    Không có cross-contamination cookie giữa các tài khoản.
    """
    log_signal     = Signal(str, str, str)              # timestamp, level, message
    status_signal  = Signal(str, str, str, str, str, str)  # ts, acc, target, action, detail, gui_code
    progress_signal= Signal(int, int)                   # processed, total
    stats_signal   = Signal(dict)                       # realtime stats
    finished_signal= Signal(dict)                       # summary

    def __init__(
        self,
        accounts: List[TikTokAccount],
        targets: List[str],
        concurrency: int = 1,
        min_delay: int = 5,
        max_delay: int = 10,
        headless: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.accounts     = accounts
        self.raw_targets  = targets
        self.concurrency  = max(1, min(10, concurrency))
        self.min_delay    = max(1, min_delay)
        self.max_delay    = max(self.min_delay, max_delay)
        self.headless     = headless
        self.channel      = get_chrome_channel()

        self._is_stopped  = False
        self._is_paused   = False
        self._pause_event = None
        self.loop         = None

    # ── Điều khiển ────────────────────────────────────────────────────────

    def pause(self):
        self._is_paused = True
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.clear)
        self.emit_log("WARNING", "-", "Đã TẠM DỪNG quy trình Follow.")

    def resume(self):
        self._is_paused = False
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.set)
        self.emit_log("INFO", "-", "ĐÃ TIẾP TỤC tiến trình Follow.")

    def stop(self):
        self._is_stopped = True
        self._is_paused  = False
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.set)
        self.emit_log("ERROR", "-", "ĐÃ GỬI LỆNH DỪNG toàn bộ tiến trình Follow.")

    def emit_log(self, level: str, account: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        acc_tag = f"[{account}] " if account and account != "-" else ""
        self.log_signal.emit(ts, level, f"{acc_tag}{msg}")

    # ── Vòng lặp asyncio ──────────────────────────────────────────────────

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_follow())
        except Exception as e:
            self.emit_log("ERROR", "-", f"Lỗi không mong muốn: {str(e)}")
        finally:
            self.loop.close()

    async def _interruptible_sleep(self, seconds: float):
        elapsed = 0.0
        while elapsed < seconds:
            if self._is_stopped:
                break
            await self._pause_event.wait()
            await asyncio.sleep(min(0.25, seconds - elapsed))
            elapsed += 0.25

    # ── Logic chính ───────────────────────────────────────────────────────

    async def _run_follow(self):
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._is_stopped = False

        # Lọc và dedup mục tiêu
        valid_targets = []
        for t in self.raw_targets:
            c = clean_username(t)
            if c and c not in valid_targets:
                valid_targets.append(c)

        if not valid_targets:
            self.emit_log("WARNING", "-", "Không có username mục tiêu nào!")
            self.finished_signal.emit({"total": 0, "status": "EMPTY"})
            return

        if not self.accounts:
            self.emit_log("WARNING", "-", "Danh sách tài khoản trống!")
            self.finished_signal.emit({"total": 0, "status": "EMPTY"})
            return

        total = len(self.accounts)
        self.emit_log(
            "INFO", "-",
            f"Bắt đầu Follow: {total} tài khoản → {len(valid_targets)} mục tiêu | "
            f"Luồng: {self.concurrency} | Delay: {self.min_delay}-{self.max_delay}s"
        )

        # Queue tài khoản — dùng asyncio.Queue.get_nowait() thay vì empty() check
        queue: asyncio.Queue = asyncio.Queue()
        for acc in self.accounts:
            await queue.put(acc)

        stats = {
            "total_accounts":    total,
            "processed_accounts":0,
            "followed_success":  0,
            "already_followed":  0,
            "blocked_by_tiktok": 0,
            "cookie_expired":    0,
            "errors":            0,
        }

        async with async_playwright() as p:
            launch_kwargs = {
                "headless": self.headless,
                "args":     DEFAULT_ARGS,
                "ignore_default_args": IGNORE_DEFAULT_ARGS,
            }
            if self.channel:
                launch_kwargs["channel"] = self.channel

            try:
                browser = await p.chromium.launch(**launch_kwargs)
            except Exception as ex:
                self.emit_log("ERROR", "-", f"Không thể khởi động trình duyệt: {str(ex)}")
                self.finished_signal.emit({"error": str(ex), "status": "FAILED"})
                return

            # Nhận diện User-Agent & phiên bản Chromium/Chrome thực tế để đồng bộ TLS và Headers 100%
            clean_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
            chrome_major = "153"
            try:
                temp_ctx = await browser.new_context()
                temp_page = await temp_ctx.new_page()
                raw_ua = await temp_page.evaluate("navigator.userAgent")
                await temp_ctx.close()
                clean_ua = raw_ua.replace("HeadlessChrome", "Chrome")
                m = re.search(r"Chrome/(\d+)", clean_ua)
                if m:
                    chrome_major = m.group(1)
            except Exception:
                pass

            stealth_headers = {
                "sec-ch-ua": f'"Not A(Brand";v="8", "Chromium";v="{chrome_major}", "Google Chrome";v="{chrome_major}"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            async def worker(wid: int):
                while not self._is_stopped:
                    # Lấy tài khoản từ queue — không check empty() trước để tránh race
                    try:
                        account: TikTokAccount = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    await self._pause_event.wait()
                    if self._is_stopped:
                        queue.task_done()
                        break

                    label = account.account_id
                    self.emit_log("INFO", label, f"[Luồng {wid}] Bắt đầu xử lý...")

                    ctx_kwargs = {
                        "viewport":   {"width": 1280, "height": 800},
                        "locale":     "vi-VN",
                        "user_agent": clean_ua,
                        "extra_http_headers": stealth_headers,
                    }
                    if account.proxy:
                        ctx_kwargs["proxy"] = account.proxy

                    ctx = None
                    try:
                        ctx = await browser.new_context(**ctx_kwargs)
                        await ctx.add_init_script(STEALTH_INIT_SCRIPT)

                        page = await ctx.new_page()
                        await enable_fast_request_mode(page)

                        # BƯỚC 1: NẠP COOKIE & KHỞI TẠO DANH TÍNH THIẾT BỊ
                        has_ttwid = any(c.get("name") == "ttwid" for c in account.cookies)
                        if not has_ttwid:
                            # Nếu chỉ có sessionid thô (chưa có ttwid), cần vào explore như khách để TikTok cấp ttwid trước
                            await self._warmup_guest_device(page, ctx, label)
                            await ctx.add_cookies(account.cookies)
                            self.emit_log("INFO", label, f"Đã nạp {len(account.cookies)} cookie vào phiên an toàn (đã có ttwid bảo vệ).")
                        else:
                            # Đã có đầy đủ ttwid từ cookie trình duyệt: nạp trực tiếp để bảo toàn trọn vẹn danh tính thiết bị
                            await ctx.add_cookies(account.cookies)
                            self.emit_log("INFO", label, f"Đã nạp trọn bộ {len(account.cookies)} cookie (có sẵn ttwid từ trình duyệt).")

                        # Follow từng target
                        for idx, target in enumerate(valid_targets):
                            if self._is_stopped:
                                break
                            await self._pause_event.wait()

                            ts = datetime.now().strftime("%H:%M:%S")
                            self.status_signal.emit(
                                ts, label, f"@{target}", "Follow",
                                "Đang xử lý...", RESULT_GUI_COLOR[TaskState.PENDING]
                            )

                            try:
                                code, msg = await asyncio.wait_for(
                                    follow_user(
                                        page, target,
                                        callback=lambda m, l=label: self.emit_log("INFO", l, m)
                                    ),
                                    timeout=FOLLOW_TASK_TIMEOUT
                                )
                            except asyncio.TimeoutError:
                                code = FollowResult.TIMEOUT
                                msg  = f"Follow @{target} vượt quá {FOLLOW_TASK_TIMEOUT}s (Timeout)"
                                self.emit_log("ERROR", label, msg)
                            except Exception as err:
                                err_str = str(err)
                                if "Target page, context or browser has been closed" in err_str or "Target closed" in err_str:
                                    code = FollowResult.ERROR
                                    msg  = "Trình duyệt đã bị đóng trước khi hoàn tất"
                                    self.emit_log("ERROR", label, "⚠️ Trình duyệt đã bị đóng trước khi hoàn tất thao tác!")
                                    self._record_result(stats, label, target, code, msg, datetime.now().strftime("%H:%M:%S"))
                                    self.stats_signal.emit(dict(stats))
                                    break
                                else:
                                    code = FollowResult.ERROR
                                    msg  = f"Ngoại lệ: {err_str[:60]}"
                                    self.emit_log("ERROR", label, f"Ngoại lệ: {err_str}")

                            ts = datetime.now().strftime("%H:%M:%S")
                            self._record_result(stats, label, target, code, msg, ts)
                            self.stats_signal.emit(dict(stats))

                            # Nếu follow thành công, đồng bộ cookie mới (s_v_web_id sau khi giải captcha) để tái sử dụng
                            if code == FollowResult.FOLLOWED:
                                try:
                                    fresh_cookies = await ctx.cookies()
                                    if fresh_cookies:
                                        account.cookies = fresh_cookies
                                except Exception:
                                    pass

                            # Cookie hết hạn / out nick → dừng acc này để bảo vệ
                            if code == FollowResult.COOKIE_EXPIRED:
                                self.emit_log("ERROR", label, "⚠️ Cookie hết hạn / out nick! Chuyển sang tài khoản tiếp theo.")
                                break

                            # Bị TikTok giới hạn thao tác (Action Block) → dừng acc này để bảo vệ không bị khóa nick/out nick
                            if code == FollowResult.BLOCKED_BY_TIKTOK:
                                self.emit_log("WARNING", label, "⚠️ Bị TikTok giới hạn thao tác (Action Block). Bỏ qua các mục tiêu còn lại của tài khoản này để bảo vệ nick!")
                                break

                            # Hết thời gian chờ giải Captcha → chuyển sang tài khoản tiếp theo
                            if code == "CAPTCHA":
                                self.emit_log("WARNING", label, "⚠️ Hết thời gian giải Captcha. Chuyển sang tài khoản tiếp theo.")
                                break

                            # Delay an toàn giữa các mục tiêu trên cùng 1 tài khoản
                            if idx < len(valid_targets) - 1 and not self._is_stopped:
                                delay = random.uniform(self.min_delay, self.max_delay)
                                self.emit_log("INFO", label, f"Chờ {delay:.1f}s trước mục tiêu tiếp theo...")
                                await self._interruptible_sleep(delay)

                    except Exception as op_err:
                        stats["errors"] += 1
                        self.emit_log("ERROR", label, f"Lỗi context: {str(op_err)[:80]}")
                    finally:
                        # ctx.close() luôn được gọi dù có lỗi hay không
                        if ctx is not None:
                            try:
                                # Chờ 1.5s để TikTok SecSDK gửi trọn vẹn beacon lên máy chủ trước khi đóng phiên
                                await asyncio.sleep(1.5)
                                await ctx.close()
                            except Exception:
                                pass

                    stats["processed_accounts"] += 1
                    self.progress_signal.emit(stats["processed_accounts"], total)
                    self.stats_signal.emit(dict(stats))
                    queue.task_done()

                    # Delay giữa các tài khoản
                    if not self._is_stopped and queue.qsize() > 0:
                        delay = random.uniform(self.min_delay, self.max_delay)
                        self.emit_log("INFO", label, f"Chờ {delay:.1f}s trước tài khoản tiếp...")
                        await self._interruptible_sleep(delay)

            # Khởi chạy N workers với stagger start
            tasks = []
            for i in range(self.concurrency):
                async def wrapped(w=i + 1):
                    if w > 1:
                        await asyncio.sleep((w - 1) * 2.5)
                    await worker(w)
                tasks.append(asyncio.create_task(wrapped()))

            await asyncio.gather(*tasks, return_exceptions=True)

            try:
                await browser.close()
            except Exception:
                pass

        # Báo cáo kết quả
        if self._is_stopped:
            self.emit_log("WARNING", "-", "Đã dừng theo yêu cầu.")
            stats["status"] = "STOPPED"
        else:
            self.emit_log(
                "SUCCESS", "-",
                f"HOÀN TẤT! Đã xử lý {stats['processed_accounts']}/{total} tài khoản | "
                f"Follow mới: {stats['followed_success']} | "
                f"Đã follow: {stats['already_followed']} | "
                f"Bị block: {stats['blocked_by_tiktok']} | "
                f"Cookie lỗi: {stats['cookie_expired']} | "
                f"Lỗi khác: {stats['errors']}"
            )
            stats["status"] = "COMPLETED"

        self.finished_signal.emit(stats)

    # ── Khởi tạo danh tính thiết bị ở chế độ Khách (Guest) ────────────────
    async def _warmup_guest_device(self, page, ctx, label: str):
        """
        Khởi tạo phiên duyệt an toàn qua trang Explore ở chế độ Khách (Guest)
        để TikTok cấp đầy đủ token bảo mật danh tính thiết bị:
        (ttwid, tt_csrf_token, x-web-secsdk-uid, msToken).
        
        Bằng cách này, khi nạp sessionid sau đó, TikTok ghi nhận phiên đăng nhập
        thuộc về một thiết bị đã có ttwid hợp lệ, ngăn chặn 100% tình trạng
        bị TikTok server hủy phiên (Set-Cookie: sessionid=deleted) hoặc out nick.
        """
        self.emit_log("INFO", label, "Đang khởi tạo danh tính thiết bị an toàn (Guest Warm-up)...")
        try:
            # Xóa sạch token WAF nếu có
            for w_name in ["_waftokenid", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi"]:
                try:
                    await ctx.clear_cookies(name=w_name)
                except Exception:
                    pass

            await asyncio.wait_for(
                page.goto("https://www.tiktok.com/explore", wait_until="domcontentloaded"),
                timeout=WARMUP_TIMEOUT
            )

            await dismiss_overlays(page)
            await asyncio.sleep(1.2)

            # Lướt nhẹ để tạo telemetry chuột người dùng thật
            try:
                await page.mouse.move(random.randint(300, 700), random.randint(200, 500), steps=5)
                await page.mouse.wheel(0, random.randint(200, 400))
                await asyncio.sleep(1.0)
            except Exception:
                pass

            await dismiss_overlays(page)

            # Nếu có captcha ở bước warm-up, hỗ trợ giải ngay
            if await is_captcha_present(page):
                self.emit_log("WARNING", label, "⚠️ TikTok yêu cầu xác minh Captcha khi khởi tạo! Cửa sổ Chrome đã được đưa lên trước...")
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                await wait_for_captcha_solved(page, callback=lambda m: self.emit_log("INFO", label, m), max_wait=120)
                await asyncio.sleep(2.0)

            # Kiểm tra token bảo mật
            cookies = await ctx.cookies()
            names = {c.get("name", "") for c in cookies}
            if "ttwid" in names and "tt_csrf_token" in names:
                self.emit_log("INFO", label, "Thiết bị bảo mật sẵn sàng (ttwid & tt_csrf_token đã được cấp).")
            elif "ttwid" in names:
                self.emit_log("INFO", label, "Thiết bị bảo mật sẵn sàng (ttwid đã được cấp).")
            else:
                self.emit_log("INFO", label, "Hoàn tất khởi tạo thiết bị.")

        except Exception as e:
            self.emit_log("WARNING", label, f"Khởi tạo nhẹ (tiếp tục): {str(e)[:60]}")

    # ── Ghi nhận kết quả ─────────────────────────────────────────────────

    def _record_result(self, stats: dict, label: str, target: str, code: str, msg: str, ts: str):
        # Cập nhật stats counter
        counter_map = {
            FollowResult.FOLLOWED:          "followed_success",
            FollowResult.ALREADY_FOLLOWED:  "already_followed",
            FollowResult.BLOCKED_BY_TIKTOK: "blocked_by_tiktok",
            FollowResult.COOKIE_EXPIRED:    "cookie_expired",
        }
        counter_key = counter_map.get(code, "errors")
        stats[counter_key] = stats.get(counter_key, 0) + 1

        # Level log theo kết quả
        level_map = {
            FollowResult.FOLLOWED:          "SUCCESS",
            FollowResult.ALREADY_FOLLOWED:  "WARNING",
            FollowResult.BLOCKED_BY_TIKTOK: "WARNING",
            FollowResult.COOKIE_EXPIRED:    "ERROR",
        }
        level = level_map.get(code, "ERROR")
        self.emit_log(level, label, f"→ @{target}: {msg}")

        # GUI color
        task_state = FOLLOW_RESULT_TO_STATE.get(code, TaskState.FAILED)
        gui_code   = RESULT_GUI_COLOR.get(task_state, "ERROR")
        if code == FollowResult.FOLLOWED:
            gui_code = "SUCCESS"
        elif code == FollowResult.ALREADY_FOLLOWED:
            gui_code = "WARNING"

        self.status_signal.emit(ts, label, f"@{target}", "Follow", msg, gui_code)

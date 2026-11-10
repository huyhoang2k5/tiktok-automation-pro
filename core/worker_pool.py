import asyncio
import random
from datetime import datetime
from typing import List
from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from core.browser_manager import BrowserManager
from core.tiktok_scraper import clean_username, get_user_videos, like_video, enable_fast_request_mode
from core.error_codes import LikeResult, TaskState, LIKE_RESULT_TO_STATE, RESULT_GUI_COLOR

# Timeout tối đa cho mỗi thao tác like (giây)
LIKE_TASK_TIMEOUT = 90


class TikTokAutomationWorker(QThread):
    # Signals truyền dữ liệu an toàn sang giao diện PySide6
    log_signal     = Signal(str, str, str)       # timestamp, level, message
    status_signal  = Signal(str, str, str, str, str)  # username, video_id, action, status_msg, gui_code
    progress_signal= Signal(int, int)            # processed_count, total_count
    stats_signal   = Signal(dict)                # realtime stats dict
    finished_signal= Signal(dict)                # summary dictionary

    def __init__(
        self,
        usernames: List[str],
        videos_per_user: int = 5,
        concurrency: int = 2,
        min_delay: int = 5,
        max_delay: int = 10,
        headless: bool = True,
        profile_dir: str = None,
        parent=None,
    ):
        super().__init__(parent)
        self.raw_usernames   = usernames
        self.videos_per_user = max(1, videos_per_user)
        self.concurrency     = max(1, min(10, concurrency))
        self.min_delay       = max(1, min_delay)
        self.max_delay       = max(self.min_delay, max_delay)
        self.headless        = headless
        self.browser_manager = BrowserManager(profile_dir)

        self._is_stopped = False
        self._is_paused  = False
        self._pause_event = None
        self.loop = None

    # ── Điều khiển ────────────────────────────────────────────────────────

    def pause(self):
        self._is_paused = True
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.clear)
        self.emit_log("WARNING", "-", "Đã bấm TẠM DỪNG. Các tác vụ đang chờ...")

    def resume(self):
        self._is_paused = False
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.set)
        self.emit_log("INFO", "-", "ĐÃ TIẾP TỤC tiến trình.")

    def stop(self):
        self._is_stopped = True
        self._is_paused  = False
        if self._pause_event and self.loop:
            self.loop.call_soon_threadsafe(self._pause_event.set)
        self.emit_log("ERROR", "-", "ĐÃ GỬI LỆNH DỪNG toàn bộ tiến trình.")

    def emit_log(self, level: str, account: str, msg: str):
        now = datetime.now().strftime("%H:%M:%S")
        acc_tag = f"[{account}] " if account and account != "-" else ""
        self.log_signal.emit(now, level, f"{acc_tag}{msg}")

    # ── Vòng lặp asyncio ──────────────────────────────────────────────────

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_automation())
        except Exception as e:
            self.emit_log("ERROR", "-", f"Lỗi không mong muốn trong worker: {str(e)}")
        finally:
            self.loop.close()

    async def _interruptible_sleep(self, seconds: float):
        step = 0.25
        elapsed = 0.0
        while elapsed < seconds:
            if self._is_stopped:
                break
            await self._pause_event.wait()
            await asyncio.sleep(min(step, seconds - elapsed))
            elapsed += step

    # ── Logic chính ───────────────────────────────────────────────────────

    async def _run_automation(self):
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._is_stopped = False
        self._is_paused  = False

        # Làm sạch và dedup danh sách username
        valid_users = []
        for u in self.raw_usernames:
            cleaned = clean_username(u)
            if cleaned and cleaned not in valid_users:
                valid_users.append(cleaned)

        if not valid_users:
            self.emit_log("WARNING", "-", "Không có username hợp lệ nào để xử lý!")
            self.finished_signal.emit({"total_users": 0, "liked": 0, "status": "EMPTY"})
            return

        total_users_count = len(valid_users)
        self.emit_log(
            "INFO", "-",
            f"Bắt đầu xử lý {total_users_count} username | "
            f"Luồng: {self.concurrency} | "
            f"Delay: {self.min_delay}-{self.max_delay}s"
        )

        # Dùng asyncio.Queue thay cho list check → tránh race condition
        queue: asyncio.Queue = asyncio.Queue()
        for u in valid_users:
            await queue.put(u)

        stats = {
            "total_users":        total_users_count,
            "processed_users":    0,
            "total_videos_checked": 0,
            "liked_success":      0,
            "already_liked":      0,
            "blocked_by_tiktok":  0,
            "errors":             0,
        }

        async with async_playwright() as p:
            try:
                context = await self.browser_manager.create_async_context(
                    p, headless=self.headless
                )
            except Exception as e:
                self.emit_log("ERROR", "-", f"Không thể khởi động trình duyệt: {str(e)}")
                self.finished_signal.emit({"error": str(e), "status": "FAILED"})
                return

            async def worker_task(worker_id: int):
                # Tái sử dụng tab đầu tiên nếu có để tránh mở thêm tab about:blank thừa
                if worker_id == 1 and context.pages:
                    page = context.pages[0]
                    for extra in context.pages[1:]:
                        try:
                            await extra.close()
                        except Exception:
                            pass
                else:
                    page = await context.new_page()

                await enable_fast_request_mode(page)
                try:
                    while not self._is_stopped:
                        # Lấy task từ queue — không dùng empty() check để tránh race
                        try:
                            username = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        await self._pause_event.wait()
                        if self._is_stopped:
                            queue.task_done()
                            break

                        self.emit_log("INFO", username, f"[Luồng {worker_id}] Bắt đầu xử lý...")
                        self.status_signal.emit(
                            username, "-", "Tìm kiếm video",
                            "Đang quét danh sách...", "PENDING"
                        )

                        # ── OPENING: Lấy danh sách video ──
                        self.status_signal.emit(
                            username, "-", "Điều hướng profile",
                            "Đang mở trang cá nhân...", RESULT_GUI_COLOR[TaskState.OPENING]
                        )
                        video_urls = await get_user_videos(
                            page, username, self.videos_per_user,
                            callback=lambda m, u=username: self.emit_log("WARNING", u, m)
                        )

                        if self._is_stopped:
                            queue.task_done()
                            break

                        if not video_urls:
                            self.emit_log(
                                "WARNING", username,
                                "Không tìm thấy video công khai (hoặc tài khoản riêng tư / Captcha chặn)"
                            )
                            self.status_signal.emit(
                                username, "-", "Quét video",
                                "Không có video hoặc tài khoản riêng tư", "WARNING"
                            )
                            stats["processed_users"] += 1
                            self.progress_signal.emit(stats["processed_users"], total_users_count)
                            self.stats_signal.emit(dict(stats))
                            queue.task_done()
                            continue

                        self.emit_log("INFO", username, f"Tìm thấy {len(video_urls)} video. Bắt đầu thả tim...")

                        # ── PROCESSING: Like từng video ──
                        for idx, v_url in enumerate(video_urls, start=1):
                            if self._is_stopped:
                                break
                            await self._pause_event.wait()

                            v_id = v_url.split("/video/")[-1].split("?")[0] if "/video/" in v_url else v_url[-12:]
                            self.status_signal.emit(
                                username, v_id,
                                f"Video {idx}/{len(video_urls)}",
                                "Đang mở video...",
                                RESULT_GUI_COLOR[TaskState.OPENING]
                            )

                            # Wrap với timeout để tránh hang vô hạn
                            try:
                                status_code, msg = await asyncio.wait_for(
                                    like_video(
                                        page, v_url, username=username,
                                        callback=lambda m, u=username: self.emit_log("INFO", u, m)
                                    ),
                                    timeout=LIKE_TASK_TIMEOUT
                                )
                            except asyncio.TimeoutError:
                                status_code = LikeResult.TIMEOUT
                                msg = f"Thả tim video {v_id} vượt quá {LIKE_TASK_TIMEOUT}s (Timeout)"
                                self.emit_log("ERROR", username, msg)
                            except Exception as ex:
                                status_code = LikeResult.ERROR
                                msg = f"Ngoại lệ: {str(ex)[:80]}"
                                self.emit_log("ERROR", username, f"Ngoại lệ khi like: {str(ex)}")

                            stats["total_videos_checked"] += 1
                            task_state = LIKE_RESULT_TO_STATE.get(status_code, TaskState.FAILED)
                            gui_code   = RESULT_GUI_COLOR.get(task_state, "ERROR")

                            # Cập nhật stats theo kết quả
                            if status_code == LikeResult.LIKED:
                                stats["liked_success"] += 1
                                self.emit_log("SUCCESS", username, f"[{idx}/{len(video_urls)}] {msg}")
                            elif status_code == LikeResult.ALREADY_LIKED:
                                stats["already_liked"] += 1
                                self.emit_log("WARNING", username, f"[{idx}/{len(video_urls)}] {msg}")
                            elif status_code == LikeResult.BLOCKED_BY_TIKTOK:
                                stats["blocked_by_tiktok"] = stats.get("blocked_by_tiktok", 0) + 1
                                stats["errors"] += 1
                                self.emit_log("ERROR", username, f"[{idx}/{len(video_urls)}] {msg}")
                            elif status_code == LikeResult.NOT_LOGGED_IN:
                                stats["errors"] += 1
                                self.emit_log("ERROR", username, msg)
                                self.status_signal.emit(username, v_id, "Thả tim", msg, "ERROR")
                                self.stats_signal.emit(dict(stats))
                                # Dừng toàn bộ — không có session thì không làm gì được
                                self.stop()
                                queue.task_done()
                                return
                            else:
                                stats["errors"] += 1
                                self.emit_log("ERROR", username, f"[{idx}/{len(video_urls)}] {msg}")

                            self.status_signal.emit(username, v_id, "Thả tim", msg, gui_code)
                            self.stats_signal.emit(dict(stats))

                            # Delay giữa các video (không delay sau video cuối)
                            if not self._is_stopped and idx < len(video_urls):
                                delay = random.uniform(self.min_delay, self.max_delay)
                                self.emit_log("INFO", username, f"Chờ {delay:.1f}s...")
                                await self._interruptible_sleep(delay)

                        stats["processed_users"] += 1
                        self.progress_signal.emit(stats["processed_users"], total_users_count)
                        self.stats_signal.emit(dict(stats))
                        queue.task_done()

                        # Delay giữa các username
                        if not self._is_stopped and queue.qsize() > 0:
                            delay = random.uniform(self.min_delay, self.max_delay)
                            await self._interruptible_sleep(delay)

                except Exception as ex:
                    self.emit_log("ERROR", f"luong_{worker_id}", f"Lỗi: {str(ex)}")
                finally:
                    await page.close()

            async def worker_task_wrapper(worker_id: int):
                # Stagger start để tránh tất cả workers cùng tấn công WAF một lúc
                if worker_id > 1:
                    await asyncio.sleep((worker_id - 1) * 2.0)
                await worker_task(worker_id)

            tasks = [asyncio.create_task(worker_task_wrapper(i + 1)) for i in range(self.concurrency)]
            await asyncio.gather(*tasks, return_exceptions=True)

            try:
                await context.close()
            except Exception:
                pass

        if self._is_stopped:
            self.emit_log("WARNING", "-", "Quá trình đã dừng lại theo yêu cầu.")
            stats["status"] = "STOPPED"
        else:
            self.emit_log(
                "SUCCESS", "-",
                f"HOÀN TẤT! Xử lý {stats['processed_users']}/{total_users_count} users | "
                f"Thả tim mới: {stats['liked_success']} | "
                f"Đã có tim: {stats['already_liked']} | "
                f"Bị giới hạn: {stats.get('blocked_by_tiktok', 0)} | "
                f"Lỗi khác: {stats['errors']}"
            )
            stats["status"] = "COMPLETED"

        self.finished_signal.emit(stats)

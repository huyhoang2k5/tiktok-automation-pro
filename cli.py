import argparse
import sys
import os
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.browser_manager import BrowserManager
from core.tiktok_scraper import clean_username, get_user_videos, like_video
from playwright.async_api import async_playwright
import random


async def run_cli(usernames, videos_per_user, concurrency, min_delay, max_delay, headless):
    bm = BrowserManager()
    valid_users = [clean_username(u) for u in usernames if clean_username(u)]
    if not valid_users:
        print("[ERROR] Không có username hợp lệ!")
        return

    print(f"[*] Bắt đầu xử lý {len(valid_users)} username:")
    for u in valid_users:
        print(f"    - @{u}")
    print(f"[*] Cấu hình: {videos_per_user} video/user | {concurrency} luồng | Delay: {min_delay}-{max_delay}s | Headless: {headless}\n")

    queue = asyncio.Queue()
    for u in valid_users:
        queue.put_nowait(u)

    async with async_playwright() as p:
        context = await bm.create_async_context(p, headless=headless)

        async def worker(worker_id):
            page = await context.new_page()
            try:
                while not queue.empty():
                    username = await queue.get()
                    print(f"[{worker_id}] Đang quét video của @{username}...")
                    video_urls = await get_user_videos(page, username, videos_per_user)
                    if not video_urls:
                        print(f"[{worker_id}] @{username}: Không có video công khai nào.")
                        queue.task_done()
                        continue

                    print(f"[{worker_id}] @{username}: Tìm thấy {len(video_urls)} video.")
                    for idx, v_url in enumerate(video_urls, start=1):
                        status_code, msg = await like_video(page, v_url)
                        print(f"[{worker_id}] @{username} [Video {idx}/{len(video_urls)}]: [{status_code}] {msg}")
                        if idx < len(video_urls):
                            delay = random.uniform(min_delay, max_delay)
                            print(f"[{worker_id}] Chờ {delay:.1f}s...")
                            await asyncio.sleep(delay)
                    queue.task_done()
            except Exception as e:
                print(f"[{worker_id}] [ERROR]: {e}")
            finally:
                await page.close()

        tasks = [asyncio.create_task(worker(i + 1)) for i in range(concurrency)]
        await asyncio.gather(*tasks)
        await context.close()

    print("\n[✔] Quá trình xử lý hoàn tất!")


def main():
    parser = argparse.ArgumentParser(description="TikTok Auto Like Tool CLI")
    parser.add_argument("--login", action="store_true", help="Mở Google Chrome để đăng nhập tài khoản TikTok")
    parser.add_argument("--cookie", type=str, help="Nhập chuỗi cookie hoặc mã sessionid trực tiếp")
    parser.add_argument("--status", action="store_true", help="Kiểm tra trạng thái đăng nhập TikTok hiện tại")
    parser.add_argument("--users", nargs="+", help="Danh sách usernames TikTok")
    parser.add_argument("--file", type=str, help="File .txt chứa danh sách usernames")
    parser.add_argument("--follow", nargs="+", help="Chế độ Follow: Danh sách username mục tiêu cần follow")
    parser.add_argument("--accounts", type=str, help="Chế độ Follow: File .txt chứa danh sách tài khoản (sessionid/cookie)")
    parser.add_argument("--videos", type=int, default=5, help="Số video cần tim mỗi user (mặc định: 5)")
    parser.add_argument("--concurrency", type=int, default=1, help="Số luồng xử lý đồng thời (mặc định: 1)")
    parser.add_argument("--min-delay", type=int, default=5, help="Delay tối thiểu giữa các thao tác (giây)")
    parser.add_argument("--max-delay", type=int, default=10, help="Delay tối đa giữa các thao tác (giây)")
    parser.add_argument("--headless", action="store_true", help="Chạy ở chế độ ẩn trình duyệt")

    args = parser.parse_args()

    bm = BrowserManager()

    if args.status:
        is_logged = bm.check_login_status()
        if is_logged:
            print("[✔] Trạng thái: ĐÃ ĐĂNG NHẬP TikTok thành công!")
        else:
            print("[!] Trạng thái: CHƯA ĐĂNG NHẬP TikTok.")
        return

    if args.cookie:
        success, msg = bm.import_cookies(args.cookie)
        if success:
            print(f"[✔] {msg}")
        else:
            print(f"[ERROR] {msg}")
        return

    if args.login:
        print("[*] Đang mở Google Chrome (chống chặn) để bạn đăng nhập TikTok...")
        success = bm.open_manual_login(status_callback=lambda m: print(f"[+] {m}"))
        if success:
            print("[✔] Đã lưu phiên đăng nhập TikTok thành công!")
        else:
            print("[!] Chưa nhận diện được phiên đăng nhập. Bạn có thể kiểm tra lại hoặc thử nhập Cookie.")
        return

    # Chế độ Follow hàng loạt
    if args.follow:
        if not args.accounts or not os.path.exists(args.accounts):
            print("[!] Vui lòng chỉ định file chứa danh sách tài khoản qua tham số --accounts <file.txt>")
            return
        from core.account_parser import parse_accounts_list
        from core.follow_worker import TikTokFollowWorker
        with open(args.accounts, "r", encoding="utf-8") as f:
            raw_accs = f.read()
        accs = parse_accounts_list(raw_accs)
        if not accs:
            print("[!] Không tìm thấy tài khoản/cookie hợp lệ nào trong file!")
            return
        print(f"[*] Bắt đầu Follow: {len(accs)} tài khoản -> {len(args.follow)} mục tiêu.")
        worker = TikTokFollowWorker(
            accounts=accs,
            targets=args.follow,
            concurrency=args.concurrency,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            headless=args.headless,
        )
        worker.log_signal.connect(lambda ts, lvl, msg: print(f"[{ts}] [{lvl}] {msg}"))
        worker.status_signal.connect(lambda ts, acc, tgt, act, st, code: print(f"[{ts}] {acc} -> {tgt}: [{code}] {st}"))
        worker.run()
        return

    usernames = args.users or []
    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            usernames.extend([line.strip() for line in f if line.strip()])

    if not usernames:
        print("[!] Vui lòng chỉ định danh sách usernames qua --users hoặc --file, hoặc dùng --follow với --accounts.")
        parser.print_help()
        return

    asyncio.run(
        run_cli(
            usernames=usernames,
            videos_per_user=args.videos,
            concurrency=args.concurrency,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            headless=args.headless,
        )
    )


if __name__ == "__main__":
    main()

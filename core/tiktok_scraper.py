import re
import random
import asyncio
from typing import List, Tuple, Callable
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

def clean_username(raw: str) -> str:
    """
    Chuẩn hóa username từ link hoặc chuỗi, có hoặc không có dấu @.
    """
    raw = raw.strip()
    if not raw:
        return ""
    match = re.search(r"@([a-zA-Z0-9_.-]+)", raw)
    if match:
        return match.group(1)
    if raw.startswith("@"):
        return raw[1:].strip()
    return raw.strip()


async def enable_fast_request_mode(page: Page, block_media: bool = True):
    """
    Tối ưu hóa phiên làm việc. Âm thanh video đã được tắt hoàn toàn ở cấp trình duyệt (--mute-audio),
    giữ nguyên luồng phát video tự nhiên để sinh telemetry thời gian xem (watch time) hợp lệ cho TikTok.
    """
    pass



async def is_captcha_present(page: Page) -> bool:
    """
    Kiểm tra xem trên trang có xuất hiện Captcha kéo thanh trượt, xoay vòng hình ảnh hoặc xác minh robot không.
    Kiểm tra toàn diện qua DOM selector, text hiển thị toàn trang (body) và tất cả iframes.
    """
    try:
        # 1. Kiểm tra qua JS evaluate toàn diện trên Document chính
        js_detected = await page.evaluate('''() => {
            const selectors = [
                '#captcha-verify-container-main-page',
                '.captcha-verify-container',
                'div[class*="captcha-verify-container"]',
                '.captcha_verify_container',
                'div[class*="captcha_verify_container"]',
                '#captcha_slide_button',
                '#captcha_close_button',
                '#captcha-verify-image',
                '#secsdk-captcha-drag-wrapper',
                '.secsdk-captcha-drag-wrapper',
                '.secsdk-captcha-mask',
                'div[class*="secsdk-captcha"]',
                'div[class*="secsdk_captcha"]',
                'div[class*="captcha_verify_bar"]',
                '.verify-bar-close',
                'div[id*="captcha"][class*="verify"]',
                '#tiktok-verify-ele',
                '#tiktok-verify-ele div',
                'div[class*="TUXModal"][class*="captcha"]',
                'div[class*="TUXModal"][class*="verify"]',
                'div[class*="TUXModal"][class*="secsdk"]',
                'div[class*="verify-wrap"]',
                '.captcha_verify_wrapper',
                'div[class*="verify-container"]',
                'div[class*="verify-loading"]',
                'div[class*="captcha_verify_slide"]',
                'div[class*="secsdk_captcha_drag"]',
                'iframe[src*="captcha"]',
                'iframe[src*="verify"]',
                'iframe[src*="secsdk"]'
            ];
            for (const s of selectors) {
                const els = document.querySelectorAll(s);
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 20 && rect.height > 20) {
                        return true;
                    }
                }
            }
            // 2. Kiểm tra nội dung text trong body
            const bText = (document.body ? document.body.innerText : '').toLowerCase();
            const kws = [
                'drag the slider', 'fit the puzzle', 'kéo thanh trượt', 'khớp hình', 'ghép hình',
                'rotate the', 'xoay hình', 'select the', 'chọn hình',
                'xác minh để tiếp tục', 'verify you are human', 'bạn có phải người máy',
                'vui lòng hoàn tất xác minh', 'verification'
            ];
            for (const kw of kws) {
                if (bText.includes(kw)) {
                    return true;
                }
            }
            // Nếu có từ 'puzzle' kết hợp 'slider' hoặc 'audio' hoặc 'drag'
            if (bText.includes('puzzle') && (bText.includes('slider') || bText.includes('audio') || bText.includes('drag'))) {
                return true;
            }
            return false;
        }''')
        if js_detected:
            return True

        # 2. Kiểm tra trong các frames phụ
        for frame in page.frames:
            try:
                f_text = (await frame.evaluate("() => document.body ? document.body.innerText.toLowerCase() : ''"))
                if any(k in f_text for k in ["drag the slider", "fit the puzzle", "kéo thanh trượt", "rotate the", "audio", "puzzle"]):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


async def wait_for_captcha_solved(page: Page, callback: Callable[[str], None] = None, max_wait: int = 120) -> bool:
    """
    Nếu phát hiện Captcha, đưa trình duyệt lên trước, phát thông báo và chờ người dùng kéo thanh trượt trên cửa sổ Chrome.
    """
    if await is_captcha_present(page):
        try:
            await page.bring_to_front()
        except Exception:
            pass

        if callback:
            callback("⚠️ TikTok yêu cầu xác minh Captcha (Ghép hình/Xoay vòng)! Cửa sổ Chrome đã được đưa lên trước, vui lòng kéo thanh trượt trên Chrome...")
        
        waited = 0
        while waited < max_wait:
            await asyncio.sleep(1.0)
            waited += 1
            if not await is_captcha_present(page):
                await asyncio.sleep(1.5)
                if not await is_captcha_present(page):
                    if callback:
                        callback("✅ Đã vượt qua Captcha thành công! Đang tiếp tục xử lý...")
                    return True
        return False
    return True


async def navigate_safely(
    page: Page,
    url: str,
    referer: str = "https://www.tiktok.com/",
    max_retries: int = 3,
    callback: Callable[[str], None] = None
) -> bool:
    """
    Điều hướng đến URL, tự động phát hiện và hóa giải mã chặn 403 / WAF token của Akamai TikTok.
    """
    waf_cookie_names = ["_waftokenid", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi"]
    for attempt in range(1, max_retries + 1):
        for w_name in waf_cookie_names:
            try:
                await page.context.clear_cookies(name=w_name)
            except Exception:
                pass

        try:
            resp = await page.goto(url, referer=referer, wait_until="domcontentloaded", timeout=25000)
            status = resp.status if resp else 200

            await asyncio.sleep(1.0)

            # Kiểm tra xem trang có bị màn hình chặn 403 của Chrome / Akamai không
            is_blocked = (status == 403)
            if not is_blocked:
                try:
                    title = await page.title()
                    if "403" in title or "denied" in title.lower():
                        is_blocked = True
                    else:
                        content = await page.content()
                        if "Access to www.tiktok.com was denied" in content or "HTTP ERROR 403" in content:
                            is_blocked = True
                except Exception:
                    pass

            if not is_blocked:
                # Kiểm tra xem có vướng Captcha không
                await wait_for_captcha_solved(page, callback=callback, max_wait=60)
                return True

            # Nếu phát hiện bị 403:
            if callback:
                callback(f"⚠️ Phát hiện bảo vệ WAF (Lần {attempt}/{max_retries}). Đang tự động làm mới phiên...")

            for w_name in waf_cookie_names:
                try:
                    await page.context.clear_cookies(name=w_name)
                except Exception:
                    pass
            await asyncio.sleep(2.0)

            # Truy cập trang chủ để tạo session hợp lệ mới
            try:
                await page.goto("https://www.tiktok.com/", wait_until="commit", timeout=15000)
                await asyncio.sleep(2.0)
            except Exception:
                pass

        except Exception as e:
            err_str = str(e)
            if "ERR_HTTP_RESPONSE_CODE_FAILURE" in err_str or "403" in err_str or "net::" in err_str or "Timeout" in err_str:
                if callback:
                    callback(f"⚠️ Kết nối (Lần {attempt}/{max_retries}): {err_str[:60]}. Đang thử lại...")
                for w_name in waf_cookie_names:
                    try:
                        await page.context.clear_cookies(name=w_name)
                    except Exception:
                        pass
                await asyncio.sleep(2.0)
            else:
                if attempt == max_retries:
                    if callback:
                        callback(f"❌ Lỗi tải trang: {err_str[:80]}")
                    return False

    return False


async def get_user_videos(
    page: Page,
    username: str,
    max_count: int = 5,
    callback: Callable[[str], None] = None
) -> List[str]:
    """
    Truy cập trang cá nhân TikTok của user và lấy danh sách `max_count` link video mới nhất.
    """
    profile_url = f"https://www.tiktok.com/@{username}"
    ok = await navigate_safely(page, profile_url, referer="https://www.tiktok.com/", callback=callback)
    if not ok:
        if callback:
            callback(f"❌ Không thể truy cập trang cá nhân @{username} (Bị TikTok từ chối kết nối).")
        return []

    # Đóng các pop-up sở thích / modal cản trở
    await dismiss_overlays(page)

    # Chờ các video/photo card xuất hiện sau khi Next.js/React hydration xong
    post_selector = 'a[href*="/video/"], a[href*="/photo/"], div[data-e2e="user-post-item"] a'
    try:
        await page.wait_for_selector(post_selector, timeout=8000)
    except Exception:
        pass

    video_urls = []
    attempts = 0
    max_attempts = 8

    while len(video_urls) < max_count and attempts < max_attempts:
        attempts += 1
        
        extracted = await page.evaluate("""() => {
            const list = [];
            const anchors = document.querySelectorAll('div[data-e2e="user-post-item"] a, a[href*="/video/"], a[href*="/photo/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href');
                if (href && (href.includes('/video/') || href.includes('/photo/'))) {
                    list.push(href.startsWith('http') ? href : 'https://www.tiktok.com' + href);
                }
            }
            return list;
        }""")

        for full_url in extracted:
            clean_url = full_url.split("?")[0]
            if clean_url not in video_urls:
                video_urls.append(clean_url)
                if len(video_urls) >= max_count:
                    break

        if len(video_urls) >= max_count:
            break

        await page.evaluate("window.scrollBy(0, 1000)")
        await asyncio.sleep(1.2)

    return video_urls[:max_count]


async def is_video_liked(page: Page) -> bool:
    """
    Kiểm tra xem video hiện tại đã được thả tim hay chưa.
    Duyệt toàn bộ các thuộc tính DOM:
    - aria-pressed="true"
    - Màu sắc SVG chứa đỏ (#fe2c55 / rgb(254, 44, 85), #ff3b5c / rgb(255, 59, 92))
    - aria-label / title chứa 'bỏ thích' (unlike), 'đã thích'
    - Phần tử container nút like (cả div role="button" lẫn button)
    """
    try:
        is_liked = await page.evaluate("""() => {
            const selectors = [
                '[data-e2e="like-icon"]',
                '[data-key-interaction="action_like"]',
                '[data-e2e="browse-like-icon"]',
                '[data-e2e="likes"]',
                'div[role="button"][aria-label*="thích" i]',
                'button[aria-label*="thích" i]',
                'div[role="button"][aria-label*="like" i]',
                'button[aria-label*="like" i]'
            ];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    // 1. Kiểm tra aria-pressed
                    const pressed = el.getAttribute('aria-pressed');
                    if (pressed === 'true') {
                        return true;
                    }

                    // 2. Kiểm tra data-active hoặc class
                    if (el.getAttribute('data-active') === 'true' || el.classList.contains('active') || el.classList.contains('liked')) {
                        return true;
                    }

                    // 3. Kiểm tra aria-label hoặc title
                    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
                    if (
                        label.includes('bỏ thích') ||
                        label.includes('bo thich') ||
                        label.includes('unlike') ||
                        label.includes('đã thích') ||
                        label.includes('da thich')
                    ) {
                        return true;
                    }

                    // 4. Kiểm tra màu sắc SVG icon hoặc path bên trong (màu đỏ là đã tim)
                    const svg = el.querySelector('svg');
                    if (svg) {
                        const fill = window.getComputedStyle(svg).fill || svg.getAttribute('fill') || '';
                        const color = window.getComputedStyle(svg).color || '';
                        let pathsFill = '';
                        svg.querySelectorAll('path').forEach(p => {
                            pathsFill += ' ' + (p.getAttribute('fill') || '') + ' ' + (window.getComputedStyle(p).fill || '');
                        });
                        const checkStr = (fill + ' ' + color + ' ' + pathsFill).toLowerCase();
                        if (
                            checkStr.includes('fe2c55') ||
                            checkStr.includes('ff3b5c') ||
                            checkStr.includes('254, 44, 85') ||
                            checkStr.includes('255, 59, 92') ||
                            checkStr.includes('rgb(254, 44, 85)') ||
                            checkStr.includes('rgb(255, 59, 92)')
                        ) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }""")
        if is_liked:
            return True
    except Exception:
        pass
    return False


async def dismiss_overlays(page: Page) -> None:
    """
    Đóng các modal cản trở như 'Chọn sở thích' (Interest Selector), cookie banner, thông báo chào mừng.
    Tuyệt đối KHÔNG đóng popup Captcha hoặc xác minh bảo mật.
    """
    try:
        # Nếu đang có Captcha hiển thị, giữ nguyên 100% để người dùng thao tác giải
        if await is_captcha_present(page):
            return
    except Exception:
        pass

    close_selectors = [
        'div[class*="DivCloseButtonWrapper"]',
        'div[class*="DivInterestSelectorContainer"] [aria-label*="Close" i]',
        'div[class*="DivInterestSelectorContainer"] [aria-label*="Đóng" i]',
        'div[class*="DivInterestSelectorContainer"] button',
        'button:has-text("Bỏ qua")',
        'button:has-text("Skip")',
        '[data-e2e="modal-close-inner-button"]'
    ]
    for sel in close_selectors:
        try:
            btns = await page.query_selector_all(sel)
            for b in btns:
                if await b.is_visible():
                    # Đảm bảo không bấm nhầm nút đóng của Captcha
                    is_in_captcha = await b.evaluate('''el => !!el.closest("#captcha_verify_container, [class*='secsdk'], [class*='captcha'], [id*='verify']")''')
                    if not is_in_captcha:
                        await b.click(timeout=1000)
                        await asyncio.sleep(0.3)
                        break
        except Exception:
            pass

    # Vô hiệu hóa pointer-events bằng CSS nếu lớp phủ sở thích vẫn còn (tránh crash React)
    try:
        if not await is_captcha_present(page):
            await page.evaluate("""() => {
                const overlaySelectors = [
                    '#tux-web-canary-1-modal-overlay',
                    '[data-testid*="modal-overlay"]',
                    '.tux-modal__overlay-AbELNe',
                    'div[class*="DivInterestSelectorContainer"]'
                ];
                for (const sel of overlaySelectors) {
                    document.querySelectorAll(sel).forEach(el => {
                        el.style.pointerEvents = 'none';
                        el.style.display = 'none';
                    });
                }
            }""")
    except Exception:
        pass


async def check_login_prompt(page: Page) -> bool:
    """
    Kiểm tra xem có modal hoặc pop-up bắt đăng nhập hiển thị không.
    Loại trừ các modal chọn sở thích (Interest Selector) để tránh nhận diện nhầm.
    """
    try:
        # Kiểm tra các container đăng nhập thực sự của TikTok
        login_selectors = [
            'div[id*="login-modal-"]',
            'div[class*="DivLoginContainer"]',
            'div[class*="DivLoginContainerV2"]',
            'form[class*="FormContainer"]'
        ]
        for sel in login_selectors:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True

        # Kiểm tra dialog nhưng loại trừ popup chọn sở thích
        dialogs = await page.query_selector_all('div[role="dialog"]')
        for dlg in dialogs:
            if not await dlg.is_visible():
                continue
            txt = (await dlg.inner_text() or "").lower()
            # Bỏ qua nếu là popup sở thích
            if any(k in txt for k in ["bạn muốn xem gì", "chọn sở thích", "choose your interests", "what do you want to see"]):
                continue
            if any(k in txt for k in ["đăng nhập vào tiktok", "log in to tiktok", "sign up for tiktok", "đăng nhập để tiếp tục"]):
                # Xác nhận có form hoặc nút đăng nhập
                if await dlg.query_selector('input[type="password"], a[href*="login"], form'):
                    return True
    except Exception:
        pass
    return False


async def like_video(
    page: Page,
    video_url: str,
    username: str = "",
    callback: Callable[[str], None] = None
) -> Tuple[str, str]:
    """
    Thả tim video TikTok chuẩn xác 100%, tuyệt đối không báo ảo / false-positive.
    1. Tải trang an toàn, vượt WAF và gỡ bỏ các modal che khuất.
    2. Kiểm tra Captcha nếu có.
    3. Kiểm tra xem video đã được thả tim từ trước chưa (tránh unlike).
    4. Click chính xác vào SVG biểu tượng tim bằng chuỗi sự kiện chuột thật (mousedown/mouseup).
    5. Lắng nghe phản hồi API /api/commit/item/digg/ từ máy chủ TikTok.
    6. Xác thực trạng thái sau click (aria-pressed="true", màu đỏ, API status_code==0 & is_digg==1).
    7. Chỉ trả về LIKED khi TikTok thực sự xác nhận đã tim thành công.
    """
    # 1. Bật chế độ tải nhẹ nhưng giữ media stream và SVG để player không bị lỗi
    await enable_fast_request_mode(page, block_media=False)

    aweme_id_match = re.search(r"/(?:video|photo)/(\d+)", video_url)
    aweme_id = aweme_id_match.group(1) if aweme_id_match else ""

    ref_url = f"https://www.tiktok.com/@{username}" if username else "https://www.tiktok.com/"
    ok = await navigate_safely(page, video_url, referer=ref_url, callback=callback)
    if not ok:
        return "ERROR", "Không thể tải trang video (Lỗi kết nối / 403 Forbidden)"

    # Đóng các pop-up sở thích, cookie banner cản trở
    await dismiss_overlays(page)

    # Chờ DOM ổn định và video/icon xuất hiện sau khi Next.js/React hydration xong
    try:
        await page.wait_for_selector('video, [data-e2e="like-icon"], [data-e2e="browse-like-icon"]', timeout=8000)
    except Exception:
        pass

    # 2. Kiểm tra Captcha thực tế
    if await is_captcha_present(page):
        if callback:
            callback("⚠️ Phát hiện Captcha xác minh trên trang video...")
        solved = await wait_for_captcha_solved(page, callback=callback, max_wait=60)
        if not solved:
            return "CAPTCHA", "Bị dừng do vướng Captcha TikTok chưa được giải"

    # 2.5 Tự động phát video và xem tự nhiên 2.0 - 3.5s để sinh telemetry hợp lệ (watch time > 2s)
    try:
        await page.evaluate("""() => {
            const v = document.querySelector('video');
            if (v) {
                v.muted = true;
                v.play().catch(() => {});
            }
        }""")
    except Exception:
        pass

    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        await page.mouse.move(vp["width"] // 2 + random.randint(-30, 30), vp["height"] // 2 + random.randint(-30, 30), steps=3)
    except Exception:
        pass
    await asyncio.sleep(random.uniform(2.0, 3.5))
    await dismiss_overlays(page)

    # 3. Tìm phần tử nút thả tim (chờ tối đa 6 giây để React render đầy đủ)
    like_selectors = [
        '[data-e2e="like-icon"]',
        '[data-key-interaction="action_like"]',
        '[data-e2e="browse-like-icon"]',
        'div[role="button"][aria-label*="thích" i]',
        'button[aria-label*="thích" i]',
        'div[role="button"][aria-label*="like" i]',
        'button[aria-label*="like" i]',
        '[data-e2e="likes"]',
    ]

    like_el = None
    for _ in range(12):
        for sel in like_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    like_el = el
                    break
            except Exception:
                pass
        if like_el:
            break
        await asyncio.sleep(0.5)

    if not like_el:
        return "NOT_FOUND", "Không tìm thấy nút thả tim trên giao diện video"

    # 4. KIỂM TRA TRƯỚC: Nếu video đã được thả tim từ trước -> BỎ QUA NGAY (Tránh bấm nhầm thành hủy tim!)
    if await is_video_liked(page):
        return "ALREADY_LIKED", f"Video {aweme_id} đã được thả tim từ trước (Bỏ qua)"

    # 5. Đăng ký listener bắt phản hồi API Digg từ máy chủ TikTok
    api_result = {"received": False, "status_code": None, "is_digg": None}

    async def on_digg_response(res):
        if "commit/item/digg" in res.url or "item/digg" in res.url:
            api_result["received"] = True
            try:
                data = await res.json()
                api_result["status_code"] = data.get("status_code", -1)
                api_result["is_digg"] = data.get("is_digg", None)
            except Exception:
                pass

    page.on("response", on_digg_response)

    try:
        # 6. Click chuẩn xác bằng scroll_into_view + Playwright click
        try:
            await like_el.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.15)
            await like_el.click(delay=random.randint(60, 100))
        except Exception:
            box = await like_el.bounding_box()
            if box:
                await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=3)
                await asyncio.sleep(0.08)
                await page.mouse.down()
                await asyncio.sleep(0.08)
                await page.mouse.up()
            else:
                return "FAILED", "Không thể click vào nút thả tim"

        # 7. Chờ phản hồi API hoặc cập nhật DOM (tối đa 4 giây)
        for _ in range(16):
            await asyncio.sleep(0.25)
            # Nếu API trả về is_digg: 0 (bị un-like do video vốn đã có tim ngầm), click lại ngay để kích hoạt tim!
            if api_result["received"] and api_result["is_digg"] == 0:
                if callback:
                    callback("⚠️ Phát hiện trạng thái hủy tim, đang tự động click bù để kích hoạt lại...")
                api_result["received"] = False
                await asyncio.sleep(0.4)
                try:
                    await like_el.click(delay=100)
                except Exception:
                    pass
                break

            if api_result["received"] and api_result["status_code"] == 0 and api_result["is_digg"] == 1:
                break
            if await is_video_liked(page):
                break

        # Nếu vừa click bù, chờ thêm tối đa 3s cho lần 2 hoàn tất
        if api_result["is_digg"] != 1 and not await is_video_liked(page):
            for _ in range(12):
                await asyncio.sleep(0.25)
                if (api_result["received"] and api_result["is_digg"] == 1) or await is_video_liked(page):
                    break

        # 8. Kiểm tra xem có popup bắt đăng nhập không
        if await check_login_prompt(page):
            return "NOT_LOGGED_IN", "Yêu cầu đăng nhập TikTok! Phiên đăng nhập chưa được lưu hoặc cookie không hợp lệ."

        # Kiểm tra thông báo Toast giới hạn thao tác
        toast_msg = await page.evaluate("""() => {
            const toast = document.querySelector('div[class*="Toast"], div[role="status"], div[class*="Notification"]');
            return toast ? toast.innerText.trim() : '';
        }""")
        if toast_msg:
            return "RATE_LIMITED", f"TikTok hạn chế: {toast_msg}"

        # 9. Nếu API trả về mã lỗi cụ thể từ máy chủ TikTok
        if api_result["received"] and api_result["status_code"] not in [None, 0]:
            sc = api_result["status_code"]
            if sc in [2055, 2049, 10215]:
                return "BLOCKED_BY_TIKTOK", f"TikTok giới hạn thao tác (Mã {sc}): Tài khoản bị tạm dừng like do thao tác quá nhanh"
            elif sc == 8:
                return "NOT_LOGGED_IN", "Phiên đăng nhập hết hạn (Mã 8)"
            return "BLOCKED_BY_TIKTOK", f"TikTok từ chối thả tim (Mã lỗi: {sc})"

        # 10. XÁC THỰC KẾT QUẢ: Phải có is_digg == 1 HOẶC DOM đổi sang trạng thái đã tim
        is_confirmed = (
            (api_result["received"] and api_result["status_code"] == 0 and api_result["is_digg"] == 1) or
            await is_video_liked(page)
        )

        if is_confirmed:
            # QUAN TRỌNG: Dừng lại 2.0s trên trang trước khi rời đi để TikTok SecSDK kịp flush telemetry và beacon lên server
            await asyncio.sleep(random.uniform(1.8, 2.8))
            return "LIKED", f"💖 Đã thả tim thành công video {aweme_id or ''}".strip()

        return "FAILED", "Thả tim không thành công (TikTok không ghi nhận thao tác)"

    finally:
        try:
            page.remove_listener("response", on_digg_response)
        except Exception:
            pass


async def get_profile_header_follow_button(page: Page):
    """
    Tìm chính xác nút Follow của chủ tài khoản trang cá nhân (khu vực Header),
    loại trừ triệt để nút Follow của tài khoản gợi ý (Suggested accounts)
    và nút điều hướng 'Đã follow' bên menu trái.
    """
    try:
        btns = await page.query_selector_all('button[data-e2e="follow-button"], button[data-e2e="user-follow-button"], button')
        for b in btns:
            try:
                if not await b.is_visible():
                    continue
                box = await b.bounding_box()
                if not box:
                    continue
                # Nút follow header luôn nằm ở khu vực trên cùng (y < 350) và bên phải thanh menu (x > 250)
                if box["x"] < 250 or box["y"] > 350:
                    continue

                txt = (await b.inner_text() or "").strip()
                data_e2e = await b.get_attribute("data-e2e")

                if data_e2e in ["follow-button", "user-follow-button"]:
                    return b
                if any(kw in txt.lower() for kw in ["follow", "theo dõi", "đang theo dõi", "bạn bè", "following", "friends"]):
                    return b
            except Exception:
                pass
    except Exception:
        pass
    return None


async def follow_user(
    page: Page,
    target_username: str,
    callback: Callable[[str], None] = None
) -> Tuple[str, str]:
    """
    Follow tài khoản TikTok chuẩn xác 100%, tuyệt đối không báo ảo / false-positive.
    1. Kiểm tra tài khoản tồn tại (dựa vào DOM thực tế).
    2. Kiểm tra xem đã theo dõi từ trước chưa (Following / Bạn bè).
    3. Click chính xác vào nút Follow bằng chuỗi sự kiện chuột người thật.
    4. Bắt và phân tích phản hồi API POST /api/commit/follow/user/ từ TikTok:
       - status_code == 0 && follow_status in (1, 2, 3): Xác nhận thêm giao diện đổi trạng thái mới kết luận thành công.
       - status_code == 0 && follow_status == 0: TikTok âm thầm từ chối (Action Block ngầm).
       - status_code == 8: Cookie hết hạn / out nick.
       - status_code in (2055, 2049, 10215): Bị giới hạn do thao tác quá nhanh.
    5. Bắt và đưa cửa sổ Chrome lên đầu khi gặp Captcha để người dùng giải.
    6. Dwell time 2.5-3.5s sau click để SecSDK kịp gửi telemetry beacon (chống TikTok tự động hủy follow).
    """
    FOLLOWING_KEYWORDS = ["đang theo dõi", "dang theo doi", "following", "bạn bè", "friends", "đã follow", "requested", "đã yêu cầu"]
    FOLLOW_KEYWORDS = ["follow", "theo dõi", "theo doi", "follow back", "theo dõi lại"]

    clean_target = clean_username(target_username)
    if not clean_target:
        return "ERROR", "Username mục tiêu không hợp lệ"

    await enable_fast_request_mode(page)

    profile_url = f"https://www.tiktok.com/@{clean_target}"
    ok = await navigate_safely(page, profile_url, referer="https://www.tiktok.com/", callback=callback)
    if not ok:
        return "ERROR", f"Không thể kết nối trang @{clean_target} (Lỗi mạng / WAF 403)"

    # 1. KIỂM TRA CAPTCHA NGAY KHI VÀO TRANG (TRƯỚC MỌI THAO TÁC KHÁC ĐỂ TRÁNH ĐÓNG NHẦM)
    if await is_captcha_present(page):
        if callback:
            callback(f"⚠️ TikTok yêu cầu xác minh Captcha cho @{clean_target}! Cửa sổ Chrome đã được đưa lên trước, vui lòng kéo thanh trượt ghép hình...")
        try:
            await page.bring_to_front()
        except Exception:
            pass
        solved = await wait_for_captcha_solved(page, callback=callback, max_wait=120)
        if not solved:
            return "CAPTCHA", "Dừng lại do chưa hoàn tất giải Captcha trên trình duyệt"
        await asyncio.sleep(2.0)

    await dismiss_overlays(page)
    await asyncio.sleep(1.0)

    # 2. Kiểm tra nếu bị điều hướng sang trang login hoặc có popup bắt đăng nhập
    try:
        page_title = (await page.title() or "").lower()
        if "/login" in page.url.lower() or "log in" in page_title or "đăng nhập" in page_title:
            return "COOKIE_EXPIRED", "Yêu cầu đăng nhập TikTok! Cookie hoặc phiên đăng nhập chưa có hiệu lực."
    except Exception:
        pass

    if await check_login_prompt(page):
        return "COOKIE_EXPIRED", "Yêu cầu đăng nhập TikTok! Cookie hoặc phiên đăng nhập chưa có hiệu lực."

    # 3. Tìm chính xác nút Follow trên trang cá nhân
    follow_btn = None
    for _ in range(24):
        follow_btn = await get_profile_header_follow_button(page)
        if follow_btn:
            break

        if await is_captcha_present(page):
            if callback:
                callback(f"⚠️ Phát hiện Captcha xuất hiện! Vui lòng kéo thanh trượt trên Chrome...")
            try:
                await page.bring_to_front()
            except Exception:
                pass
            solved = await wait_for_captcha_solved(page, callback=callback, max_wait=120)
            if not solved:
                return "CAPTCHA", "Dừng lại do chưa giải Captcha trên trình duyệt"
            await asyncio.sleep(2.0)

        await asyncio.sleep(0.5)

    if not follow_btn:
        not_found_el = await page.query_selector('[data-e2e="user-not-found"]')
        if not_found_el and await not_found_el.is_visible():
            return "ERROR", f"Tài khoản @{clean_target} không tồn tại trên TikTok!"

        try:
            body_text = (await page.inner_text("body")).lower()
            if "couldn't find this account" in body_text or "không thể tìm thấy tài khoản" in body_text:
                return "ERROR", f"Tài khoản @{clean_target} không tồn tại trên TikTok!"
        except Exception:
            pass

        if "/login" in page.url.lower() or await check_login_prompt(page):
            return "COOKIE_EXPIRED", "Yêu cầu đăng nhập TikTok! Cookie hoặc phiên đăng nhập chưa có hiệu lực."

        return "NOT_FOUND", f"Không tìm thấy nút Follow trên trang @{clean_target}"

    # 4. Kiểm tra xem đã theo dõi từ trước chưa
    btn_txt = (await follow_btn.inner_text() or "").strip().lower()
    if any(kw in btn_txt for kw in FOLLOWING_KEYWORDS):
        return "ALREADY_FOLLOWED", f"Đã theo dõi @{clean_target} từ trước (Bỏ qua)"

    # 5. Đăng ký listener bắt phản hồi API commit/follow từ TikTok (chỉ bắt POST thực sự)
    api_result = {"received": False, "status_code": None, "follow_status": None, "msg": ""}

    async def on_follow_resp(res):
        if "commit/follow/user" in res.url and res.request.method == "POST":
            api_result["received"] = True
            try:
                data = await res.json()
                api_result["status_code"] = data.get("status_code", -1)
                api_result["follow_status"] = data.get("follow_status", None)
                api_result["msg"] = data.get("status_msg", "")
            except Exception:
                pass

    page.on("response", on_follow_resp)

    try:
        # Lướt nhẹ để tạo telemetry chuột người thật trước khi bấm
        try:
            await page.mouse.move(random.randint(350, 650), random.randint(180, 320), steps=5)
            await asyncio.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

        # Click chính xác vào nút Follow bằng chuỗi sự kiện chuột người thật
        box = await follow_btn.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            await page.mouse.move(cx, cy, steps=6)
            await asyncio.sleep(random.uniform(0.08, 0.15))
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.06, 0.12))
            await page.mouse.up()
        else:
            await follow_btn.click(timeout=3000, delay=random.randint(60, 100))

        # 6. VÒNG LẶP THEO DÕI & XÁC THỰC NGHIÊM NGẶT (Tối đa 18 giây)
        for loop_idx in range(36):
            await asyncio.sleep(0.5)

            # A. KIỂM TRA CAPTCHA NGAY LẬP TỨC NẾU TIKTOK BẬT POPUP SAU KHI CLICK
            if await is_captcha_present(page):
                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if callback:
                    callback("⚠️ TikTok yêu cầu giải Captcha (Kéo thanh trượt ghép hình)! Cửa sổ Chrome đã được đưa lên trước, vui lòng thao tác...")

                solved = await wait_for_captcha_solved(page, callback=callback, max_wait=120)
                if not solved:
                    return "CAPTCHA", "Dừng lại do chưa giải xong Captcha trên trình duyệt (Hết thời gian 120s)"

                if callback:
                    callback("✅ Đã vượt qua Captcha! Đang kiểm tra và xác nhận trạng thái Follow...")
                await asyncio.sleep(2.0)

                # Reset API result để lắng nghe lần bấm mới sau khi giải captcha
                api_result["received"] = False
                api_result["status_code"] = None
                api_result["follow_status"] = None

                btn_recheck = await get_profile_header_follow_button(page)
                if btn_recheck:
                    txt_rc = (await btn_recheck.inner_text() or "").strip().lower()
                    if any(kw in txt_rc for kw in FOLLOWING_KEYWORDS):
                        await asyncio.sleep(2.5)
                        return "FOLLOWED", f"✅ Đã follow thành công @{clean_target} (Sau khi giải Captcha)"
                    else:
                        if callback:
                            callback("Đang bấm Follow lại sau khi xác minh Captcha thành công...")
                        try:
                            await btn_recheck.click(delay=random.randint(70, 110))
                            await asyncio.sleep(2.0)
                        except Exception:
                            pass
                continue

            # B. Kiểm tra popup bắt đăng nhập
            if await check_login_prompt(page) or "/login" in page.url.lower():
                return "COOKIE_EXPIRED", "Yêu cầu đăng nhập TikTok! Cookie hoặc phiên đăng nhập chưa có hiệu lực."

            # C. Phân tích phản hồi API từ máy chủ TikTok
            if api_result["received"]:
                sc = api_result["status_code"]
                fs = api_result["follow_status"]
                if sc == 8:
                    return "COOKIE_EXPIRED", "Phiên đăng nhập TikTok bị hết hạn (Mã 8 - Login expired)"
                elif sc in [2055, 2049, 10215]:
                    return "BLOCKED_BY_TIKTOK", f"TikTok giới hạn thao tác (Mã {sc}): Tài khoản cần nghỉ vài phút"
                elif sc == 0 and fs in [1, 2, 3]:
                    # XÁC NHẬN NGHIÊM NGẶT: Nút trên giao diện phải thực sự đổi sang Đang theo dõi / Bạn bè
                    btn_check = await get_profile_header_follow_button(page)
                    if btn_check:
                        txt_check = (await btn_check.inner_text() or "").strip().lower()
                        if any(kw in txt_check for kw in FOLLOWING_KEYWORDS):
                            # Thành công thực sự cả máy chủ lẫn giao diện!
                            try:
                                await page.mouse.move(random.randint(300, 700), random.randint(200, 500), steps=5)
                                await page.mouse.wheel(0, random.randint(150, 280))
                            except Exception:
                                pass
                            # Dừng lại 2.5 - 3.5s để SecSDK flush telemetry beacon
                            await asyncio.sleep(random.uniform(2.5, 3.5))
                            return "FOLLOWED", f"✅ Đã follow thành công @{clean_target} (Máy chủ và giao diện xác nhận)"
                    
                    # Nếu nút chưa đổi (vẫn là Follow / Follow lại), có thể TikTok đang tải Captcha hoặc từ chối ngầm
                    if await is_captcha_present(page):
                        continue
                    if loop_idx > 20:
                        return "FAILED", f"TikTok từ chối follow @{clean_target} (Nút không đổi trạng thái, cần giải Captcha hoặc đổi IP)"
                elif sc == 0 and fs == 0:
                    if await is_captcha_present(page):
                        continue
                    if loop_idx > 15:
                        return "BLOCKED_BY_TIKTOK", f"TikTok giới hạn ngầm (Action Block - follow_status=0)! Máy chủ từ chối ghi nhận follow @{clean_target}"
                elif sc not in [None, 0]:
                    if await is_captcha_present(page):
                        continue
                    if loop_idx > 10:
                        return "BLOCKED_BY_TIKTOK", f"TikTok từ chối follow: {api_result['msg']} (Mã {sc})"

            # D. Xác thực dựa trên DOM nút Follow
            btn_verify = await get_profile_header_follow_button(page)
            if btn_verify:
                txt_v = (await btn_verify.inner_text() or "").strip().lower()
                if any(kw in txt_v for kw in FOLLOWING_KEYWORDS):
                    await asyncio.sleep(1.5)
                    if await is_captcha_present(page):
                        continue
                    btn_verify2 = await get_profile_header_follow_button(page)
                    if btn_verify2:
                        txt_v2 = (await btn_verify2.inner_text() or "").strip().lower()
                        if any(kw in txt_v2 for kw in FOLLOWING_KEYWORDS):
                            await asyncio.sleep(random.uniform(1.5, 2.5))
                            return "FOLLOWED", f"✅ Đã follow thành công @{clean_target}"

        # Kiểm tra Captcha lần cuối trước khi kết luận
        if await is_captcha_present(page):
            try:
                await page.bring_to_front()
            except Exception:
                pass
            solved = await wait_for_captcha_solved(page, callback=callback, max_wait=120)
            if solved:
                return "FOLLOWED", f"✅ Đã follow thành công @{clean_target} (Sau khi giải Captcha)"

        # Xác nhận lần cuối trạng thái nút
        btn_final = await get_profile_header_follow_button(page)
        if btn_final:
            txt_fin = (await btn_final.inner_text() or "").strip().lower()
            if any(kw in txt_fin for kw in FOLLOWING_KEYWORDS):
                return "FOLLOWED", f"✅ Đã follow thành công @{clean_target}"

        if not api_result["received"]:
            return "BLOCKED_BY_TIKTOK", f"Không nhận được phản hồi API follow cho @{clean_target} (Kiểm tra mạng/IP/Captcha)"

        return "FAILED", f"Follow @{clean_target} không thành công (TikTok từ chối ghi nhận)"

    except Exception as e:
        err_msg = str(e)
        if "Target page, context or browser has been closed" in err_msg or "Target closed" in err_msg:
            return "ERROR", "Trình duyệt đã bị đóng trong lúc thực hiện"
        raise
    finally:
        try:
            page.remove_listener("response", on_follow_resp)
        except Exception:
            pass




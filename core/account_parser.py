import re
import json
from typing import List, Dict, Optional, Tuple

WAF_COOKIES = {"_waftokenid", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi"}


def clean_cookie_for_playwright(raw_cookie: dict) -> Optional[dict]:
    """
    Chuẩn hóa dict cookie sang định dạng nghiêm ngặt của Playwright.
    Loại bỏ các trường lạ (storeId, hostOnly, id...) và chuẩn hóa sameSite.
    """
    if not isinstance(raw_cookie, dict):
        return None

    name = str(raw_cookie.get("name", "")).strip()
    value = str(raw_cookie.get("value", "")).strip()
    if not name or not value or name in WAF_COOKIES:
        return None

    domain = str(raw_cookie.get("domain", ".tiktok.com")).strip()
    if not domain.endswith("tiktok.com"):
        domain = ".tiktok.com"
    elif not domain.startswith("."):
        domain = "." + domain

    cookie = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": str(raw_cookie.get("path", "/")),
        "secure": bool(raw_cookie.get("secure", True)),
        "httpOnly": bool(raw_cookie.get("httpOnly", False)),
    }

    # Chuẩn hóa sameSite sang ("Strict", "Lax", "None") mà Playwright yêu cầu
    raw_ss = str(raw_cookie.get("sameSite", "")).lower().strip()
    if raw_ss in ["strict"]:
        cookie["sameSite"] = "Strict"
    elif raw_ss in ["lax"]:
        cookie["sameSite"] = "Lax"
    elif raw_ss in ["none", "no_restriction"]:
        cookie["sameSite"] = "None"

    # Hạn sử dụng (nếu có)
    exp = raw_cookie.get("expires") or raw_cookie.get("expirationDate")
    if exp:
        try:
            cookie["expires"] = int(float(exp))
        except (ValueError, TypeError):
            pass

    return cookie


def extract_cookies_and_session(text: str) -> Tuple[List[dict], str]:
    """
    Trích xuất danh sách cookie và sessionid từ bất kỳ định dạng nào:
    - Mảng JSON (Cookie-Editor, EditThisCookie, J2Team...)
    - Chuỗi cookie trình duyệt: key=value; key2=value2
    - Token sessionid thô (chuỗi hex/alphanumeric 20-64 ký tự)
    """
    text = text.strip()
    if not text:
        return [], ""

    parsed: List[dict] = []
    sessionid = ""

    # 1. Thử phân tích cú pháp JSON
    if ("[" in text and "]" in text) or ("{" in text and "}" in text):
        # Trích xuất phần JSON nếu có ký tự thừa xung quanh
        json_match = re.search(r"\[.*\]|\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                items = data if isinstance(data, list) else data.get("cookies", [data])
                for item in items:
                    c = clean_cookie_for_playwright(item)
                    if c:
                        parsed.append(c)
                        if c["name"] in ["sessionid", "sessionid_ss", "sid_tt"] and not sessionid:
                            sessionid = c["value"]
            except Exception:
                pass

    # 2. Nếu không phải JSON, kiểm tra định dạng key=value; ...
    if not parsed and "=" in text:
        # Tách theo dấu chấm phẩy hoặc dòng
        parts = re.split(r"[;\r\n]+", text)
        for p in parts:
            p = p.strip()
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in WAF_COOKIES:
                    c = clean_cookie_for_playwright({
                        "name": k,
                        "value": v,
                        "domain": ".tiktok.com",
                        "path": "/",
                    })
                    if c:
                        parsed.append(c)
                        if k in ["sessionid", "sessionid_ss", "sid_tt"] and not sessionid:
                            sessionid = v

    # 3. Chuỗi token sessionid thô (không có dấu =, chỉ có giá trị)
    if not parsed:
        clean_tok = text.strip().strip('"').strip("'")
        # Token sessionid của TikTok thường dài từ 20 đến 64 ký tự
        if len(clean_tok) >= 20 and re.match(r"^[a-zA-Z0-9_-]+$", clean_tok):
            sessionid = clean_tok
            parsed.append({
                "name": "sessionid",
                "value": sessionid,
                "domain": ".tiktok.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })

    # Tự động đồng bộ sessionid, sessionid_ss và sid_tt nếu bị thiếu
    if sessionid:
        has_sid = any(c["name"] == "sessionid" for c in parsed)
        has_sid_ss = any(c["name"] == "sessionid_ss" for c in parsed)
        has_sid_tt = any(c["name"] == "sid_tt" for c in parsed)
        if not has_sid:
            parsed.append({
                "name": "sessionid",
                "value": sessionid,
                "domain": ".tiktok.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })
        if not has_sid_ss:
            parsed.append({
                "name": "sessionid_ss",
                "value": sessionid,
                "domain": ".tiktok.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })
        if not has_sid_tt:
            parsed.append({
                "name": "sid_tt",
                "value": sessionid,
                "domain": ".tiktok.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })

    return parsed, sessionid


def parse_proxy_string(proxy_str: str) -> Optional[dict]:
    """Phân tích proxy từ chuỗi: ip:port, ip:port:user:pass, hoặc http/socks URL."""
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    if proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://"):
        return {"server": proxy_str}

    parts = proxy_str.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        return {
            "server": f"http://{ip}:{port}",
            "username": user,
            "password": pwd,
        }
    elif len(parts) == 2:
        ip, port = parts
        return {"server": f"http://{ip}:{port}"}

    return None


class TikTokAccount:
    """
    Đại diện cho 1 tài khoản TikTok dùng để chạy tự động hóa.
    Hỗ trợ nhận diện thông minh đa định dạng:
    - uid|pass|cookie
    - uid|pass|2fa|cookie
    - uid|pass|cookie|proxy
    - uid|cookie
    - cookie|proxy
    - cookie thuần (chuỗi hoặc JSON)
    - sessionid thuần
    """
    def __init__(self, raw: str, index: int = 1):
        self.raw = raw.strip()
        self.index = index
        self.account_id = f"Acc #{index}"
        self.sessionid = ""
        self.cookies: List[dict] = []
        self.proxy: Optional[dict] = None
        self._parse()

    def is_valid(self) -> bool:
        return bool(self.cookies and self.sessionid)

    def _parse(self):
        line = self.raw.strip()
        if not line:
            return

        # Nếu là toàn bộ JSON array, xử lý trực tiếp
        if line.startswith("[") and line.endswith("]"):
            self.cookies, self.sessionid = extract_cookies_and_session(line)
            if self.sessionid:
                short = self.sessionid[:6] + "..." + self.sessionid[-4:]
                self.account_id = f"Acc #{self.index} ({short})"
            return

        # Tách các thành phần phân cách bởi '|' hoặc tab
        parts = [p.strip() for p in re.split(r"[|\t]+", line) if p.strip()]

        if len(parts) == 1:
            # 1 phần duy nhất: là cookie hoặc sessionid
            self.cookies, self.sessionid = extract_cookies_and_session(parts[0])
        else:
            # Nhiều phần: tìm thông minh phần nào là cookie, proxy, username
            cookie_part = ""
            proxy_part = ""
            label_candidate = ""

            for idx, p in enumerate(parts):
                # Kiểm tra proxy (ip:port hoặc http/socks URL)
                if re.search(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+", p) or p.startswith(("http://", "https://", "socks5://")):
                    proxy_part = p
                    continue

                # Kiểm tra cookie: chứa 'sessionid', '=', JSON, hoặc là token dài >= 20 ký tự
                is_cookie_candidate = (
                    "sessionid" in p.lower()
                    or ("=" in p and ";" in p)
                    or (p.startswith("[") and p.endswith("]"))
                    or (len(p) >= 28 and "=" in p)
                )

                if is_cookie_candidate and not cookie_part:
                    cookie_part = p
                    continue

                # Nếu chưa tìm thấy cookie, token dài >= 32 chars hex cũng có thể là sessionid
                if len(p) >= 32 and re.match(r"^[a-zA-Z0-9_-]+$", p) and not cookie_part:
                    cookie_part = p
                    continue

                # Nhãn tài khoản: thường là phần đầu tiên (username hoặc uid)
                if idx == 0 and not label_candidate:
                    label_candidate = p

            # Nếu vẫn chưa xác định được cookie_part, lấy phần dài nhất
            if not cookie_part and parts:
                cookie_part = max(parts, key=len)

            if cookie_part:
                self.cookies, self.sessionid = extract_cookies_and_session(cookie_part)

            if proxy_part:
                self.proxy = parse_proxy_string(proxy_part)

            if label_candidate:
                self.account_id = label_candidate if label_candidate.startswith("@") else f"@{label_candidate}"

        if self.account_id == f"Acc #{self.index}" and self.sessionid:
            short = self.sessionid[:6] + "..." + self.sessionid[-4:]
            self.account_id = f"Acc #{self.index} ({short})"


def parse_accounts_list(raw_text: str) -> List[TikTokAccount]:
    """
    Phân tích toàn bộ văn bản đầu vào thành danh sách TikTokAccount hợp lệ.
    Tự động xử lý cả:
    - Multi-line JSON (toàn bộ nội dung là 1 JSON array lớn)
    - Danh sách nhiều dòng (mỗi dòng 1 tài khoản)
    - Định dạng nhiều JSON blocks
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return []

    # Trường hợp 1: Toàn bộ văn bản là 1 mảng JSON cookie của 1 tài khoản
    if raw_text.startswith("[") and raw_text.endswith("]"):
        try:
            data = json.loads(raw_text)
            if isinstance(data, list):
                # Nếu là mảng dict cookie thông thường
                if data and isinstance(data[0], dict) and "name" in data[0]:
                    acc = TikTokAccount(raw_text, index=1)
                    if acc.is_valid():
                        return [acc]
                # Nếu là mảng các mảng cookie (danh sách nhiều tài khoản dạng JSON)
                elif data and isinstance(data[0], list):
                    accounts = []
                    for idx, acc_data in enumerate(data, start=1):
                        acc = TikTokAccount(json.dumps(acc_data), index=idx)
                        if acc.is_valid():
                            accounts.append(acc)
                    if accounts:
                        return accounts
        except Exception:
            pass

    # Trường hợp 2: Từng dòng là một tài khoản
    lines = raw_text.splitlines()
    accounts = []
    idx = 1
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        acc = TikTokAccount(line, index=idx)
        if acc.is_valid():
            accounts.append(acc)
            idx += 1

    return accounts

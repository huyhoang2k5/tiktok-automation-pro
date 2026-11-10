# ⚡ TikTok Automation Pro - Auto Like & Multi-Account Follow

Công cụ tự động hóa tương tác TikTok chuyên nghiệp với giao diện đồ họa **PySide6** (Qt) hiện đại và hỗ trợ dòng lệnh **CLI**. Hỗ trợ 2 chế độ độc lập: **Tự động thả tim video** và **Follow hàng loạt / Chéo acc từ hàng trăm tài khoản**.

---

## 🌟 Phân hệ 1: 💖 Tự Động Thả Tim Video (Auto Like)
- **Nhập danh sách username:** Nhập trực tiếp nhiều dòng hoặc bấm **"📂 Nhập từ file .txt"**.
- **Tùy chỉnh số lượng video:** Cài đặt số video mới nhất cần thả tim cho mỗi tài khoản (ví dụ 5-10 video).
- **Đa luồng đồng thời (Concurrency):** Chạy song song nhiều luồng tối ưu thời gian.
- **Delay ngẫu nhiên:** Tự do đặt Min - Max delay (ví dụ: 5–10s) chống quét bot.
- **Tự động hóa giải WAF / 403:** Xóa bỏ token chặn `_waftokenid`, tự làm mới session và vượt qua bảo vệ Akamai.

---

## 👥 Phân hệ 2: Follow Hàng Loạt / Chéo Acc (Multi-Account Follow)
- **Hỗ trợ 100+ tài khoản tự tạo:** Nạp danh sách hàng chục đến hàng trăm tài khoản TikTok thông qua Cookie / `sessionid`.
  - Hỗ trợ các định dạng:
    1. Mỗi dòng 1 mã `sessionid`: `757e930fca5d82098...`
    2. Mỗi dòng 1 chuỗi Cookie đầy đủ: `sessionid=xxx; ttwid=yyy; ...`
    3. Định dạng phân cách: `username|password|sessionid`
    4. Định dạng kèm Proxy: `sessionid|ip:port:user:pass`
    5. Nhập danh sách từ file `.txt`.
- **Chỉ định mục tiêu (Targets):** Nhập 1 hoặc nhiều tài khoản đích cần tăng follow (ví dụ: `@dangquochuy.dev`).
- **Context trong RAM (Ephemeral BrowserContext):** Mỗi tài khoản chạy trong một ngữ cảnh RAM riêng biệt, chuyển đổi tài khoản cực nhanh, **không tạo rác ổ cứng** và **không lo bị xung đột khóa profile**.
- **Kiểm soát trạng thái thông minh:** Tự động phát hiện nếu tài khoản đã follow trước đó (`ALREADY_FOLLOWED`), phát hiện cookie hết hạn (`COOKIE_EXPIRED`), xác nhận trạng thái sau khi click.

---

## 🛠️ Hướng dẫn cài đặt & Khởi chạy

### 1. Cài đặt thư viện (nếu chưa có)
Mở PowerShell hoặc Command Prompt tại thư mục dự án và chạy:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Khởi chạy giao diện đồ họa (GUI)
```bash
python main.py
```

### 3. Khởi chạy bằng dòng lệnh (CLI)
- **Thả tim video:**
  ```bash
  python cli.py --users dangquochuy.dev username2 --videos 5 --concurrency 1 --min-delay 5 --max-delay 10
  ```
- **Follow hàng loạt từ danh sách tài khoản:**
  ```bash
  python cli.py --follow dangquochuy.dev --accounts danh_sach_acc.txt --concurrency 2 --min-delay 5 --max-delay 10
  ```
- **Đăng nhập TikTok thủ công (lưu vào máy):**
  ```bash
  python cli.py --login
  ```
- **Kiểm tra trạng thái đăng nhập:**
  ```bash
  python cli.py --status
  ```

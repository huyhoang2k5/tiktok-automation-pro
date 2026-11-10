@echo off
chcp 65001 >nul
title Cài đặt TikTok Automation Pro
echo ======================================================
echo   ĐANG TỰ ĐỘNG CÀI ĐẶT MÔI TRƯỜNG CHO TIKTOK AUTOMATION
echo ======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [LỖI] Máy tính của bạn chưa cài đặt Python!
    echo Vui lòng tải Python tại: https://www.python.org/downloads/
    echo LƯU Ý QUAN TRỌNG: Khi cài nhớ tích ô "Add Python to PATH"!
    echo.
    pause
    exit /b
)

echo [1/2] Đang cài đặt thư viện Python (PySide6, Playwright, psutil)...
pip install -r requirements.txt

echo.
echo [2/2] Đang khởi tạo trình duyệt Chromium cho Playwright...
playwright install chromium

echo.
echo ======================================================
echo   CÀI ĐẶT THÀNH CÔNG!
echo   Bây giờ bạn chỉ cần nhấp đúp vào 'Chay_Tool.bat' để mở tool.
echo ======================================================
echo.
pause

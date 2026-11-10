@echo off
chcp 65001 >nul
title TikTok Automation Pro
echo Đang khởi động TikTok Automation Pro...
python main.py
if errorlevel 1 (
    echo.
    echo ======================================================
    echo [LƯU Ý] Nếu tool không mở được, hãy chạy file 'Cai_Dat.bat' trước!
    echo ======================================================
    pause
)

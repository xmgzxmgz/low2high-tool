@echo off
chcp 65001 >nul
title Low2High 高帧视频处理器
echo ============================================
echo   Low2High - 高帧视频处理器 (本地版)
echo   插帧 + 防限流伪装，纯本地运行
echo ============================================
echo.
cd /d "%~dp0"
echo 正在启动服务，请在浏览器打开： http://127.0.0.1:5000
echo (关闭此窗口即可停止服务)
echo.
"./venv/Scripts/python.exe" app.py
pause

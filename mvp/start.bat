@echo off
chcp 65001 >nul
if "%MYSQL_PASS%"=="" echo 请先设置 MYSQL_PASS 环境变量 && pause && exit /b 1
set PYTHONIOENCODING=utf-8
echo ================================
echo   Infinite Flow MVP Launcher
echo ================================
echo Starting server...
python server.py
pause

@echo off
chcp 65001 >nul
set MYSQL_PASS=root
set PYTHONIOENCODING=utf-8
echo ================================
echo   Infinite Flow MVP Launcher
echo ================================
echo Starting server...
python server.py
pause

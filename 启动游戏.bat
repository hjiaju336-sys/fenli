@echo off
chcp 65001 >nul
title 无限流规则怪谈
cd /d "%~dp0mvp"

echo 无限流规则怪谈 v0.6.1
echo.

echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8777.*LISTENING"') do taskkill /PID %%a /F >nul 2>&1
ping -n 2 127.0.0.1 >nul

echo [2/3] 启动服务器...
set MYSQL_PASS=root
set PYTHONIOENCODING=utf-8
start "FenliServer" /MIN python server.py

echo [3/3] 等待就绪...
:wait
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr ":8777.*LISTENING" >nul
if errorlevel 1 goto wait

start http://localhost:8777
echo 游戏已启动 http://localhost:8777
ping -n 4 127.0.0.1 >nul
exit

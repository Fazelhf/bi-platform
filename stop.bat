@echo off
chcp 65001 >nul
title توقف سرورها
echo بستن سرورهای نسخه 2 روی پورت 8001 و 5174 ...
for %%P in (8001 5174) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%A >nul 2>&1
  )
)
echo انجام شد. سرورها متوقف شدند.
timeout /t 2 /nobreak >nul

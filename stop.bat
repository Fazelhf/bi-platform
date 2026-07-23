@echo off
chcp 65001 >nul
title توقف سرورها
echo بستن سرورهای پورت 8000 و 5173 ...
for %%P in (8000 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%A >nul 2>&1
  )
)
echo انجام شد. سرورها متوقف شدند.
timeout /t 2 /nobreak >nul

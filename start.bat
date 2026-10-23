@echo off
chcp 65001 >nul
title کاغذ حساس نمابر مهر - راه اندازی سرورها
cd /d "%~dp0"

echo ================================================
echo   شرکت کاغذ حساس نمابر مهر - BI Platform v2
echo ================================================
echo.

REM --- Free ports 8001 and 5174 if something is already using them ---
echo [1/3] آزادسازی پورت های 8001 و 5174 ...
for %%P in (8001 5174) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%A >nul 2>&1
  )
)

REM --- Backend (Django) on :8001 ---
echo [2/3] اجرای سرور بک اند (Django) روی پورت 8001 ...
start "Backend - Django :8001" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001"

REM --- Frontend (Vite) on :5174 ---
echo [3/3] اجرای سرور فرانت (Vite) روی پورت 5174 ...
start "Frontend - Vite :5174" cmd /k "cd /d %~dp0frontend && npm run dev"

REM --- Wait a bit, then open the app in the default browser ---
echo.
echo چند لحظه صبر کنید تا سرورها بالا بیایند ...
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:5174"

echo.
echo ------------------------------------------------
echo   اپلیکیشن:        http://127.0.0.1:5174
echo   API و Swagger:   http://127.0.0.1:8001/api/docs/
echo   پنل ادمین:       http://127.0.0.1:8001/admin/
echo ------------------------------------------------
echo.
echo برای بستن سرورها، پنجره های Backend و Frontend را ببندید یا stop.bat را اجرا کنید.
echo این پنجره را می توانید ببندید.
pause

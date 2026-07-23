@echo off
chcp 65001 >nul
title کاغذ حساس نمابر مهر - راه اندازی سرورها
cd /d "%~dp0"

echo ================================================
echo   شرکت کاغذ حساس نمابر مهر - BI Platform
echo ================================================
echo.

REM --- Free ports 8000 and 5173 if something is already using them ---
echo [1/3] آزادسازی پورت های 8000 و 5173 ...
for %%P in (8000 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%A >nul 2>&1
  )
)

REM --- Backend (Django) on :8000 ---
echo [2/3] اجرای سرور بک اند (Django) روی پورت 8000 ...
start "Backend - Django :8000" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000"

REM --- Frontend (Vite) on :5173 ---
echo [3/3] اجرای سرور فرانت (Vite) روی پورت 5173 ...
start "Frontend - Vite :5173" cmd /k "cd /d "%~dp0frontend" && npm run dev"

REM --- Wait a bit, then open the app in the default browser ---
echo.
echo چند لحظه صبر کنید تا سرورها بالا بیایند ...
timeout /t 6 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo ------------------------------------------------
echo   اپلیکیشن:        http://localhost:5173
echo   API و Swagger:   http://localhost:8000/api/docs/
echo   پنل ادمین:       http://localhost:8000/admin/
echo ------------------------------------------------
echo.
echo برای بستن سرورها، پنجره های Backend و Frontend را ببندید.
echo این پنجره را می توانید ببندید.
pause

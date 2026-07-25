@echo off
chcp 65001 >nul
title کاغذ حساس نمابر مهر - نسخه 2 (CRM)
cd /d "%~dp0"

echo ================================================
echo   BI Platform - نسخه 2 (CRM)  -  8001 / 5174
echo ================================================
echo.

REM --- Free ports 8001 and 5174 (v1 on 8000/5173 is left alone) ---
echo [1/3] آزادسازی پورت های 8001 و 5174 ...
for %%P in (8001 5174) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%A >nul 2>&1
  )
)

REM --- Backend (Django) on :8001 ---
echo [2/3] اجرای سرور بک اند (Django) روی پورت 8001 ...
start "Backend v2 - Django :8001" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001"

REM --- Frontend (Vite) on :5174 ---
echo [3/3] اجرای سرور فرانت (Vite) روی پورت 5174 ...
start "Frontend v2 - Vite :5174" cmd /k "cd /d "%~dp0frontend" && npm run dev"

REM --- Wait a bit, then open the app in the default browser ---
echo.
echo چند لحظه صبر کنید تا سرورها بالا بیایند ...
timeout /t 6 /nobreak >nul
start "" "http://localhost:5174"

echo.
echo ------------------------------------------------
echo   اپلیکیشن:        http://localhost:5174
echo   API و Swagger:   http://localhost:8001/api/docs/
echo   پنل ادمین:       http://localhost:8001/admin/
echo ------------------------------------------------
echo.
echo برای بستن سرورها، پنجره های Backend و Frontend را ببندید.
echo این پنجره را می توانید ببندید.
pause

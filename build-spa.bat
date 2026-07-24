@echo off
chcp 65001 >nul
title ساخت فرانت برای دیپلوی
cd /d "%~dp0"

echo ================================================
echo   ساخت فرانت و آماده‌سازی برای دیپلوی
echo ================================================
echo.
echo مهم: deploy.sh روی سرور فرانت را build نمی‌کند.
echo هر بار که فرانت را تغییر دادید، این فایل را اجرا کنید،
echo بعد commit و push کنید تا تغییرات روی سایت بیاید.
echo.

echo [1/2] build فرانت ...
cd frontend
call npm run build
if errorlevel 1 (
  echo.
  echo ❌ build ناموفق بود. خطاها را بالا ببینید.
  pause
  exit /b 1
)
cd ..

echo.
echo [2/2] کپی خروجی در backend\spa ...
if exist "backend\spa" rmdir /s /q "backend\spa"
mkdir "backend\spa"
xcopy "frontend\dist\*" "backend\spa\" /e /i /q >nul

echo.
echo ✅ آماده شد. حالا:
echo     git add -A
echo     git commit -m "rebuild frontend"
echo     git push
echo.
echo و سپس روی سرور:  bash ~/bi-platform/deploy.sh
echo.
pause

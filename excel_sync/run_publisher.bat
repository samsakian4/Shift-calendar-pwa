@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo همگام‌ساز اکسل ← سایت  (برای توقف این پنجره را ببندید)
python publish.py --watch
pause

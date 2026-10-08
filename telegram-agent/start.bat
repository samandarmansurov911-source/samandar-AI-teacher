@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Kutubxonalar tekshirilmoqda...
python -m pip install -q -r requirements.txt
python start.py
pause

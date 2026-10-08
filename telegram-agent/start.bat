@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Kutubxonalar tekshirilmoqda, 1-2 daqiqa kuting...
python -m pip install -q -r requirements.txt
if errorlevel 1 echo XATOLIK: kutubxonalar o'rnatilmadi. Shu oynaning skrinshotini yuboring.
python start.py
echo.
set /p _="Oynani yopish uchun Enter bosing..."

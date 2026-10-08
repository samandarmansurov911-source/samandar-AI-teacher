"""Bir martalik: Telegram hisobingizga kirib TELEGRAM_SESSION satrini oladi.

Ishga tushirish:
    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... python login.py

Chiqqan satrni hech kimga bermang: u hisobingizga to'liq kirish huquqini beradi.
"""

import os

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


API_ID = int(os.environ.get("TELEGRAM_API_ID") or input("API ID: "))
API_HASH = os.environ.get("TELEGRAM_API_HASH") or input("API HASH: ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nTELEGRAM_SESSION (maxfiy saqlang!):\n")
    print(client.session.save())
    client.send_message("me", "✅ Telegram agent uchun sessiya yaratildi.")

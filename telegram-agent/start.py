"""Agentni bitta faylda ishga tushirish.

Birinchi marta: kalitlarni so'raydi, Telegram'ga kiradi va hammasini .env ga saqlaydi.
Keyingi safar: darhol agentni ishga tushiradi.
"""

import asyncio
import os
import re
import traceback
from pathlib import Path

ENV_FILE = Path(__file__).with_name(".env")


def load_env():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def save_env(values):
    ENV_FILE.write_text(
        "".join(f"{k}={v}\n" for k, v in values.items()),
        encoding="utf-8",
    )


# Bloknotdan "api_id: 123" ko'rinishida ko'chirilsa ham to'g'ri qiymatni ajratib olamiz
def clean_api_id(text):
    digits = re.sub(r"\D", "", text)
    return digits if 4 <= len(digits) <= 12 else None


def clean_api_hash(text):
    match = re.search(r"\b[0-9a-fA-F]{32}\b", text)
    return match.group(0).lower() if match else None


def clean_gemini_key(text):
    # "gemini: KALIT" kabi yozuvdan oxirgi bo'lakni olamiz
    parts = text.replace(":", " ").split()
    key = parts[-1].strip("'\"") if parts else ""
    return key if len(key) >= 20 else None


def ask(values, key, question, cleaner, hint):
    value = cleaner(values.get(key, "")) if values.get(key) else None
    while not value:
        value = cleaner(input(question))
        if not value:
            print(f"❌ Noto'g'ri. {hint}\n")
    values[key] = value
    save_env(values)


def main():
    values = load_env()

    ask(values, "TELEGRAM_API_ID", "Telegram api_id ni yozing (faqat raqam): ",
        clean_api_id, "api_id faqat raqamlardan iborat, masalan 21234567.")
    ask(values, "TELEGRAM_API_HASH", "Telegram api_hash ni yozing: ",
        clean_api_hash, "api_hash 32 ta harf va raqamdan iborat.")
    ask(values, "GEMINI_API_KEY", "Gemini API kalitini yozing: ",
        clean_gemini_key, "Gemini kalitini to'liq ko'chiring (u juda uzun bo'ladi).")

    if not values.get("TELEGRAM_SESSION"):
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient

        print("\nEndi Telegram hisobingizga kiramiz.")
        print("Telefon raqamni +998 bilan yozing, keyin Telegram'ga kelgan kodni kiriting.\n")
        with TelegramClient(
            StringSession(),
            int(values["TELEGRAM_API_ID"]),
            values["TELEGRAM_API_HASH"],
        ) as client:
            values["TELEGRAM_SESSION"] = client.session.save()
        save_env(values)
        print("\n✅ Telegram'ga kirildi va saqlandi.\n")

    os.environ.update(values)

    import agent
    asyncio.run(agent.main())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent to'xtatildi.")
    except Exception:
        print("\n❌ XATOLIK YUZ BERDI. Shu oynaning skrinshotini yuboring:\n")
        traceback.print_exc()

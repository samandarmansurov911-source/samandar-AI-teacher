"""Agentni bitta faylda ishga tushirish.

Birinchi marta: kalitlarni so'raydi, Telegram'ga kiradi va hammasini .env ga saqlaydi.
Keyingi safar: darhol agentni ishga tushiradi.
"""

import asyncio
import os
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


def ask(values, key, question):
    while not values.get(key):
        values[key] = input(question).strip()
    save_env(values)


def main():
    values = load_env()

    ask(values, "TELEGRAM_API_ID", "Telegram api_id ni yozing (faqat raqam): ")
    ask(values, "TELEGRAM_API_HASH", "Telegram api_hash ni yozing: ")
    ask(values, "GEMINI_API_KEY", "Gemini API kalitini yozing: ")

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
    main()

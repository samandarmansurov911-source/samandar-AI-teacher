"""
Qo'shimcha aiogram botlarini bot.py bilan bitta jarayonda ishga tushiradi.

Render'ning bepul tarifi servisni uxlatib qo'yadi, shuning uchun hamma botlar
uxlamaydigan bitta pulli servisda ishlaydi. main.py, speaking.py va vocab.py
faqat o'z tokeni berilgan bo'lsa ishga tushadi. Har biri alohida thread va
event loop'da ishlaydi: biri yiqilsa, qayta ko'tariladi va qolganlariga
ta'sir qilmaydi.
"""

import asyncio
import importlib
import logging
import os
import threading
import time

log = logging.getLogger("side_bots")

# (modul, token environment variable'i)
BOTS = [
    ("main", "ESSAY_BOT_TOKEN"),
    ("speaking", "SPEAKING_BOT_TOKEN"),
    ("vocab", "VOCAB_BOT_TOKEN"),
]

RESTART_DELAY = 10
MAX_RESTART_DELAY = 300


def _run(module_name):
    delay = RESTART_DELAY
    while True:
        started = time.monotonic()
        try:
            module = importlib.import_module(module_name)
            log.info("%s.py ishga tushdi", module_name)
            asyncio.run(module.dp.start_polling(module.bot, handle_signals=False))
            log.warning("%s.py polling to'xtadi", module_name)
        except BaseException:
            log.exception("%s.py yiqildi", module_name)
        if time.monotonic() - started > 600:
            delay = RESTART_DELAY
        log.info("%s.py %s soniyadan keyin qayta ishga tushadi", module_name, delay)
        time.sleep(delay)
        delay = min(delay * 2, MAX_RESTART_DELAY)


def start(main_token):
    """Tokeni berilgan har bir botni fon thread'ida ishga tushiradi."""
    seen = {main_token.strip(): "TELEGRAM_BOT_TOKEN"}
    for module_name, env in BOTS:
        token = os.environ.get(env, "").strip()
        if not token:
            log.info("%s.py: %s berilmagan, o'chiq", module_name, env)
            continue
        # Bitta token bilan ikkita bot polling qilsa, Telegram ikkalasini ham
        # "Conflict: terminated by other getUpdates request" bilan to'xtatadi.
        if token in seen:
            log.error("%s.py: %s %s bilan bir xil token, ishga tushirilmadi. "
                      "@BotFather'dan alohida token oling", module_name, env, seen[token])
            continue
        seen[token] = env
        threading.Thread(target=_run, args=(module_name,), name=module_name, daemon=True).start()

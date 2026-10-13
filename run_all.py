"""
Barcha botlarni bitta Render servisida ishga tushiradi.

bot.py (essay checker + kanal va Instagram menejerlari) doim ishlaydi.
main.py, speaking.py va vocab.py esa faqat o'z tokeni berilgan bo'lsa
ishga tushadi. Har bir bot alohida jarayonda ishlaydi va yiqilsa qayta
ko'tariladi, shuning uchun bittasidagi xato qolganlarini to'xtatmaydi.

Render "Start Command": python run_all.py
"""

import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (skript, token environment variable'i)
BOTS = [
    ("bot.py", "TELEGRAM_BOT_TOKEN"),
    ("main.py", "ESSAY_BOT_TOKEN"),
    ("speaking.py", "SPEAKING_BOT_TOKEN"),
    ("vocab.py", "VOCAB_BOT_TOKEN"),
]

RESTART_DELAY = 10
MAX_RESTART_DELAY = 300


def log(msg):
    print(f"[run_all] {msg}", flush=True)


def enabled_bots():
    seen = {}
    bots = []
    for script, env in BOTS:
        token = os.environ.get(env, "").strip()
        if not token:
            log(f"{script}: {env} berilmagan, o'tkazib yuborildi")
            continue
        # Bitta token bilan ikkita bot polling qilsa, Telegram ikkalasini ham
        # "Conflict: terminated by other getUpdates request" bilan to'xtatadi.
        if token in seen:
            log(f"{script}: {env} {seen[token]} bilan bir xil token, o'tkazib yuborildi. "
                "Har bir bot uchun @BotFather'dan alohida token oling")
            continue
        seen[token] = env
        bots.append(script)
    return bots


def start(script):
    log(f"{script} ishga tushirilmoqda")
    return subprocess.Popen([sys.executable, "-u", os.path.join(HERE, script)], cwd=HERE)


def main():
    scripts = enabled_bots()
    if not scripts:
        sys.exit("[run_all] Hech qanday bot tokeni berilmagan")

    procs = {s: start(s) for s in scripts}
    delays = {s: RESTART_DELAY for s in scripts}
    restart_at = {}
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        now = time.monotonic()
        for script, proc in procs.items():
            if script in restart_at:
                if now >= restart_at[script]:
                    del restart_at[script]
                    procs[script] = start(script)
                continue
            code = proc.poll()
            if code is None:
                continue
            log(f"{script} to'xtadi (kod {code}), {delays[script]} soniyadan keyin qayta ishga tushadi")
            restart_at[script] = now + delays[script]
            delays[script] = min(delays[script] * 2, MAX_RESTART_DELAY)
        time.sleep(1)

    for proc in procs.values():
        if proc.poll() is None:
            proc.terminate()
    for proc in procs.values():
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()

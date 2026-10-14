"""
Bitta Render servisida hamma narsani ishga tushiradi.

- bot.py: essay checker, kanal va Instagram menejerlari
- telegram-agent/agent.py: shaxsiy Telegram agenti. U writing, speaking,
  vocab va intizor botlarini ishga tushishi bilan o'zi yoqadi.

Ikkalasi alohida jarayonda ishlaydi va yiqilsa qayta ko'tariladi.
Render "Start Command": python start_all.py
"""

import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESTART_DELAY = 10
MAX_RESTART_DELAY = 300


def log(msg):
    print(f"[start_all] {msg}", flush=True)


def programs():
    progs = [("bot.py", os.path.join(HERE, "bot.py"), {})]
    agent_env = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")
    if all(os.environ.get(k) for k in agent_env):
        # Render faqat PORT ga qaraydi; agentning health serveri boshqa portda turadi
        port = int(os.environ.get("PORT", 10000)) + 1
        progs.append(("agent", os.path.join(HERE, "telegram-agent", "agent.py"), {"PORT": str(port)}))
    else:
        log("Telegram agent o'chiq: " + ", ".join(agent_env) + " kerak")
    return progs


def start(name, path, extra_env):
    log(f"{name} ishga tushirilmoqda")
    env = {**os.environ, **extra_env}
    return subprocess.Popen([sys.executable, "-u", path], cwd=os.path.dirname(path), env=env)


def main():
    progs = {name: (path, env) for name, path, env in programs()}
    procs = {name: start(name, *progs[name]) for name in progs}
    started = {name: time.monotonic() for name in progs}
    delays = {name: RESTART_DELAY for name in progs}
    restart_at = {}
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        now = time.monotonic()
        for name in progs:
            if name in restart_at:
                if now >= restart_at[name]:
                    del restart_at[name]
                    procs[name] = start(name, *progs[name])
                    started[name] = now
                continue
            code = procs[name].poll()
            if code is None:
                continue
            if now - started[name] > 600:
                delays[name] = RESTART_DELAY
            log(f"{name} to'xtadi (kod {code}), {delays[name]} soniyadan keyin qayta ishga tushadi")
            restart_at[name] = now + delays[name]
            delays[name] = min(delays[name] * 2, MAX_RESTART_DELAY)
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

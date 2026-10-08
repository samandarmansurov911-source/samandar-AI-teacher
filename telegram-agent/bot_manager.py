"""O'quvchilar botlarini agent ichida yoqish/o'chirish.

Har bir bot faqat ustoz buyrug'i bilan yonadi va server qayta ishga tushsa o'chiq turadi.
"""

import asyncio
import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

BOTS = {
    "essay": {"title": "Essay checker", "module": "bot", "kind": "ptb", "env": "TELEGRAM_BOT_TOKEN"},
    "writing": {"title": "Writing teacher", "module": "bots.writing", "kind": "aiogram", "env": "WRITING_BOT_TOKEN"},
    "speaking": {"title": "Speaking checker", "module": "bots.speaking", "kind": "aiogram", "env": "SPEAKING_BOT_TOKEN"},
    "vocab": {"title": "Vocab quiz", "module": "bots.vocab", "kind": "aiogram", "env": "VOCAB_BOT_TOKEN"},
}


class BotManager:

    def __init__(self, tz):
        self.tz = tz
        self.running = {}  # nomi -> {"stop": coroutine function, "since": datetime}

    def _check(self, name):
        if name not in BOTS:
            raise ValueError(f"'{name}' degan bot yo'q. Botlar: {', '.join(BOTS)}")
        info = BOTS[name]
        if not (REPO_ROOT / (info["module"].replace(".", "/") + ".py")).exists():
            raise RuntimeError("Bot fayllari topilmadi: botlar faqat serverda (Render) ishlaydi.")
        if not os.environ.get(info["env"]):
            raise RuntimeError(f"Serverda {info['env']} kaliti kiritilmagan.")
        return info

    def _load(self, module_name):
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        # Har safar qayta yuklaymiz: bot va dispatcher yangidan yaratiladi
        if module_name in sys.modules:
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)

    async def _start_ptb(self, mod):
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        app = Application.builder().token(mod.TOKEN).build()
        app.add_handler(CommandHandler("start", mod.start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mod.check_essay))
        await app.initialize()
        await app.start()
        # Bot o'chiq paytda kelgan eski xabarlarni tashlab yuboramiz
        await app.updater.start_polling(drop_pending_updates=True)

        async def stop():
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        return stop

    async def _start_aiogram(self, mod):
        await mod.bot.get_me()  # token noto'g'ri bo'lsa shu yerda xato beradi
        await mod.bot.delete_webhook(drop_pending_updates=True)
        task = asyncio.create_task(mod.dp.start_polling(mod.bot, handle_signals=False))
        await asyncio.sleep(0)  # polling boshlanishiga imkon beramiz

        async def stop():
            try:
                await mod.dp.stop_polling()
                await asyncio.wait_for(task, timeout=10)
            except Exception:
                # To'xtamasa, majburan to'xtatamiz
                task.cancel()
            await mod.bot.session.close()

        return stop

    async def start(self, name):
        if name == "all":
            return await self._for_all(self.start, only_stopped=True)
        if name in self.running:
            return f"{BOTS[name]['title']} allaqachon yoniq."

        info = self._check(name)
        mod = self._load(info["module"])
        if info["kind"] == "ptb":
            stop = await self._start_ptb(mod)
        else:
            stop = await self._start_aiogram(mod)

        self.running[name] = {"stop": stop, "since": datetime.now(self.tz)}
        return f"✅ {BOTS[name]['title']} yoqildi."

    async def stop(self, name):
        if name == "all":
            return await self._for_all(self.stop, only_stopped=False)
        if name not in BOTS:
            raise ValueError(f"'{name}' degan bot yo'q. Botlar: {', '.join(BOTS)}")
        if name not in self.running:
            return f"{BOTS[name]['title']} allaqachon o'chiq."

        await self.running.pop(name)["stop"]()
        return f"⛔ {BOTS[name]['title']} o'chirildi."

    async def _for_all(self, action, only_stopped):
        results = []
        for name in BOTS:
            if only_stopped and (name in self.running or not os.environ.get(BOTS[name]["env"])):
                continue
            if not only_stopped and name not in self.running:
                continue
            try:
                results.append(await action(name))
            except Exception as e:
                results.append(f"❌ {BOTS[name]['title']}: {e}")
        return "\n".join(results) or "O'zgartiradigan bot yo'q."

    def status(self):
        lines = []
        for name, info in BOTS.items():
            if name in self.running:
                state = f"🟢 yoniq ({self.running[name]['since']:%H:%M} dan beri)"
            elif not os.environ.get(info["env"]):
                state = f"⚪ sozlanmagan ({info['env']} yo'q)"
            else:
                state = "🔴 o'chiq"
            lines.append(f"{info['title']} [{name}]: {state}")
        return "\n".join(lines)

    async def stop_everything(self):
        for name in list(self.running):
            try:
                await self.stop(name)
            except Exception as e:
                print(f"{name} to'xtatishda xato: {e}")

"""Essay checker bot'ni (repo ildizidagi bot.py) agent ichida yoqish/o'chirish."""

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class EssayBotController:

    def __init__(self, tz):
        self.tz = tz
        self.app = None
        self.started_at = None

    async def start(self):
        if self.app:
            return "Essay bot allaqachon yoniq."

        if not (REPO_ROOT / "bot.py").exists():
            raise RuntimeError("bot.py topilmadi: essay bot faqat serverda (Render) ishlaydi.")
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        try:
            import bot as essay
        except KeyError as e:
            raise RuntimeError(f"Serverda {e} kaliti kiritilmagan.") from None

        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        app = Application.builder().token(essay.TOKEN).build()
        app.add_handler(CommandHandler("start", essay.start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, essay.check_essay))

        await app.initialize()
        await app.start()
        # Bot o'chiq paytda kelgan eski xabarlarni tashlab yuboramiz
        await app.updater.start_polling(drop_pending_updates=True)

        self.app = app
        self.started_at = datetime.now(self.tz)
        return "✅ Essay bot yoqildi. O'quvchilar endi essay yubora oladi."

    async def stop(self):
        if not self.app:
            return "Essay bot allaqachon o'chiq."

        app, self.app = self.app, None
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        self.started_at = None
        return "⛔ Essay bot o'chirildi."

    def status(self):
        if not self.app:
            return "Essay bot o'chiq."
        return f"Essay bot yoniq ({self.started_at:%H:%M} dan beri)."

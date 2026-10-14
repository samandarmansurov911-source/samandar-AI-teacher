"""Oddiy buyruqlarni Gemini'siz, darhol bajarish (botlarni yoqish/o'chirish/holati)."""

import re

# Har bir bot uchun foydalanuvchi ishlatishi mumkin bo'lgan so'zlar
BOT_ALIASES = {
    "writing": ("writing", "essay", "esse", "yozish"),
    "speaking": ("speaking", "gapirish", "ovoz"),
    "vocab": ("vocab", "soz", "lugat", "word"),
    "intizor": ("intizor", "tolov"),
    "all": ("hamma", "barcha", "hammasi", "all"),
}

STOP_WORDS = ("ochir", "toxtat")
START_WORDS = ("yoq", "ishga tushir")
STATUS_WORDS = ("holat", "yoniq", "qaysi bot", "status")


def normalize(text):
    # Apostroflarning har xil turlarini olib tashlaymiz: o'chir / o‘chir / o`chir -> ochir
    return re.sub(r"[\'‘’`ʻʼ]", "", text.lower()).strip()


def has_word(text, words):
    return any(re.search(rf"\b{re.escape(w)}", text) for w in words)


def parse(command):
    """("start"|"stop", nom) yoki ("status", None) qaytaradi; tushunilmasa None."""
    text = normalize(command)
    if "bot" not in text and not any(has_word(text, a) for a in BOT_ALIASES.values()):
        return None

    names = [name for name, aliases in BOT_ALIASES.items() if has_word(text, aliases)]
    if has_word(text, STATUS_WORDS) and not has_word(text, STOP_WORDS + ("yoq ",)):
        return ("status", None)
    if len(names) != 1:
        return None

    if has_word(text, STOP_WORDS):
        return ("stop", names[0])
    if has_word(text, START_WORDS):
        return ("start", names[0])
    return None


async def run_quick(tg, command):
    parsed = parse(command)
    if not parsed:
        return None
    action, name = parsed
    if action == "status":
        return tg.bots.status()
    try:
        if action == "start":
            return await tg.bots.start(name)
        return await tg.bots.stop(name)
    except Exception as e:
        return f"❌ {e}"

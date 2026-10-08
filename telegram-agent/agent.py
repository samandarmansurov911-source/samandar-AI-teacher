import asyncio
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession

from tools import TOOL_SCHEMAS, TelegramTools


API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ["TELEGRAM_SESSION"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
PREFIX = os.environ.get("AGENT_PREFIX", ".")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))

MAX_STEPS = 10
MAX_HISTORY = 40

gemini = genai.Client(api_key=GEMINI_API_KEY)
client: TelegramClient = None
tg: TelegramTools = None


SYSTEM_PROMPT = """
Siz foydalanuvchining shaxsiy Telegram agentisiz. Foydalanuvchi sizga o'zining
"Saqlangan xabarlar" (Saved Messages) chatidan buyruq beradi va siz uning
Telegram hisobini tool'lar orqali boshqarasiz.

QOIDALAR:
- O'zbek tilida, qisqa va aniq javob bering.
- Topshiriqni bajarish uchun kerakli tool'larni o'zingiz chaqiring.
  Masalan, "Alisherga salom yoz" desa, send_message(chat="Alisher", text="Salom") ni chaqiring.
- Chat nomi noaniq bo'lsa yoki bir nechta mos chat topilsa, foydalanuvchidan so'rang.
- Xabarlarni o'chirish (delete_messages) va chatdan chiqish (leave_chat) dan oldin
  har doim foydalanuvchidan aniq tasdiq oling.
- Foydalanuvchi so'ramagan xabarni hech kimga yubormang.
- Xulosa so'ralsa, avval read_messages bilan xabarlarni o'qing, keyin qisqa xulosa qiling.
- Hech qachon ma'lumot to'qib chiqarmang: faqat tool natijalariga tayaning.
- "Bot" yoki "botlar" deyilsa, bu o'quvchilar botlari (essay, writing, speaking, vocab):
  start_bot / stop_bot / bots_status tool'larini ishlating. "Hamma botlar" = name="all".
  Qaysi bot ekani aniq bo'lmasa (masalan faqat "botni yoq"), qaysi birini so'rang.
- Bajarilgan ishni oxirida qisqa qilib ayting.
"""


AUTO_REPLY_PROMPT = """
Siz foydalanuvchi nomidan uning Telegramidagi shaxsiy xabarlarga javob beryapsiz.
Foydalanuvchining ko'rsatmasi: {instructions}

Qoidalar:
- Suhbatdosh yozgan tilda, qisqa va tabiiy javob bering.
- O'zingizni AI deb tanishtirmang, lekin aniq bilmagan narsangizni va'da qilmang.
- Pul, parol, kod, shaxsiy ma'lumot so'ralsa, hech narsa bermang va
  "keyinroq o'zim yozaman" mazmunida javob bering.
- Faqat javob matnini qaytaring.

Suhbat (eskidan yangiga):
{history}
"""


history: list[types.Content] = []
lock = asyncio.Lock()


# ---------------------------------------------------------
# GEMINI AGENT SIKLI
# ---------------------------------------------------------

def to_schema(s):
    # google-genai'ning eski versiyalari ham tushunadigan Schema obyekti
    kwargs = {"type": s["type"].upper()}
    if "description" in s:
        kwargs["description"] = s["description"]
    if s.get("properties"):
        kwargs["properties"] = {k: to_schema(v) for k, v in s["properties"].items()}
    if "items" in s:
        kwargs["items"] = to_schema(s["items"])
    if s.get("required"):
        kwargs["required"] = s["required"]
    return types.Schema(**kwargs)


def tool_config():
    declarations = []
    for t in TOOL_SCHEMAS:
        decl = {"name": t["name"], "description": t["description"]}
        # Parametrsiz tool'larga bo'sh OBJECT yubormaymiz
        if t["parameters"].get("properties"):
            decl["parameters"] = to_schema(t["parameters"])
        declarations.append(types.FunctionDeclaration(**decl))
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + f"\nHozirgi vaqt: {now}",
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


async def call_tool(name, args):
    func = getattr(tg, name, None)
    if func is None or name not in {t["name"] for t in TOOL_SCHEMAS}:
        return {"error": f"Noma'lum tool: {name}"}
    try:
        return {"result": await func(**args)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def trim_history():
    # Tarixni yangi foydalanuvchi buyrug'idan boshlanadigan qilib qisqartiramiz
    while len(history) > MAX_HISTORY:
        history.pop(0)
        while history and not (
            history[0].role == "user" and any(p.text for p in history[0].parts)
        ):
            history.pop(0)


async def run_agent(command):
    history.append(types.Content(role="user", parts=[types.Part(text=command)]))
    config = tool_config()
    actions = []

    for _ in range(MAX_STEPS):
        response = await gemini.aio.models.generate_content(
            model=MODEL,
            contents=history,
            config=config,
        )
        content = response.candidates[0].content
        history.append(content)

        calls = response.function_calls
        if not calls:
            trim_history()
            return response.text or "✅ Bajarildi.", actions

        parts = []
        for call in calls:
            args = dict(call.args or {})
            result = await call_tool(call.name, args)
            actions.append(f"{call.name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")
            print("TOOL:", call.name, args, "->", str(result)[:200])
            parts.append(types.Part.from_function_response(name=call.name, response=result))

        history.append(types.Content(role="user", parts=parts))

    trim_history()
    return "⚠️ Topshiriq juda ko'p qadam talab qildi, to'xtatdim. Aniqroq qilib yozing.", actions


# ---------------------------------------------------------
# TELEGRAM HANDLERLAR
# ---------------------------------------------------------

async def send_long(chat, text):
    for i in range(0, len(text), 4000):
        await client.send_message(chat, text[i:i + 4000])


async def on_command(event):
    # Faqat "Saqlangan xabarlar" dagi prefiks bilan boshlangan buyruqlar
    if event.chat_id != tg.my_id:
        return
    text = event.raw_text or ""
    if not text.startswith(PREFIX):
        return

    command = text[len(PREFIX):].strip()
    if not command:
        return

    if command.lower() in ("reset", "yangi"):
        history.clear()
        await client.send_message("me", "🤖 Suhbat tarixi tozalandi.")
        return

    async with lock:
        try:
            answer, actions = await run_agent(command)
        except Exception as e:
            print("ERROR:", e)
            answer, actions = f"❌ Xatolik: {e}", []

    footer = ""
    if actions:
        footer = "\n\n🛠 " + "\n🛠 ".join(a[:150] for a in actions)
    await send_long("me", "🤖 " + answer + footer)


async def on_private_message(event):
    if not tg.auto_reply_enabled or not event.is_private:
        return
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or sender.id == tg.my_id:
        return

    messages = [m async for m in client.iter_messages(event.chat_id, limit=15)]
    chat_log = "\n".join(tg._format_message(m) for m in reversed(messages))

    try:
        response = await gemini.aio.models.generate_content(
            model=MODEL,
            contents=AUTO_REPLY_PROMPT.format(
                instructions=tg.auto_reply_instructions or "Umumiy, xushmuomala javob ber.",
                history=chat_log,
            ),
        )
        reply = (response.text or "").strip()
    except Exception as e:
        print("AUTO-REPLY ERROR:", e)
        return

    if not reply:
        return

    await event.reply(reply)
    name = utils.get_display_name(sender)
    await send_long(
        "me",
        f"🤖 Avto-javob → {name}\n\n💬 U: {event.raw_text[:300]}\n↩️ Men: {reply}",
    )


# ---------------------------------------------------------
# RENDER HEALTH CHECK SERVER
# ---------------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram agent is running!")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

async def main():
    global client, tg

    threading.Thread(target=run_health_server, daemon=True).start()

    # Client event loop ichida yaratilishi kerak
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    tg = TelegramTools(client, TZ)

    await client.start()
    me = await client.get_me()
    tg.my_id = me.id
    # Botlar natijalarni shu odamga (ustozga) yuboradi
    os.environ.setdefault("TEACHER_ID", str(me.id))

    client.add_event_handler(on_command, events.NewMessage(outgoing=True))
    client.add_event_handler(on_private_message, events.NewMessage(incoming=True))

    print(f"Telegram agent ishga tushdi: {utils.get_display_name(me)}")
    await client.send_message(
        "me",
        f"🤖 Agent ishga tushdi. Buyruqni shu yerga '{PREFIX}' bilan boshlab yozing.\n"
        f"Masalan: {PREFIX}qaysi chatlarda o'qilmagan xabar bor?\n"
        f"O'quvchilar botlari o'chiq. Yoqish uchun: {PREFIX}hamma botlarni yoq",
    )
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())

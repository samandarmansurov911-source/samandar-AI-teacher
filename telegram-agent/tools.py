"""Telegram hisobi ustida agent bajara oladigan amallar (Telethon orqali)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telethon import TelegramClient, utils

from bot_manager import BOTS, BotManager


class TelegramTools:

    def __init__(self, client: TelegramClient, tz: ZoneInfo):
        self.client = client
        self.tz = tz
        self.my_id = None
        self.bots = BotManager(tz)
        self.auto_reply_enabled = False
        self.auto_reply_instructions = ""

    # ---------------------------------------------------------
    # YORDAMCHI FUNKSIYALAR
    # ---------------------------------------------------------

    async def resolve_chat(self, chat):
        """Chat nomi, @username, link yoki ID bo'yicha chatni topadi."""
        s = str(chat).strip()

        if s.lower() in ("me", "saved", "saved messages", "saqlangan"):
            return await self.client.get_entity("me")

        if s.lstrip("-").isdigit():
            return await self.client.get_entity(int(s))

        if s.startswith("@") or "t.me/" in s or s.startswith("+"):
            return await self.client.get_entity(s)

        exact, partial = [], []
        async for dialog in self.client.iter_dialogs():
            name = (dialog.name or "").lower()
            if name == s.lower():
                exact.append(dialog)
            elif s.lower() in name:
                partial.append(dialog)

        if len(exact) == 1:
            return exact[0].entity
        matches = exact or partial
        if len(matches) == 1:
            return matches[0].entity
        if len(matches) > 1:
            options = ", ".join(f"{d.name} (id={d.id})" for d in matches[:10])
            raise ValueError(f"'{s}' bo'yicha bir nechta chat topildi: {options}. Aniqrog'ini ayting.")

        return await self.client.get_entity(s)

    def _format_message(self, msg):
        date = msg.date.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        if msg.out:
            sender = "Men"
        elif msg.sender:
            sender = utils.get_display_name(msg.sender)
        else:
            sender = "Noma'lum"

        text = msg.message or ""
        if msg.media:
            text = f"[media] {text}".strip()

        return f"[id={msg.id}] {date} {sender}: {text}"

    # ---------------------------------------------------------
    # AGENT TOOL'LARI
    # ---------------------------------------------------------

    async def get_me(self):
        me = await self.client.get_me()
        return {
            "id": me.id,
            "name": utils.get_display_name(me),
            "username": me.username,
            "phone": me.phone,
        }

    async def list_chats(self, limit=20, unread_only=False):
        result = []
        async for dialog in self.client.iter_dialogs(limit=None if unread_only else limit):
            if unread_only and dialog.unread_count == 0:
                continue

            kind = "kanal" if dialog.is_channel and not dialog.is_group else (
                "guruh" if dialog.is_group else "shaxsiy"
            )
            last = (dialog.message.message or "[media]") if dialog.message else ""
            result.append(
                f"{dialog.name} (id={dialog.id}, {kind}, o'qilmagan={dialog.unread_count}): "
                f"{last[:100]}"
            )
            if len(result) >= limit:
                break

        return "\n".join(result) or "Chatlar topilmadi."

    async def read_messages(self, chat, limit=20):
        entity = await self.resolve_chat(chat)
        messages = [m async for m in self.client.iter_messages(entity, limit=limit)]
        lines = [self._format_message(m) for m in reversed(messages)]
        return "\n".join(lines) or "Xabarlar yo'q."

    async def send_message(self, chat, text, reply_to_message_id=None, schedule_in_minutes=0):
        entity = await self.resolve_chat(chat)
        schedule = None
        if schedule_in_minutes and schedule_in_minutes > 0:
            schedule = datetime.now(timezone.utc) + timedelta(minutes=schedule_in_minutes)

        msg = await self.client.send_message(
            entity,
            text,
            reply_to=reply_to_message_id,
            schedule=schedule,
        )
        name = utils.get_display_name(entity)
        if schedule:
            return f"Xabar '{name}' ga {schedule_in_minutes} daqiqadan keyin yuborilishi rejalashtirildi."
        return f"Xabar '{name}' ga yuborildi (id={msg.id})."

    async def edit_message(self, chat, message_id, text):
        entity = await self.resolve_chat(chat)
        await self.client.edit_message(entity, message_id, text)
        return "Xabar tahrirlandi."

    async def delete_messages(self, chat, message_ids):
        entity = await self.resolve_chat(chat)
        await self.client.delete_messages(entity, message_ids)
        return f"{len(message_ids)} ta xabar o'chirildi."

    async def forward_messages(self, from_chat, message_ids, to_chat):
        source = await self.resolve_chat(from_chat)
        target = await self.resolve_chat(to_chat)
        await self.client.forward_messages(target, message_ids, source)
        return f"{len(message_ids)} ta xabar '{utils.get_display_name(target)}' ga yuborildi."

    async def search_messages(self, query, chat=None, limit=20):
        entity = await self.resolve_chat(chat) if chat else None
        lines = []
        async for msg in self.client.iter_messages(entity, search=query, limit=limit):
            prefix = ""
            if entity is None and msg.chat:
                prefix = f"<{utils.get_display_name(msg.chat)}, chat_id={msg.chat_id}> "
            lines.append(prefix + self._format_message(msg))
        return "\n".join(lines) or "Hech narsa topilmadi."

    async def mark_as_read(self, chat):
        entity = await self.resolve_chat(chat)
        await self.client.send_read_acknowledge(entity)
        return f"'{utils.get_display_name(entity)}' o'qilgan deb belgilandi."

    async def get_chat_info(self, chat):
        entity = await self.resolve_chat(chat)
        return {
            "id": utils.get_peer_id(entity),
            "name": utils.get_display_name(entity),
            "username": getattr(entity, "username", None),
            "type": type(entity).__name__,
            "phone": getattr(entity, "phone", None),
            "participants_count": getattr(entity, "participants_count", None),
        }

    async def join_chat(self, link_or_username):
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest

        s = link_or_username.strip()
        if "/+" in s or "joinchat/" in s:
            invite_hash = s.rstrip("/").split("/")[-1].lstrip("+")
            await self.client(ImportChatInviteRequest(invite_hash))
        else:
            await self.client(JoinChannelRequest(await self.client.get_entity(s)))
        return "Chatga qo'shildingiz."

    async def leave_chat(self, chat):
        entity = await self.resolve_chat(chat)
        await self.client.delete_dialog(entity)
        return f"'{utils.get_display_name(entity)}' dan chiqildi."

    async def set_auto_reply(self, enabled, instructions=""):
        self.auto_reply_enabled = bool(enabled)
        if instructions:
            self.auto_reply_instructions = instructions
        if self.auto_reply_enabled:
            return f"Avto-javob yoqildi. Ko'rsatma: {self.auto_reply_instructions or '(umumiy)'}"
        return "Avto-javob o'chirildi."

    async def start_bot(self, name):
        return await self.bots.start(name)

    async def stop_bot(self, name):
        return await self.bots.stop(name)

    async def bots_status(self):
        return self.bots.status()


# ---------------------------------------------------------
# GEMINI UCHUN TOOL TAVSIFLARI
# ---------------------------------------------------------

CHAT = {"type": "string", "description": "Chat nomi, @username, t.me link, ID yoki 'me' (Saqlangan xabarlar)."}
BOT_NAME = {
    "type": "string",
    "description": "Bot: " + ", ".join(f"{k} ({v['title']})" for k, v in BOTS.items()) + ", yoki hammasi uchun 'all'.",
}
IDS = {"type": "array", "items": {"type": "integer"}, "description": "Xabar ID'lari."}

TOOL_SCHEMAS = [
    {
        "name": "get_me",
        "description": "Hisob egasining ma'lumotlarini qaytaradi.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_chats",
        "description": "Oxirgi chatlar ro'yxati: nomi, ID, turi, o'qilmagan xabarlar soni va oxirgi xabar.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Nechta chat (standart 20)."},
                "unread_only": {"type": "boolean", "description": "Faqat o'qilmagan xabari bor chatlar."},
            },
        },
    },
    {
        "name": "read_messages",
        "description": "Chatdagi oxirgi xabarlarni o'qiydi (eskidan yangiga).",
        "parameters": {
            "type": "object",
            "properties": {
                "chat": CHAT,
                "limit": {"type": "integer", "description": "Nechta xabar (standart 20)."},
            },
            "required": ["chat"],
        },
    },
    {
        "name": "send_message",
        "description": "Chatga xabar yuboradi. Javob qaytarish yoki keyinroq yuborishni rejalashtirish mumkin.",
        "parameters": {
            "type": "object",
            "properties": {
                "chat": CHAT,
                "text": {"type": "string"},
                "reply_to_message_id": {"type": "integer", "description": "Qaysi xabarga javob (ixtiyoriy)."},
                "schedule_in_minutes": {"type": "integer", "description": "Necha daqiqadan keyin yuborish (ixtiyoriy)."},
            },
            "required": ["chat", "text"],
        },
    },
    {
        "name": "edit_message",
        "description": "O'zingiz yuborgan xabarni tahrirlaydi.",
        "parameters": {
            "type": "object",
            "properties": {"chat": CHAT, "message_id": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["chat", "message_id", "text"],
        },
    },
    {
        "name": "delete_messages",
        "description": "Xabarlarni o'chiradi. Faqat foydalanuvchi aniq tasdiqlagandan keyin chaqiring.",
        "parameters": {
            "type": "object",
            "properties": {"chat": CHAT, "message_ids": IDS},
            "required": ["chat", "message_ids"],
        },
    },
    {
        "name": "forward_messages",
        "description": "Xabarlarni bir chatdan boshqasiga forward qiladi.",
        "parameters": {
            "type": "object",
            "properties": {"from_chat": CHAT, "message_ids": IDS, "to_chat": CHAT},
            "required": ["from_chat", "message_ids", "to_chat"],
        },
    },
    {
        "name": "search_messages",
        "description": "Xabarlarni matn bo'yicha qidiradi. chat berilmasa, barcha chatlardan qidiradi.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "chat": CHAT,
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mark_as_read",
        "description": "Chatni o'qilgan deb belgilaydi.",
        "parameters": {"type": "object", "properties": {"chat": CHAT}, "required": ["chat"]},
    },
    {
        "name": "get_chat_info",
        "description": "Chat yoki foydalanuvchi haqida ma'lumot.",
        "parameters": {"type": "object", "properties": {"chat": CHAT}, "required": ["chat"]},
    },
    {
        "name": "join_chat",
        "description": "Kanal yoki guruhga @username yoki taklif linki orqali qo'shiladi.",
        "parameters": {
            "type": "object",
            "properties": {"link_or_username": {"type": "string"}},
            "required": ["link_or_username"],
        },
    },
    {
        "name": "leave_chat",
        "description": "Guruh/kanaldan chiqadi yoki chatni o'chiradi. Faqat foydalanuvchi aniq tasdiqlagandan keyin chaqiring.",
        "parameters": {"type": "object", "properties": {"chat": CHAT}, "required": ["chat"]},
    },
    {
        "name": "set_auto_reply",
        "description": "Shaxsiy chatlarga kelgan xabarlarga foydalanuvchi nomidan avtomatik javob berishni yoqadi/o'chiradi.",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "instructions": {
                    "type": "string",
                    "description": "Qanday javob berish kerakligi, masalan: 'Men darsdaman, 18:00 dan keyin yozaman deb ayt'.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "start_bot",
        "description": "O'quvchilar botini yoqadi ('botni yoq', 'vocabni yoq', 'hamma botlarni yoq').",
        "parameters": {"type": "object", "properties": {"name": BOT_NAME}, "required": ["name"]},
    },
    {
        "name": "stop_bot",
        "description": "O'quvchilar botini o'chiradi ('botni o'chir', 'hamma botlarni o'chir').",
        "parameters": {"type": "object", "properties": {"name": BOT_NAME}, "required": ["name"]},
    },
    {
        "name": "bots_status",
        "description": "Qaysi o'quvchilar botlari yoniq yoki o'chiqligini ko'rsatadi.",
        "parameters": {"type": "object", "properties": {}},
    },
]

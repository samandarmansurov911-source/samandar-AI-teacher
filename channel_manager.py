"""
Autonomous Telegram English channel manager.

Runs inside the same process as bot.py (python-telegram-bot JobQueue) and,
on a schedule, decides what the channel needs, writes the post with Gemini,
has it checked by a second "strict editor" pass, publishes it and remembers
what was posted so future posts stay varied.

Environment variables:
    CHANNEL_ID          @channel_username or -100... id (required to enable)
    ADMIN_ID            owner's Telegram user id (alerts, memory backup, commands)
    POST_TIMES          daily posting times, default "08:30,13:30,19:30"
    TIMEZONE            default "Asia/Tashkent"
    GEMINI_MODEL        default "gemini-3.1-flash-lite"
    EXPLANATION_LANGUAGE  language for short explanations, default "Uzbek"
    TREND_RESEARCH      "1" (default) to refresh trend notes weekly via Google Search
    MEMORY_FILE         default "channel_memory.json"
"""

import asyncio
import difflib
import html
import io
import json
import logging
import os
import random
import re
import time
import uuid
from collections import Counter
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types as genai_types
from telegram import (
    InputMediaDocument,
    LinkPreviewOptions,
    ReplyParameters,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageReactionHandler,
    PollHandler,
    filters,
)

from tg_backup import find_pinned_document

log =logging.getLogger("channel_manager")


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
ADMIN_ID = int(os.environ["ADMIN_ID"]) if os.environ.get("ADMIN_ID") else None
POST_TIMES = os.environ.get("POST_TIMES", "08:30,13:30,19:30")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
EXPLANATION_LANGUAGE = os.environ.get("EXPLANATION_LANGUAGE", "Uzbek")
TREND_RESEARCH = os.environ.get("TREND_RESEARCH", "1") == "1"
MEMORY_FILE = os.environ.get("MEMORY_FILE", "channel_memory.json")

BACKUP_FILENAME = "channel_memory.json"
MAX_POSTS_KEPT = 400
MAX_ATTEMPTS = 3
SLOT_CATCHUP_WINDOW = timedelta(hours=3)
SLOT_MAX_TRIES = 3
SLOT_RETRY_GAP = timedelta(minutes=20)
ALERT_COOLDOWN = 6 * 3600

PILLARS = [
    "vocabulary",
    "grammar",
    "quiz",
    "speaking",
    "writing",
    "reading",
    "motivation",
    "english_fact",
    "challenge",
    "error_correction",
]

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
LEVEL_BADGES = {
    "A1": "⚪ A1", "A2": "🟢 A2", "B1": "🔵 B1",
    "B2": "🟣 B2", "C1": "🔴 C1", "C2": "⚫ C2",
}

FORMATS = ["text", "text_spoiler", "text_answer_later", "quiz_poll"]

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "blockquote", "span",
}


# ---------------------------------------------------------
# PROMPTS
# ---------------------------------------------------------

MANAGER_BRIEF = f"""
You are the autonomous manager of an English-learning Telegram channel run by
Samandar Teacher. You act as content strategist, English teacher, quiz creator,
editor and scheduler. The owner does not choose topics; you decide what the
channel needs right now.

Audience: Uzbek-speaking English learners, mostly A2-C1. The main content is
in English. Short explanations, translations or tips may be in
{EXPLANATION_LANGUAGE} (Latin script) when that genuinely helps understanding.

Content pillars: vocabulary (daily words, synonyms, antonyms, collocations,
phrasal verbs, idioms, academic/IELTS words, confused words, word families),
grammar (tips, common mistakes, mini lessons, transformations), quiz
(vocabulary/grammar/fill-in/find-the-mistake/synonym/translation/IELTS-style),
speaking (IELTS/CEFR Part 1/2/3, cue cards, model answers, natural phrases),
writing (essay topics, ideas, linking phrases, sentence improvement, common
mistakes), reading (short passage + MCQ or True/False/Not Given), motivation
(concrete, tied to discipline, consistency, daily practice - never empty
quotes), english_fact (etymology, pronunciation, British vs American),
challenge (translate / correct / complete / use this word), error_correction
(❌ wrong ✅ right + short why).

Brand voice: knowledgeable, friendly, demanding teacher. Professional, clear,
practical, sometimes lightly humorous. No excessive slang, no clickbait, no
fake claims, no exaggerated promises, never childish.

Rules: every post must be original (no copying other channels or teachers),
100% accurate, and useful. Mix accessible and challenging content. Do not make
every post IELTS-focused. Calls to action are welcome but not in every post.
"""

FORMAT_RULES = """
Telegram formatting rules for post_html / answer_reveal_html:
- Use ONLY Telegram HTML tags: <b>, <i>, <u>, <s>, <code>, <blockquote>,
  <tg-spoiler>. No Markdown (no ** or __), no <br>, <p>, <ul>, <li>, <h1>.
- Use real newlines for line breaks. Escape a literal < or & as &lt; &amp;.
- Short paragraphs, clear heading, numbered lists where useful, blank lines
  between blocks. Emojis are fine but do not overload. Vary the visual
  structure; do not make every post look the same.
- Show the level badge near the top when useful, e.g. "🔵 B1".
- Keep visible text under 2500 characters.
Formats:
- text: normal post.
- text_spoiler: the post contains a task; put the answer inside <tg-spoiler>.
- text_answer_later: the post contains a task with NO answer; put the answer
  and a short explanation in answer_reveal_html (it is posted later as a reply).
- quiz_poll: set use_poll=true. post_html may be a short intro (or empty).
  poll_question <= 280 chars, 3-4 options, each <= 90 chars, exactly one
  correct option, poll_explanation <= 190 chars. Plain text only in the poll.
For non-poll formats set use_poll=false and leave poll fields empty.
For formats other than text_answer_later leave answer_reveal_html empty.
"""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "content_type": {"type": "string", "enum": PILLARS},
        "subtype": {"type": "string"},
        "level": {"type": "string", "enum": LEVELS},
        "topic": {"type": "string"},
        "format": {"type": "string", "enum": FORMATS},
        "exam_focus": {"type": "boolean"},
        "include_cta": {"type": "boolean"},
    },
    "required": [
        "analysis", "content_type", "subtype", "level", "topic",
        "format", "exam_focus", "include_cta",
    ],
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "post_html": {"type": "string"},
        "use_poll": {"type": "boolean"},
        "poll_question": {"type": "string"},
        "poll_options": {"type": "array", "items": {"type": "string"}},
        "poll_correct_index": {"type": "integer"},
        "poll_explanation": {"type": "string"},
        "answer_reveal_html": {"type": "string"},
        "vocabulary": {"type": "array", "items": {"type": "string"}},
        "topic": {"type": "string"},
        "quiz_answer": {"type": "string"},
        "engagement_type": {"type": "string"},
    },
    "required": [
        "post_html", "use_poll", "poll_question", "poll_options",
        "poll_correct_index", "poll_explanation", "answer_reveal_html",
        "vocabulary", "topic", "quiz_answer", "engagement_type",
    ],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "issues"],
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def sanitize_html(text: str) -> str:
    """Turn common LLM formatting slips into Telegram-safe HTML."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>|</h\d\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.I)

    def drop_unknown(match):
        name = match.group(1).lower()
        return match.group(0) if name in ALLOWED_TAGS else ""

    text = re.sub(r"</?([a-zA-Z][\w-]*)[^>]*>", drop_unknown, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def similar(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() > 0.85


def is_quota_error(error: Exception) -> bool:
    text = str(error)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def slot_name(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


# ---------------------------------------------------------
# MEMORY
# ---------------------------------------------------------

class Memory:
    """Published-content record, kept on disk and backed up to Telegram.

    Hosts like Render wipe the disk on every deploy, so the JSON is also kept
    as a pinned document in the owner's chat with the bot and restored from
    there on startup.
    """

    def __init__(self):
        self.data = {
            "posts": [],
            "pending_reveals": [],
            "trends": {"updated": None, "notes": ""},
            "paused": False,
            "backup_message_id": None,
        }
        self.dirty = False

    @property
    def posts(self):
        return self.data["posts"]

    async def load(self, bot):
        try:
            with open(MEMORY_FILE, encoding="utf-8") as f:
                self.data.update(json.load(f))
            log.info("Memory loaded from %s (%d posts)", MEMORY_FILE, len(self.posts))
            return
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error("Memory file unreadable: %s", e)

        if ADMIN_ID is None:
            return
        try:
            msg = await find_pinned_document(bot, ADMIN_ID, BACKUP_FILENAME)
            if msg:
                file = await bot.get_file(msg.document.file_id)
                raw = await file.download_as_bytearray()
                self.data.update(json.loads(raw.decode("utf-8")))
                self.data["backup_message_id"] = msg.message_id
                self.save_local()
                log.info("Memory restored from Telegram backup (%d posts)", len(self.posts))
        except Exception as e:
            log.error("Memory restore from Telegram failed: %s", e)

    def save_local(self):
        self.data["posts"] = self.posts[-MAX_POSTS_KEPT:]
        tmp = MEMORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, MEMORY_FILE)

    async def save(self, bot, backup=True):
        self.save_local()
        self.dirty = not backup
        if backup:
            await self.backup(bot)

    async def backup(self, bot):
        if ADMIN_ID is None:
            return
        payload = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        media = InputMediaDocument(io.BytesIO(payload), filename=BACKUP_FILENAME)
        msg_id = self.data.get("backup_message_id")
        try:
            if msg_id:
                try:
                    await bot.edit_message_media(
                        media=media, chat_id=ADMIN_ID, message_id=msg_id
                    )
                    self.dirty = False
                    return
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        self.dirty = False
                        return
                    log.warning("Backup edit failed, sending new: %s", e)
            msg = await bot.send_document(
                ADMIN_ID,
                io.BytesIO(payload),
                filename=BACKUP_FILENAME,
                caption="🗂 Kanal xotirasi (zaxira). O'chirmang va unpin qilmang.",
                disable_notification=True,
            )
            await bot.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
            self.data["backup_message_id"] = msg.message_id
            self.save_local()
            self.dirty = False
        except Exception as e:
            log.error("Memory backup failed: %s", e)


# ---------------------------------------------------------
# CHANNEL MANAGER
# ---------------------------------------------------------

class ChannelManager:

    def __init__(self, gemini_client: genai.Client):
        self.client = gemini_client
        self.memory = Memory()
        self.channel_chat_id = None
        self.ready = False
        self.init_lock = asyncio.Lock()
        self.cycle_lock = asyncio.Lock()
        self.last_alerts = {}
        self.last_error = ""
        self.slot_tries = {}

    # ---------------- startup ----------------

    async def ensure_ready(self, bot):
        async with self.init_lock:
            if self.ready:
                return
            await self.memory.load(bot)
            chat = await bot.get_chat(CHANNEL_ID)
            self.channel_chat_id = chat.id
            me = await bot.get_me()
            member = await bot.get_chat_member(chat.id, me.id)
            if member.status != "administrator" or not getattr(member, "can_post_messages", False):
                await self.alert(
                    bot, "not_admin",
                    f"⚠️ Bot {chat.title or CHANNEL_ID} kanalida post qilish huquqiga ega emas.\n"
                    "Botni kanalga admin qilib qo'shing va \"Post messages\" huquqini bering.",
                )
            self.ready = True
            log.info("Channel manager ready for %s (%s)", chat.title, chat.id)

    # ---------------- owner alerts ----------------

    async def alert(self, bot, key: str, text: str):
        log.error("ALERT %s: %s", key, text)
        if ADMIN_ID is None:
            return
        now = time.time()
        if now - self.last_alerts.get(key, 0) < ALERT_COOLDOWN:
            return
        self.last_alerts[key] = now
        try:
            await bot.send_message(ADMIN_ID, f"🤖 Kanal menejeri:\n\n{text}")
        except Exception as e:
            log.error("Could not alert owner: %s", e)

    # ---------------- gemini ----------------

    async def gen_json(self, system: str, prompt: str, schema: dict, temperature: float):
        last_error = None
        for attempt in range(3):
            try:
                response = await self.client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=temperature,
                        response_mime_type="application/json",
                        response_json_schema=schema,
                    ),
                )
                return json.loads(response.text)
            except Exception as e:
                last_error = e
                log.warning("Gemini call failed (attempt %d): %s", attempt + 1, e)
                if attempt < 2:
                    # Per-minute quota (429) needs a real pause before retrying.
                    await asyncio.sleep(40 * (attempt + 1) if is_quota_error(e) else 2 ** attempt * 3)
        raise RuntimeError(f"Gemini failed: {last_error}")

    # ---------------- analysis of history ----------------

    def recent_vocab(self, n_posts=120):
        words = set()
        for p in self.memory.posts[-n_posts:]:
            words.update(w.lower().strip() for w in p.get("vocabulary", []))
        return words

    def performance(self):
        """Average engagement (reactions + poll votes) per content type."""
        cutoff = datetime.now(TZ) - timedelta(hours=6)
        scores = {}
        for p in self.memory.posts[-90:]:
            try:
                posted = datetime.fromisoformat(p["datetime"])
            except Exception:
                continue
            if posted > cutoff:
                continue
            score = p.get("reactions", 0) + p.get("poll_voters", 0)
            scores.setdefault(p["content_type"], []).append(score)
        return {
            t: {"posts": len(v), "avg_engagement": round(sum(v) / len(v), 1)}
            for t, v in scores.items()
        }

    def history_context(self, now: datetime) -> str:
        posts = self.memory.posts
        recent = posts[-25:]
        lines = [
            f"- {p['datetime'][:16]} | {p['content_type']}/{p.get('subtype', '')} | "
            f"{p['level']} | {p['format']} | {p['topic']}"
            for p in recent
        ] or ["(no posts yet - this is a fresh channel)"]
        counts = Counter(p["content_type"] for p in posts[-20:])
        levels = Counter(p["level"] for p in posts[-20:])
        exam = sum(1 for p in posts[-20:] if p.get("exam_focus"))
        unused = [t for t in PILLARS if counts.get(t, 0) == 0]
        topics = [p["topic"] for p in posts[-80:]]
        vocab = sorted(self.recent_vocab())[:250]
        trends = self.memory.data["trends"].get("notes") or "(none)"

        return f"""
NOW: {now.strftime('%A %Y-%m-%d %H:%M')} ({slot_name(now.hour)}, {TZ.key})

RECENT POSTS (oldest -> newest):
{chr(10).join(lines)}

TYPE COUNTS (last 20): {dict(counts)}
UNUSED TYPES (last 20): {unused}
LEVEL COUNTS (last 20): {dict(levels)}
EXAM-FOCUSED POSTS (last 20): {exam}
ENGAGEMENT BY TYPE (reactions + poll votes; Telegram does not give views to bots):
{json.dumps(self.performance(), ensure_ascii=False)}

TOPICS ALREADY COVERED: {json.dumps(topics, ensure_ascii=False)}
VOCABULARY ALREADY TAUGHT: {json.dumps(vocab, ensure_ascii=False)}

TREND NOTES (inspiration only): {trends}
"""

    # ---------------- planning ----------------

    async def plan(self, now: datetime, forced_type: str | None = None) -> dict:
        context = self.history_context(now)
        blocked = [p["content_type"] for p in self.memory.posts[-2:]]
        if forced_type:
            blocked = []

        prompt = f"""{context}

Decide the single best next post for the channel. Think about: what type is
needed for variety, what has been missing or overused, an appropriate level
(mostly A2-C1, mix easy and hard), a useful topic that is NOT already covered,
the best format, whether this time of day suits it (morning: learning content,
afternoon: interactive, evening: speaking/vocabulary/quiz/motivation - but
adapt), and whether engagement is needed. If a type performs well, favour
variations of it; if it performs poorly, change its format.
Do not choose these content types now (posted just before): {blocked}.
{f'The owner explicitly requested content_type = {forced_type}.' if forced_type else ''}
Use quiz_poll for most quizzes, text_answer_later or text_spoiler for
challenges/error-finding tasks, text for lessons and lists.
Put your short reasoning in "analysis"."""

        for _ in range(2):
            plan = await self.gen_json(MANAGER_BRIEF, prompt, PLAN_SCHEMA, 0.9)
            if forced_type:
                plan["content_type"] = forced_type
            if plan["content_type"] not in blocked:
                return plan
            prompt += f"\n\nYou chose {plan['content_type']}, which is not allowed now. Choose another type."

        recent_types = [p["content_type"] for p in self.memory.posts[-12:]]
        options = [t for t in PILLARS if t not in blocked]
        plan["content_type"] = min(options, key=lambda t: (recent_types.count(t), random.random()))
        return plan

    # ---------------- writing + verification ----------------

    def local_checks(self, plan: dict, post: dict) -> list[str]:
        issues = []
        post["post_html"] = sanitize_html(post.get("post_html", ""))
        post["answer_reveal_html"] = sanitize_html(post.get("answer_reveal_html", ""))
        visible = strip_tags(post["post_html"])

        if len(visible) > 3800:
            issues.append("post_html is too long; keep it under 2500 characters.")
        if plan["format"] != "quiz_poll" and len(visible) < 40:
            issues.append("post_html is empty or too short.")

        if plan["format"] == "quiz_poll":
            opts = [o.strip() for o in post.get("poll_options", []) if o.strip()]
            post["poll_options"] = opts
            idx = post.get("poll_correct_index", -1)
            if not post.get("use_poll"):
                issues.append("format is quiz_poll but use_poll is false.")
            if not 2 <= len(opts) <= 10:
                issues.append("poll must have 3-4 options.")
            if len(set(o.lower() for o in opts)) != len(opts):
                issues.append("poll options must be distinct.")
            if not isinstance(idx, int) or not 0 <= idx < len(opts):
                issues.append("poll_correct_index is out of range.")
            if not 1 <= len(post.get("poll_question", "")) <= 300:
                issues.append("poll_question must be 1-300 characters.")
            if any(len(o) > 100 for o in opts):
                issues.append("each poll option must be at most 90 characters.")
            if len(post.get("poll_explanation", "")) > 200:
                issues.append("poll_explanation must be at most 190 characters.")
            for p in self.memory.posts[-150:]:
                if similar(p.get("poll_question", ""), post.get("poll_question", "")):
                    issues.append("this quiz question was already used; write a new one.")
                    break
        else:
            post["use_poll"] = False

        if plan["format"] == "text_answer_later" and len(strip_tags(post["answer_reveal_html"])) < 5:
            issues.append("answer_reveal_html is required for text_answer_later.")
        if plan["format"] == "text_spoiler" and "<tg-spoiler>" not in post["post_html"]:
            issues.append("text_spoiler format needs the answer inside <tg-spoiler>.")

        repeated = {w.lower().strip() for w in post.get("vocabulary", [])} & self.recent_vocab()
        if repeated and plan["content_type"] in ("vocabulary", "quiz", "challenge"):
            issues.append(f"these words were taught recently, replace them: {sorted(repeated)}")

        topic = post.get("topic") or plan["topic"]
        for p in self.memory.posts[-40:]:
            if similar(p["topic"], topic):
                issues.append(f"topic '{topic}' is nearly identical to a recent post; change the angle.")
                break
        return issues

    async def verify(self, plan: dict, post: dict) -> list[str]:
        system = (
            "You are a meticulous English teacher and editor reviewing a Telegram "
            "post before publication. Be strict about correctness, not style."
        )
        prompt = f"""Planned: {json.dumps(plan, ensure_ascii=False)}

Post to review:
{json.dumps(post, ensure_ascii=False)}

Check every item:
- English grammar, spelling, punctuation and meaning are correct.
- Examples are natural and correct; facts and etymologies are true.
- Every quiz/task has exactly ONE clearly correct answer, and the stated
  answer (poll_correct_index / quiz_answer / spoiler / answer_reveal_html)
  really is correct. Count the poll options from index 0.
- Level matches the content; content is useful and not padded.
- {EXPLANATION_LANGUAGE} parts (if any) are correct and natural.
- Formatting is readable on Telegram.
Return ok=false with concrete issues if anything is wrong or doubtful."""
        result = await self.gen_json(system, prompt, VERIFY_SCHEMA, 0.0)
        return [] if result.get("ok") else (result.get("issues") or ["reviewer rejected the post"])

    async def write_post(self, now: datetime, plan: dict) -> dict:
        context = self.history_context(now)
        issues = []
        for attempt in range(MAX_ATTEMPTS):
            fix_note = ""
            if issues:
                fix_note = "\nYOUR PREVIOUS DRAFT WAS REJECTED. Fix these problems:\n- " + "\n- ".join(issues)
            prompt = f"""{context}

Write this post:
{json.dumps(plan, ensure_ascii=False)}

{FORMAT_RULES}
Include a call to action only if include_cta is true.
Fill "vocabulary" with the key English words/phrases taught (empty if none),
"topic" with a short precise topic label, "quiz_answer" with the correct
answer if there is a task (else empty), "engagement_type" with one of:
poll, comment, reflection, none.
Before answering, double-check every answer key.{fix_note}"""
            post = await self.gen_json(MANAGER_BRIEF, prompt, POST_SCHEMA, 0.8)
            issues = self.local_checks(plan, post)
            if not issues:
                issues = await self.verify(plan, post)
            if not issues:
                return post
            log.info("Draft %d rejected: %s", attempt + 1, issues)
        raise RuntimeError(f"Could not produce a verified post: {issues}")

    # ---------------- telegram sending ----------------

    async def send_html(self, bot, chat_id, text: str, reply_to: int | None = None):
        kwargs = {
            "link_preview_options": LinkPreviewOptions(is_disabled=True),
        }
        if reply_to:
            kwargs["reply_parameters"] = ReplyParameters(
                message_id=reply_to, allow_sending_without_reply=True
            )
        try:
            return await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, **kwargs)
        except BadRequest as e:
            if "parse" not in str(e).lower() and "entit" not in str(e).lower():
                raise
            log.warning("HTML rejected (%s), sending as plain text", e)
            return await bot.send_message(chat_id, strip_tags(text), **kwargs)

    async def publish(self, bot, chat_id, plan: dict, post: dict):
        """Send the post; returns (first_message_id, poll_message or None)."""
        first_id = None
        poll_msg = None
        if post["post_html"] and len(strip_tags(post["post_html"])) > 0:
            msg = await self.send_html(bot, chat_id, post["post_html"])
            first_id = msg.message_id
        if post.get("use_poll"):
            poll_msg = await bot.send_poll(
                chat_id,
                question=post["poll_question"],
                options=post["poll_options"],
                type="quiz",
                correct_option_id=post["poll_correct_index"],
                explanation=post.get("poll_explanation") or None,
                is_anonymous=True,
            )
            first_id = first_id or poll_msg.message_id
        return first_id, poll_msg

    # ---------------- reveal answers ----------------

    async def post_due_reveals(self, bot):
        pending = self.memory.data["pending_reveals"]
        if not pending:
            return
        for item in list(pending):
            try:
                await self.send_html(
                    bot, self.channel_chat_id, item["html"], reply_to=item["message_id"]
                )
                for p in self.memory.posts:
                    if p["id"] == item["post_id"]:
                        p["answer_revealed"] = True
            except Exception as e:
                log.error("Reveal failed: %s", e)
            pending.remove(item)
        await self.memory.save(bot, backup=False)

    # ---------------- main cycle ----------------

    async def run_cycle(self, bot, forced_type: str | None = None, manual: bool = False) -> dict | None:
        try:
            await self.ensure_ready(bot)
        except Exception as e:
            await self.alert(bot, "startup", f"❌ Kanalga ulanib bo'lmadi ({CHANNEL_ID}): {e}")
            return None
        if self.memory.data.get("paused") and not manual:
            log.info("Channel manager paused, skipping cycle")
            return None

        async with self.cycle_lock:
            now = datetime.now(TZ)
            try:
                await self.post_due_reveals(bot)
                plan = await self.plan(now, forced_type)
                log.info("Plan: %s", plan)
                post = await self.write_post(now, plan)
                first_id, poll_msg = await self.publish(bot, self.channel_chat_id, plan, post)
            except Forbidden as e:
                await self.alert(
                    bot, "forbidden",
                    f"❌ Telegram kanalga yozishga ruxsat bermadi: {e}\n"
                    "Bot kanaldan chiqarilgan yoki admin huquqi olib tashlangan bo'lishi mumkin.",
                )
                return None
            except Exception as e:
                log.exception("Cycle failed")
                if is_quota_error(e):
                    reason = (
                        "Gemini API limiti tugadi (429). Bepul kalitda daqiqalik va "
                        "kunlik so'rovlar soni cheklangan."
                    )
                else:
                    reason = str(e)[:500]
                self.last_error = reason
                await self.alert(
                    bot, "cycle_failed",
                    f"❌ Post tayyorlab bo'lmadi: {reason}\n"
                    "Keyingi rejalashtirilgan vaqtda yana urinaman.",
                )
                return None

            record = {
                "id": uuid.uuid4().hex[:10],
                "datetime": now.isoformat(),
                "weekday": now.strftime("%A"),
                "slot": slot_name(now.hour),
                "content_type": plan["content_type"],
                "subtype": plan.get("subtype", ""),
                "level": plan["level"],
                "format": plan["format"],
                "exam_focus": plan.get("exam_focus", False),
                "topic": post.get("topic") or plan["topic"],
                "vocabulary": post.get("vocabulary", []),
                "quiz_answer": post.get("quiz_answer", ""),
                "engagement_type": post.get("engagement_type", ""),
                "message_id": first_id,
                "message_ids": [first_id] + ([poll_msg.message_id] if poll_msg and poll_msg.message_id != first_id else []),
                "poll_id": poll_msg.poll.id if poll_msg else None,
                "poll_question": post.get("poll_question", "") if poll_msg else "",
                "reactions": 0,
                "poll_voters": 0,
                "answer_revealed": plan["format"] != "text_answer_later",
            }
            self.memory.posts.append(record)
            if plan["format"] == "text_answer_later":
                self.memory.data["pending_reveals"].append({
                    "post_id": record["id"],
                    "message_id": first_id,
                    "html": post["answer_reveal_html"],
                })
            await self.memory.save(bot)
            log.info("Published %s / %s / %s", record["content_type"], record["level"], record["topic"])
            return record

    # ---------------- trend research ----------------

    async def refresh_trends(self, bot):
        await self.ensure_ready(bot)
        trends = self.memory.data["trends"]
        now = datetime.now(TZ)
        if trends.get("updated"):
            if now - datetime.fromisoformat(trends["updated"]) < timedelta(days=7):
                return
        # Do not spend Gemini quota retrying on every restart after a failure.
        if trends.get("last_attempt"):
            if now - datetime.fromisoformat(trends["last_attempt"]) < timedelta(days=1):
                return
        trends["last_attempt"] = now.isoformat()
        self.memory.save_local()
        try:
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=(
                    "Research current English-learning trends useful for an "
                    "English-learning Telegram channel for Uzbek learners: recent "
                    "IELTS Speaking/Writing topics, frequently confused expressions, "
                    "popular learner questions, useful modern vocabulary. Return a "
                    "compact bullet list (max 15 bullets) of ideas only, no copied text."
                ),
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.7,
                ),
            )
            notes = (response.text or "").strip()
            if notes:
                trends["notes"] = notes[:2500]
                trends["updated"] = datetime.now(TZ).isoformat()
                await self.memory.save(bot)
                log.info("Trend notes refreshed")
        except Exception as e:
            log.warning("Trend research failed (non-critical): %s", e)

    # ---------------- analytics updates ----------------

    def find_post(self, **match):
        key, value = next(iter(match.items()))
        for p in reversed(self.memory.posts):
            if key == "message_id" and value in p.get("message_ids", []):
                return p
            if p.get(key) == value:
                return p
        return None

    async def on_reaction_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rc = update.message_reaction_count
        if not rc or rc.chat.id != self.channel_chat_id:
            return
        post = self.find_post(message_id=rc.message_id)
        if post:
            post["reactions"] = sum(r.total_count for r in rc.reactions)
            self.memory.dirty = True
            self.memory.save_local()

    async def on_poll(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        poll = update.poll
        post = self.find_post(poll_id=poll.id)
        if post:
            post["poll_voters"] = poll.total_voter_count
            self.memory.dirty = True
            self.memory.save_local()

    # ---------------- jobs ----------------

    def due_slot(self, now: datetime) -> datetime | None:
        """Today's posting slot that has passed recently and has no post yet.

        Checked every few minutes instead of firing once at the exact time,
        so a slot missed while the host was asleep or restarting is still
        posted (within SLOT_CATCHUP_WINDOW) and never posted twice.
        """
        posted = []
        for p in self.memory.posts[-20:]:
            try:
                posted.append(datetime.fromisoformat(p["datetime"]))
            except Exception:
                continue
        for t in parse_post_times():
            slot = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if not slot <= now < slot + SLOT_CATCHUP_WINDOW:
                continue
            if any(d >= slot for d in posted):
                continue
            tries = self.slot_tries.get(slot.isoformat(), [])
            if len(tries) >= SLOT_MAX_TRIES or (tries and now - tries[-1] < SLOT_RETRY_GAP):
                continue
            return slot
        return None

    async def job_tick(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.ensure_ready(context.bot)
        except Exception as e:
            log.error("Channel manager not ready: %s", e)
            return
        if self.memory.data.get("paused") or self.cycle_lock.locked():
            return
        now = datetime.now(TZ)
        slot = self.due_slot(now)
        if slot is None:
            return
        self.slot_tries.setdefault(slot.isoformat(), []).append(now)
        log.info("Slot %s is due (now %s)", slot.strftime("%H:%M"), now.strftime("%H:%M"))
        await self.run_cycle(context.bot)

    async def job_backup(self, context: ContextTypes.DEFAULT_TYPE):
        if self.ready and self.memory.dirty:
            await self.memory.backup(context.bot)

    async def job_trends(self, context: ContextTypes.DEFAULT_TYPE):
        await self.refresh_trends(context.bot)

    async def job_startup(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.ensure_ready(context.bot)
        except Exception as e:
            log.exception("Channel manager startup failed")
            await self.alert(
                context.bot, "startup",
                f"❌ Kanalga ulanib bo'lmadi ({CHANNEL_ID}): {e}\n"
                "CHANNEL_ID to'g'riligini va bot kanalda admin ekanini tekshiring.",
            )

    # ---------------- owner commands ----------------

    def posts_today(self) -> int:
        today = datetime.now(TZ).date().isoformat()
        return sum(1 for p in self.memory.posts if p["datetime"][:10] == today)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        posts = self.memory.posts
        last = posts[-1] if posts else None
        lines = [
            f"📡 Kanal: {CHANNEL_ID}",
            f"⏸ Pauza: {'ha' if self.memory.data.get('paused') else 'yo‘q'}",
            f"🕒 Post vaqtlari: {POST_TIMES} ({TZ.key})",
            f"📅 Bugun chiqqan postlar: {self.posts_today()}",
            f"📝 Jami postlar xotirada: {len(posts)}",
            f"⏳ Javobi kutilayotgan topshiriqlar: {len(self.memory.data['pending_reveals'])}",
        ]
        if last:
            lines.append(
                f"🆕 Oxirgi post: {last['datetime'][:16]} — {last['content_type']} "
                f"({last['level']}): {last['topic']}"
            )
        perf = self.performance()
        if perf:
            lines.append("\n📊 Faollik (reaksiya + so‘rovnoma ovozlari, o‘rtacha):")
            for t, v in sorted(perf.items(), key=lambda x: -x[1]["avg_engagement"]):
                lines.append(f"• {t}: {v['avg_engagement']} ({v['posts']} ta post)")
        await update.message.reply_text("\n".join(lines))

    def parse_type_arg(self, context) -> str | None:
        if context.args and context.args[0] in PILLARS:
            return context.args[0]
        return None

    async def cmd_post_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        forced = self.parse_type_arg(context)
        await update.message.reply_text("⏳ Post tayyorlanmoqda...")
        record = await self.run_cycle(context.bot, forced_type=forced, manual=True)
        if record:
            await update.message.reply_text(
                f"✅ Chiqdi: {record['content_type']} ({record['level']}) — {record['topic']}"
            )
        else:
            await update.message.reply_text(
                f"❌ Post chiqmadi: {self.last_error or 'sababini Render Logs dan ko‘ring.'}"
            )

    async def cmd_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        forced = self.parse_type_arg(context)
        await update.message.reply_text("⏳ Namuna tayyorlanmoqda (kanalga chiqmaydi)...")
        try:
            now = datetime.now(TZ)
            plan = await self.plan(now, forced)
            post = await self.write_post(now, plan)
            await update.message.reply_text(
                f"🧭 Reja: {plan['content_type']} / {plan['level']} / {plan['format']}\n"
                f"💭 {plan['analysis'][:800]}"
            )
            await self.publish(context.bot, update.effective_chat.id, plan, post)
            if post.get("answer_reveal_html"):
                await self.send_html(context.bot, update.effective_chat.id, post["answer_reveal_html"])
        except Exception as e:
            reason = "Gemini API limiti tugadi (429)." if is_quota_error(e) else str(e)[:500]
            await update.message.reply_text(f"❌ Xato: {reason}")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        self.memory.data["paused"] = True
        await self.memory.save(context.bot)
        await update.message.reply_text("⏸ Avtomatik postlar to‘xtatildi. /resume_channel bilan qayta yoqing.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        self.memory.data["paused"] = False
        await self.memory.save(context.bot)
        await update.message.reply_text("▶️ Avtomatik postlar qayta yoqildi.")


# ---------------------------------------------------------
# WIRING
# ---------------------------------------------------------

def parse_post_times() -> list[dtime]:
    times = []
    for part in POST_TIMES.split(","):
        part = part.strip()
        if not part:
            continue
        hour, minute = part.split(":")
        times.append(dtime(int(hour), int(minute), tzinfo=TZ))
    return times


def setup(app: Application, gemini_client: genai.Client) -> ChannelManager | None:
    """Register channel-manager jobs and handlers. No-op if CHANNEL_ID is unset."""
    if not CHANNEL_ID:
        log.warning("CHANNEL_ID is not set - channel manager disabled")
        return None
    if app.job_queue is None:
        raise RuntimeError(
            'JobQueue is unavailable. Install "python-telegram-bot[job-queue]".'
        )
    if ADMIN_ID is None:
        log.warning("ADMIN_ID is not set - no owner alerts, commands or memory backup")

    manager = ChannelManager(gemini_client)
    jq = app.job_queue

    jq.run_once(manager.job_startup, when=5)
    jq.run_repeating(manager.job_tick, interval=300, first=60, name="channel_tick")
    jq.run_repeating(manager.job_backup, interval=1800, first=1800)
    if TREND_RESEARCH:
        jq.run_repeating(manager.job_trends, interval=timedelta(hours=12), first=120)

    app.add_handler(MessageReactionHandler(
        manager.on_reaction_count,
        message_reaction_types=MessageReactionHandler.MESSAGE_REACTION_COUNT_UPDATED,
    ))
    app.add_handler(PollHandler(manager.on_poll))

    if ADMIN_ID is not None:
        owner = filters.User(ADMIN_ID) & filters.ChatType.PRIVATE
        app.add_handler(CommandHandler("channel_status", manager.cmd_status, filters=owner))
        app.add_handler(CommandHandler("post_now", manager.cmd_post_now, filters=owner))
        app.add_handler(CommandHandler("preview", manager.cmd_preview, filters=owner))
        app.add_handler(CommandHandler("pause_channel", manager.cmd_pause, filters=owner))
        app.add_handler(CommandHandler("resume_channel", manager.cmd_resume, filters=owner))

    log.info("Channel manager scheduled at %s (%s)", POST_TIMES, TZ.key)
    return manager

"""
Autonomous Instagram manager for the Nur Academy / Samandar Mansurov brand.

Runs inside the same process as bot.py (python-telegram-bot JobQueue). It:
  1. audits the Instagram profile (followers, recent posts, their insights)
     and writes a growth strategy, refreshed weekly;
  2. plans and writes Reels that fit the strategy and past performance,
     with a second "strict editor" pass;
  3. renders the video itself (branded slides + AI voice-over, optionally a
     Veo-generated hook clip);
  4. sends the draft to the owner in Telegram for approval, or publishes it
     straight away when IG_APPROVAL=0;
  5. tracks reach/views/saves/shares and follower growth against the goal
     and adapts future content; optionally replies to comments.

Environment variables:
    IG_ACCESS_TOKEN     long-lived Instagram token (required to enable)
    IG_USER_ID          Instagram professional account id (auto-detected)
    IG_POST_TIMES       daily Reel times, default "12:30,20:00"
    IG_APPROVAL         "1" (default) send drafts to the owner first; "0" auto-publish
    IG_AUTO_REPLY       "1" to answer comments automatically, default "0"
    IG_FOLLOWER_GOAL    default 100000
    IG_GOAL_DAYS        default 60
    BRAND_NAME          default "Nur Academy"
    PERSON_NAME         default "Samandar Mansurov"
    IG_CONTENT_LANGUAGE language of voice-over and captions, default "Uzbek"
    VIDEO_ENGINE        "slides" (default) or "veo"
    VEO_MODEL           default "veo-3.0-fast-generate-001"
    TTS_MODEL           default "gemini-2.5-flash-preview-tts"; "" disables voice
    TTS_VOICE           default "Charon"
    IG_MUSIC_FILE       optional path to a royalty-free background track
    IG_MEMORY_FILE      default "instagram_memory.json"
"""

import asyncio
import hashlib
import io
import json
import logging
import os
import random
import time
import uuid
from collections import Counter
from datetime import datetime, time as dtime, timedelta

from google import genai
from google.genai import types as genai_types
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaDocument, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, filters

import reel_renderer
from channel_manager import ADMIN_ID, GEMINI_MODEL, TZ, is_quota_error, similar
from instagram_api import GRAPH_HOST, InstagramAPI, InstagramError
from tg_backup import find_pinned_document

log = logging.getLogger("instagram_manager")


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip() or None
IG_POST_TIMES = os.environ.get("IG_POST_TIMES", "12:30,20:00")
IG_APPROVAL = os.environ.get("IG_APPROVAL", "1") == "1" and ADMIN_ID is not None
IG_AUTO_REPLY = os.environ.get("IG_AUTO_REPLY", "0") == "1"
FOLLOWER_GOAL = int(os.environ.get("IG_FOLLOWER_GOAL", "100000"))
GOAL_DAYS = int(os.environ.get("IG_GOAL_DAYS", "60"))
BRAND_NAME = os.environ.get("BRAND_NAME", "Nur Academy")
PERSON_NAME = os.environ.get("PERSON_NAME", "Samandar Mansurov")
CONTENT_LANGUAGE = os.environ.get("IG_CONTENT_LANGUAGE", "Uzbek")
VIDEO_ENGINE = os.environ.get("VIDEO_ENGINE", "slides")
VEO_MODEL = os.environ.get("VEO_MODEL", "veo-3.0-fast-generate-001")
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "Charon")
MUSIC_FILE = os.environ.get("IG_MUSIC_FILE") or None
MEMORY_FILE = os.environ.get("IG_MEMORY_FILE", "instagram_memory.json")

BACKUP_FILENAME = "instagram_memory.json"
MAX_POSTS_KEPT = 300
MAX_ATTEMPTS = 3
ALERT_COOLDOWN = 6 * 3600
DRAFTS_KEPT = 8

PILLARS = [
    "uzbek_traps",        # o'zbekchadan so'zma-so'z tarjima xatolari
    "common_mistakes",
    "vocabulary_pack",
    "speaking_phrases",
    "ielts_tip",
    "grammar_hack",
    "pronunciation",
    "quiz_challenge",
    "motivation_story",
    "myth_busting",
]
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
LINE_STYLES = ["normal", "wrong", "right", "highlight"]


# ---------------------------------------------------------
# PROMPTS
# ---------------------------------------------------------

BRAND_BRIEF = f"""
You are the autonomous Instagram manager, content strategist and Reels
scriptwriter for "{BRAND_NAME}", an English-learning academy, and its face
and lead teacher {PERSON_NAME}. Your job is to grow the account fast with
genuinely useful, highly shareable short videos and to make both
"{BRAND_NAME}" and "{PERSON_NAME}" recognisable names among Uzbek English
learners.

Audience: Uzbek-speaking English learners (school/university students,
IELTS/CEFR candidates, young professionals), mostly A2-C1.
Voice-over and caption language: {CONTENT_LANGUAGE} (Latin script), with the
English examples in English.

What grows educational accounts on Instagram (use it):
- The first 1-2 seconds decide everything: a sharp hook that names a pain,
  a mistake, a surprising fact or a challenge ("Bu xatoni 90% o'quvchi
  qiladi", "IELTSda 7 olish uchun bu so'zni tashlang").
- One idea per Reel, fast pace, 20-45 seconds, concrete examples.
- Content people SAVE (cheat sheets, lists) and SHARE (relatable mistakes,
  Uzbek-vs-English traps, funny contrasts) and COMMENT on (quiz, "write your
  answer").
- A clear, varied call to action: save, share with a friend, comment the
  answer, follow {BRAND_NAME} for daily English.
- Consistent branding: a recognisable series format, the teacher's name.

Content pillars: uzbek_traps (word-for-word translation mistakes Uzbeks
make), common_mistakes, vocabulary_pack (5 words/phrases on one theme),
speaking_phrases (sound natural), ielts_tip (band-raising tips, real exam
format), grammar_hack, pronunciation (commonly mispronounced words, with
simple respelling), quiz_challenge (question in the video, answer in the
comments / end), motivation_story (concrete study discipline, no empty
quotes), myth_busting (learning myths).

Hard rules:
- 100% accurate English and correct {CONTENT_LANGUAGE}. Every answer key
  must be right.
- Never invent student results, testimonials, statistics presented as
  research, guarantees ("IELTS 8 kafolat") or fake urgency. "90% o'quvchi"
  style hooks are fine only as an obvious rhetorical exaggeration about
  common mistakes, never about results or prices.
- Original content only; no copying other creators.
- No politics, religion debates, or mocking anyone.
"""

STRATEGY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "positioning": {"type": "string"},
        "bio_suggestion": {"type": "string"},
        "pillar_weights": {
            "type": "object",
            "properties": {p: {"type": "number"} for p in PILLARS},
            "required": PILLARS,
        },
        "series_ideas": {"type": "array", "items": {"type": "string"}},
        "hook_patterns": {"type": "array", "items": {"type": "string"}},
        "caption_rules": {"type": "array", "items": {"type": "string"}},
        "hashtag_sets": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "owner_actions": {"type": "array", "items": {"type": "string"}},
        "report_uz": {"type": "string"},
    },
    "required": [
        "summary", "strengths", "weaknesses", "positioning", "bio_suggestion",
        "pillar_weights", "series_ideas", "hook_patterns", "caption_rules",
        "hashtag_sets", "owner_actions", "report_uz",
    ],
}

REEL_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "pillar": {"type": "string", "enum": PILLARS},
        "series": {"type": "string"},
        "topic": {"type": "string"},
        "level": {"type": "string", "enum": LEVELS},
        "hook_text": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "style": {"type": "string", "enum": LINE_STYLES},
                            },
                            "required": ["text", "style"],
                        },
                    },
                    "voice": {"type": "string"},
                },
                "required": ["title", "lines", "voice"],
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "vocabulary": {"type": "array", "items": {"type": "string"}},
        "veo_prompt": {"type": "string"},
    },
    "required": [
        "analysis", "pillar", "series", "topic", "level", "hook_text", "scenes",
        "caption", "hashtags", "vocabulary", "veo_prompt",
    ],
}

SCRIPT_RULES = f"""
Reel script rules:
- 4-7 scenes. Scene 1 is the HOOK: "title" = the on-screen hook (max 60
  characters, no lines), "voice" = the spoken hook (1 short sentence).
  "hook_text" repeats the on-screen hook.
- Middle scenes teach: a short title (max 45 chars) and 1-5 lines (each max
  70 chars). Use style "wrong" for an incorrect example, "right" for the
  correct one, "highlight" for the key word/phrase, "normal" otherwise.
  Do NOT put emoji in titles or lines (the renderer cannot draw them).
- Last scene is the CTA (follow {BRAND_NAME}, save, comment ...). Vary it.
- "voice" is what the AI narrator says over that scene, in {CONTENT_LANGUAGE}
  with English examples, natural spoken style, as {PERSON_NAME} would talk.
  Total voice-over 60-150 words (about 20-50 seconds).
- caption: {CONTENT_LANGUAGE}, starts with a strong first line (it is shown
  before "more"), adds value (a short recap or extra example), ends with a
  question or CTA, mentions {BRAND_NAME}. Emoji are fine here. Max 1500
  characters. No hashtags inside the caption.
- hashtags: 3-5 relevant hashtags (Instagram limits hashtags), mix of niche
  (#ingliztili #ieltsuzbekistan) and branded ones.
- veo_prompt: an English prompt for an 8-second vertical cinematic clip that
  illustrates the hook (no on-screen text, no logos, no real people's
  likeness, no children). Leave it empty for list-style topics.
"""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "issues"],
}

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "replies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comment_id": {"type": "string"},
                    "reply": {"type": "string"},
                },
                "required": ["comment_id", "reply"],
            },
        },
    },
    "required": ["replies"],
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def engagement_score(m: dict) -> float:
    """Weighted interactions per reach: shares and saves matter most."""
    reach = m.get("reach") or 0
    if not reach:
        return 0.0
    weighted = (
        m.get("likes", 0) + 2 * m.get("comments", 0)
        + 3 * m.get("saved", 0) + 4 * m.get("shares", 0)
    )
    return round(100 * weighted / reach, 2)


def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def parse_times(spec: str) -> list[dtime]:
    times = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            hour, minute = part.split(":")
            times.append(dtime(int(hour), int(minute), tzinfo=TZ))
    return times


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


# ---------------------------------------------------------
# MEMORY
# ---------------------------------------------------------

class Memory:
    """Instagram manager state, on disk and as a pinned document in the owner's chat."""

    def __init__(self):
        self.data = {
            "posts": [],
            "drafts": {},
            "profile": {},
            "media_snapshot": [],
            "strategy": {},
            "strategy_updated": None,
            "trends": {"updated": None, "last_attempt": None, "notes": ""},
            "followers": [],
            "goal": {},
            "token": {},
            "replied_comments": [],
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
            return
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error("Instagram memory unreadable: %s", e)
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
                log.info("Instagram memory restored from Telegram (%d posts)", len(self.posts))
        except Exception as e:
            log.error("Instagram memory restore failed: %s", e)

    def save_local(self):
        self.data["posts"] = self.posts[-MAX_POSTS_KEPT:]
        self.data["replied_comments"] = self.data["replied_comments"][-3000:]
        self.data["followers"] = self.data["followers"][-200:]
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
        msg_id = self.data.get("backup_message_id")
        try:
            if msg_id:
                try:
                    await bot.edit_message_media(
                        media=InputMediaDocument(io.BytesIO(payload), filename=BACKUP_FILENAME),
                        chat_id=ADMIN_ID, message_id=msg_id,
                    )
                    self.dirty = False
                    return
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        self.dirty = False
                        return
                    log.warning("Instagram backup edit failed, sending new: %s", e)
            msg = await bot.send_document(
                ADMIN_ID, io.BytesIO(payload), filename=BACKUP_FILENAME,
                caption="🗂 Instagram xotirasi (zaxira). O'chirmang va unpin qilmang.",
                disable_notification=True,
            )
            await bot.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
            self.data["backup_message_id"] = msg.message_id
            self.save_local()
            self.dirty = False
        except Exception as e:
            log.error("Instagram backup failed: %s", e)


# ---------------------------------------------------------
# INSTAGRAM MANAGER
# ---------------------------------------------------------

class InstagramManager:

    def __init__(self, gemini_client: genai.Client):
        self.client = gemini_client
        self.memory = Memory()
        self.ig: InstagramAPI | None = None
        self.ready = False
        self.init_lock = asyncio.Lock()
        self.cycle_lock = asyncio.Lock()
        self.last_alerts = {}
        self.last_error = ""

    # ---------------- startup ----------------

    async def ensure_ready(self, bot):
        async with self.init_lock:
            if self.ready:
                return
            await self.memory.load(bot)
            token = IG_ACCESS_TOKEN
            saved = self.memory.data.get("token") or {}
            # Prefer the refreshed token unless the owner put a new one in the env.
            if saved.get("value") and saved.get("env_fingerprint") == token_fingerprint(IG_ACCESS_TOKEN):
                token = saved["value"]
            self.ig = InstagramAPI(token, IG_USER_ID)
            profile = await self.ig.profile()
            self.memory.data["profile"] = profile
            goal = self.memory.data["goal"]
            if not goal:
                start = datetime.now(TZ)
                goal.update({
                    "start_date": start.isoformat(),
                    "start_followers": profile.get("followers_count", 0),
                    "target": FOLLOWER_GOAL,
                    "deadline": (start + timedelta(days=GOAL_DAYS)).isoformat(),
                })
            self.memory.save_local()
            self.ready = True
            log.info("Instagram manager ready for @%s", profile.get("username"))

    def brand(self) -> dict:
        return {
            "brand": BRAND_NAME,
            "person": PERSON_NAME,
            "handle": self.memory.data["profile"].get("username", ""),
        }

    async def alert(self, bot, key: str, text: str):
        log.error("ALERT %s: %s", key, text)
        if ADMIN_ID is None:
            return
        now = time.time()
        if now - self.last_alerts.get(key, 0) < ALERT_COOLDOWN:
            return
        self.last_alerts[key] = now
        try:
            await bot.send_message(ADMIN_ID, f"📸 Instagram menejeri:\n\n{text}")
        except Exception as e:
            log.error("Could not alert owner: %s", e)

    def explain_error(self, e: Exception) -> str:
        if is_quota_error(e):
            return "Gemini API limiti tugadi (429)."
        if isinstance(e, InstagramError) and (e.code == 190 or e.status == 401):
            return (
                "Instagram tokeni yaroqsiz yoki muddati tugagan. Yangi IG_ACCESS_TOKEN "
                "oling va Render'da yangilang."
            )
        return str(e)[:500]

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
                    await asyncio.sleep(40 * (attempt + 1) if is_quota_error(e) else 2 ** attempt * 3)
        raise RuntimeError(f"Gemini failed: {last_error}")

    # ---------------- analytics ----------------

    async def refresh_metrics(self, bot, media_limit: int = 30):
        """Pull profile, recent media and insights; snapshot followers."""
        await self.ensure_ready(bot)
        profile = await self.ig.profile()
        self.memory.data["profile"] = profile
        today = datetime.now(TZ).date().isoformat()
        followers = self.memory.data["followers"]
        count = profile.get("followers_count", 0)
        if followers and followers[-1][0] == today:
            followers[-1][1] = count
        else:
            followers.append([today, count])

        media = await self.ig.recent_media(media_limit)
        ours = {p.get("media_id"): p for p in self.memory.posts if p.get("media_id")}
        snapshot = []
        for item in media:
            try:
                metrics = await self.ig.media_insights(item["id"])
            except InstagramError as e:
                log.info("No insights for %s: %s", item["id"], e)
                metrics = {}
            metrics.setdefault("likes", item.get("like_count", 0))
            metrics.setdefault("comments", item.get("comments_count", 0))
            entry = {
                "id": item["id"],
                "timestamp": item.get("timestamp", ""),
                "type": item.get("media_product_type") or item.get("media_type"),
                "caption": (item.get("caption") or "")[:300],
                "permalink": item.get("permalink", ""),
                "metrics": metrics,
                "score": engagement_score(metrics),
            }
            snapshot.append(entry)
            if item["id"] in ours:
                ours[item["id"]]["metrics"] = metrics
                ours[item["id"]]["score"] = entry["score"]
        self.memory.data["media_snapshot"] = snapshot
        await self.memory.save(bot)
        return snapshot

    def pillar_performance(self) -> dict:
        cutoff = datetime.now(TZ) - timedelta(hours=24)
        stats = {}
        for p in self.memory.posts[-80:]:
            if not p.get("metrics") or datetime.fromisoformat(p["datetime"]) > cutoff:
                continue
            s = stats.setdefault(p["pillar"], {"posts": 0, "views": 0, "score": 0.0})
            s["posts"] += 1
            s["views"] += p["metrics"].get("views", 0) or p["metrics"].get("reach", 0)
            s["score"] += p.get("score", 0)
        return {
            k: {"posts": v["posts"], "avg_views": round(v["views"] / v["posts"]),
                "avg_engagement": round(v["score"] / v["posts"], 2)}
            for k, v in stats.items()
        }

    def growth_status(self) -> dict:
        goal = self.memory.data["goal"]
        followers = self.memory.data["followers"]
        current = followers[-1][1] if followers else self.memory.data["profile"].get("followers_count", 0)
        now = datetime.now(TZ)
        start = datetime.fromisoformat(goal["start_date"])
        deadline = datetime.fromisoformat(goal["deadline"])
        days_passed = max((now - start).days, 1)
        days_left = max((deadline - now).days, 1)
        gained = current - goal["start_followers"]
        week_ago = next(
            (c for d, c in reversed(followers)
             if datetime.fromisoformat(d).date() <= (now - timedelta(days=7)).date()),
            followers[0][1] if followers else current,
        )
        return {
            "current": current,
            "target": goal["target"],
            "gained": gained,
            "per_day": round(gained / days_passed),
            "last_7_days": current - week_ago,
            "needed_per_day": max(round((goal["target"] - current) / days_left), 0),
            "days_left": days_left,
        }

    def history_context(self) -> str:
        profile = self.memory.data["profile"]
        strategy = self.memory.data.get("strategy") or {}
        posts = self.memory.posts
        recent = [
            f"- {p['datetime'][:16]} | {p['pillar']} | {p.get('series', '')} | {p['level']} | "
            f"{p['topic']} | hook: {p.get('hook_text', '')} | "
            f"views {p.get('metrics', {}).get('views', '?')} | score {p.get('score', '?')}"
            for p in posts[-25:]
        ] or ["(nothing published by the agent yet)"]
        top = sorted(self.memory.data["media_snapshot"], key=lambda m: -m["score"])[:5]
        top_lines = [
            f"- score {m['score']} | views {m['metrics'].get('views', '?')} | {m['caption'][:120]!r}"
            for m in top
        ]
        counts = Counter(p["pillar"] for p in posts[-14:])
        vocab = sorted({w.lower() for p in posts[-100:] for w in p.get("vocabulary", [])})[:200]
        trends = self.memory.data["trends"].get("notes") or "(none)"
        return f"""
ACCOUNT: @{profile.get('username')} | followers {profile.get('followers_count')} | posts {profile.get('media_count')}
BIO: {profile.get('biography', '')!r}
GROWTH: {json.dumps(self.growth_status())}

STRATEGY (from the latest audit):
positioning: {strategy.get('positioning', '(no audit yet)')}
pillar weights: {json.dumps(strategy.get('pillar_weights', {}))}
series ideas: {json.dumps(strategy.get('series_ideas', []), ensure_ascii=False)}
hook patterns: {json.dumps(strategy.get('hook_patterns', []), ensure_ascii=False)}
caption rules: {json.dumps(strategy.get('caption_rules', []), ensure_ascii=False)}
hashtag sets: {json.dumps(strategy.get('hashtag_sets', []), ensure_ascii=False)}

AGENT REELS (oldest -> newest):
{chr(10).join(recent)}

PILLAR COUNTS (last 14): {dict(counts)}
PILLAR PERFORMANCE (avg views, avg weighted engagement % of reach):
{json.dumps(self.pillar_performance())}

TOP POSTS ON THE ACCOUNT RIGHT NOW:
{chr(10).join(top_lines) or '(no data)'}

TOPICS ALREADY COVERED: {json.dumps([p['topic'] for p in posts[-80:]], ensure_ascii=False)}
VOCABULARY ALREADY TAUGHT: {json.dumps(vocab, ensure_ascii=False)}
TREND NOTES (inspiration only): {trends}
"""

    # ---------------- profile audit ----------------

    async def audit(self, bot, notify: bool = True) -> dict:
        await self.refresh_metrics(bot)
        profile = self.memory.data["profile"]
        media = self.memory.data["media_snapshot"]
        lines = [
            f"- {m['timestamp'][:10]} | {m['type']} | score {m['score']} | "
            f"{json.dumps(m['metrics'])} | {m['caption'][:200]!r}"
            for m in media
        ] or ["(the account has no posts yet)"]
        prompt = f"""Audit this Instagram account and write the growth strategy.

PROFILE: {json.dumps(profile, ensure_ascii=False)}
GOAL: grow from {profile.get('followers_count')} to {FOLLOWER_GOAL} followers in {GOAL_DAYS} days.
GROWTH SO FAR: {json.dumps(self.growth_status())}

RECENT POSTS WITH INSIGHTS (score = weighted interactions per reach, %):
{chr(10).join(lines)}

AGENT PILLAR PERFORMANCE: {json.dumps(self.pillar_performance())}
TREND NOTES: {self.memory.data['trends'].get('notes') or '(none)'}

Explain what works and what does not, using the numbers. Then give:
positioning (one sentence), a bio suggestion (max 150 chars, mentions
{BRAND_NAME} and {PERSON_NAME}, clear value + CTA), pillar_weights (0-1, sum
about 1, favour what performs), 3-5 recognisable series ideas, hook
patterns, caption rules, 3 hashtag sets of 3-5 tags, and owner_actions:
things only a human can do that speed up growth (collabs with other
creators, Lives, appearing on camera, giveaways with partners, paid
promotion budget, cross-posting from Telegram/YouTube Shorts).
Be honest about whether the goal is realistic from the current base.
report_uz: a concise report for the owner in Uzbek (Latin script), max
2500 characters, plain text with short bullet points."""
        strategy = await self.gen_json(BRAND_BRIEF, prompt, STRATEGY_SCHEMA, 0.4)
        self.memory.data["strategy"] = strategy
        self.memory.data["strategy_updated"] = datetime.now(TZ).isoformat()
        await self.memory.save(bot)
        if notify and ADMIN_ID is not None:
            text = (
                f"📊 Instagram audit — @{profile.get('username')}\n\n{strategy['report_uz']}\n\n"
                f"✍️ Bio taklifi (API orqali o'zgartirib bo'lmaydi, qo'lda qo'ying):\n"
                f"{strategy['bio_suggestion']}"
            )
            for i in range(0, len(text), 4000):
                await bot.send_message(ADMIN_ID, text[i:i + 4000])
        return strategy

    async def refresh_trends(self, bot):
        trends = self.memory.data["trends"]
        now = datetime.now(TZ)
        if trends.get("updated") and now - datetime.fromisoformat(trends["updated"]) < timedelta(days=7):
            return
        if trends.get("last_attempt") and now - datetime.fromisoformat(trends["last_attempt"]) < timedelta(days=1):
            return
        trends["last_attempt"] = now.isoformat()
        self.memory.save_local()
        try:
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=(
                    "Research what currently performs on Instagram Reels for English "
                    "teachers targeting Uzbek / Central Asian learners and globally: "
                    "viral educational Reel formats, hook styles, trending topics, "
                    "IELTS updates, Instagram algorithm changes for Reels this year. "
                    "Return a compact bullet list (max 15 bullets), ideas only."
                ),
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.7,
                ),
            )
            notes = (response.text or "").strip()
            if notes:
                trends["notes"] = notes[:2500]
                trends["updated"] = now.isoformat()
                await self.memory.save(bot)
        except Exception as e:
            log.warning("Instagram trend research failed (non-critical): %s", e)

    # ---------------- script writing ----------------

    def local_checks(self, script: dict) -> list[str]:
        issues = []
        scenes = script.get("scenes") or []
        if not 4 <= len(scenes) <= 8:
            issues.append("use 4-7 scenes.")
        if scenes and scenes[0].get("lines"):
            scenes[0]["lines"] = []
        if len(script.get("hook_text", "")) > 80:
            issues.append("hook_text must be at most 60 characters.")
        for i, scene in enumerate(scenes):
            if len(scene.get("lines", [])) > 6:
                issues.append(f"scene {i + 1} has too many lines (max 5).")
            if any(len(l.get("text", "")) > 90 for l in scene.get("lines", [])):
                issues.append(f"scene {i + 1} has a line over 70 characters.")
        words = sum(reel_renderer.word_count(s.get("voice", "")) for s in scenes)
        if not 40 <= words <= 190:
            issues.append(f"voice-over is {words} words; keep it 60-150 words.")
        if len(script.get("caption", "")) > 2000:
            issues.append("caption is too long (max 1500 characters).")
        tags = [t.strip() for t in script.get("hashtags", []) if t.strip()]
        script["hashtags"] = ["#" + t.lstrip("#").replace(" ", "") for t in tags][:5]
        for p in self.memory.posts[-60:]:
            if similar(p["topic"], script.get("topic", "")):
                issues.append(f"topic '{script['topic']}' was already covered; pick another angle.")
                break
            if similar(p.get("hook_text", ""), script.get("hook_text", "")):
                issues.append("this hook was already used; write a fresh one.")
                break
        return issues

    async def verify(self, script: dict) -> list[str]:
        system = (
            "You are a meticulous English teacher, Uzbek editor and brand-safety "
            "reviewer checking an Instagram Reel script before it is published."
        )
        prompt = f"""Script:
{json.dumps(script, ensure_ascii=False)}

Check every item strictly:
- All English is correct and natural; every "right" example really is
  correct and every "wrong" example really is a mistake; facts, rules,
  pronunciations and answers are true.
- {CONTENT_LANGUAGE} text is correct and natural.
- The hook is strong and matches the content; one clear idea.
- No fabricated results, testimonials, guarantees, fake statistics
  presented as facts, or misleading claims about {BRAND_NAME}.
- Caption has a CTA and mentions {BRAND_NAME}; 3-5 hashtags.
Return ok=false with concrete issues if anything is wrong or doubtful."""
        result = await self.gen_json(system, prompt, VERIFY_SCHEMA, 0.0)
        return [] if result.get("ok") else (result.get("issues") or ["reviewer rejected the script"])

    async def write_script(self, forced_pillar: str | None = None) -> dict:
        context = self.history_context()
        now = datetime.now(TZ)
        recent = [p["pillar"] for p in self.memory.posts[-2:]]
        issues = []
        for attempt in range(MAX_ATTEMPTS):
            fix_note = ""
            if issues:
                fix_note = "\nYOUR PREVIOUS DRAFT WAS REJECTED. Fix these problems:\n- " + "\n- ".join(issues)
            pillar_note = (
                f"The owner requested pillar = {forced_pillar}."
                if forced_pillar
                else f"Do not use these pillars now (just posted): {recent}. "
                     "Follow the strategy's pillar weights and favour what performs."
            )
            prompt = f"""{context}

NOW: {now.strftime('%A %Y-%m-%d %H:%M')} ({TZ.key})

Decide the single best next Reel for growth and write it. {pillar_note}
Put your short reasoning in "analysis" (why this pillar/topic/hook now).
{SCRIPT_RULES}
Double-check every English example and answer.{fix_note}"""
            script = await self.gen_json(BRAND_BRIEF, prompt, REEL_SCHEMA, 0.9)
            if forced_pillar:
                script["pillar"] = forced_pillar
            issues = self.local_checks(script)
            if not issues:
                issues = await self.verify(script)
            if not issues:
                return script
            log.info("Reel draft %d rejected: %s", attempt + 1, issues)
        raise RuntimeError(f"Could not produce a verified Reel script: {issues}")

    def full_caption(self, script: dict) -> str:
        caption = script["caption"].strip()
        tags = " ".join(script.get("hashtags", []))
        return f"{caption}\n\n{tags}".strip()[:2200]

    # ---------------- creation / publishing ----------------

    async def create_reel(self, forced_pillar: str | None = None) -> tuple[dict, bytes, dict]:
        script = await self.write_script(forced_pillar)
        video, info = await reel_renderer.render_reel(
            self.client, script, self.brand(),
            engine=VIDEO_ENGINE,
            tts_model=TTS_MODEL,
            tts_voice=TTS_VOICE,
            tts_style=(
                f"Read this as {PERSON_NAME}, an energetic, warm English teacher, "
                "at a brisk social-media pace:"
            ),
            veo_model=VEO_MODEL,
            music_file=MUSIC_FILE,
        )
        return script, video, info

    async def publish(self, bot, script: dict, video: bytes, info: dict) -> dict:
        media_id = await self.ig.publish_reel(video, self.full_caption(script), thumb_offset_ms=600)
        try:
            permalink = await self.ig.permalink(media_id)
        except InstagramError:
            permalink = ""
        now = datetime.now(TZ)
        record = {
            "id": uuid.uuid4().hex[:10],
            "datetime": now.isoformat(),
            "pillar": script["pillar"],
            "series": script.get("series", ""),
            "topic": script["topic"],
            "level": script["level"],
            "hook_text": script.get("hook_text", ""),
            "vocabulary": script.get("vocabulary", []),
            "hashtags": script.get("hashtags", []),
            "engine": info.get("engine"),
            "media_id": media_id,
            "permalink": permalink,
            "metrics": {},
            "score": 0,
        }
        self.memory.posts.append(record)
        await self.memory.save(bot)
        log.info("Published reel %s: %s", media_id, record["topic"])
        return record

    def draft_markup(self, draft_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Joylash", callback_data=f"ig:pub:{draft_id}"),
            InlineKeyboardButton("🔄 Boshqasi", callback_data=f"ig:redo:{draft_id}"),
            InlineKeyboardButton("❌ Bekor", callback_data=f"ig:skip:{draft_id}"),
        ]])

    async def send_draft(self, bot, script: dict, video: bytes, info: dict) -> str:
        draft_id = uuid.uuid4().hex[:10]
        summary = (
            f"🎬 Yangi Reel qoralamasi\n"
            f"🧭 {script['pillar']} / {script['level']} — {script['topic']}\n"
            f"🎞 {info.get('engine')} · {info.get('seconds')}s · ovoz: {'bor' if info.get('voice') else 'yo‘q'}\n"
            f"💭 {script['analysis'][:300]}\n\n"
            f"📝 Caption:\n{self.full_caption(script)}"
        )
        msg = await bot.send_video(
            ADMIN_ID, video=io.BytesIO(video), filename="reel.mp4",
            caption=summary[:1024], supports_streaming=True,
            reply_markup=self.draft_markup(draft_id),
            read_timeout=120, write_timeout=120,
        )
        drafts = self.memory.data["drafts"]
        drafts[draft_id] = {
            "created": datetime.now(TZ).isoformat(),
            "script": script,
            "info": info,
            "file_id": msg.video.file_id if msg.video else msg.document.file_id,
            "message_id": msg.message_id,
        }
        for old in sorted(drafts, key=lambda d: drafts[d]["created"])[:-DRAFTS_KEPT]:
            drafts.pop(old, None)
        await self.memory.save(bot)
        return draft_id

    async def run_cycle(self, bot, forced_pillar: str | None = None, manual: bool = False,
                        approval: bool | None = None) -> str:
        """Create one Reel. Returns a short status line for the owner."""
        try:
            await self.ensure_ready(bot)
        except Exception as e:
            reason = self.explain_error(e)
            await self.alert(bot, "startup", f"❌ Instagramga ulanib bo'lmadi: {reason}")
            return f"❌ {reason}"
        if self.memory.data.get("paused") and not manual:
            return "⏸ pauza"
        approval = IG_APPROVAL if approval is None else approval

        async with self.cycle_lock:
            try:
                script, video, info = await self.create_reel(forced_pillar)
                if approval:
                    await self.send_draft(bot, script, video, info)
                    return f"📨 Qoralama yuborildi: {script['topic']}"
                record = await self.publish(bot, script, video, info)
            except Exception as e:
                log.exception("Instagram cycle failed")
                reason = self.explain_error(e)
                self.last_error = reason
                await self.alert(
                    bot, "cycle_failed",
                    f"❌ Reel tayyorlab bo'lmadi: {reason}\nKeyingi vaqtda yana urinaman.",
                )
                return f"❌ {reason}"
        if ADMIN_ID is not None:
            await bot.send_message(
                ADMIN_ID,
                f"✅ Instagram'ga Reel chiqdi: {record['topic']}\n{record['permalink']}",
            )
        return f"✅ Chiqdi: {record['topic']}"

    # ---------------- approval buttons ----------------

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query.from_user or query.from_user.id != ADMIN_ID:
            await query.answer("Ruxsat yo'q", show_alert=True)
            return
        try:
            _, action, draft_id = query.data.split(":", 2)
        except ValueError:
            await query.answer()
            return
        await self.ensure_ready(context.bot)
        draft = self.memory.data["drafts"].get(draft_id)
        if not draft:
            await query.answer("Qoralama topilmadi (eskirgan).", show_alert=True)
            return

        async def set_caption(text: str):
            try:
                await query.edit_message_caption(caption=text[:1024], reply_markup=None)
            except BadRequest as e:
                log.warning("Could not edit draft message: %s", e)

        if action == "skip":
            self.memory.data["drafts"].pop(draft_id, None)
            await self.memory.save(context.bot)
            await query.answer("Bekor qilindi")
            await set_caption(f"❌ Bekor qilindi: {draft['script']['topic']}")
            return

        if action == "redo":
            self.memory.data["drafts"].pop(draft_id, None)
            await self.memory.save(context.bot)
            await query.answer("Yangisi tayyorlanmoqda...")
            await set_caption(f"🔄 Almashtirildi: {draft['script']['topic']}")
            status = await self.run_cycle(context.bot, manual=True, approval=True)
            if status.startswith("❌"):
                await context.bot.send_message(ADMIN_ID, status)
            return

        if action == "pub":
            await query.answer("Instagram'ga yuklanmoqda...")
            await set_caption(f"⏳ Yuklanmoqda: {draft['script']['topic']}")
            try:
                file = await context.bot.get_file(draft["file_id"])
                video = bytes(await file.download_as_bytearray())
                async with self.cycle_lock:
                    record = await self.publish(context.bot, draft["script"], video, draft["info"])
                self.memory.data["drafts"].pop(draft_id, None)
                await self.memory.save(context.bot)
                await set_caption(f"✅ Joylandi: {record['topic']}\n{record['permalink']}")
            except Exception as e:
                log.exception("Publishing draft failed")
                reason = self.explain_error(e)
                try:
                    await query.edit_message_caption(
                        caption=f"❌ Joylab bo'lmadi: {reason}"[:1024],
                        reply_markup=self.draft_markup(draft_id),
                    )
                except BadRequest:
                    await context.bot.send_message(ADMIN_ID, f"❌ Joylab bo'lmadi: {reason}")

    # ---------------- comments ----------------

    async def reply_to_comments(self, bot):
        await self.ensure_ready(bot)
        own = (self.memory.data["profile"].get("username") or "").lower()
        replied = set(self.memory.data["replied_comments"])
        cutoff = datetime.now(TZ) - timedelta(days=7)
        recent = [p for p in self.memory.posts if p.get("media_id")
                  and datetime.fromisoformat(p["datetime"]) > cutoff][-10:]
        pending = []
        for post in recent:
            try:
                comments = await self.ig.comments(post["media_id"])
            except InstagramError as e:
                log.info("Comments unavailable for %s: %s", post["media_id"], e)
                continue
            for c in comments:
                if c["id"] in replied or (c.get("username") or "").lower() == own:
                    continue
                answered = any(
                    (r.get("username") or "").lower() == own
                    for r in (c.get("replies") or {}).get("data", [])
                )
                if answered:
                    replied.add(c["id"])
                    continue
                pending.append({
                    "comment_id": c["id"],
                    "username": c.get("username", ""),
                    "text": (c.get("text") or "")[:400],
                    "reel_topic": post["topic"],
                })
        if not pending:
            self.memory.data["replied_comments"] = list(replied)
            return
        pending = pending[:15]
        prompt = f"""Reply to these Instagram comments on {BRAND_NAME} Reels as
{PERSON_NAME}'s team. Short (max 200 chars), warm, helpful, in the
commenter's language (default {CONTENT_LANGUAGE}). If someone answers a quiz,
say whether it is right and why in one line. Invite questions; occasionally
mention following {BRAND_NAME}. Never promise prices, results or personal
data. Return an empty reply for spam, insults, emoji-only comments, or
anything that needs the owner personally (prices, enrolment, complaints).

COMMENTS:
{json.dumps(pending, ensure_ascii=False)}"""
        result = await self.gen_json(BRAND_BRIEF, prompt, REPLY_SCHEMA, 0.6)
        ids = {c["comment_id"] for c in pending}
        for item in result.get("replies", []):
            if item["comment_id"] not in ids:
                continue
            replied.add(item["comment_id"])
            text = item.get("reply", "").strip()
            if not text:
                continue
            try:
                await self.ig.reply_comment(item["comment_id"], text[:300])
                await asyncio.sleep(random.uniform(4, 12))
            except InstagramError as e:
                log.warning("Reply failed: %s", e)
        self.memory.data["replied_comments"] = list(replied)
        await self.memory.save(bot, backup=False)

    # ---------------- token ----------------

    async def maybe_refresh_token(self, bot):
        if GRAPH_HOST != "graph.instagram.com":
            return
        await self.ensure_ready(bot)
        saved = self.memory.data.get("token") or {}
        if saved.get("refreshed") and datetime.now(TZ) - datetime.fromisoformat(saved["refreshed"]) < timedelta(days=7):
            return
        try:
            body = await self.ig.refresh_token()
        except InstagramError as e:
            await self.alert(bot, "token", f"⚠️ Instagram tokenini yangilab bo'lmadi: {e}")
            return
        self.memory.data["token"] = {
            "value": body["access_token"],
            "refreshed": datetime.now(TZ).isoformat(),
            "env_fingerprint": token_fingerprint(IG_ACCESS_TOKEN),
        }
        await self.memory.save(bot)
        log.info("Instagram token refreshed")

    # ---------------- reports ----------------

    def report_text(self) -> str:
        g = self.growth_status()
        profile = self.memory.data["profile"]
        lines = [
            f"📈 @{profile.get('username')} — o'sish hisoboti",
            f"👥 Obunachilar: {fmt_int(g['current'])} / {fmt_int(g['target'])}",
            f"➕ Boshlanganidan beri: {g['gained']:+,} (kuniga ~{g['per_day']})".replace(",", " "),
            f"🗓 Oxirgi 7 kun: {g['last_7_days']:+,}".replace(",", " "),
            f"🎯 Maqsadga yetish uchun kuniga: {fmt_int(g['needed_per_day'])} ({g['days_left']} kun qoldi)",
        ]
        week_ago = datetime.now(TZ) - timedelta(days=7)
        week = [p for p in self.memory.posts if datetime.fromisoformat(p["datetime"]) > week_ago]
        if week:
            best = max(week, key=lambda p: p.get("metrics", {}).get("views", 0) or p.get("score", 0))
            m = best.get("metrics", {})
            lines.append(
                f"\n🏆 Haftaning eng yaxshi Reel'i: {best['topic']}\n"
                f"   👁 {fmt_int(m.get('views', 0))} · ❤️ {m.get('likes', 0)} · 💾 {m.get('saved', 0)} · "
                f"🔁 {m.get('shares', 0)}\n   {best.get('permalink', '')}"
            )
        perf = self.pillar_performance()
        if perf:
            lines.append("\n📊 Rubrikalar (o'rtacha ko'rishlar):")
            for k, v in sorted(perf.items(), key=lambda x: -x[1]["avg_views"]):
                lines.append(f"• {k}: {fmt_int(v['avg_views'])} ({v['posts']} ta)")
        if g["needed_per_day"] > max(g["per_day"], 1) * 3:
            lines.append(
                "\n⚠️ Hozirgi sur'at maqsaddan ancha past. Tezlashtirish uchun: kollaboratsiyalar, "
                "Live efirlar, yuzingiz bilan videolar va reklama byudjeti (/ig_audit tavsiyalari)."
            )
        return "\n".join(lines)

    # ---------------- jobs ----------------

    async def job_post(self, context: ContextTypes.DEFAULT_TYPE):
        await asyncio.sleep(random.randint(0, 300))
        await self.run_cycle(context.bot)

    async def job_startup(self, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        try:
            await self.ensure_ready(bot)
        except Exception as e:
            log.exception("Instagram manager startup failed")
            await self.alert(bot, "startup", f"❌ Instagramga ulanib bo'lmadi: {self.explain_error(e)}")
            return
        await self.refresh_trends(bot)
        updated = self.memory.data.get("strategy_updated")
        if not updated or datetime.now(TZ) - datetime.fromisoformat(updated) > timedelta(days=7):
            try:
                await self.audit(bot)
            except Exception as e:
                log.exception("Instagram audit failed")
                await self.alert(bot, "audit", f"⚠️ Profil tahlili bajarilmadi: {self.explain_error(e)}")

    async def job_metrics(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.refresh_metrics(context.bot)
        except Exception as e:
            log.warning("Metrics refresh failed: %s", e)

    async def job_weekly(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.refresh_trends(context.bot)
            await self.audit(context.bot)
        except Exception as e:
            log.warning("Weekly audit failed: %s", e)

    async def job_report(self, context: ContextTypes.DEFAULT_TYPE):
        if ADMIN_ID is None or not self.ready:
            return
        await context.bot.send_message(ADMIN_ID, self.report_text())

    async def job_comments(self, context: ContextTypes.DEFAULT_TYPE):
        if self.memory.data.get("paused"):
            return
        try:
            await self.reply_to_comments(context.bot)
        except Exception as e:
            log.warning("Comment replies failed: %s", e)

    async def job_token(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.maybe_refresh_token(context.bot)
        except Exception as e:
            log.warning("Token refresh job failed: %s", e)

    async def job_backup(self, context: ContextTypes.DEFAULT_TYPE):
        if self.ready and self.memory.dirty:
            await self.memory.backup(context.bot)

    # ---------------- owner commands ----------------

    def parse_pillar(self, context) -> str | None:
        if context.args and context.args[0] in PILLARS:
            return context.args[0]
        return None

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.ensure_ready(context.bot)
        except Exception as e:
            await update.message.reply_text(f"❌ {self.explain_error(e)}")
            return
        last = self.memory.posts[-1] if self.memory.posts else None
        lines = [
            f"📸 Instagram: @{self.memory.data['profile'].get('username')}",
            f"⏸ Pauza: {'ha' if self.memory.data.get('paused') else 'yo‘q'}",
            f"🕒 Reel vaqtlari: {IG_POST_TIMES} ({TZ.key})",
            f"✅ Tasdiqlash rejimi: {'yoqilgan' if IG_APPROVAL else 'o‘chiq (avtomatik)'}",
            f"💬 Avto-javob: {'yoqilgan' if IG_AUTO_REPLY else 'o‘chiq'}",
            f"🎞 Video: {VIDEO_ENGINE}",
            f"📝 Agent chiqargan Reel'lar: {len(self.memory.posts)}",
            f"📨 Kutilayotgan qoralamalar: {len(self.memory.data['drafts'])}",
        ]
        if last:
            lines.append(f"🆕 Oxirgi: {last['datetime'][:16]} — {last['topic']}")
        lines.append("")
        lines.append(self.report_text())
        await update.message.reply_text("\n".join(lines))

    async def cmd_audit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Profil tahlil qilinmoqda...")
        try:
            await self.ensure_ready(context.bot)
            await self.audit(context.bot)
        except Exception as e:
            await update.message.reply_text(f"❌ {self.explain_error(e)}")

    async def cmd_post_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Reel tayyorlanmoqda (1-3 daqiqa)...")
        status = await self.run_cycle(context.bot, self.parse_pillar(context), manual=True)
        await update.message.reply_text(status)

    async def cmd_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Qoralama tayyorlanmoqda (1-3 daqiqa)...")
        status = await self.run_cycle(
            context.bot, self.parse_pillar(context), manual=True, approval=True
        )
        if status.startswith("❌"):
            await update.message.reply_text(status)

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await self.refresh_metrics(context.bot)
            await update.message.reply_text(self.report_text())
        except Exception as e:
            await update.message.reply_text(f"❌ {self.explain_error(e)}")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        self.memory.data["paused"] = True
        await self.memory.save(context.bot)
        await update.message.reply_text("⏸ Instagram avtomatik postlari to‘xtatildi. /ig_resume bilan yoqing.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.ensure_ready(context.bot)
        self.memory.data["paused"] = False
        await self.memory.save(context.bot)
        await update.message.reply_text("▶️ Instagram avtomatik postlari yoqildi.")


# ---------------------------------------------------------
# WIRING
# ---------------------------------------------------------

def setup(app: Application, gemini_client: genai.Client) -> InstagramManager | None:
    """Register Instagram jobs and handlers. No-op if IG_ACCESS_TOKEN is unset."""
    if not IG_ACCESS_TOKEN:
        log.warning("IG_ACCESS_TOKEN is not set - Instagram manager disabled")
        return None
    if app.job_queue is None:
        raise RuntimeError('JobQueue is unavailable. Install "python-telegram-bot[job-queue]".')
    if ADMIN_ID is None:
        log.warning("ADMIN_ID is not set - Instagram drafts are auto-published, no reports")

    manager = InstagramManager(gemini_client)
    jq = app.job_queue
    jq.run_once(manager.job_startup, when=20)
    for t in parse_times(IG_POST_TIMES):
        jq.run_daily(manager.job_post, time=t, name=f"ig_post_{t.strftime('%H%M')}")
    jq.run_repeating(manager.job_metrics, interval=timedelta(hours=6), first=600)
    jq.run_daily(manager.job_weekly, time=dtime(9, 0, tzinfo=TZ), days=(1,), name="ig_weekly")
    jq.run_daily(manager.job_report, time=dtime(21, 30, tzinfo=TZ), name="ig_report")
    jq.run_repeating(manager.job_token, interval=timedelta(days=1), first=900)
    jq.run_repeating(manager.job_backup, interval=1800, first=1800)
    if IG_AUTO_REPLY:
        jq.run_repeating(manager.job_comments, interval=timedelta(minutes=30), first=300)

    if ADMIN_ID is not None:
        # Long-running commands use block=False so the essay bot keeps answering.
        owner = filters.User(ADMIN_ID) & filters.ChatType.PRIVATE
        app.add_handler(CommandHandler("ig_status", manager.cmd_status, filters=owner))
        app.add_handler(CommandHandler("ig_audit", manager.cmd_audit, filters=owner, block=False))
        app.add_handler(CommandHandler("ig_post_now", manager.cmd_post_now, filters=owner, block=False))
        app.add_handler(CommandHandler("ig_preview", manager.cmd_preview, filters=owner, block=False))
        app.add_handler(CommandHandler("ig_report", manager.cmd_report, filters=owner, block=False))
        app.add_handler(CommandHandler("ig_pause", manager.cmd_pause, filters=owner))
        app.add_handler(CommandHandler("ig_resume", manager.cmd_resume, filters=owner))
        app.add_handler(CallbackQueryHandler(manager.on_callback, pattern=r"^ig:", block=False))

    log.info("Instagram manager scheduled at %s (%s)", IG_POST_TIMES, TZ.key)
    return manager

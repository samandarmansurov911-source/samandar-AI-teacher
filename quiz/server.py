"""Lug'at musobaqasi — Kahoot uslubidagi so'z yodlash o'yini.

O'qituvchi lug'at ro'yxatlarini joylaydi va o'yinni boshqaradi (/host).
O'quvchilar ism tanlab kiradi (/), ekranda o'zbekcha so'z chiqadi,
ular inglizchasini yozadi. Tez va to'g'ri javob ko'proq ball beradi,
hamma o'z o'rnini va umumiy reytingni ko'rib turadi.

Ishga tushirish:  python server.py   (PORT, HOST_PASSWORD, DATA_DIR)
"""

import asyncio
import json
import logging
import os
import random
import re
import secrets
import time
import unicodedata
from pathlib import Path

from aiohttp import WSMsgType, web

log = logging.getLogger("quiz")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
LISTS_FILE = DATA_DIR / "lists.json"
HOST_PASSWORD = os.environ.get("HOST_PASSWORD", "teacher123")
DEFAULT_PASSWORD = "HOST_PASSWORD" not in os.environ

MAX_PLAYERS = 300
MAX_NAME = 20
REVEAL_PAUSE = 6  # avtomatik rejimda natijadan keyin kutish (soniya)

SAMPLE_LIST = """apple - olma
book - kitob
house / home - uy
to run - yugurmoq
beautiful - chiroyli
teacher - o'qituvchi
water - suv
friend - do'st
big / large - katta
to learn - o'rganmoq"""


# ---------------------------------------------------------------- lug'atlar

LINE_NUMBER = re.compile(r"^\s*\d+\s*[.)]\s*")
SEPARATORS = ["\t", " — ", " – ", " - ", "=", "—", "–", ":", " -", "- ", "-"]


def parse_words(text, swap=False):
    """Matnni (inglizcha - o'zbekcha) juftliklarga ajratadi."""
    words, bad = [], []
    for raw in text.splitlines():
        line = LINE_NUMBER.sub("", raw.replace("*", "")).strip()
        if not line:
            continue
        for sep in SEPARATORS:
            if sep in line:
                left, right = line.split(sep, 1)
                break
        else:
            left = right = ""
        left, right = left.strip(" ;,\t"), right.strip(" ;,\t")
        if not left or not right:
            bad.append(raw.strip())
            continue
        en, uz = (right, left) if swap else (left, right)
        words.append({"en": en[:120], "uz": uz[:160]})
    return words, bad


class ListStore:
    def __init__(self, path):
        self.path = path
        self.lists = {}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text("utf-8"))
            self.lists = {l["id"]: l for l in data.get("lists", []) if l.get("words")}
        except FileNotFoundError:
            words, _ = parse_words(SAMPLE_LIST)
            self.add("Namuna lug'at", words)
        except Exception:
            log.exception("lists.json o'qilmadi")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"lists": list(self.lists.values())}, ensure_ascii=False, indent=1),
            "utf-8",
        )
        tmp.replace(self.path)

    def add(self, name, words, list_id=None):
        list_id = list_id or secrets.token_hex(4)
        self.lists[list_id] = {
            "id": list_id,
            "name": name.strip()[:60] or "Nomsiz",
            "words": words,
            "updated": int(time.time()),
        }
        self.save()
        return self.lists[list_id]

    def delete(self, list_id):
        if self.lists.pop(list_id, None):
            self.save()

    def summary(self):
        items = sorted(self.lists.values(), key=lambda l: -l["updated"])
        return [{"id": l["id"], "name": l["name"], "count": len(l["words"])} for l in items]


# ---------------------------------------------------------- javob tekshirish

def normalize(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[‘’`ʻʼ´]", "'", text)
    text = re.sub(r"[^\w' -]", " ", text)
    text = re.sub(r"[\s-]+", " ", text).strip()
    for prefix in ("to ", "a ", "an ", "the "):
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix):]
            break
    return text


def accepted_answers(en):
    variants = set()
    for part in re.split(r"[/;,|]", en):
        if not part.strip():
            continue
        # "(to) run" -> "run" va "to run"
        for v in (re.sub(r"\([^)]*\)", " ", part), part.replace("(", " ").replace(")", " ")):
            n = normalize(v)
            if n:
                variants.add(n)
    return variants


def close_enough(a, b):
    """Bitta harf xatosi (qo'shilgan, tushib qolgan, almashgan yoki o'rni almashgan)."""
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 4:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def check_answer(given, en, allow_typos):
    """(to'g'rimi, kichik_xato_bilanmi)"""
    g = normalize(given)
    if not g:
        return False, False
    options = accepted_answers(en)
    if g in options:
        return True, False
    if allow_typos and any(close_enough(g, o) for o in options):
        return True, True
    return False, False


# ------------------------------------------------------------------- o'yin

class Player:
    def __init__(self, name):
        self.id = secrets.token_hex(4)
        self.token = secrets.token_urlsafe(16)
        self.name = name
        self.score = 0
        self.streak = 0
        self.correct = 0
        self.rank = 0
        self.prev_rank = 0
        self.sockets = set()
        self.answer = None  # joriy savolga javob

    @property
    def online(self):
        return bool(self.sockets)


class Game:
    def __init__(self, store):
        self.store = store
        self.players = {}  # id -> Player
        self.hosts = set()
        self.phase = "lobby"  # lobby | question | reveal | final
        self.list_id = next(iter(store.lists), None)
        self.order, self.pos = [], 0
        self.question = None
        self.qnum = 0
        self.timer = None
        self.settings = {"time": 20, "auto": False, "typos": False}
        self.shuffle()

    # --- yordamchilar
    @property
    def current_list(self):
        return self.store.lists.get(self.list_id)

    def shuffle(self):
        lst = self.current_list
        self.order = list(range(len(lst["words"]))) if lst else []
        random.shuffle(self.order)
        self.pos = 0

    def cancel_timer(self):
        if self.timer and not self.timer.done() and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None

    def rerank(self):
        ranked = sorted(self.players.values(), key=lambda p: (-p.score, p.name.lower()))
        rank, last = 0, None
        for i, p in enumerate(ranked):
            if p.score != last:
                rank, last = i + 1, p.score
            p.rank = rank
        return ranked

    def leaderboard(self):
        return [
            {
                "id": p.id,
                "name": p.name,
                "score": p.score,
                "rank": p.rank,
                "move": (p.prev_rank - p.rank) if p.prev_rank else 0,
                "streak": p.streak,
                "online": p.online,
            }
            for p in self.rerank()
        ]

    def remaining(self):
        if self.phase != "question":
            return 0
        return max(0, int((self.question["ends"] - time.monotonic()) * 1000))

    # --- holatni yuborish
    def base_state(self):
        lst = self.current_list
        state = {
            "t": "state",
            "phase": self.phase,
            "list": {"name": lst["name"], "count": len(lst["words"])} if lst else None,
            "leaderboard": self.leaderboard(),
            "playerCount": len(self.players),
        }
        q = self.question
        if q and self.phase in ("question", "reveal"):
            answered = [p for p in self.players.values() if p.answer]
            state["question"] = {
                "num": self.qnum,
                "left": len(self.order) - self.pos,
                "uz": q["uz"],
                "duration": q["duration"],
                "remaining": self.remaining(),
                "answered": len(answered),
            }
            if self.phase == "reveal":
                right = sorted((p for p in answered if p.answer["correct"]), key=lambda p: p.answer["ms"])
                state["question"].update(
                    en=q["en"],
                    correctCount=len(right),
                    fastest=[{"name": p.name, "ms": p.answer["ms"]} for p in right[:5]],
                )
        return state

    def host_state(self, base):
        state = dict(base)
        state["host"] = True
        state["settings"] = self.settings
        state["listId"] = self.list_id
        state["lists"] = self.store.summary()
        state["defaultPassword"] = DEFAULT_PASSWORD
        if self.phase == "reveal" and self.question:
            wrong = {}
            for p in self.players.values():
                if p.answer and not p.answer["correct"] and p.answer["text"].strip():
                    key = p.answer["text"].strip().lower()
                    wrong[key] = wrong.get(key, 0) + 1
            state["wrongAnswers"] = sorted(wrong.items(), key=lambda kv: -kv[1])[:8]
        answered = {pid for pid, p in self.players.items() if p.answer}
        state["answeredIds"] = list(answered)
        return state

    def player_state(self, base, p):
        state = dict(base)
        you = {"id": p.id, "name": p.name, "score": p.score, "rank": p.rank,
               "streak": p.streak, "answered": bool(p.answer)}
        if self.phase == "reveal":
            a = p.answer or {"text": "", "correct": False, "points": 0, "typo": False}
            you["result"] = {k: a.get(k) for k in ("text", "correct", "points", "typo")}
        state["you"] = you
        return state

    async def broadcast(self):
        base = self.base_state()
        jobs = []
        if self.hosts:
            data = json.dumps(self.host_state(base), ensure_ascii=False)
            jobs += [send_raw(ws, data) for ws in list(self.hosts)]
        for p in self.players.values():
            if p.sockets:
                data = json.dumps(self.player_state(base, p), ensure_ascii=False)
                jobs += [send_raw(ws, data) for ws in list(p.sockets)]
        if jobs:
            await asyncio.gather(*jobs)

    async def send_state(self, ws, player=None):
        base = self.base_state()
        state = self.player_state(base, player) if player else self.host_state(base)
        await send_raw(ws, json.dumps(state, ensure_ascii=False))

    # --- o'yin jarayoni
    async def next_question(self):
        lst = self.current_list
        if not lst or not lst["words"]:
            return
        if self.pos >= len(self.order):
            self.shuffle()
        self.cancel_timer()
        word = lst["words"][self.order[self.pos]]
        self.pos += 1
        self.qnum += 1
        duration = self.settings["time"]
        self.question = {
            "en": word["en"],
            "uz": word["uz"],
            "duration": duration,
            "start": time.monotonic(),
            "ends": time.monotonic() + duration,
        }
        self.rerank()
        for p in self.players.values():
            p.answer = None
            p.prev_rank = p.rank
        self.phase = "question"
        self.timer = asyncio.create_task(self._question_timer(duration))
        await self.broadcast()

    async def _question_timer(self, duration):
        await asyncio.sleep(duration + 0.3)
        await self.reveal()

    async def reveal(self):
        if self.phase != "question":
            return
        self.cancel_timer()
        for p in self.players.values():
            if not p.answer or not p.answer["correct"]:
                p.streak = 0
        self.phase = "reveal"
        await self.broadcast()
        if self.settings["auto"]:
            self.timer = asyncio.create_task(self._auto_next())

    async def _auto_next(self):
        await asyncio.sleep(REVEAL_PAUSE)
        if self.pos >= len(self.order):
            await self.finish()
        else:
            await self.next_question()

    async def finish(self):
        self.cancel_timer()
        self.phase = "final"
        await self.broadcast()

    async def submit(self, p, text):
        if self.phase != "question" or p.answer is not None:
            return
        q = self.question
        elapsed = time.monotonic() - q["start"]
        if elapsed > q["duration"] + 0.5:
            return
        correct, typo = check_answer(text[:120], q["en"], self.settings["typos"])
        points = 0
        if correct:
            p.streak += 1
            speed = max(0.0, 1 - elapsed / q["duration"])
            points = round(500 + 500 * speed) + min(p.streak - 1, 5) * 50
            p.score += points
            p.correct += 1
        p.answer = {"text": text[:120], "correct": correct, "typo": typo,
                    "points": points, "ms": int(elapsed * 1000)}
        online = [x for x in self.players.values() if x.online]
        if online and all(x.answer for x in online):
            await self.reveal()
        else:
            await self.broadcast()


async def send_raw(ws, data):
    try:
        await ws.send_str(data)
    except Exception:
        pass


# --------------------------------------------------------------- HTTP / WS

def is_host(request):
    return secrets.compare_digest(request.headers.get("X-Host-Password", ""), HOST_PASSWORD)


def require_host(handler):
    async def wrapper(request):
        if not is_host(request):
            return web.json_response({"error": "Parol noto'g'ri"}, status=401)
        return await handler(request)
    return wrapper


@require_host
async def api_lists(request):
    return web.json_response(request.app["game"].store.summary())


@require_host
async def api_get_list(request):
    lst = request.app["game"].store.lists.get(request.match_info["id"])
    if not lst:
        raise web.HTTPNotFound()
    text = "\n".join(f"{w['en']} - {w['uz']}" for w in lst["words"])
    return web.json_response({"id": lst["id"], "name": lst["name"], "text": text})


@require_host
async def api_parse(request):
    body = await request.json()
    words, bad = parse_words(body.get("text", ""), bool(body.get("swap")))
    return web.json_response({"words": words, "bad": bad})


@require_host
async def api_save_list(request):
    game = request.app["game"]
    body = await request.json()
    words, bad = parse_words(body.get("text", ""), bool(body.get("swap")))
    if not words:
        return web.json_response({"error": "Birorta ham so'z topilmadi"}, status=400)
    list_id = body.get("id") if body.get("id") in game.store.lists else None
    lst = game.store.add(body.get("name", ""), words, list_id)
    if list_id and list_id == game.list_id or not game.current_list:
        game.list_id = lst["id"]
        game.shuffle()
    await game.broadcast()
    return web.json_response({"id": lst["id"], "count": len(words), "bad": bad})


@require_host
async def api_delete_list(request):
    game = request.app["game"]
    game.store.delete(request.match_info["id"])
    if not game.current_list:
        game.list_id = next(iter(game.store.lists), None)
        game.shuffle()
    await game.broadcast()
    return web.json_response({"ok": True})


@require_host
async def api_export(request):
    data = json.dumps({"lists": list(request.app["game"].store.lists.values())},
                      ensure_ascii=False, indent=1)
    return web.Response(
        text=data,
        content_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="lugatlar.json"'},
    )


@require_host
async def api_import(request):
    game = request.app["game"]
    try:
        data = await request.json()
        added = 0
        for l in data.get("lists", []):
            words = [{"en": str(w["en"])[:120], "uz": str(w["uz"])[:160]}
                     for w in l.get("words", []) if w.get("en") and w.get("uz")]
            if words:
                game.store.add(str(l.get("name", "")), words, str(l.get("id") or "") or None)
                added += 1
    except Exception:
        return web.json_response({"error": "Fayl formati noto'g'ri"}, status=400)
    if not game.current_list:
        game.list_id = next(iter(game.store.lists), None)
        game.shuffle()
    await game.broadcast()
    return web.json_response({"added": added})


async def handle_host(game, ws, msg):
    t = msg.get("t")
    if t == "start" or t == "next":
        if game.phase == "question":
            await game.reveal()
        else:
            await game.next_question()
    elif t == "reveal":
        await game.reveal()
    elif t == "finish":
        await game.finish()
    elif t == "lobby":
        game.cancel_timer()
        game.phase = "lobby"
        game.question = None
        await game.broadcast()
    elif t == "set_list":
        if msg.get("id") in game.store.lists:
            game.list_id = msg["id"]
            game.shuffle()
            await game.broadcast()
    elif t == "settings":
        s = msg.get("settings", {})
        if s.get("time") in (5, 10, 15, 20, 30, 45, 60):
            game.settings["time"] = s["time"]
        for key in ("auto", "typos"):
            if key in s:
                game.settings[key] = bool(s[key])
        if game.settings["auto"] and game.phase == "reveal" and not game.timer:
            game.timer = asyncio.create_task(game._auto_next())
        if not game.settings["auto"] and game.phase == "reveal":
            game.cancel_timer()
        await game.broadcast()
    elif t == "kick":
        p = game.players.pop(msg.get("id"), None)
        if p:
            for s in list(p.sockets):
                await send_raw(s, json.dumps({"t": "kicked"}))
                await s.close()
            await game.broadcast()
    elif t == "reset":
        game.cancel_timer()
        for p in game.players.values():
            p.score = p.streak = p.correct = p.rank = p.prev_rank = 0
            p.answer = None
        game.phase, game.question, game.qnum = "lobby", None, 0
        game.shuffle()
        await game.broadcast()
    elif t == "clear_players":
        for p in list(game.players.values()):
            for s in list(p.sockets):
                await send_raw(s, json.dumps({"t": "kicked"}))
                await s.close()
        game.players.clear()
        await game.broadcast()


async def ws_handler(request):
    game = request.app["game"]
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    player, host = None, False

    async def error(text):
        await send_raw(ws, json.dumps({"t": "error", "text": text}, ensure_ascii=False))

    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                msg = json.loads(m.data)
            except ValueError:
                continue
            t = msg.get("t")

            if t == "host_auth":
                if secrets.compare_digest(str(msg.get("password", "")), HOST_PASSWORD):
                    host = True
                    game.hosts.add(ws)
                    await send_raw(ws, json.dumps({"t": "host_ok"}))
                    await game.send_state(ws)
                else:
                    await error("Parol noto'g'ri")
            elif host:
                await handle_host(game, ws, msg)
            elif t == "join":
                token = msg.get("token")
                known = next((p for p in game.players.values() if token and p.token == token), None)
                if known:
                    player = known
                else:
                    name = re.sub(r"\s+", " ", str(msg.get("name", ""))).strip()[:MAX_NAME]
                    if not name:
                        await error("Ismingizni yozing")
                        continue
                    if any(p.name.lower() == name.lower() for p in game.players.values()):
                        await error("Bu ism band. Boshqa ism tanlang")
                        continue
                    if len(game.players) >= MAX_PLAYERS:
                        await error("O'yin to'lgan")
                        continue
                    player = Player(name)
                    game.players[player.id] = player
                    game.rerank()
                player.sockets.add(ws)
                await send_raw(ws, json.dumps({"t": "joined", "token": player.token,
                                               "name": player.name}, ensure_ascii=False))
                await game.broadcast()
            elif t == "answer" and player and player.id in game.players:
                await game.submit(player, str(msg.get("text", "")))
            elif t == "leave" and player:
                game.players.pop(player.id, None)
                player.sockets.discard(ws)
                player = None
                await send_raw(ws, json.dumps({"t": "left"}))
                await game.broadcast()
    finally:
        game.hosts.discard(ws)
        if player:
            player.sockets.discard(ws)
            if player.id in game.players:
                await game.broadcast()
    return ws


def page(name):
    async def handler(request):
        return web.FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})
    return handler


async def health(request):
    return web.Response(text="ok")


def make_app():
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app["game"] = Game(ListStore(LISTS_FILE))
    app.router.add_get("/", page("index.html"))
    app.router.add_get("/host", page("host.html"))
    app.router.add_get("/health", health)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/lists", api_lists)
    app.router.add_get("/api/lists/{id}", api_get_list)
    app.router.add_post("/api/parse", api_parse)
    app.router.add_post("/api/lists", api_save_list)
    app.router.add_delete("/api/lists/{id}", api_delete_list)
    app.router.add_get("/api/export", api_export)
    app.router.add_post("/api/import", api_import)
    app.router.add_static("/static/", STATIC_DIR)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if DEFAULT_PASSWORD:
        log.warning("HOST_PASSWORD berilmagan, standart parol: %s", HOST_PASSWORD)
    web.run_app(make_app(), port=int(os.environ.get("PORT", 8080)))

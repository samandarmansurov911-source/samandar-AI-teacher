"""
Turns a reel script into a branded vertical MP4 (1080x1920, H.264/AAC).

Engines:
    slides  animated text slides + Gemini TTS voice-over (default, cheap)
    veo     a Veo-generated cinematic hook clip with brand overlay, followed
            by the slides lesson. Falls back to slides if Veo fails.

Script format (produced by instagram_manager):
    {
      "hook_text": "...",
      "scenes": [
        {"title": "...", "lines": [{"text": "...", "style": "normal"}], "voice": "..."},
        ...
      ],
      "veo_prompt": "..."
    }
Line styles: normal, wrong, right, highlight.
"""

import asyncio
import io
import logging
import os
import re
import shutil
import tempfile
import wave

from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types as genai_types

log = logging.getLogger("reel_renderer")

W, H = 1080, 1920
FPS = 30
MAX_SECONDS = 90

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_FILES = {
    "bold": os.environ.get("FONT_BOLD") or os.path.join(FONT_DIR, "Inter-ExtraBold.otf"),
    "medium": os.environ.get("FONT_MEDIUM") or os.path.join(FONT_DIR, "Inter-Medium.otf"),
}

# Nur Academy palette: deep navy + warm gold ("nur" = light).
BG_TOP = (8, 22, 48)
BG_BOTTOM = (18, 58, 99)
GOLD = (245, 183, 0)
WHITE = (255, 255, 255)
SOFT = (200, 214, 232)
RED = (255, 92, 92)
GREEN = (64, 214, 128)
CARD = (255, 255, 255, 20)

CONTENT_TOP = 380
CONTENT_BOTTOM = 1450  # Instagram covers roughly the bottom 400px with UI.
SIDE = 80


# ---------------------------------------------------------
# TEXT HELPERS
# ---------------------------------------------------------

_font_cache = {}


def font(kind: str, size: int):
    key = (kind, size)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(FONT_FILES[kind], size)
        except OSError:
            log.warning("Font %s missing, using Pillow default", FONT_FILES[kind])
            _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def clean_text(text: str) -> str:
    """Normalise apostrophes and drop emoji the fonts cannot draw."""
    text = re.sub(r"[ʻʼ‘’`]", "'", text or "")
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[\U00010000-\U0010FFFF☀-➿️‍]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(), ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=fnt) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            # Break words that are wider than the line on their own.
            while draw.textlength(word, font=fnt) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and draw.textlength(word[:cut], font=fnt) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return lines


def text_height(fnt) -> int:
    ascent, descent = fnt.getmetrics()
    return ascent + descent


# ---------------------------------------------------------
# FRAMES
# ---------------------------------------------------------

def background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=color)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([W - 420, -260, W + 260, 420], fill=(245, 183, 0, 16))
    gdraw.ellipse([-300, H - 700, 380, H - 20], fill=(80, 160, 255, 12))
    return Image.alpha_composite(img.convert("RGBA"), glow)


_bg_cache = None


def base_frame(brand: dict, scene_index: int, scene_count: int) -> Image.Image:
    global _bg_cache
    if _bg_cache is None:
        _bg_cache = background()
    img = _bg_cache.copy()
    draw = ImageDraw.Draw(img)

    # Story-style progress segments.
    gap, top = 10, 70
    seg = (W - 2 * SIDE - gap * (scene_count - 1)) / max(scene_count, 1)
    for i in range(scene_count):
        x0 = SIDE + i * (seg + gap)
        fill = GOLD if i <= scene_index else (255, 255, 255, 60)
        draw.rounded_rectangle([x0, top, x0 + seg, top + 8], radius=4, fill=fill)

    brand_font = font("bold", 50)
    name = brand["brand"].upper()
    spaced = " ".join(name)
    width = draw.textlength(spaced, font=brand_font)
    draw.text(((W - width) / 2, 130), spaced, font=brand_font, fill=GOLD)
    person_font = font("medium", 36)
    person = f"with {brand['person']}"
    width = draw.textlength(person, font=person_font)
    draw.text(((W - width) / 2, 205), person, font=person_font, fill=SOFT)
    draw.line([(W / 2 - 60, 275), (W / 2 + 60, 275)], fill=GOLD, width=4)

    if brand.get("handle"):
        handle_font = font("medium", 36)
        handle = f"@{brand['handle']}"
        width = draw.textlength(handle, font=handle_font)
        draw.text(((W - width) / 2, CONTENT_BOTTOM + 40), handle, font=handle_font, fill=SOFT)
    return img


def draw_mark(draw, x, y, size, style):
    if style == "right":
        draw.line([(x, y + size * 0.55), (x + size * 0.38, y + size * 0.9), (x + size, y + size * 0.1)],
                  fill=GREEN, width=9, joint="curve")
    elif style == "wrong":
        draw.line([(x, y), (x + size, y + size)], fill=RED, width=9)
        draw.line([(x + size, y), (x, y + size)], fill=RED, width=9)


def layout_scene(draw, scene: dict, is_hook: bool, scale: float):
    """Return a list of (kind, text, font, color, style, height) blocks."""
    max_w = W - 2 * SIDE - 60
    blocks = []
    title = clean_text(scene.get("title", ""))
    if title:
        tf = font("bold", int((100 if is_hook else 70) * scale))
        for line in wrap(draw, title, tf, max_w):
            blocks.append(("title", line, tf, GOLD if is_hook else WHITE, "normal", int(text_height(tf) * 1.08)))
        blocks.append(("gap", "", None, None, None, int(40 * scale)))
    for item in scene.get("lines", []):
        text = clean_text(item.get("text", ""))
        if not text:
            continue
        style = item.get("style", "normal")
        lf = font("bold" if style == "highlight" else "medium", int(52 * scale))
        color = {"wrong": RED, "right": GREEN, "highlight": GOLD}.get(style, WHITE)
        indent = 70 if style in ("wrong", "right") else 0
        wrapped = wrap(draw, text, lf, max_w - indent)
        for n, line in enumerate(wrapped):
            mark = style if n == 0 else "normal"
            blocks.append(("line", line, lf, color, mark, int(text_height(lf) * 1.12)))
        blocks.append(("gap", "", None, None, None, int(26 * scale)))
    return blocks


def render_scene_frames(scene: dict, brand: dict, index: int, count: int) -> list[Image.Image]:
    """One frame per reveal step: title first, then lines appear one by one."""
    is_hook = index == 0
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    scale = 1.0
    while True:
        blocks = layout_scene(probe, scene, is_hook, scale)
        total = sum(b[5] for b in blocks)
        if total <= CONTENT_BOTTOM - CONTENT_TOP - 80 or scale < 0.55:
            break
        scale -= 0.07

    # Reveal steps: the title is step 0, then each source line (blocks between gaps).
    steps, current, prev_gap = [], 0, True
    for b in blocks:
        if b[0] == "line" and prev_gap:
            current += 1
        steps.append(current)
        prev_gap = b[0] == "gap"
    n_steps = max(steps) if steps else 0
    if is_hook:
        n_steps = 0  # the hook appears at once

    has_marks = any(b[4] in ("wrong", "right") for b in blocks if b[0] == "line")
    top = CONTENT_TOP + (CONTENT_BOTTOM - CONTENT_TOP - sum(b[5] for b in blocks)) // 2
    frames = []
    for step in range(n_steps + 1):
        img = base_frame(brand, index, count)
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle(
            [SIDE - 20, CONTENT_TOP - 20, W - SIDE + 20, CONTENT_BOTTOM + 10], radius=40, fill=CARD
        )
        img = Image.alpha_composite(img, card)
        draw = ImageDraw.Draw(img)
        y = top
        for b, s in zip(blocks, steps):
            kind, text, fnt, color, style, height = b
            if kind != "gap" and (is_hook or s <= step):
                width = draw.textlength(text, font=fnt)
                if kind == "title" or is_hook:
                    x = (W - width) / 2
                else:
                    x = SIDE + 30
                    if style in ("wrong", "right"):
                        draw_mark(draw, x, y + height * 0.18, height * 0.5, style)
                    if has_marks:
                        x += 70
                draw.text((x, y), text, font=fnt, fill=color)
            y += height
        frames.append(img.convert("RGB"))
    return frames


def overlay_png(brand: dict, hook_text: str) -> Image.Image:
    """Transparent brand overlay for the Veo hook clip."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 300], fill=(8, 22, 48, 150))
    brand_font = font("bold", 50)
    spaced = " ".join(brand["brand"].upper())
    width = draw.textlength(spaced, font=brand_font)
    draw.text(((W - width) / 2, 120), spaced, font=brand_font, fill=GOLD)
    person_font = font("medium", 36)
    person = f"with {brand['person']}"
    width = draw.textlength(person, font=person_font)
    draw.text(((W - width) / 2, 195), person, font=person_font, fill=WHITE)

    hook = clean_text(hook_text)
    if hook:
        hf = font("bold", 84)
        lines = wrap(draw, hook, hf, W - 2 * SIDE - 40)
        lh = int(text_height(hf) * 1.1)
        box_h = lh * len(lines) + 70
        y0 = (H - box_h) // 2
        draw.rounded_rectangle([SIDE - 20, y0, W - SIDE + 20, y0 + box_h], radius=36, fill=(8, 22, 48, 190))
        y = y0 + 35
        for line in lines:
            width = draw.textlength(line, font=hf)
            draw.text(((W - width) / 2, y), line, font=hf, fill=WHITE)
            y += lh
    return img


# ---------------------------------------------------------
# AUDIO
# ---------------------------------------------------------

async def synthesize_voice(client: genai.Client, text: str, model: str, voice: str, style: str):
    """Gemini TTS -> WAV bytes, or None if TTS is unavailable."""
    prompt = f"{style}\n\n{text}" if style else text
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    part = response.candidates[0].content.parts[0]
    pcm = part.inline_data.data
    mime = part.inline_data.mime_type or ""
    match = re.search(r"rate=(\d+)", mime)
    rate = int(match.group(1)) if match else 24000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue(), len(pcm) / (2 * rate)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def scene_durations(scenes: list[dict], audio_seconds: float | None) -> list[float]:
    words = [max(word_count(s.get("voice", "")), 3) for s in scenes]
    if audio_seconds:
        total = sum(words)
        durations = [audio_seconds * w / total for w in words]
    else:
        durations = [w / 2.6 for w in words]
    durations = [max(d, 1.8) for d in durations]
    durations[-1] += 0.8  # let the last slide breathe after the voice ends
    return durations


# ---------------------------------------------------------
# FFMPEG
# ---------------------------------------------------------

def ffmpeg_exe() -> str:
    path = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    if path:
        return path
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


async def run_ffmpeg(args: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='ignore')[-800:]}")
    return err.decode(errors="ignore")


async def has_audio(path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe(), "-hide_banner", "-i", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return "Audio:" in err.decode(errors="ignore")


ENCODE_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-crf", "21",
    "-pix_fmt", "yuv420p", "-r", str(FPS),
    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
    "-threads", "2", "-movflags", "+faststart",
]


def write_slides(scenes, brand, durations, workdir) -> tuple[str, float]:
    """Render frames + an ffmpeg concat list. Returns (list_path, seconds)."""
    entries = []
    for i, scene in enumerate(scenes):
        frames = render_scene_frames(scene, brand, i, len(scenes))
        # The first reveal steps go faster; the full slide stays longest.
        if len(frames) == 1:
            parts = [durations[i]]
        else:
            first = durations[i] * 0.55 / (len(frames) - 1)
            parts = [first] * (len(frames) - 1) + [durations[i] * 0.45]
        for j, (frame, seconds) in enumerate(zip(frames, parts)):
            path = os.path.join(workdir, f"s{i:02d}_{j:02d}.png")
            frame.save(path, optimize=False, compress_level=1)
            entries.append((path, seconds))
    list_path = os.path.join(workdir, "slides.txt")
    with open(list_path, "w") as f:
        for path, seconds in entries:
            f.write(f"file '{path}'\nduration {seconds:.3f}\n")
        f.write(f"file '{entries[-1][0]}'\n")
    return list_path, sum(s for _, s in entries)


async def render_slides_video(scenes, brand, voice_wav, voice_seconds, workdir, music_file=None) -> str:
    durations = scene_durations(scenes, voice_seconds)
    list_path, total = await asyncio.to_thread(write_slides, scenes, brand, durations, workdir)
    total = min(total, MAX_SECONDS)
    out = os.path.join(workdir, "slides.mp4")

    args = ["-f", "concat", "-safe", "0", "-i", list_path]
    if voice_wav:
        voice_path = os.path.join(workdir, "voice.wav")
        with open(voice_path, "wb") as f:
            f.write(voice_wav)
        args += ["-i", voice_path]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    if music_file and os.path.exists(music_file):
        args += ["-stream_loop", "-1", "-i", music_file]
        voice_level = "1.0" if voice_wav else "0"
        args += [
            "-filter_complex",
            f"[1:a]volume={voice_level},apad[v];[2:a]volume=0.12[m];[v][m]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]",
        ]
    else:
        args += ["-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]"]

    args += ["-vf", f"fps={FPS},format=yuv420p", "-t", f"{total:.2f}", *ENCODE_ARGS, out]
    await run_ffmpeg(args)
    return out


async def veo_clip(client: genai.Client, prompt: str, model: str, workdir: str) -> str:
    operation = await client.aio.models.generate_videos(
        model=model,
        prompt=prompt,
        config=genai_types.GenerateVideosConfig(aspect_ratio="9:16", number_of_videos=1),
    )
    waited = 0
    while not operation.done:
        if waited > 900:
            raise RuntimeError("Veo timed out")
        await asyncio.sleep(15)
        waited += 15
        operation = await client.aio.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"Veo error: {operation.error}")
    videos = (operation.response.generated_videos if operation.response else None) or []
    if not videos:
        raise RuntimeError("Veo returned no video (possibly blocked by safety filters)")
    video = videos[0].video
    data = video.video_bytes or await asyncio.to_thread(client.files.download, file=video)
    path = os.path.join(workdir, "veo.mp4")
    with open(path, "wb") as f:
        f.write(data)
    return path


async def brand_veo_clip(veo_path: str, brand: dict, hook_text: str, workdir: str) -> str:
    png = os.path.join(workdir, "overlay.png")
    overlay_png(brand, hook_text).save(png)
    out = os.path.join(workdir, "veo_branded.mp4")
    audio = await has_audio(veo_path)
    args = ["-i", veo_path, "-i", png]
    if not audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    args += [
        "-filter_complex",
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
        f"[b][1:v]overlay=0:0,fps={FPS},format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a" if audio else "2:a", "-t", "8", "-shortest",
        *ENCODE_ARGS, out,
    ]
    await run_ffmpeg(args)
    return out


async def concat_videos(first: str, second: str, workdir: str) -> str:
    out = os.path.join(workdir, "final.mp4")
    await run_ffmpeg([
        "-i", first, "-i", second,
        "-filter_complex",
        "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", *ENCODE_ARGS, out,
    ])
    return out


# ---------------------------------------------------------
# PUBLIC ENTRY POINT
# ---------------------------------------------------------

async def render_reel(
    client: genai.Client,
    script: dict,
    brand: dict,
    *,
    engine: str = "slides",
    tts_model: str = "",
    tts_voice: str = "Charon",
    tts_style: str = "",
    veo_model: str = "",
    music_file: str | None = None,
) -> tuple[bytes, dict]:
    """Render the script; returns (mp4 bytes, info dict)."""
    scenes = script["scenes"]
    info = {"engine": "slides", "voice": False}
    workdir = tempfile.mkdtemp(prefix="reel_")
    try:
        voice_wav, voice_seconds = None, None
        voice_text = "\n\n".join(s.get("voice", "") for s in scenes if s.get("voice"))
        if tts_model and voice_text:
            try:
                voice_wav, voice_seconds = await synthesize_voice(
                    client, voice_text, tts_model, tts_voice, tts_style
                )
                info["voice"] = True
            except Exception as e:
                log.warning("TTS failed, rendering without voice-over: %s", e)
                info["voice_error"] = str(e)[:200]

        slides = await render_slides_video(
            scenes, brand, voice_wav, voice_seconds, workdir, music_file
        )
        final = slides
        if engine == "veo" and veo_model and script.get("veo_prompt"):
            try:
                clip = await veo_clip(client, script["veo_prompt"], veo_model, workdir)
                branded = await brand_veo_clip(clip, brand, script.get("hook_text", ""), workdir)
                final = await concat_videos(branded, slides, workdir)
                info["engine"] = "veo"
            except Exception as e:
                log.warning("Veo failed, using slides only: %s", e)
                info["veo_error"] = str(e)[:200]

        with open(final, "rb") as f:
            data = f.read()
        info["seconds"] = round(sum(scene_durations(scenes, voice_seconds)), 1)
        info["size_mb"] = round(len(data) / 1e6, 1)
        return data, info
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

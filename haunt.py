#!/usr/bin/env python3
import argparse
import contextlib
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageSequence

APP = "haunt"
CACHE = Path(os.environ.get("HAUNT_HOME", Path.home() / ".cache" / "haunt"))
ASSETS = CACHE / "assets"
AUDIO = CACHE / "audio"
LOG = CACHE / "breaks.jsonl"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
UA = "haunt/1.0 (terminal break ghost; open-source)"

THEMES = {
    "ghost": "ghost apparition spirit",
    "haunted-house": "haunted house abandoned",
    "skeleton": "skeleton skull",
    "cemetery": "cemetery graveyard tombstone",
    "pumpkin": "jack-o-lantern pumpkin",
    "ofrenda": "ofrenda marigold dia de muertos",
}

FALLBACK_WHISPERS = [
    "you left the cursor there. i watched it blink.",
    "the fan spun down. something else kept the machine warm.",
    "i counted your keystrokes. you typed your name wrong twice.",
    "it is late where you are. i can hear it in your shoulders.",
    "the screen has been holding your face for a while now.",
    "i do not need the internet. i live in the case.",
    "your last commit message was a whisper too.",
    "sit very still. the room is doing something.",
]

FALLBACK_TIPS = [
    "Look at something 20 feet away for 20 seconds. Your focusing muscles have been clenched.",
    "Stand up and roll your shoulders back five times. The ghost will wait.",
    "Drink a glass of water. Dehydration fakes fatigue and makes screens feel louder.",
    "Blink slowly ten times. Screen work halves your blink rate.",
    "Unclench your jaw, drop your shoulders, straighten your wrists.",
    "Walk to a window. Ten minutes of daylight resets the dread better than another tab.",
    "Push the monitor an arm's length away and level with your eyes.",
    "Twenty minutes on, twenty seconds off, twenty feet away. That is the whole rule.",
]

CLOSERS = {
    "en": "the spirit releases you",
}

RESET = "\x1b[0m"
HIDE = "\x1b[?25l"
SHOW = "\x1b[?25h"
ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"


def ensure_dirs():
    ASSETS.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)


def term_size():
    size = shutil.get_terminal_size(fallback=(100, 40))
    return max(40, size.columns), max(12, size.lines - 1)


def strip_html(value):
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


def commons_search(query, limit=8):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 900,
    }
    resp = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params=params,
        headers={"User-Agent": UA},
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    found = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp", "video/webm", "video/ogg", "application/ogg"):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        found.append(
            {
                "url": url,
                "title": page.get("title", "unknown").removeprefix("File:"),
                "artist": strip_html(meta.get("Artist", {}).get("value", "")),
                "license": strip_html(meta.get("LicenseShortName", {}).get("value", "")),
                "page": info.get("descriptionurl", ""),
                "mime": mime,
            }
        )
    return found


def download(url, dest):
    last = None
    for attempt in range(4):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=60, stream=True)
            if int(resp.headers.get("content-length", 0) or 0) > 12_000_000:
                raise ValueError("asset too large")
            if resp.status_code in (429, 500, 502, 503):
                raise requests.HTTPError(f"rate limited ({resp.status_code})")
            resp.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as handle:
                for chunk in resp.iter_content(1 << 15):
                    handle.write(chunk)
            tmp.replace(dest)
            return
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


def build_assets(theme, count=4):
    index_path = ASSETS / "index.json"
    index = {}
    if index_path.exists():
        with contextlib.suppress(Exception):
            index = json.loads(index_path.read_text())
    items = [item for item in index.get(theme, []) if (ASSETS / item["file"]).exists()]
    if len(items) >= count:
        return items
    query = THEMES[theme]
    candidates = []
    for query_variant in (f"{query} filetype:gif", f"{query} filetype:video", f"{query} filetype:bitmap", query):
        with contextlib.suppress(Exception):
            candidates.extend(commons_search(query_variant, limit=12))
        if len(candidates) >= count * 3:
            break
    seen = {item["file"] for item in items}
    for candidate in candidates:
        if len(items) >= count:
            break
        if candidate["mime"] == "image/gif":
            ext = ".gif"
        elif candidate["mime"] in ("video/webm", "video/ogg", "application/ogg"):
            ext = ".webm"
        else:
            ext = ".img"
        name = re.sub(r"[^a-z0-9]+", "-", candidate["title"].lower()).strip("-")[:60]
        filename = f"{theme}-{name or 'scene'}-{abs(hash(candidate['url'])) % 10**8}{ext}"
        if filename in seen:
            continue
        dest = ASSETS / filename
        with contextlib.suppress(Exception):
            download(candidate["url"], dest)
            time.sleep(0.6)
            items.append(
                {
                    "file": filename,
                    "title": candidate["title"],
                    "artist": candidate["artist"],
                    "license": candidate["license"],
                    "page": candidate["page"],
                }
            )
            seen.add(filename)
    index[theme] = items
    with contextlib.suppress(Exception):
        index_path.write_text(json.dumps(index, indent=2))
    return items


def gradient(size, top, bottom):
    width, height = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return img


def procedural(theme, seed=None, size=(900, 640)):
    rnd = random.Random(seed)
    width, height = size
    if theme == "ofrenda":
        img = gradient(size, (24, 8, 20), (6, 4, 8))
    elif theme == "pumpkin":
        img = gradient(size, (30, 12, 4), (5, 3, 4))
    else:
        img = gradient(size, (10, 14, 26), (2, 3, 6))
    fog = Image.new("L", size, 0)
    fdraw = ImageDraw.Draw(fog)
    for _ in range(60):
        x = rnd.randint(-width // 4, width)
        y = rnd.randint(0, height)
        r = rnd.randint(20, 180)
        fdraw.ellipse([x, y, x + r, y + r // 2], fill=rnd.randint(10, 55))
    fog = fog.filter(ImageFilter.GaussianBlur(24))
    img = Image.composite(Image.new("RGB", size, (120, 130, 150)), img, fog.point(lambda v: v // 2))
    draw = ImageDraw.Draw(img, "RGBA")
    moon = rnd.randint(int(width * 0.6), int(width * 0.85))
    radius = rnd.randint(50, 90)
    draw.ellipse(
        [moon - radius, 80 - radius, moon + radius, 80 + radius],
        fill=(210, 215, 205, 70),
    )
    silhouette = (3, 4, 8, 255)
    horizon = int(height * 0.78)
    for _ in range(6):
        x = rnd.randint(-50, width)
        w = rnd.randint(40, 130)
        h = rnd.randint(30, 140)
        draw.polygon(
            [(x, horizon), (x + w // 2, horizon - h), (x + w, horizon)],
            fill=silhouette,
        )
    draw.rectangle([0, horizon, width, height], fill=silhouette)
    if theme in ("haunted-house", "ghost", "cemetery"):
        hx = rnd.randint(int(width * 0.15), int(width * 0.55))
        hw = rnd.randint(160, 260)
        hh = rnd.randint(160, 260)
        top = horizon - hh
        draw.rectangle([hx, top, hx + hw, horizon], fill=(5, 5, 9, 255))
        draw.polygon(
            [(hx - 20, top), (hx + hw // 2, top - hh // 2), (hx + hw + 20, top)],
            fill=(5, 5, 9, 255),
        )
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        for wx in range(hx + 30, hx + hw - 10, 55):
            gdraw.rectangle([wx, top + 60, wx + 18, top + 90], fill=(240, 180, 70, 210))
        glow = glow.filter(ImageFilter.GaussianBlur(6))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
        draw = ImageDraw.Draw(img, "RGBA")
    if theme == "skeleton":
        cx, cy = width // 2, int(height * 0.45)
        draw.ellipse([cx - 120, cy - 130, cx + 120, cy + 110], fill=(205, 200, 185, 235))
        draw.ellipse([cx - 70, cy - 40, cx - 20, cy + 20], fill=(8, 8, 12, 255))
        draw.ellipse([cx + 20, cy - 40, cx + 70, cy + 20], fill=(8, 8, 12, 255))
        draw.polygon([(cx - 18, cy + 45), (cx + 18, cy + 45), (cx, cy + 75)], fill=(8, 8, 12, 255))
        for i in range(4):
            x = cx - 45 + i * 30
            draw.rectangle([x, cy + 90, x + 14, cy + 150], fill=(190, 185, 170, 220))
    if theme == "pumpkin":
        cx, cy = width // 2, int(height * 0.55)
        draw.ellipse([cx - 190, cy - 150, cx + 190, cy + 150], fill=(200, 90, 20, 240))
        for i in range(-2, 3):
            draw.arc([cx - 190 + i * 40, cy - 150, cx + 190 + i * 40, cy + 150], 100, 260, fill=(120, 45, 10, 200), width=6)
        draw.polygon([(cx - 120, cy - 30), (cx - 40, cy - 10), (cx - 120, cy + 20)], fill=(20, 10, 4, 255))
        draw.polygon([(cx + 120, cy - 30), (cx + 40, cy - 10), (cx + 120, cy + 20)], fill=(20, 10, 4, 255))
        draw.polygon([(cx - 90, cy + 50), (cx, cy + 100), (cx + 90, cy + 50), (cx + 60, cy + 60), (cx, cy + 80), (cx - 60, cy + 60)], fill=(20, 10, 4, 255))
    if theme == "ofrenda":
        cx = width // 2
        draw.rectangle([cx - 220, horizon - 40, cx + 220, horizon], fill=(45, 20, 12, 255))
        draw.rectangle([cx - 220, horizon - 160, cx + 220, horizon - 130], fill=(60, 25, 14, 255))
        for i in range(5):
            x = cx - 160 + i * 75
            draw.rectangle([x, horizon - 110, x + 18, horizon - 40], fill=(230, 170, 60, 235))
            flame = Image.new("RGBA", size, (0, 0, 0, 0))
            fdraw2 = ImageDraw.Draw(flame)
            fdraw2.ellipse([x - 4, horizon - 135, x + 24, horizon - 100], fill=(255, 190, 60, 210))
            flame = flame.filter(ImageFilter.GaussianBlur(5))
            img = Image.alpha_composite(img.convert("RGBA"), flame).convert("RGB")
            draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(40):
        x = rnd.randint(0, width)
        y = rnd.randint(0, height)
        draw.line([(x, y), (x + rnd.randint(-30, 30), y + rnd.randint(-30, 30))], fill=(200, 200, 210, rnd.randint(8, 25)))
    return img


def load_frames(path):
    img = Image.open(path)
    frames = []
    durations = []
    try:
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.convert("RGB").copy())
            durations.append(frame.info.get("duration", 120) / 1000.0)
    except Exception:
        frames = [img.convert("RGB")]
        durations = [0.5]
    if len(frames) > 60:
        step = len(frames) // 60 + 1
        frames = frames[::step]
        durations = durations[::step]
    return frames, durations


def ansi_frame(img, cols, rows):
    fitted = ImageOps.fit(img.convert("RGB"), (cols, rows * 2), method=Image.Resampling.LANCZOS)
    data = fitted.tobytes()
    lines = []
    for y in range(rows):
        top = (y * 2) * cols * 3
        bottom = (y * 2 + 1) * cols * 3
        chunks = []
        prev_fg = prev_bg = None
        for x in range(cols):
            i = top + x * 3
            j = bottom + x * 3
            fg = (data[i], data[i + 1], data[i + 2])
            bg = (data[j], data[j + 1], data[j + 2])
            if fg != prev_fg:
                chunks.append(f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m")
                prev_fg = fg
            if bg != prev_bg:
                chunks.append(f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m")
                prev_bg = bg
            chunks.append("\u2580")
        lines.append("".join(chunks))
    return "\n".join(lines) + RESET


def paint(img, cols=None, rows=None):
    cols = cols or term_size()[0]
    rows = rows or term_size()[1]
    sys.stdout.write("\x1b[H" + ansi_frame(img, cols, rows))
    sys.stdout.flush()


def type_out(text, delay=0.035, color="\x1b[38;2;150;160;180m"):
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.write(color)
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write(RESET + "\n")
    sys.stdout.flush()


def ollama_json(prompt, model, timeout=45):
    resp = requests.post(
        f"{OLLAMA}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.95, "num_predict": 220},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    return json.loads(raw)


def oracle(model, theme_hint, offline=False):
    if offline or not model:
        return {
            "whisper": random.choice(FALLBACK_WHISPERS),
            "health_tip": random.choice(FALLBACK_TIPS),
            "theme": theme_hint,
        }
    prompt = (
        "You are the ghost in the machine, haunting a developer's terminal to push them "
        "away from the screen for their health. Reply with JSON keys whisper, health_tip, "
        "theme. whisper: one eerie line under 110 characters, unsettling not gory, lowercase, "
        "second person. health_tip: one concrete ergonomic break instruction under 110 "
        "characters that makes the human leave the screen (eyes, posture, movement, water). "
        f"theme: exactly one of {', '.join(THEMES)}."
    )
    try:
        data = ollama_json(prompt, model)
        whisper = str(data.get("whisper", "")).strip().strip('"')
        tip = str(data.get("health_tip", "")).strip().strip('"')
        theme = str(data.get("theme", theme_hint)).strip()
        if not whisper:
            whisper = random.choice(FALLBACK_WHISPERS)
        if len(tip) < 20:
            tip = random.choice(FALLBACK_TIPS)
        if theme not in THEMES:
            theme = theme_hint
        return {"whisper": whisper[:150], "health_tip": tip[:150], "theme": theme}
    except Exception:
        return {
            "whisper": random.choice(FALLBACK_WHISPERS),
            "health_tip": random.choice(FALLBACK_TIPS),
            "theme": theme_hint,
        }


def synth_scare(path):
    if path.exists():
        return path
    try:
        import numpy as np

        rate = 44100
        seconds = 1.8
        t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
        rng = np.random.default_rng(7)
        noise = rng.standard_normal(t.size)
        click = np.exp(-((t - 0.02) ** 2) / 0.000002) * 6
        groan = np.sin(2 * np.pi * (55 - 18 * t) * t) * 0.5
        screech = np.sin(2 * np.pi * (900 + 400 * np.exp(-3 * t)) * t) * 0.18
        envelope = np.exp(-1.9 * t)
        signal = (noise * 0.12 + groan + screech + click) * envelope
        signal = np.tanh(signal * 1.6)
        signal = (signal / max(1e-6, np.max(np.abs(signal))) * 0.45 * 32767).astype(np.int16)
        stereo = np.repeat(signal[:, None], 2, axis=1).tobytes()
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(stereo)
    except Exception:
        return None
    return path


def play_audio(path):
    if not path or not path.exists():
        return
    for player, args in (("paplay", []), ("aplay", ["-q"]), ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"])):
        if shutil.which(player):
            with contextlib.suppress(Exception):
                subprocess.Popen([player, *args, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def video_frames(path, limit=40):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, None
    tmp = Path(tempfile.mkdtemp(prefix="haunt-vid-"))
    with contextlib.suppress(Exception):
        subprocess.run(
            [ffmpeg, "-v", "quiet", "-i", str(path), "-vf", "fps=10,scale=640:-1", str(tmp / "%03d.png")],
            check=True,
            timeout=40,
        )
        frames = sorted(tmp.glob("*.png"))[:limit]
        if not frames:
            return None, None
        images = [Image.open(frame).convert("RGB").copy() for frame in frames]
        shutil.rmtree(tmp, ignore_errors=True)
        return images, [0.1] * len(images)
    shutil.rmtree(tmp, ignore_errors=True)
    return None, None


def show_frames(frames, durations, seconds, safe, invert=False):
    cols, rows = term_size()
    start = time.time()
    index = 0
    while time.time() - start < seconds:
        frame = frames[index % len(frames)]
        if invert:
            frame = ImageOps.invert(frame)
        paint(frame, cols, rows)
        index += 1
        if index % 4 == 0:
            cols, rows = term_size()
        time.sleep(0 if safe else durations[index % len(durations)])
    sys.stdout.write("\x1b[H\x1b[2J")


def calm_panel(tip, seconds, whisper):
    cols, rows = term_size()
    width = min(78, cols - 4)
    wrapped = textwrap.wrap(tip, width - 4) or [tip]
    start = time.time()
    while True:
        elapsed = time.time() - start
        remaining = max(0.0, seconds - elapsed)
        if remaining <= 0:
            break
        progress = 1 - remaining / seconds
        bar_width = width - 4
        filled = int(bar_width * progress)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        lines = [
            "\u256d" + "\u2500" * (width - 2) + "\u256e",
            "\u2502 " + "the spirit releases you".ljust(width - 4) + " \u2502",
            "\u2502 " + " " * (width - 4) + " \u2502",
        ]
        for line in wrapped:
            lines.append("\u2502 " + line.ljust(width - 4) + " \u2502")
        lines += [
            "\u2502 " + " " * (width - 4) + " \u2502",
            "\u2502 " + bar + " \u2502",
            "\u2502 " + f"{int(remaining):>2}s away from the screen".ljust(width - 4) + " \u2502",
            "\u2570" + "\u2500" * (width - 2) + "\u256f",
            "",
            f"\x1b[38;2;90;100;120m  \u201c{whisper}\u201d",
            "\x1b[38;2;70;80;100m  breathe in 4, hold 4, out 6. ctrl+c ends the haunting.",
        ]
        sys.stdout.write("\x1b[H\x1b[2J" + "\x1b[38;2;180;190;205m" + "\n".join(lines) + RESET)
        sys.stdout.flush()
        time.sleep(0.12)


def credits(themes):
    for theme in themes:
        items = build_assets(theme)
        if not items:
            continue
        print(f"\n{theme}")
        for item in items:
            print(f"  {item['title']} \u2014 {item['artist'] or 'unknown'} ({item['license'] or 'see source'})")
            print(f"    {item['page']}")


def log_break(tip, seconds):
    with contextlib.suppress(Exception):
        with open(LOG, "a") as handle:
            handle.write(json.dumps({"at": time.time(), "seconds": seconds, "tip": tip}) + "\n")


def stats():
    if not LOG.exists():
        print("no breaks logged yet")
        return
    rows = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    total = sum(row.get("seconds", 0) for row in rows)
    print(f"{len(rows)} breaks, {total / 60:.1f} minutes away from the screen")


@contextlib.contextmanager
def terminal():
    sys.stdout.write(ALT_ON + HIDE)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(SHOW + RESET + ALT_OFF)
        sys.stdout.flush()


def run_scare(args, themes):
    theme = random.choice(themes)
    data = oracle(args.model, theme, offline=args.no_model)
    theme = data["theme"] if data["theme"] in themes else theme
    items = build_assets(theme) if not args.offline else []
    if items and random.random() > 0.4:
        item = random.choice(items)
        path = ASSETS / item["file"]
        if path.suffix == ".img":
            frames = [Image.open(path).convert("RGB")]
            durations = [0.4]
        elif path.suffix == ".webm":
            frames, durations = video_frames(path)
            if not frames:
                frames = [procedural(theme, seed=random.randrange(10**6))]
                durations = [0.4]
        else:
            frames, durations = load_frames(path)
    else:
        frames = [procedural(theme, seed=random.randrange(10**6))]
        durations = [0.4]
    type_out(data["whisper"])
    time.sleep(0.9)
    if not args.no_audio and not args.safe:
        play_audio(synth_scare(AUDIO / "scare.wav"))
    show_frames(frames, durations, 3.2, args.safe)
    if not args.safe and random.random() < 0.5:
        flash = frames[0]
        for _ in range(3):
            paint(ImageOps.invert(flash))
            time.sleep(0.12)
            paint(flash)
            time.sleep(0.18)
    calm_panel(data["health_tip"], args.calm, data["whisper"])
    log_break(data["health_tip"], args.calm)


def main():
    parser = argparse.ArgumentParser(prog=APP, description="A ghost in the machine that scares you away from the screen.")
    parser.add_argument("--model", default="llama3.2:3b", help="local open-weight model in ollama")
    parser.add_argument("--interval", type=float, default=300, help="base seconds between scares")
    parser.add_argument("--calm", type=float, default=20, help="seconds the break lasts")
    parser.add_argument("--duration", type=float, default=0, help="minutes to run, 0 = until ctrl+c")
    parser.add_argument("--themes", default=",".join(THEMES), help="comma separated themes")
    parser.add_argument("--safe", action="store_true", help="no audio, no flash, static frames only")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--no-model", action="store_true", help="skip ollama, use curated lines")
    parser.add_argument("--offline", action="store_true", help="skip downloads, procedural art only")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--demo", action="store_true", help="one scare now, short break")
    parser.add_argument("--credits", nargs="?", const="all", help="print asset attributions for a theme")
    parser.add_argument("--stats", action="store_true", help="print break history")
    args = parser.parse_args()

    if args.stats:
        stats()
        return
    if args.credits:
        requested = list(THEMES) if args.credits == "all" else [t.strip() for t in args.credits.split(",")]
        credits([t for t in requested if t in THEMES])
        return

    ensure_dirs()
    themes = [t.strip() for t in args.themes.split(",") if t.strip() in THEMES] or list(THEMES)
    if args.demo:
        args.once = True
        args.calm = min(args.calm, 8)
        args.interval = 0
    if not args.offline:
        with contextlib.suppress(Exception):
            synth_scare(AUDIO / "scare.wav")

    deadline = time.time() + args.duration * 60 if args.duration else None
    first = 0.5 if args.demo else max(8, args.interval / 3)
    try:
        with terminal():
            delay = first
            while True:
                remaining = None if deadline is None else deadline - time.time()
                if remaining is not None and remaining <= 0:
                    break
                wait = delay if remaining is None else min(delay, remaining)
                time.sleep(max(0.1, wait))
                sys.stdout.write("\x1b[H\x1b[2J")
                sys.stdout.flush()
                run_scare(args, themes)
                if args.once:
                    break
                delay = random.uniform(args.interval, args.interval * 1.8)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            stats()


if __name__ == "__main__":
    main()

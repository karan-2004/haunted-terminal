# haunt

A ghost in the machine that scares you **away from the screen**.

`haunt` lives in your terminal. Every few minutes it wakes up, whispers something
unsettling, and floods your terminal with a horror still, GIF, or video pulled
from the public domain and Creative Commons archives. Then it does the part that
actually matters: it holds the screen hostage for a short, calm break and tells
you to look away, stand up, drink water, and move.

You cannot keep working through a jump scare. That is the point.

Built for the **Hacktoberfest Open-Source AI Challenge: Week 4 — Ghost in the Machine**,
using a local open-weight model (Ollama + `llama3.2:3b`).

## How it works

1. **Oracle** — a local open-weight model writes the whisper and the health tip
   for each haunting. No API keys, no cloud, nothing leaves the machine.
2. **Assets** — stills, animated GIFs, and videos are fetched from Wikimedia
   Commons (public domain and CC licensed) and cached locally under
   `~/.cache/haunt/assets`. Attribution is kept for every file.
3. **Fallback art** — if the network is down or you pass `--offline`, the ghost
   paints its own scene procedurally with Pillow, so the haunting works with the
   internet off.
4. **Render** — frames are drawn to the terminal with 24-bit colour half-blocks.
   No terminal graphics protocol required.
5. **The break** — a calm panel shows the model's health tip, a countdown, and a
   breathing prompt. Every break is logged and summarised when you exit.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

ollama pull llama3.2:3b
```

Optional: `paplay` or `aplay` for the sound, `ffmpeg` to play videos from
Commons (without it, videos fall back to procedural art).

## Run

```bash
python3 haunt.py
```

```bash
python3 haunt.py --demo            # one haunting right now, short break
python3 haunt.py --safe            # no sound, no flash, static frames
python3 haunt.py --interval 600    # haunt roughly every 10-18 minutes
python3 haunt.py --calm 30         # 30 second break
python3 haunt.py --duration 90     # stop after 90 minutes
python3 haunt.py --themes ghost,ofrenda,cemetery
python3 haunt.py --offline --no-model   # fully offline, curated lines only
python3 haunt.py --credits ghost   # print attribution for a theme
python3 haunt.py --stats           # how long you have stayed away
```

Press `Ctrl+C` at any time; the terminal is restored and your break stats print.

## A note on safety

Scares are meant to interrupt, not harm. `--safe` disables audio and the single
inverted-frame flash. The flash is deliberately single and slow to avoid
strobing. If you are photosensitive or share the machine, run with `--safe`.

The health advice is ordinary workplace ergonomics: the 20-20-20 rule, standing
and moving, hydration, blinking, posture, and wrist position. It is not medical
advice.

## Why open matters here

- The model runs locally on `llama3.2:3b`, so the ghost works offline and your
  terminal history never goes to a provider.
- The assets are public domain and CC licensed from Wikimedia Commons, with
  attribution kept and printable with `--credits`.
- When the network is gone, the fallback art is generated locally, so the habit
  the tool is trying to build does not depend on a service that might disappear.

## Licence

MIT. Assets fetched at runtime keep their own licenses; see `--credits`.

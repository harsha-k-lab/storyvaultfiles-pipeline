# StoryVaultFiles pipeline

A free pipeline for a faceless unsolved-mysteries channel. Each day it suggests 3 cases
on Telegram, makes a narrated story video plus a Short for the one you pick, and posts
to YouTube and Instagram once you approve.

**→ Start with [SETUP.md](SETUP.md).**

## How it works

```
12:00 daily ─► GitHub Actions ─► Wikipedia (cases) + Gemini (pitches) ─► Telegram: 3 ideas
You tap ─► Telegram ─► Cloudflare Worker ─► GitHub Actions:
     Gemini script ─► edge-tts voice ─► Pixabay/Openverse/Wikimedia visuals ─► FFmpeg edit
     ─► preview on Telegram ─► you: notes (re-render) or Publish
Publish ─► YouTube (video + Short) ─► Instagram Reel ─► links on Telegram
```

| Folder | What's inside |
|--------|---------------|
| `config.yaml` | All settings (voice, length, schedule, privacy) |
| `pipeline/` | Python code: research, writer, tts, stock, render, graphics, publish, run |
| `worker/` | Cloudflare Worker that forwards Telegram taps to GitHub |
| `.github/workflows/` | Daily topics, Telegram actions, Instagram token refresh, test run |
| `state/` | Saved progress (case numbers, history, scripts), committed automatically |
| `assets/music/` | Optional: your own royalty-free tracks |

Local offline test (needs Python 3.11+ and ffmpeg): `SVF_FAKE=1 python tests/smoke_test.py`

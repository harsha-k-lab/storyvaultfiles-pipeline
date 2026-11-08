"""Free AI voiceover via edge-tts, with word timings for burned-in captions."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from .core import CFG, FAKE, log, media_duration, run

V = CFG["voice"]


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("…", "...")


async def _edge(text: str, out_mp3: Path) -> list[dict]:
    import edge_tts

    comm = edge_tts.Communicate(text, V["name"], rate=V["rate"], pitch=V["pitch"],
                                boundary="WordBoundary")
    words = []
    with open(out_mp3, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"word": chunk["text"],
                              "start": chunk["offset"] / 1e7,
                              "end": (chunk["offset"] + chunk["duration"]) / 1e7})
    return words


def _even_timings(text: str, duration: float) -> list[dict]:
    """Fallback captions: spread words across the audio by length."""
    tokens = text.split()
    weights = [len(t) + 2 for t in tokens]
    total = sum(weights) or 1
    t, out = 0.0, []
    for tok, w in zip(tokens, weights):
        d = duration * w / total
        out.append({"word": tok, "start": t, "end": t + d * 0.92, "ti": len(out)})
        t += d
    return out


def _attach_punctuation(text: str, words: list[dict]) -> list[dict]:
    """edge-tts drops punctuation from word events; put it back for nicer captions,
    and remember which word of the script ("ti") each spoken word is, so visuals can
    be cut exactly where each sentence starts."""
    tokens = text.split()
    out, ti = [], 0
    for w in words:
        bare = re.sub(r"\W", "", w["word"]).lower()
        match = None
        for j in range(ti, min(ti + 4, len(tokens))):
            if bare and re.sub(r"\W", "", tokens[j]).lower().startswith(bare[:3]):
                match = j
                break
        if match is not None:
            out.append({**w, "word": tokens[match], "ti": match})
            ti = match + 1
        else:
            out.append({**w, "ti": max(ti - 1, 0)})
    return out


def speak(text: str, out_wav: Path) -> tuple[float, list[dict]]:
    """Make narration audio. Returns (seconds, word timings)."""
    text = _clean(text)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    mp3 = out_wav.with_suffix(".mp3")
    words: list[dict] = []
    if FAKE:
        dur = max(1.5, len(text.split()) * 0.40)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=f=180:d={dur}", "-af", "volume=0.05",
             "-ar", "44100", "-ac", "1", out_wav])
    else:
        for attempt in range(4):
            try:
                words = asyncio.run(_edge(text, mp3))
                if mp3.stat().st_size > 1000:
                    break
            except Exception as exc:  # noqa: BLE001
                log(f"Voice attempt {attempt + 1} failed: {exc}")
        else:
            raise RuntimeError("Free voice service did not respond. Try again in a few minutes.")
        run(["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "1",
             "-af", "highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=10:release=200",
             out_wav])
    dur = media_duration(out_wav)
    words = _attach_punctuation(text, words) if words else _even_timings(text, dur)
    return dur, words

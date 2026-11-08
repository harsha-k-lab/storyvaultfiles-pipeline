"""Assembles narration, footage, cards, captions and music into finished videos."""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from . import graphics
from .core import CFG, log, media_duration, run
from .stock import MOOD_FALLBACKS, Footage
from .tts import speak

VC = CFG["video"]
FPS = int(VC["fps"])
GRADE = ("eq=saturation=0.70:contrast=1.07:brightness=-0.035,"
         "colorbalance=bs=0.05:bm=0.025:rs=-0.025,vignette=angle=PI/4.6,noise=alls=5:allf=t")


def _frames(seconds: float) -> int:
    return max(1, round(seconds * FPS))


def _enc_fast(out: Path) -> list:
    return ["-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
            "-pix_fmt", "yuv420p", "-r", str(FPS), out]


def shot_from_video(src: Path, frames: int, out: Path, w: int, h: int):
    length = media_duration(src)
    need = frames / FPS
    start = random.uniform(0, max(0.0, length - need - 0.5)) if length > need + 1 else 0
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,crop={w}:{h},"
          f"fps={FPS},setsar=1,{GRADE}")
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", src,
         "-vf", vf, "-frames:v", frames, *_enc_fast(out)])


def shot_from_image(src: Path, frames: int, out: Path, w: int, h: int, grade: bool = True,
                    fade: bool = False):
    zin = random.random() < 0.6
    z = "min(1.0+0.10*on/{n},1.10)" if zin else "max(1.10-0.10*on/{n},1.0)"
    z = z.format(n=frames)
    xs = random.choice(["iw/2-(iw/zoom/2)", "(iw-iw/zoom)*on/{n}", "(iw-iw/zoom)*(1-on/{n})"]).format(n=frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{xs}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS},setsar=1")
    if grade:
        vf += "," + GRADE
    if fade:
        d = frames / FPS
        vf += f",fade=t=in:st=0:d=0.5,fade=t=out:st={max(d - 0.5, 0):.2f}:d=0.5"
    run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-frames:v", frames, *_enc_fast(out)])


def _pad_audio(src: Path | None, seconds: float, out: Path, lead: float = 0.0):
    if src is None:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{seconds:.4f}",
             "-c:a", "pcm_s16le", out])
    else:
        run(["ffmpeg", "-y", "-i", src, "-af", f"adelay={int(lead * 1000)},apad",
             "-t", f"{seconds:.4f}", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", out])


def _concat(files: list[Path], out: Path, copy: bool = True):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files), encoding="utf-8")
    args = ["-c", "copy"] if copy else []
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, *args, out])


def _frame_grab(video: Path, out: Path) -> Path | None:
    try:
        run(["ffmpeg", "-y", "-ss", "1.5", "-i", video, "-frames:v", "1", "-q:v", "2", out])
        return out
    except RuntimeError:
        return None


def _finish(silent: Path, narration: Path, ass: Path, out: Path, crf: int = 21):
    mv = float(VC["music_volume"])
    music = out.parent / (out.stem + "-music.wav")
    graphics.ambient_music(music, media_duration(narration))
    fontsdir = graphics.FONT_DIR.resolve()
    fc = (
        f"[0:v]subtitles=filename='{ass.name}':fontsdir='{fontsdir}',format=yuv420p[v];"
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[n1][n2];"
        f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={mv}[m];"
        f"[m][n2]sidechaincompress=threshold=0.025:ratio=5:attack=40:release=800[md];"
        f"[n1][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11[a]"
    )
    cmd = ["ffmpeg", "-y", "-i", silent.resolve(), "-i", narration.resolve(), "-i", music.resolve(),
           "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest",
           out.resolve()]
    proc = subprocess.run([str(c) for c in cmd], cwd=ass.parent, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("Final video encode failed:\n" + proc.stderr[-1500:])


def preview(src: Path, out: Path) -> Path:
    """Small copy (≤ 50 MB) that plays right inside Telegram."""
    for crf, height in ((30, 480), (34, 360)):
        run(["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:{height}", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", "-b:a", "64k", "-ac", "1",
             "-movflags", "+faststart", out])
        if out.stat().st_size < 48 * 1024 * 1024:
            break
    return out


# ── long-form ────────────────────────────────────────────────────────────────

def render_long(script: dict, work: Path, case_no: int, photos: list[Path | None]) -> dict:
    w, h = int(VC["width"]), int(VC["height"])
    shots_dir = work / "shots"
    audio_dir = work / "audio"
    for d in (shots_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)
    footage = Footage(work / "footage", "landscape")
    per_shot = float(VC["seconds_per_shot"])

    # 1) Voice for every scene first (also tells us the timing).
    beats = [{"kind": "intro", "seconds": 4.0}]
    chapter_no = 0
    for i, sc in enumerate(script["scenes"]):
        if sc.get("chapter"):
            chapter_no += 1
            beats.append({"kind": "chapter", "seconds": 2.8, "name": sc["chapter"], "no": chapter_no})
        log(f"Voice {i + 1}/{len(script['scenes'])}")
        wav = audio_dir / f"scene{i:03d}.wav"
        dur, words = speak(sc["narration"], wav)
        beats.append({"kind": "scene", "seconds": dur + 0.45, "wav": wav, "words": words, "scene": sc})
    beats.append({"kind": "end", "seconds": 6.0})

    # 2) Visuals.
    shot_files, audio_files, all_words, credits = [], [], [], {}
    t = 0.0
    first_frame: Path | None = next((p for p in photos if p), None)
    card_bg = first_frame
    fallback = MOOD_FALLBACKS[:]
    for bi, b in enumerate(beats):
        frames = _frames(b["seconds"])
        seconds = frames / FPS
        if b["kind"] == "scene":
            sc = b["scene"]
            n = max(1, round(seconds / per_shot))
            base = frames // n
            parts = [base] * (n - 1) + [frames - base * (n - 1)]
            img_idx = sc.get("image", -1)
            photo = photos[img_idx] if isinstance(img_idx, int) and 0 <= img_idx < len(photos) else None
            for k, fcount in enumerate(parts):
                out = shots_dir / f"b{bi:03d}_{k}.mp4"
                if k == 0 and photo:
                    shot_from_image(photo, fcount, out, w, h)
                else:
                    random.shuffle(fallback)
                    qs = sc.get("visuals") or []
                    got = footage.get(qs[k % len(qs):] + qs[:k % len(qs)] if qs else [], fallback[:3])
                    if got:
                        path, item = got
                        if item["kind"] == "video":
                            shot_from_video(path, fcount, out, w, h)
                        else:
                            shot_from_image(path, fcount, out, w, h)
                        credits[item.get("credit", "")] = True
                        if card_bg is None and item["kind"] == "video":
                            card_bg = _frame_grab(path, work / "cardbg.jpg")
                    else:
                        shot_from_image(graphics.end_card(work / "blank.jpg", w, h), fcount, out, w, h)
                shot_files.append(out)
            pad = audio_dir / f"pad{bi:03d}.wav"
            _pad_audio(b["wav"], seconds, pad, lead=0.15)
            all_words += [{**wd, "start": wd["start"] + t + 0.15, "end": wd["end"] + t + 0.15}
                          for wd in b["words"]]
        else:
            png = work / f"card{bi:03d}.jpg"
            if b["kind"] == "intro":
                graphics.intro_card(png, case_no, script["title"], w, h, card_bg)
            elif b["kind"] == "chapter":
                graphics.chapter_card(png, b["no"], b["name"], w, h, card_bg)
            else:
                graphics.end_card(png, w, h, card_bg)
            out = shots_dir / f"b{bi:03d}_card.mp4"
            shot_from_image(png, frames, out, w, h, grade=False, fade=True)
            shot_files.append(out)
            pad = audio_dir / f"pad{bi:03d}.wav"
            _pad_audio(None, seconds, pad)
        audio_files.append(pad)
        t += seconds
        log(f"Visual beat {bi + 1}/{len(beats)} done ({t / 60:.1f} min)")

    # 3) Stitch + finish.
    silent = work / "long_silent.mp4"
    _concat(shot_files, silent)
    narration = work / "long_narration.wav"
    _concat(audio_files, narration)
    ass = graphics.write_ass(all_words, work / "long.ass", w, h, vertical=False)
    final = work / "video.mp4"
    log("Final encode (long video)…")
    _finish(silent, narration, ass, final)
    thumb_bg = first_frame or card_bg
    thumb = graphics.thumbnail(work / "thumbnail.jpg", thumb_bg, script.get("thumbnail_text", script["title"]), case_no)
    return {"video": final, "thumbnail": thumb, "seconds": t,
            "chapters": _chapters(beats), "credits": [c for c in credits if c]}


def _chapters(beats: list[dict]) -> list[tuple[float, str]]:
    out, t = [(0.0, "Intro")], 0.0
    for b in beats:
        if b["kind"] == "chapter":
            out.append((t, b["name"]))
        t += _frames(b["seconds"]) / FPS
    return out if len(out) >= 3 else []


# ── short / reel ─────────────────────────────────────────────────────────────

def render_short(script: dict, work: Path) -> dict:
    w, h = 1080, 1920
    sh = script["short"]
    sdir = work / "short"
    sdir.mkdir(parents=True, exist_ok=True)
    dur, words = speak(sh["narration"], sdir / "voice.wav")
    total = dur + 0.6
    frames = _frames(total)
    footage = Footage(work / "footage_v", "portrait")
    n = max(4, round(total / 3.2))  # fast cuts keep short-form viewers watching
    base = frames // n
    parts = [base] * (n - 1) + [frames - base * (n - 1)]
    qs = sh.get("visuals") or ["dark forest fog"]
    shot_files = []
    for k, fc in enumerate(parts):
        out = sdir / f"s{k:02d}.mp4"
        fallback = MOOD_FALLBACKS[:]
        random.shuffle(fallback)
        got = footage.get([qs[k % len(qs)]], fallback[:3])
        if got and got[1]["kind"] == "video":
            shot_from_video(got[0], fc, out, w, h)
        elif got:
            shot_from_image(got[0], fc, out, w, h)
        else:
            shot_from_image(graphics.end_card(sdir / "blank.jpg", w, h), fc, out, w, h)
        shot_files.append(out)
    silent = sdir / "silent.mp4"
    _concat(shot_files, silent)
    narration = sdir / "narration.wav"
    _pad_audio(sdir / "voice.wav", frames / FPS, narration, lead=0.1)
    words = [{**wd, "start": wd["start"] + 0.1, "end": wd["end"] + 0.1} for wd in words]
    ass = graphics.write_ass(words, sdir / "short.ass", w, h, vertical=True)
    final = work / "short.mp4"
    log("Final encode (short)…")
    _finish(silent, narration, ass, final, crf=22)
    return {"video": final, "seconds": frames / FPS}

"""Assembles narration, footage, cards, captions and music into finished videos."""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from . import graphics
from .core import CFG, log, media_duration, run
from .aiimages import Images
from .stock import Footage
from .tts import speak_sentences

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


def audio_holes(path: Path) -> list[tuple[float, float]]:
    """Places where an encoded file's sound track skips ahead: [(at seconds, missing seconds)].
    An AAC packet holds 1024 samples (about 0.02 s); a longer one means audio was dropped there,
    which players hear as the voice cutting out mid-sentence."""
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                           "packet=pts_time,duration_time", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True)
    holes = []
    for line in proc.stdout.split():
        parts = line.split(",")
        try:
            at, d = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            continue
        if d > 0.1:
            holes.append((round(at, 2), round(d, 2)))
    return holes


def _check_sound(path: Path, what: str):
    holes = audio_holes(path)
    if holes:
        raise RuntimeError(f"{what}: the sound track has gaps at "
                           + ", ".join(f"{a:.1f}s ({d:.1f}s)" for a, d in holes[:6]))


def _finish(silent: Path, narration: Path, ass: Path, out: Path, crf: int = 21, maxrate: str = "8M"):
    """Burn captions, mix voice + music, and join them into the final file.

    The sound and the picture are encoded separately and then copied together. Encoding them in
    one ffmpeg run with -shortest made ffmpeg 6.1 (the version on GitHub's machines) throw away
    whole seconds of narration whenever the slower video encode fell behind: the 'voice going
    off' in earlier videos."""
    vdur = media_duration(silent)
    mv = float(VC["music_volume"])
    music = out.parent / (out.stem + "-music.wav")
    graphics.ambient_music(music, vdur)

    # 1) Sound only: voice + ducked music, loudness-normalised, exactly as long as the picture.
    sound = out.parent / (out.stem + "-sound.m4a")
    fa = (
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[n1][n2];"
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={mv}[m];"
        f"[m][n2]sidechaincompress=threshold=0.025:ratio=5:attack=40:release=800[md];"
        f"[n1][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11,"
        f"aresample=48000,apad,atrim=0:{vdur:.3f}[a]"
    )
    run(["ffmpeg", "-y", "-i", narration.resolve(), "-i", music.resolve(), "-filter_complex", fa,
         "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", sound.resolve()])
    _check_sound(sound, "Sound mix")

    # 2) Picture only, with the captions burned in.
    picture = out.parent / (out.stem + "-picture.mp4")
    fontsdir = graphics.FONT_DIR.resolve()
    cmd = ["ffmpeg", "-y", "-i", silent.resolve(),
           "-vf", f"subtitles=filename='{ass.name}':fontsdir='{fontsdir}',format=yuv420p", "-an",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-profile:v", "high",
           "-maxrate", maxrate, "-bufsize", str(int(maxrate[:-1]) * 2) + "M", picture.resolve()]
    proc = subprocess.run([str(c) for c in cmd], cwd=ass.parent, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("Final video encode failed:\n" + proc.stderr[-1500:])

    # 3) Join them without re-encoding, so nothing can be dropped.
    run(["ffmpeg", "-y", "-i", picture.resolve(), "-i", sound.resolve(), "-map", "0:v:0", "-map", "1:a:0",
         "-c", "copy", "-movflags", "+faststart", out.resolve()])
    _check_sound(out, "Final video")
    for f in (sound, picture, music):
        f.unlink(missing_ok=True)


def preview(src: Path, out: Path, vertical: bool = False) -> Path:
    """Small copy (under 50 MB) that plays right inside Telegram."""
    sizes = ((26, 1280), (30, 960)) if vertical else ((30, 480), (34, 360))
    for crf, height in sizes:
        run(["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:{height}", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", "-b:a", "96k",
             "-movflags", "+faststart", out])
        if audio_holes(out):   # never send a preview whose voice skips: copy the sound as-is
            run(["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:{height}", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", str(crf), "-c:a", "copy", "-movflags", "+faststart", out])
        if out.stat().st_size < 48 * 1024 * 1024:
            break
    _check_sound(out, "Telegram preview")
    return out


def plan_cuts(shots: list[dict], words: list[dict], total_frames: int, lead: float,
              min_s: float, max_s: float) -> list[tuple[int, dict, int]]:
    """Cut the picture exactly where each sentence starts being spoken.

    Returns [(frames, shot, part)]: part 0 is the shot's first clip; long sentences are
    split into extra clips (part 1, 2…) that show the same subject from another clip."""
    counts = [max(1, len(sh["text"].split())) for sh in shots]
    total_tokens = sum(counts)
    starts, cum = [0], 0
    for c in counts[:-1]:
        cum += c
        if words:
            w = next((wd for wd in words if wd.get("ti", 0) >= cum), words[-1])
            t = w["start"] + lead - 0.10          # cut just before the first word of the sentence
        else:
            t = total_frames / FPS * cum / total_tokens
        starts.append(max(starts[-1], round(t * FPS)))
    bounds = list(zip(starts, starts[1:] + [total_frames]))
    # merge sentences too short to hold a clip into the one before
    merged: list[list] = []
    for (a, b), sh in zip(bounds, shots):
        if merged and (b - a) < min_s * FPS:
            merged[-1][1] = b
        else:
            merged.append([a, b, sh])
    if len(merged) > 1 and merged[0][1] - merged[0][0] < min_s * FPS:
        merged[1][0] = 0
        merged.pop(0)
    plan = []
    for a, b, sh in merged:
        n = max(1, round((b - a) / (max_s * FPS) + 0.25))
        size = (b - a) // n
        for k in range(n):
            plan.append((size if k < n - 1 else (b - a) - size * (n - 1), sh, k))
    return plan


def _shot_clip(footage: Footage, sh: dict, part: int, photos: list, mood: list[str],
               fcount: int, out: Path, w: int, h: int, credits: dict, blank: Path,
               images: Images | None = None, look: str = "") -> Path | None:
    """Make one clip for a sentence. Order: the case's real photo → an AI picture made for
    this exact sentence → matching stock footage → a plain dark card. Returns the still used."""
    img_idx = sh.get("image", -1)
    photo = photos[img_idx] if isinstance(img_idx, int) and 0 <= img_idx < len(photos) else None
    if part == 0 and photo:
        shot_from_image(photo, fcount, out, w, h)
        log(f'  “{sh["text"][:50]}…” → real case photo')
        return photo
    if images is not None and sh.get("image_prompt"):
        pic = images.get(sh["image_prompt"], look, variant=part)
        if pic:
            shot_from_image(pic, fcount, out, w, h)
            log(f'  “{sh["text"][:50]}…” → AI picture')
            return pic
    got = footage.get(sh.get("search") or [], mood)
    if not got:
        shot_from_image(blank, fcount, out, w, h)
        return None
    path, item = got
    if item["kind"] == "video":
        shot_from_video(path, fcount, out, w, h)
    else:
        shot_from_image(path, fcount, out, w, h)
    credits[item.get("credit", "")] = True
    log(f'  “{sh["text"][:50]}…” → stock {item["kind"]} for “{item.get("query", "")}”')
    return path if item["kind"] != "video" else _frame_grab(path, out.with_suffix(".jpg"))


# ── long-form ────────────────────────────────────────────────────────────────

def render_long(script: dict, work: Path, case_no: int, photos: list[Path | None]) -> dict:
    w, h = int(VC["width"]), int(VC["height"])
    shots_dir = work / "shots"
    audio_dir = work / "audio"
    for d in (shots_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)
    footage = Footage(work / "footage", "landscape")
    images = Images(work.parent / "images", script.get("picture_salt", ""))      # shared cache: the Short and revisions reuse pictures
    look = script.get("look", "")
    per_shot = float(VC["seconds_per_shot"])

    # 1) Voice for every scene first (also tells us the timing). No silent cards:
    #    the narration runs continuously and titles appear on top of the footage.
    beats, chapter_no = [], 0
    for i, sc in enumerate(script["scenes"]):
        log(f"Voice {i + 1}/{len(script['scenes'])}")
        wav = audio_dir / f"scene{i:03d}.wav"
        dur, words = speak_sentences([sh["text"] for sh in sc["shots"]], wav)
        b = {"kind": "scene", "seconds": dur + 0.25, "wav": wav, "words": words, "scene": sc}
        if sc.get("chapter") and i > 0:
            chapter_no += 1
            b.update(chapter=sc["chapter"], chapter_no=chapter_no)
        beats.append(b)
    beats.append({"kind": "end", "seconds": 3.5})

    # where the title goes: over "This is case file number …", else the 2nd sentence
    title_at = next(((bi, si) for bi, b in enumerate(beats[:3]) if b["kind"] == "scene"
                     for si, sh in enumerate(b["scene"]["shots"]) if "case file" in sh["text"].lower()),
                    (0, 1 if len(beats[0]["scene"]["shots"]) > 1 else 0))

    # 2) Visuals.
    shot_files, audio_files, all_words, credits = [], [], [], {}
    t = 0.0
    first_frame: Path | None = next((p for p in photos if p), None)
    card_bg = first_frame
    mood = script.get("mood") or []
    blank = graphics.end_card(work / "blank.jpg", w, h)
    for bi, b in enumerate(beats):
        frames = _frames(b["seconds"])
        seconds = frames / FPS
        b["start"] = t
        if b["kind"] == "scene":
            sc = b["scene"]
            plan = plan_cuts(sc["shots"], b["words"], frames, lead=0.05, min_s=2.2, max_s=per_shot)
            title_k = -1
            if bi == title_at[0]:   # the clip that holds the title sentence (it may have been merged)
                idxs = [sc["shots"].index(p[1]) for p in plan]
                title_k = max((k for k, i in enumerate(idxs) if i <= title_at[1] and plan[k][2] == 0), default=0)
            for k, (fcount, sh, part) in enumerate(plan):
                out = shots_dir / f"b{bi:03d}_{k:02d}.mp4"
                still = _shot_clip(footage, sh, part, photos, mood, fcount, out, w, h, credits, blank,
                                   images, look)
                if card_bg is None and still:
                    card_bg = still
                if bi == 0 and k == 0:
                    _overlay(out, graphics.title_card_overlay(work / "titlecard.png", script["title_card"], w, h), 4.2)
                if k == 0 and b.get("chapter"):
                    _overlay(out, graphics.chapter_overlay(work / f"ch{bi:03d}.png", b["chapter_no"],
                                                           b["chapter"], w, h), 3.8)
                if k == title_k and not (bi == 0 and k == 0):
                    lb = script["label"]
                    _overlay(out, graphics.label_overlay(work / "label.png", graphics.file_label(script, case_no),
                                                         lb["name"] or script["title_card"]["title"],
                                                         lb["detail"], w, h), 4.5)
                shot_files.append(out)
            pad = audio_dir / f"pad{bi:03d}.wav"
            _pad_audio(b["wav"], seconds, pad, lead=0.05)
            all_words += [{**wd, "start": wd["start"] + t + 0.05, "end": wd["end"] + t + 0.05}
                          for wd in b["words"]]
        else:
            png = work / "endcard.jpg"
            graphics.file_end_card(png, case_no, script.get("end_line", ""), w, h, graphics.file_label(script, case_no))
            out = shots_dir / f"b{bi:03d}_end.mp4"
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
    log("Images:", images.summary())
    thumb_bg = first_frame or card_bg
    thumb = graphics.thumbnail(work / "thumbnail.jpg", thumb_bg, script.get("thumbnail_text", script["title"]), case_no,
                               script.get("kind", "case"))
    return {"video": final, "thumbnail": thumb, "seconds": t, "images": images.summary(),
            "chapters": _chapters(beats), "credits": [c for c in credits if c]}


def _chapters(beats: list[dict]) -> list[tuple[float, str]]:
    """YouTube chapters: first at 0:00, at least 3, each at least 10 seconds long."""
    out = [(0.0, "Intro")] + [(b["start"], b["chapter"]) for b in beats if b.get("chapter")]
    out = [c for i, c in enumerate(out) if i == 0 or c[0] - out[i - 1][0] >= 10]
    return out if len(out) >= 3 else []


def _overlay(clip: Path, png: Path, seconds: float):
    """Fade a transparent title image in and out over the start of a clip."""
    d = min(seconds, media_duration(clip))
    tmp = clip.with_name(clip.stem + "_ov.mp4")
    run(["ffmpeg", "-y", "-i", clip, "-loop", "1", "-t", f"{d:.2f}", "-i", png, "-filter_complex",
         f"[1:v]format=rgba,fade=t=in:st=0:d=0.4:alpha=1,fade=t=out:st={max(d - 0.6, 0.4):.2f}:d=0.6:alpha=1[o];"
         f"[0:v][o]overlay=0:0:eof_action=pass,format=yuv420p[v]", "-map", "[v]", *_enc_fast(tmp)])
    tmp.replace(clip)


# ── short / reel ─────────────────────────────────────────────────────────────

def render_short(script: dict, work: Path, case_no: int = 0) -> dict:
    w, h = 1080, 1920
    sh = script["short"]
    sdir = work / "short"
    sdir.mkdir(parents=True, exist_ok=True)
    dur, words = speak_sentences([x["text"] for x in sh["shots"]], sdir / "voice.wav")
    total = dur + 0.5
    frames = _frames(total)
    footage = Footage(work / "footage_v", "portrait")
    images = Images(work.parent / "images", script.get("picture_salt", ""))
    blank = graphics.end_card(sdir / "blank.jpg", w, h)
    plan = plan_cuts(sh["shots"], words, frames, lead=0.05, min_s=1.6, max_s=3.8)  # a new picture every 2–4 s
    shot_files, credits, t = [], {}, 0.0
    label_done, first_still = False, None
    for k, (fc, shot, part) in enumerate(plan):
        out = sdir / f"s{k:02d}.mp4"
        still = _shot_clip(footage, shot, part, [], script.get("mood") or [], fc, out, w, h, credits, blank,
                           images, script.get("look", ""))
        first_still = first_still or still
        if k == 0:
            _overlay(out, graphics.title_card_overlay(sdir / "titlecard.png", script["title_card"], w, h), 3.6)
        elif not label_done and t >= 6.0 and script["label"]["name"]:
            _overlay(out, graphics.label_overlay(sdir / "label.png", graphics.file_label(script, case_no),
                                                 script["label"]["name"], script["label"]["detail"], w, h), 3.5)
            label_done = True
        shot_files.append(out)
        t += fc / FPS
    end_frames = _frames(2.5)
    end_png = graphics.file_end_card(sdir / "endcard.jpg", case_no, script.get("end_line", ""), w, h,
                                     graphics.file_label(script, case_no))
    end_clip = sdir / "s_end.mp4"
    shot_from_image(end_png, end_frames, end_clip, w, h, grade=False, fade=True)
    shot_files.append(end_clip)
    silent = sdir / "silent.mp4"
    _concat(shot_files, silent)
    narration = sdir / "narration.wav"
    _pad_audio(sdir / "voice.wav", (frames + end_frames) / FPS, narration, lead=0.05)
    words = [{**wd, "start": wd["start"] + 0.05, "end": wd["end"] + 0.05} for wd in words]
    ass = graphics.write_ass(words, sdir / "short.ass", w, h, vertical=True)
    final = work / "short.mp4"
    log("Final encode (short)…", images.summary())
    _finish(silent, narration, ass, final, crf=22, maxrate="5M")
    return {"video": final, "seconds": (frames + end_frames) / FPS, "still": first_still,
            "images": images.summary(), "credits": [c for c in credits if c]}


def short_thumbnail(script: dict, work: Path, case_no: int, short: dict) -> Path:
    """Cover image for a Short-only video (used in Telegram and as the YouTube thumbnail)."""
    return graphics.thumbnail(work / "thumbnail.jpg", short.get("still"),
                              script.get("thumbnail_text") or script["title"], case_no, script.get("kind", "case"))

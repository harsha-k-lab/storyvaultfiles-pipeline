"""Title cards, thumbnails, captions (ASS) and the free generated soundtrack."""
from __future__ import annotations

import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .core import ASSETS, CFG, run

FONT_DIR = ASSETS / "fonts"
RED = (196, 30, 36)
PAPER = (232, 224, 205)


def font_path(kind: str = "display") -> str:
    """display = big headline font, body = clean sans, type = typewriter."""
    wanted = {
        "display": ["Anton-Regular.ttf", "BebasNeue-Regular.ttf"],
        "type": ["SpecialElite-Regular.ttf"],
        "body": [],
    }[kind]
    for name in wanted:
        if (FONT_DIR / name).exists():
            return str(FONT_DIR / name)
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"):
        if Path(p).exists():
            return p
    return ""


def _font(kind: str, size: int):
    p = font_path(kind)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS)


def _grade(img: Image.Image, darkness: float = 0.45) -> Image.Image:
    img = ImageEnhance.Color(img).enhance(0.45)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Brightness(img).enhance(darkness)
    tint = Image.new("RGB", img.size, (20, 40, 55))
    return Image.blend(img, tint, 0.18)


def _vignette(img: Image.Image, strength: float = 0.8) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


def _background(w: int, h: int, bg: Path | None) -> Image.Image:
    if bg and bg.exists():
        try:
            img = _cover(Image.open(bg), w, h).filter(ImageFilter.GaussianBlur(6))
            return _vignette(_grade(img, 0.32))
        except Exception:  # noqa: BLE001
            pass
    img = Image.new("RGB", (w, h), (14, 17, 20))
    noise = Image.effect_noise((w, h), 22).convert("RGB")
    return _vignette(Image.blend(img, noise, 0.06))


def _fit_text(draw, text, kind, max_w, start, min_size=30):
    size = start
    while size > min_size:
        f = _font(kind, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(kind, min_size)


def _stamp(base: Image.Image, text: str, xy, size: int, angle: float = -8):
    f = _font("display", size)
    tmp = Image.new("RGBA", (int(size * len(text) * 0.75 + 60), int(size * 1.8)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    tw = d.textlength(text, font=f)
    box = [10, 10, tw + 50, size * 1.55]
    d.rectangle(box, outline=RED + (235,), width=max(4, size // 12))
    d.text((30, size * 0.18), text, font=f, fill=RED + (235,))
    tmp = tmp.crop((0, 0, int(tw + 62), int(size * 1.7))).rotate(angle, expand=True, resample=Image.BICUBIC)
    base.paste(tmp, xy, tmp)


def intro_card(out: Path, case_no: int, title: str, w: int, h: int, bg: Path | None = None) -> Path:
    img = _background(w, h, bg)
    d = ImageDraw.Draw(img)
    s = h / 1080
    brand = CFG["channel"]["name"].upper()
    fb = _font("type", int(40 * s))
    d.text((w / 2, h * 0.24), brand, font=fb, fill=PAPER, anchor="mm")
    d.line([(w / 2 - 260 * s, h * 0.29), (w / 2 + 260 * s, h * 0.29)], fill=PAPER, width=max(1, int(2 * s)))
    lines = textwrap.wrap(title.upper(), width=26 if w > h else 16)[:3]
    y = h * 0.42
    for line in lines:
        f = _fit_text(d, line, "display", w * 0.86, int(118 * s))
        d.text((w / 2, y), line, font=f, fill=(245, 245, 240), anchor="mm")
        y += f.size * 1.12
    _stamp(img, f"CASE FILE #{case_no:03d}", (int(w / 2 - 230 * s), int(y + 30 * s)), int(64 * s))
    img.save(out, quality=95)
    return out


def chapter_card(out: Path, number: int, name: str, w: int, h: int, bg: Path | None = None) -> Path:
    img = _background(w, h, bg)
    d = ImageDraw.Draw(img)
    s = h / 1080
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][min(number, 10) - 1]
    d.text((w / 2, h * 0.40), f"CHAPTER {roman}", font=_font("type", int(46 * s)), fill=RED, anchor="mm")
    f = _fit_text(d, name.upper(), "display", w * 0.85, int(110 * s))
    d.text((w / 2, h * 0.53), name.upper(), font=f, fill=(240, 238, 230), anchor="mm")
    img.save(out, quality=95)
    return out


def end_card(out: Path, w: int, h: int, bg: Path | None = None) -> Path:
    img = _background(w, h, bg)
    d = ImageDraw.Draw(img)
    s = h / 1080
    d.text((w / 2, h * 0.40), "THIS FILE REMAINS OPEN", font=_fit_text(d, "THIS FILE REMAINS OPEN", "display", w * .85, int(96 * s)),
           fill=(240, 238, 230), anchor="mm")
    d.text((w / 2, h * 0.53), CFG["channel"]["posting_note"], font=_font("type", int(44 * s)), fill=PAPER, anchor="mm")
    d.text((w / 2, h * 0.64), f"Subscribe  ·  {CFG['channel']['handle']}", font=_font("type", int(40 * s)),
           fill=RED, anchor="mm")
    img.save(out, quality=95)
    return out


def thumbnail(out: Path, bg: Path | None, text: str, case_no: int) -> Path:
    w, h = 1280, 720
    if bg and bg.exists():
        img = _cover(Image.open(bg), w, h)
        img = _vignette(ImageEnhance.Brightness(ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(0.6))
                                                .enhance(1.3)).enhance(0.75), 0.75)
    else:
        img = _background(w, h, None)
    # dark band behind the text on the left for readability
    shade = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(shade)
    for x in range(w):
        sd.line([(x, 0), (x, h)], fill=int(max(0, 210 - x * 0.33)))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, shade)
    d = ImageDraw.Draw(img)
    words = text.upper().split()
    lines = textwrap.wrap(" ".join(words), width=11)[:3]
    y = 110 if len(lines) == 3 else 150
    for i, line in enumerate(lines):
        f = _fit_text(d, line, "display", 700, 150, 60)
        color = (255, 214, 0) if i == len(lines) - 1 else (255, 255, 255)
        d.text((60, y), line, font=f, fill=color, stroke_width=6, stroke_fill=(0, 0, 0))
        y += f.size * 1.02
    sw = int(ImageDraw.Draw(img).textlength("UNSOLVED", font=_font("display", 70))) + 110
    _stamp(img, "UNSOLVED", (w - sw - 30, h - 200), 70, angle=-8)
    d.text((62, h - 70), f"CASE #{case_no:03d}", font=_font("type", 38), fill=PAPER,
           stroke_width=2, stroke_fill=(0, 0, 0))
    img.save(out, quality=92)
    return out


# ── captions ─────────────────────────────────────────────────────────────────

def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(words: list[dict], out: Path, w: int, h: int, vertical: bool = False) -> Path:
    """Burned-in captions: clean lower-third for long-form, big centred words for Shorts."""
    if vertical:
        size, per, align, margin_v = int(h * 0.064), 3, 5, int(h * 0.10)
        fontname = "Anton" if (FONT_DIR / "Anton-Regular.ttf").exists() else "DejaVu Sans"
        outline, primary = 7, "&H00FFFFFF"
    else:
        size, per, align, margin_v = int(h * 0.046), 7, 2, int(h * 0.07)
        fontname = "DejaVu Sans"
        outline, primary = 3, "&H00F4F4F4"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{fontname},{size},{primary},&H0000D7FF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,{outline},2,{align},{int(w * .08)},{int(w * .08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events, chunk = [], []

    def flush(next_start=None):
        if not chunk:
            return
        start = chunk[0]["start"]
        end = chunk[-1]["end"] + 0.25
        if next_start is not None:
            end = min(end, next_start - 0.02)
        text = " ".join(c["word"] for c in chunk)
        if vertical:
            text = text.upper()
        text = text.replace("{", "(").replace("}", ")")
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(max(end, start + 0.3))},Cap,,0,0,0,,{text}")
        chunk.clear()

    for i, wd in enumerate(words):
        if chunk and (wd["start"] - chunk[-1]["end"] > 0.6):
            flush(wd["start"])
        chunk.append(wd)
        chars = sum(len(c["word"]) + 1 for c in chunk)
        ends_sentence = wd["word"][-1:] in ".?!,;:"
        if len(chunk) >= per or chars > (18 if vertical else 44) or (ends_sentence and len(chunk) >= 2):
            nxt = words[i + 1]["start"] if i + 1 < len(words) else None
            flush(nxt)
    flush()
    out.write_text(head + "\n".join(events) + "\n", encoding="utf-8")
    return out


# ── music ────────────────────────────────────────────────────────────────────

def ambient_music(out: Path, seconds: float) -> Path:
    """Copyright-free dark ambient bed generated from scratch (no downloads, no Content ID)."""
    own = sorted((ASSETS / "music").glob("*.mp3")) + sorted((ASSETS / "music").glob("*.wav"))
    d = seconds + 2
    if own:
        track = random.choice(own)
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", track, "-t", f"{d:.2f}",
             "-af", f"afade=t=in:d=2,afade=t=out:st={max(d - 5, 0):.2f}:d=5", "-ar", "44100", "-ac", "2", out])
        return out
    roots = {"A": 55.0, "C": 65.41, "D": 73.42, "E": 82.41, "F": 43.65}
    root = random.choice(list(roots.values()))
    minor3, fifth, octave = root * 1.1892, root * 1.4983, root * 2
    rate = random.uniform(0.05, 0.12)
    def swell(vol, f, depth):
        return f"volume='{vol}*({1 - depth:.2f}+{depth:.2f}*(0.5+0.5*sin(2*PI*t*{f:.4f})))':eval=frame"

    fc = (
        f"[0]lowpass=f=320,highpass=f=40,volume=0.55[n];"
        f"[1]{swell(0.30, rate, 0.6)}[a];"
        f"[2]{swell(0.16, rate * 0.7, 0.7)}[b];"
        f"[3]{swell(0.13, rate * 1.3, 0.6)}[c];"
        f"[4]{swell(0.05, rate * 0.5, 0.9)}[e];"
        f"[n][a][b][c][e]amix=inputs=5:normalize=0,"
        f"aecho=0.8:0.6:900|1400:0.25|0.18,lowpass=f=1800,"
        f"afade=t=in:d=4,afade=t=out:st={max(d - 5, 0):.2f}:d=5,alimiter=limit=0.7,"
        f"aformat=channel_layouts=stereo[out]"
    )
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"anoisesrc=d={d:.2f}:c=brown:r=44100:a=0.4",
         "-f", "lavfi", "-i", f"sine=f={root:.2f}:d={d:.2f}:r=44100",
         "-f", "lavfi", "-i", f"sine=f={minor3:.2f}:d={d:.2f}:r=44100",
         "-f", "lavfi", "-i", f"sine=f={fifth:.2f}:d={d:.2f}:r=44100",
         "-f", "lavfi", "-i", f"sine=f={octave * 2:.2f}:d={d:.2f}:r=44100",
         "-filter_complex", fc, "-map", "[out]", "-ar", "44100", out])
    return out

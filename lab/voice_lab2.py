"""Voice lab 2: check every sentence of a real script for clipped endings and truncated speech."""
import json, math, struct, sys, wave
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import tts                                 # noqa: E402
from pipeline.core import run                            # noqa: E402

OUT = Path("lab_out2"); OUT.mkdir(exist_ok=True)
sc = json.load(open("state/cases/002/script.json"))
sents = [sh["text"] for s in sc["scenes"] for sh in s["shots"]] + [sh["text"] for sh in sc["short"]["shots"]]

def levels(path):
    w = wave.open(str(path)); sr = w.getframerate(); n = w.getnframes()
    x = struct.unpack("<%dh" % n, w.readframes(n)); fr = sr // 100
    return [10 * math.log10(sum(v * v for v in x[i:i + fr]) / fr / 32768 ** 2 + 1e-12) for i in range(0, n - fr, fr)]

rows = []
for i, s in enumerate(sents):
    clip = OUT / f"s{i:03d}.wav"
    dur, words = tts.speak(s, clip)
    db = levels(clip)
    voiced = [k for k, v in enumerate(db) if v > -42]
    speech_end = (voiced[-1] + 1) / 100 if voiced else 0
    speech_start = voiced[0] / 100 if voiced else 0
    tokens = len(tts._clean(s).split())
    our_cut = min(dur, words[-1]["end"] + 0.16) if words else dur
    rows.append({"i": i, "tokens": tokens, "boundaries": len(words), "audio_s": round(dur, 2),
                 "speech_start": speech_start, "speech_end": round(speech_end, 2),
                 "last_word_end": round(words[-1]["end"], 2) if words else None,
                 "our_cut": round(our_cut, 2), "clipped_ms": max(0, round((speech_end - our_cut) * 1000)),
                 "sec_per_word": round((speech_end - speech_start) / max(tokens, 1), 2), "text": s[:70]})
(OUT / "rows.json").write_text(json.dumps(rows, indent=1))
bad_clip = [r for r in rows if r["clipped_ms"] > 0]
truncated = [r for r in rows if r["boundaries"] < r["tokens"] - 1 or r["sec_per_word"] < 0.22]
print("SUMMARY", json.dumps({"sentences": len(rows), "clipped_endings": len(bad_clip),
      "max_clipped_ms": max([r["clipped_ms"] for r in rows] or [0]),
      "possibly_truncated": len(truncated)}))
for r in bad_clip + truncated:
    print("ROW", json.dumps(r))
for f in OUT.glob("*.wav"):
    run(["ffmpeg", "-y", "-i", f, "-c:a", "flac", f.with_suffix(".flac")]); f.unlink()
for f in OUT.glob("*.mp3"):
    f.unlink()

"""Voice lab: record real narration and save every processing stage for inspection."""
import json, math, struct, sys, wave
from pathlib import Path

sys.path.insert(0, ".")
from pipeline import graphics, tts                      # noqa: E402
from pipeline.core import run, media_duration           # noqa: E402

OUT = Path("lab_out"); OUT.mkdir(exist_ok=True)
sc = json.load(open("state/cases/002/script.json"))
sents = [sh["text"] for s in sc["scenes"][:2] for sh in s["shots"]][:10]
(OUT / "sentences.json").write_text(json.dumps(sents, indent=1))

def holes(path, label):
    w = wave.open(str(path)); sr = w.getframerate(); n = w.getnframes()
    x = struct.unpack("<%dh" % n, w.readframes(n)); fr = sr // 100
    db = [10 * math.log10(sum(v * v for v in x[i:i + fr]) / fr / 32768 ** 2 + 1e-12) for i in range(0, n - fr, fr)]
    res, i = [], 0
    while i < len(db):
        if db[i] < -50:
            j = i
            while j < len(db) and db[j] < -50: j += 1
            before = max(db[max(0, i - 5):i] or [-99]); after = max(db[j:j + 5] or [-99])
            if before > -30 and after > -30 and (j - i) <= 25:
                res.append({"t": i / 100, "ms": (j - i) * 10})
            i = j
        else:
            i += 1
    return {"file": label, "seconds": round(len(db) / 100, 2), "holes_inside_speech": res}

report = []
# A: one take (old way)
dA, wA = tts.speak(" ".join(sents), OUT / "A_onetake.wav")
run(["ffmpeg", "-y", "-i", OUT / "A_onetake.mp3", "-ac", "1", "-ar", "44100", OUT / "A_raw.wav"])
report += [holes(OUT / "A_raw.wav", "A_raw (Microsoft voice, untouched)"), holes(OUT / "A_onetake.wav", "A_processed (highpass+compressor)")]
(OUT / "A_words.json").write_text(json.dumps(wA, indent=1))
# B: per sentence (current way)
dB, wB = tts.speak_sentences(sents, OUT / "B_sentences.wav")
report.append(holes(OUT / "B_sentences.wav", "B_per_sentence (trimmed + joined)"))
(OUT / "B_words.json").write_text(json.dumps(wB, indent=1))
# C: final mix exactly like the pipeline
music = OUT / "music.wav"; graphics.ambient_music(music, dB)
def mix(name, fc):
    run(["ffmpeg", "-y", "-i", OUT / "B_sentences.wav", "-i", music, "-filter_complex", fc, "-map", "[a]",
         "-ac", "1", "-ar", "44100", OUT / name])
    report.append(holes(OUT / name, name))
mv = 0.32
mix("C_current_mix.wav", f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[n1][n2];"
    f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={mv}[m];"
    f"[m][n2]sidechaincompress=threshold=0.025:ratio=5:attack=40:release=800[md];"
    f"[n1][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11[a]")
mix("D_no_duck.wav", f"[1:a]volume={mv * 0.6}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11[a]")
mix("E_voice_only_loudnorm.wav", "[0:a]loudnorm=I=-15:TP=-1.5:LRA=11[a]")
for f in ["A_raw.wav", "A_onetake.wav", "B_sentences.wav", "C_current_mix.wav"]:
    run(["ffmpeg", "-y", "-t", "20", "-i", OUT / f, "-lavfi", "showspectrumpic=s=1600x400:legend=0:scale=log",
         OUT / f.replace(".wav", "_spec.png")])
(OUT / "report.json").write_text(json.dumps(report, indent=1))
print(json.dumps(report, indent=1))

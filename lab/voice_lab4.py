"""Voice lab 4: for the sentences that broke in case 002, check each step of speak_sentences."""
import json, re, subprocess, wave
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
from pipeline.tts import speak

OUT = Path("lab_out4"); OUT.mkdir(exist_ok=True)
sc = json.load(open("state/cases/002/script.json"))
long_s = [sh["text"] for s in sc["scenes"] for sh in s["shots"]]
short_s = [sh["text"] for sh in sc["short"]["shots"]]
pick = [t for t in long_s if any(k in t for k in ("3300", "Mohenjo", "Beyond the famous", "Cholistan", "Chanhudaro", "Dasht"))]
pick += short_s[:2] + long_s[:2]
model = WhisperModel("small.en", device="cpu", compute_type="int8")

def load(p):
    with wave.open(str(p)) as wf:
        sr = wf.getframerate(); x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr

def energy_bounds(x, sr):
    hop = int(sr * 0.01); n = len(x) // hop
    rms = np.array([np.sqrt(np.mean(x[i*hop:(i+1)*hop] ** 2)) for i in range(n)])
    db = 20 * np.log10(rms + 1e-9); on = np.where(db > db.max() - 40)[0]
    return (round(on[0] * 0.01, 2), round((on[-1] + 1) * 0.01, 2)) if len(on) else (0, 0)

def hear(x, sr):
    if sr != 16000:
        idx = np.linspace(0, len(x) - 1, int(len(x) * 16000 / sr)); x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    segs, _ = model.transcribe(x, beam_size=5, vad_filter=False)
    return " ".join(s.text.strip() for s in segs)

rows = []
for k, text in enumerate(pick):
    for a in range(3):
        clip = OUT / f"s{k}_{a}.wav"
        dur, words = speak(text, clip)
        x, sr = load(clip)
        eb = energy_bounds(x, sr)
        start = max(0.0, words[0]["start"] - 0.05); end = min(dur, words[-1]["end"] + 0.16)
        seg = x[int(start * sr):int(end * sr)]
        rows.append({"k": k, "try": a, "text": text, "tokens": len(text.split()), "events": len(words),
                     "first": round(words[0]["start"], 2), "last": round(words[-1]["end"], 2), "dur": round(dur, 2),
                     "energy": eb, "words": [(w["word"], round(w["start"], 2)) for w in words][:4] + [(w["word"], round(w["start"], 2)) for w in words][-3:],
                     "raw_heard": hear(x, sr), "trim_heard": hear(seg, sr)})
        print(json.dumps(rows[-1]), flush=True)
(OUT / "report.json").write_text(json.dumps(rows, indent=1))
print("REPORT_START"); print(json.dumps(rows)); print("REPORT_END")

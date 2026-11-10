"""Voice lab 3: listen to the finished videos with Whisper and compare with the script."""
import difflib, json, re, subprocess, sys
from pathlib import Path
from faster_whisper import WhisperModel

OUT = Path("lab_out3"); OUT.mkdir(exist_ok=True)
sc = json.load(open("state/cases/002/script.json"))
texts = {"video": " ".join(sh["text"] for s in sc["scenes"] for sh in s["shots"]),
         "short": " ".join(sh["text"] for sh in sc["short"]["shots"])}
model = WhisperModel("small.en", device="cpu", compute_type="int8")
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
summary = {}
for name in ("short", "video"):
    subprocess.run(["gh", "release", "download", "case-002", "-p", f"{name}.mp4", "-D", "dl", "--clobber"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"dl/{name}.mp4", "-ac", "1", "-ar", "16000", f"{name}.wav"], check=True)
    segs, _ = model.transcribe(f"{name}.wav", word_timestamps=True, vad_filter=False, beam_size=5)
    heard = [(w.word.strip(), round(w.start, 2), round(w.end, 2), round(w.probability, 2)) for s in segs for w in s.words]
    ref = [norm(w) for w in texts[name].split() if norm(w)]
    hyp = [norm(w[0]) for w in heard]
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    problems = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op != "equal":
            t = heard[b0][1] if b0 < len(heard) else (heard[-1][2] if heard else 0)
            problems.append({"at": t, "op": op, "script": " ".join(ref[a0:a1]), "heard": " ".join(hyp[b0:b1])})
    gaps = [{"at": heard[i][2], "gap_s": round(heard[i + 1][1] - heard[i][2], 2), "between": f"{heard[i][0]} | {heard[i+1][0]}"}
            for i in range(len(heard) - 1) if heard[i + 1][1] - heard[i][2] > 0.55]
    low = [h for h in heard if h[3] < 0.45]
    summary[name] = {"script_words": len(ref), "heard_words": len(hyp), "match_ratio": round(sm.ratio(), 3),
                     "differences": problems, "long_gaps": gaps, "unclear_words": low[:40]}
(OUT / "report.json").write_text(json.dumps(summary, indent=1))
print("REPORT_START"); print(json.dumps(summary)); print("REPORT_END")

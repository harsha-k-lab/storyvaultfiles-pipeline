"""Voice lab 7: full render of case 002 (video + Short) with the NEW renderer, then Whisper listens."""
import difflib, json, re, sys, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, ".")
from pipeline import render
from pipeline.core import run
from faster_whisper import WhisperModel

script = json.load(open("state/cases/002/script.json"))
work = Path("work7"); work.mkdir(exist_ok=True)
lv = render.render_long(script, work, 2, [])["video"]
sv = render.render_short(script, work, 2)["video"]
texts = {"video": " ".join(sh["text"] for s in script["scenes"] for sh in s["shots"]),
         "short": " ".join(sh["text"] for sh in script["short"]["shots"])}
model = WhisperModel("small.en", device="cpu", compute_type="int8")
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
res = {}
for name, path in (("short", sv), ("video", lv)):
    run(["ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", f"{name}.wav"])
    with wave.open(f"{name}.wav") as wf:
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=False, beam_size=5)
    heard = [(w.word.strip(), round(w.start, 2)) for s in segs for w in s.words]
    ref = [norm(w) for w in texts[name].split() if norm(w)]
    hyp = [norm(w[0]) for w in heard]
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    missing = [{"at": heard[b0][1] if b0 < len(heard) else None, "script": " ".join(ref[a0:a1]), "heard": " ".join(hyp[b0:b1])}
               for op, a0, a1, b0, b1 in sm.get_opcodes() if op in ("delete", "replace") and a1 - a0 >= 3]
    res[name] = {"holes": render.audio_holes(path), "stream_s": render.media_duration(path),
                 "decoded_s": round(len(audio) / 16000, 2), "match_ratio": round(sm.ratio(), 3),
                 "script_words": len(ref), "heard_words": len(hyp), "missing_3plus_words": missing}
Path("lab_out7").mkdir(exist_ok=True); (Path("lab_out7") / "report.json").write_text(json.dumps(res, indent=1))
print("REPORT_START"); print(json.dumps(res)); print("REPORT_END")

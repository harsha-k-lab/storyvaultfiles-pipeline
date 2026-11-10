"""Voice lab 5: does the final encode drop audio on GitHub's machines? Old vs new, same input."""
import importlib.util, json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import graphics, render as new

spec = importlib.util.spec_from_file_location("pipeline.render_old", "lab/render_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)

W = Path("lab_out5"); W.mkdir(exist_ok=True)
D = 250
silent, nar = W / "silent.mp4", W / "nar.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=30:d={D}",
                "-vf", "noise=alls=40:allf=t", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
                "-pix_fmt", "yuv420p", silent], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:d={D}", "-af",
                "volume='if(lt(mod(t,0.5),0.4),0.5,0)':eval=frame", "-ar", "44100", "-ac", "1", nar], check=True)
words = [{"word": f"word{i}", "start": i * 0.5, "end": i * 0.5 + 0.4, "ti": i} for i in range(D * 2)]
ass = graphics.write_ass(words, W / "t.ass", 1920, 1080, vertical=False)
res = {"ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]}
for name, mod in (("old", old), ("new", new)):
    out = W / f"{name}.mp4"
    t = time.time()
    try:
        mod._finish(silent, nar, ass, out)
        err = ""
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:300]
    holes = new.audio_holes(out) if out.exists() else None
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout if out.exists() else b""
    res[name] = {"seconds_to_encode": round(time.time() - t, 1), "error": err, "holes": holes,
                 "decoded_audio_s": round(len(dec) / 32000, 2), "expected_s": D}
    print(name, res[name], flush=True)
for f in W.glob("*.mp4"): f.unlink()
(W / "report.json").write_text(json.dumps(res, indent=1))
print("REPORT_START"); print(json.dumps(res)); print("REPORT_END")

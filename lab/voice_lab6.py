"""Voice lab 6: render case 002's Short for real (old renderer), then try final-step variants on the same files."""
import importlib.util, json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import render as new
from pipeline.core import run
spec = importlib.util.spec_from_file_location("pipeline.render_old", "lab/render_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)

script = json.load(open("state/cases/002/script.json"))
work = Path("work6"); work.mkdir(exist_ok=True)
res = {}
old.render_short(script, work, 2)
sd = work / "short"
res["A_old_render"] = new.audio_holes(work / "short.mp4")
silent, nar, ass, music = sd / "silent.mp4", sd / "narration.wav", sd / "short.ass", work / "short-music.wav"
res["narration_wav_s"] = new.media_duration(nar)

def variant(name, fa, extra_in=()):
    out = work / f"{name}.m4a"
    run(["ffmpeg", "-y", "-i", nar, "-i", music, "-filter_complex", fa, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])
    res[name] = {"holes": new.audio_holes(out), "dur": new.media_duration(out)}

base = ("[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[n1][n2];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.32[m];"
        "[m][n2]sidechaincompress=threshold=0.025:ratio=5:attack=40:release=800[md];"
        "[n1][md]amix=inputs=2:duration=first:normalize=0")
variant("B_audio_only_old_graph", base + ",loudnorm=I=-15:TP=-1.5:LRA=11[a]")
variant("C_audio_only_no_loudnorm", base + "[a]")
variant("D_audio_only_loudnorm_resampled", base + ",loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000[a]")
variant("E_voice_only_loudnorm", "[0:a]loudnorm=I=-15:TP=-1.5:LRA=11[a]")
variant("F_no_duck_loudnorm", "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[n];[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.2[m];[n][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11[a]")
new._finish(silent, nar, ass, work / "G_new_finish.mp4") if False else None
try:
    new._finish(silent, nar, ass, work / "G_new_finish.mp4"); res["G_new_finish"] = new.audio_holes(work / "G_new_finish.mp4")
except Exception as exc:  # noqa: BLE001
    res["G_new_finish"] = "error: " + str(exc)[:300]
res["ffmpeg"] = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
Path("lab_out6").mkdir(exist_ok=True); (Path("lab_out6") / "report.json").write_text(json.dumps(res, indent=1))
print("REPORT_START"); print(json.dumps(res)); print("REPORT_END")

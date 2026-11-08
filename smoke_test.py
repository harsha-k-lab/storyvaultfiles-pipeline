"""Offline end-to-end test: topics → pick → render → revise → publish, all faked.

    SVF_FAKE=1 python tests/smoke_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["SVF_FAKE"] = "1"
ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("SVF_STATE_DIR", tempfile.mkdtemp(prefix="svf-state-"))
os.environ.setdefault("SVF_WORK_DIR", str(ROOT / "work"))
sys.path.insert(0, str(ROOT))

from pipeline import run  # noqa: E402
from pipeline.core import State, media_duration  # noqa: E402

state = State()
run.cmd_topics(state)
job = state.latest_job("awaiting_topic")
assert job, "no job created"
run.handle(state, {"kind": "button", "data": f"pick:{job}:0"})
assert state.job(job)["status"] == "awaiting_review", state.job(job)["status"]
run.handle(state, {"kind": "text", "text": "make the intro creepier"})
assert state.job(job)["status"] == "awaiting_review"
run.handle(state, {"kind": "button", "data": f"pub:{job}"})
assert state.job(job)["status"] == "published", state.job(job)["status"]

work = Path(os.environ["SVF_WORK_DIR"]) / f"case-{job}"
for name in ("video.mp4", "short.mp4", "thumbnail.jpg", "preview.mp4"):
    p = work / name
    assert p.exists() and p.stat().st_size > 1000, f"missing {name}"
print(f"OK  long={media_duration(work / 'video.mp4'):.1f}s  short={media_duration(work / 'short.mp4'):.1f}s")
print("Description preview:\n", run.build_description(
    run.load_json(run.case_dir(job) / "script.json"), run.load_json(run.case_dir(job) / "meta.json"))[:500])

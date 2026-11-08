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

# ── Claude path: fire → Claude pushes JSON → delivery renders ─────────────────
import json  # noqa: E402

from pipeline import claude, writer  # noqa: E402
from pipeline import validate  # noqa: E402

os.environ["SVF_FAKE_CLAUDE"] = "1"
inbox = Path(tempfile.mkdtemp(prefix="svf-inbox-"))


def drop(name, data):
    for f in inbox.glob("*.json"):
        f.unlink()
    p = inbox / name
    p.write_text(json.dumps(data))
    probs = validate.check(p)
    return p, probs


state.data["last_topics_date"] = ""
run.cmd_topics(state, scheduled=False)
assert state.data.get("claude_pending", {}).get("kind") == "topics", "topics not handed to Claude"
topics = {"kind": "topics", "id": "topics-1",
          "topics": [{"wiki_title": f"Claude Case {i}", "working_title": f"Claude Case {i}",
                      "hook": "h", "why_now": "w"} for i in range(3)]}
_, probs = drop("topics-1.json", topics)
assert not probs, probs
run.cmd_deliver(state, inbox)
job2 = state.latest_job("awaiting_topic")
assert job2 and job2 != job and "claude_pending" not in state.data

run.handle(state, {"kind": "button", "data": f"pick:{job2}:1"})
assert state.job(job2)["status"] == "writing", state.job(job2)["status"]
run.handle(state, {"kind": "text", "text": "hello?"})        # answered with "still writing", no crash
script = writer.fake_script(state.job(job2)["case_no"])
for sc in script["scenes"]:                                   # stretch to a realistic length for the checker
    sc["shots"] = sc["shots"] * 26
for sc in script["scenes"]:
    sc.pop("narration", None)
script["short"].pop("narration", None)
script["short"]["shots"] = script["short"]["shots"] * 3
delivery = {"kind": "script", "id": f"script-{job2}-1", "job": job2,
            "sources": [{"title": "a", "url": "https://a"}, {"title": "b", "url": "https://b"}],
            "script": script}
_, probs = drop("script.json", delivery)
print("validator on long script:", probs or "OK")
# render a short version so the test stays quick
delivery["script"] = writer.fake_script(state.job(job2)["case_no"])
drop("script.json", delivery)
run.cmd_deliver(state, inbox)
assert state.job(job2)["status"] == "awaiting_review", state.job(job2)["status"]
run.cmd_deliver(state, inbox)                                 # same file again → ignored
run.handle(state, {"kind": "text", "text": "make the ending darker"})
assert state.job(job2)["status"] == "writing" and state.job(job2)["pending_notes"]
run.handle(state, {"kind": "button", "data": f"gemrev:{job2}"})  # owner switches to Gemini
assert state.job(job2)["status"] == "awaiting_review"
assert claude.runs_left(state) == 5 - 3, claude.runs_left(state)
desc = run.build_description(run.load_json(run.case_dir(job2) / "script.json"),
                             run.load_json(run.case_dir(job2) / "meta.json"))
assert "Research: a — https://a" in desc
print("OK  Claude path: topics → script → revision → Gemini fallback")

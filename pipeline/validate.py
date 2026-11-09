"""Claude's helper inside the routine (see ROUTINE.md).

  python -m pipeline.validate --rules SCRIPT 004   writing rules + exact JSON format for a script
  python -m pipeline.validate --rules TOPICS       format for topic pitches + cases already used
  python -m pipeline.validate inbox/<file>.json    check a file before pushing it (prints OK or problems)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .core import CFG, State
from .writer import CH, STYLE_RULES, W, _script_schema, normalize


def _state() -> State:
    return State()


def rules(kind: str, job_id: str | None):
    st = _state()
    if kind == "TOPICS":
        used = sorted(st.used_titles() | {h["wiki_title"] for h in st.data["history"]})
        print(f"""Pitch 3 cases for "{CH['name']}" ({CH['niche']}).

Choose from the CANDIDATES in your run text (GitHub fetched them from Wikipedia, because this
environment can't reach Wikipedia). You may pitch another case only if you're sure of its exact
English Wikipedia article title. Each case MUST have its own English Wikipedia article,
be genuinely unresolved, have rich documented detail, be advertiser-friendly, and be at
least {CFG['research']['avoid_recent_years']} years old. Avoid cases centred on violence against children.
Mix one famous case with lesser-known ones. Check interest with web search.

Already used — do NOT pitch these:
{json.dumps(used, ensure_ascii=False)}

File format:
{{"kind": "topics", "id": "topics-<UTC yyyymmddHHMM>",
  "topics": [{{"wiki_title": "<exact Wikipedia article title>",
              "url": "https://en.wikipedia.org/wiki/<Article_title>",
              "working_title": "<YouTube title, under 65 characters, curiosity-driven, not a lie>",
              "hook": "<one sentence on why it's fascinating>",
              "why_now": "<one short reason it will perform>"}}, …3 items]}}""")
        return
    job = st.job(job_id.zfill(3))
    topic = job.get("topic") or {}
    print(STYLE_RULES)
    print(f"""
CASE FILE NUMBER: {job['case_no']}
TOPIC: {topic.get('wiki_title')}  —  {topic.get('url')}
WORKING TITLE: {topic.get('working_title')}
ANGLE: {topic.get('hook')}

RESEARCH: the full Wikipedia article is in your run text (GitHub fetched it, because this
environment can't reach Wikipedia). It is your main source. Then use web search for other
reliable sources (official records, established newspapers, archives) and open pages only from
the search results. If other sources can't be reached, write from the article alone — don't stop.
Only use facts you actually read. Where sources disagree, say so. List the Wikipedia article and
every other page you read in "sources".

The case's real photos are matched to sentences automatically — always set "image": -1.

{_script_schema(W['target_minutes'], W['short_seconds'], 0)}

File format: {{"kind": "script", "id": "script-{job_id.zfill(3)}-<UTC yyyymmddHHMM>", "job": "{job_id.zfill(3)}",
  "sources": [{{"title": "<page title>", "url": "<url>"}}],
  "script": <the JSON object described above>}}""")


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"Not valid JSON: {exc}"]
    kind = data.get("kind")
    if not data.get("id"):
        problems.append('Missing "id".')
    if kind == "topics":
        ts = data.get("topics") or []
        if len(ts) != 3:
            problems.append(f"Need exactly 3 topics, got {len(ts)}.")
        used = _state().used_titles()
        for i, t in enumerate(ts, 1):
            for k in ("wiki_title", "working_title", "hook"):
                if not str(t.get(k, "")).strip():
                    problems.append(f'Topic {i}: missing "{k}".')
            if t.get("wiki_title") in used:
                problems.append(f"Topic {i}: '{t.get('wiki_title')}' was already used.")
            if len(str(t.get("working_title", ""))) > 70:
                problems.append(f"Topic {i}: title is over 70 characters.")
    elif kind == "script":
        if not data.get("job"):
            problems.append('Missing "job".')
        if len(data.get("sources") or []) < 1:
            problems.append('List the pages you used in "sources" (at least the Wikipedia article).')
        raw = data.get("script") or {}
        for k in ("title", "thumbnail_text", "description", "tags", "scenes", "short"):
            if not raw.get(k):
                problems.append(f'script is missing "{k}".')
        if problems:
            return problems
        for n, sc in enumerate(raw["scenes"], 1):
            for m, sh in enumerate(sc.get("shots") or [], 1):
                if not isinstance(sh.get("search"), list) or len(sh["search"]) < 2:
                    problems.append(f"Scene {n} shot {m}: \"search\" needs 3 searches, specific → general.")
        if not all(sc.get("shots") for sc in raw["scenes"]):
            problems.append('Every scene needs a "shots" list.')
        s = normalize(json.loads(json.dumps(raw)))
        words = sum(len(sc["narration"].split()) for sc in s["scenes"])
        target = W["target_minutes"] * W["words_per_minute"]
        if not 0.7 * target <= words <= 1.4 * target:
            problems.append(f"Narration is {words} words; aim for about {target} (±30%).")
        if len(s["scenes"]) < 3:
            problems.append("Need at least 3 scenes.")
        if sum(1 for sc in s["scenes"] if sc.get("chapter")) < 3:
            problems.append("Mark at least 3 chapters (\"chapter\" on the first scene of each).")
        sw = len(s["short"]["narration"].split())
        target_sw = int(W["short_seconds"] * 2.3)
        if not 0.7 * target_sw <= sw <= 1.25 * target_sw:
            problems.append(f"Short is {sw} words; aim for about {target_sw}.")
        if len(s["short"]["shots"]) < 12:
            problems.append("Short needs at least 12 shots (a new picture every 2–4 seconds).")
        all_shots = [sh for sc in s["scenes"] for sh in sc["shots"]] + s["short"]["shots"]
        missing = sum(1 for sh in all_shots if len(sh.get("image_prompt", "")) < 25)
        if missing:
            problems.append(f"{missing} shots have no proper \"image_prompt\" (describe the picture for each sentence).")
        if not raw.get("title_card") or not raw.get("label") or not raw.get("end_line") or not raw.get("look"):
            problems.append('Fill in "look", "title_card", "label" and "end_line".')
        if len(raw["title"]) > 100:
            problems.append("Title is over 100 characters.")
        if len(str(raw["thumbnail_text"]).split()) > 3:
            problems.append("Thumbnail text must be 3 words or fewer.")
    elif kind == "error":
        if not data.get("message"):
            problems.append('An error file needs a "message".')
    else:
        problems.append('"kind" must be "topics", "script" or "error".')
    return problems


def main():
    args = sys.argv[1:]
    if args[:1] == ["--rules"]:
        rules(args[1].upper(), args[2] if len(args) > 2 else None)
        return
    if not args:
        print(__doc__)
        return
    probs = check(Path(args[0]))
    if probs:
        print("PROBLEMS — fix these and run again:")
        print("\n".join(f"- {p}" for p in probs))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()

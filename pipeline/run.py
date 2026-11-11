"""Entry point. GitHub Actions calls:  python -m pipeline.run <command>

  topics [--scheduled] [--wish "idea"]   find 3 cases and send them to Telegram
  handle                                 react to a Telegram button/message (payload in SVF_PAYLOAD)
  deliver <folder>                       use the topics/script files Claude pushed
  refresh-instagram                      print a refreshed Instagram token
"""
from __future__ import annotations

import argparse
import re
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import claude, publish, render, research, telegram, writer
from .core import CFG, FAKE, STATE_DIR, WORK_DIR, State, job_dir, load_json, log, now_local, save_json
from .stock import download_image, keywords, match
from .telegram import esc


def case_dir(job_id: str) -> Path:
    d = STATE_DIR / "cases" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── 1. Topics ────────────────────────────────────────────────────────────────

def _minutes_since(iso: str) -> float:
    try:
        return (now_local() - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9


def cmd_topics(state: State, scheduled: bool = False, wish: str | None = None, force_gemini: bool = False):
    today = now_local().date().isoformat()
    if scheduled:
        hour = int(CFG["channel"]["daily_topics_hour"])
        if now_local().hour < hour or state.data.get("last_topics_date") == today:
            log("Not time yet / already sent today — skipping.")
            return
        pend = state.data.get("claude_pending") or {}
        if pend.get("kind") == "topics" and pend.get("date") == today:
            if _minutes_since(pend.get("at")) < float(CFG.get("claude", {}).get("fallback_minutes", 50)):
                log("Claude is still researching today's topics — waiting.")
                return
            telegram.send("⏰ Claude didn't send today's topics in time, so Gemini is picking them instead.")
            state.data.pop("claude_pending", None)
            force_gemini = True
    cands = None
    if not force_gemini and CFG.get("claude", {}).get("use_for_topics", True) and claude.configured():
        # The routine's network can't reach Wikipedia, so GitHub gathers candidate cases for it.
        cands = research.candidates(state.used_titles(), query=wish)
        listing = "\n".join(json.dumps({"wiki_title": c["wiki_title"], "url": c["url"],
                                         "wikipedia_views_60d": c.get("views", 0),
                                         "summary": c["summary"][:700]}, ensure_ascii=False)
                            for c in cands)
        link, why = claude.fire(state, f"TOPICS\nwish: {wish or ''}\n\nCANDIDATES (from Wikipedia, "
                                       f"one JSON per line):\n{listing}", reserve=2)
        if link is not None:
            state.data["claude_pending"] = {"kind": "topics", "date": today, "wish": wish or "",
                                            "at": now_local().isoformat(timespec="seconds")}
            state.save()
            about = f" about <b>{esc(wish)}</b>" if wish else ""
            telegram.send(f"🧠 Claude is researching cases{about} and will send 3 ideas in about 10–15 minutes."
                          + (f"\n<a href=\"{link}\">Watch Claude work</a>" if link else ""))
            return
        if why:
            log(why)
    if wish:
        telegram.send(f"🔎 Looking for cases about <b>{esc(wish)}</b>…")
    if cands is None:
        cands = research.candidates(state.used_titles(), query=wish)
    if len(cands) < 3:
        telegram.send("I couldn't find enough well-documented cases for that. Try another idea, or send /topics.")
        return
    recent = [h["wiki_title"] for h in state.data["history"]]
    send_topics(state, writer.pitch_topics(cands, recent, wish), "Gemini")


def send_topics(state: State, topics: list[dict], by: str):
    job_id = state.new_job(topics)
    state.data["last_topics_date"] = now_local().date().isoformat()
    state.data.pop("claude_pending", None)
    state.job(job_id)["topics_by"] = by
    state.save()
    case_no = state.job(job_id)["case_no"]
    lines = [f"🗂 <b>Case file #{case_no:03d} — pick today's story</b> <i>(picked by {by})</i>\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"<b>{i}. {esc(t['working_title'])}</b>\n{esc(t['hook'])}\n"
                     f"<i>{esc(t.get('why_now', ''))}</i> · <a href=\"{t['url']}\">source</a>\n")
    lines.append("Tap a number to make that video, or just type your own idea.")
    telegram.send("\n".join(lines), [
        [(f"✅ {i}", f"pick:{job_id}:{i - 1}") for i in range(1, len(topics) + 1)],
        [("🔄 3 different ideas", f"new:{job_id}")],
    ])


# ── 2. Produce ───────────────────────────────────────────────────────────────

def _photos(images: list[dict], work: Path) -> list[Path | None]:
    out = []
    for i, im in enumerate(images):
        out.append(download_image(im["url"], work / f"photo{i}.jpg"))
    return out


def _job_kind(job: dict) -> tuple[str, str]:
    return job.get("kind", "case"), job.get("format", "both")


def _render_and_send(state: State, job_id: str, script: dict, images: list[dict], note: str):
    job = state.job(job_id)
    kind, fmt = _job_kind(job)
    work = job_dir(job_id)
    script = writer.normalize(script)   # also upgrades drafts written in the older format
    script.update({"kind": kind, "format": fmt})
    photos = _photos(images, work)
    pics = WORK_DIR / "images"
    publish.restore_images(job_id, pics)          # a revision reuses pictures that didn't change
    try:
        long = render.render_long(script, work, job["case_no"], photos) if fmt != "short" else None
        short = render.render_short(script, work, job["case_no"])
    except render.NoAIPictures as exc:
        return _ask_about_pictures(state, job_id, script, pics, work, note, exc)
    thumb = long["thumbnail"] if long else render.short_thumbnail(script, work, job["case_no"], short)
    files = [short["video"], thumb] + ([long["video"]] if long else [])
    bundle = publish.bundle_images(pics, work / "images.tar")
    if bundle:
        files.append(bundle)
    links = publish.save_draft(job_id, files, script["title"])
    pics_note = (long or short).get("images")
    note = f"{note}\n🖼 {pics_note}" if pics_note else note
    meta = load_json(case_dir(job_id) / "meta.json")
    meta.update({"chapters": long["chapters"] if long else [], "credits": (long or short)["credits"],
                 "links": links, "minutes": round((long or short)["seconds"] / 60, 1)})
    save_json(case_dir(job_id) / "meta.json", meta)
    job["status"] = "awaiting_review"
    job["revisions"] = job.get("revisions", 0)
    state.data["review_job"] = job_id
    state.save()

    what = "Short only" if fmt == "short" else "Video + Short"
    cap = (f"🎬 <b>{esc(script['title'])}</b>\n{note}\n"
           f"{what} · {meta['minutes']} min · #{job['case_no']:03d}\n\n"
           f"<b>Description</b>\n{esc(script['description'][:600])}")
    telegram.send_photo(thumb, cap)
    review_rows = [[("✅ Publish", f"pub:{job_id}"), ("🎞 New pictures", f"redo:{job_id}")],
                   [("🗑 Discard", f"drop:{job_id}")]]
    if long:
        prev = render.preview(long["video"], work / "preview.mp4")
        if not telegram.send_video(prev, "▶️ Preview (small copy). Full quality is saved for upload."):
            telegram.send(f"▶️ Watch the full video: <a href=\"{links['video.mp4']}\">video.mp4</a>")
    short_file = short["video"]
    if short_file.stat().st_size > 48 * 1024 * 1024:
        short_file = render.preview(short_file, work / "short_preview.mp4", vertical=True)
    if not telegram.send_video(short_file, "📱 Short / Reel" + (" (the whole video)" if not long else " version")):
        telegram.send(f"📱 Short / Reel: <a href=\"{links['short.mp4']}\">short.mp4</a>")
    where = "YouTube Shorts + Instagram" if not long else "YouTube + Instagram"
    full = (f"<a href=\"{links['video.mp4']}\">video</a> · " if long else "") + f"<a href=\"{links['short.mp4']}\">short</a>"
    telegram.send(
        "👀 <b>Your review</b>\n"
        f"• Tap <b>Publish</b> to post to {where}\n"
        "• Or <b>type your changes</b> (e.g. <i>“make the opening punchier and explain step 3 more simply”</i>) "
        "and I'll rewrite and re-render it\n"
        f"• Full quality: {full}", review_rows)


def _ask_about_pictures(state: State, job_id: str, script: dict, pics: Path, work: Path, note: str, exc):
    """AI pictures are the first choice. When they can't be made, keep the ones made so far and
    let the owner decide: wait for AI pictures, or use real photos + stock footage this time."""
    job = state.job(job_id)
    bundle = publish.bundle_images(pics, work / "images.tar")
    if bundle:
        publish.save_images(job_id, bundle, script["title"])
    job["status"] = "awaiting_pictures"
    job["pending_render_note"] = note
    state.save()
    have = exc.made + exc.reused
    telegram.send(
        f"🖼 <b>AI pictures aren't available right now</b> for <b>{esc(script['title'])}</b>\n"
        f"Reason: {esc(exc.reason)}.\n"
        + (f"{have} AI pictures are ready and saved, so they won't be made again.\n" if have else "")
        + "\nWhat would you like to do?\n"
        "• <b>Try AI pictures again</b> (best after the allowance resets)\n"
        "• <b>Use real photos + stock</b>: finish now with real case photos and stock footage "
        "for the sentences that have no AI picture",
        [[("🔁 Try AI pictures again", f"aipics:{job_id}")],
         [("📷 Use real photos + stock", f"stockpics:{job_id}")],
         [("🗑 Discard", f"drop:{job_id}")]])


def cmd_rerender(state: State, job_id: str, fallback: bool):
    """Render the saved script again after the owner answered the AI-pictures question."""
    job = state.job(job_id)
    if job["status"] != "awaiting_pictures":
        return telegram.send(f"Case #{job['case_no']:03d} is {job['status'].replace('_', ' ')}, "
                             "so there's nothing waiting for pictures.")
    script = load_json(case_dir(job_id) / "script.json")
    images = load_json(case_dir(job_id) / "meta.json").get("images", [])
    note = job.get("pending_render_note") or "Here's your draft."
    job["status"] = "producing"
    state.save()
    if fallback:
        script["picture_fallback"] = True     # this render only: the next one tries AI pictures first again
        telegram.send("📷 Finishing with AI pictures where we have them, then real photos and stock "
                      "footage. New version in ~20–30 minutes.")
    else:
        telegram.send("🔁 Trying AI pictures again. New version in ~20–30 minutes.")
    state.data["retry_payload"] = {"kind": "button", "data": f"{'stockpics' if fallback else 'aipics'}:{job_id}"}
    _render_and_send(state, job_id, script, images, note)
    if state.job(job_id)["status"] == "awaiting_review":
        job.pop("pending_render_note", None)
        state.save()


def _article_block(title: str, limit: int = 50000) -> str:
    """The Wikipedia article text, fetched here on GitHub (the routine can't reach Wikipedia)."""
    try:
        a = research.article(title)
    except Exception as exc:  # noqa: BLE001
        log("Couldn't fetch article for Claude:", exc)
        return f"WIKIPEDIA ARTICLE: {title} (couldn't be fetched — research it with web search)"
    imgs = research.free_images(a["title"])
    photos = "\n".join(f"- {im['caption'] or im['file']}" for im in imgs) or "- none"
    return (f"WIKIPEDIA ARTICLE: {a['title']} — {a['url']}\n"
            f"Free case photos the video will use (they're placed automatically):\n{photos}\n\n"
            f"ARTICLE TEXT:\n{a['text'][:limit]}")


def _custom_material(job: dict) -> tuple[str, dict, list[dict], list[dict]]:
    """For a custom topic: (text block for Claude, source dict for Gemini, sources, free photos)."""
    sources = research.custom_sources(job["topic"]["request"])
    wiki = next((x for x in sources if x.get("wiki")), None)
    images = research.free_images(wiki["wiki_title"]) if wiki else []
    block = research.sources_block(sources)
    photos = "\n".join(f"- {im['caption'] or im['file']}" for im in images) or "- none"
    text = (f"OWNER'S REQUEST: {job['topic']['request']}\nFORMAT: "
            f"{'SHORT ONLY' if job.get('format') == 'short' else 'FULL VIDEO + SHORT'}\n"
            f"Free photos the video will use (placed automatically):\n{photos}\n\n{block}")
    return text, {"text": block, "url": wiki["url"] if wiki else "", "title": wiki["title"] if wiki else ""}, sources, images


def cmd_produce(state: State, job_id: str, index: int, force_gemini: bool = False):
    job = state.job(job_id)
    allowed = {"awaiting_topic"} | ({"writing"} if force_gemini else set())
    if job["status"] not in allowed:
        telegram.send(f"Case #{job['case_no']:03d} is already {job['status'].replace('_', ' ')}.")
        return
    topic = job["topics"][index]
    job.update({"status": "producing", "topic": topic, "topic_index": index})
    state.save()
    kind, fmt = _job_kind(job)
    custom = None
    if kind == "custom":
        telegram.send(f"🔎 Researching <b>{esc(topic['request'])}</b>…")
        custom = _custom_material(job)
    if not force_gemini and claude.configured():
        brief = custom[0] if custom else _article_block(topic["wiki_title"])
        link, why = claude.fire(state, f"SCRIPT {job_id}\n\n" + brief)
        if link is not None:
            job.update({"status": "writing", "writer": "Claude",
                        "requested_at": now_local().isoformat(timespec="seconds")})
            state.save()
            telegram.send(
                f"🎬 {'On it' if custom else 'Great choice'}: <b>{esc(topic['working_title'])}</b>\n"
                f"🧠 Claude is researching and writing the {'Short' if fmt == 'short' else 'script'} (about 10–20 minutes). "
                "Then the voice and video take about 25 minutes. I'll send the preview here."
                + (f"\n<a href=\"{link}\">Watch Claude work</a>" if link else ""),
                [[("⚡ Use Gemini instead", f"gem:{job_id}:{index}")]])
            return
        if why:
            telegram.send(f"ℹ️ {esc(why)} — Gemini will write this one.")
    telegram.send(f"🎬 {'On it' if custom else 'Great choice'}: <b>{esc(topic['working_title'])}</b>\n"
                  "Researching, writing, recording the voice and editing. This usually takes "
                  "20–35 minutes — I'll send the preview here.")
    job.update({"status": "producing", "writer": "Gemini"})
    if custom:
        _, source, sources, images = custom
        extra = [{"title": x["title"], "url": x["url"]} for x in sources if x.get("url")]
    else:
        source = research.article(topic["wiki_title"])
        images = research.free_images(source["title"])
        extra = []
    script = writer.write_script(topic, source, images, job["case_no"], kind, fmt)
    _check_script(script, fmt)
    save_json(case_dir(job_id) / "script.json", script)
    save_json(case_dir(job_id) / "meta.json", {"source_url": source["url"], "source_title": source["title"],
                                                "images": images, "extra_sources": extra})
    _render_and_send(state, job_id, script, images, "Here's your draft (written by Gemini).")


def _check_script(script: dict, fmt: str = "both"):
    need = ["title", "description", "short"] + ([] if fmt == "short" else ["scenes"])
    missing = [k for k in need if not script.get(k)]
    if missing or (fmt != "short" and len(script["scenes"]) < 3) or len(script["short"].get("shots", [])) < 3:
        raise RuntimeError(f"The AI returned an incomplete script (missing {missing}). Tap Retry.")


def cmd_revise(state: State, job_id: str, feedback: str | None, force_gemini: bool = False):
    job = state.job(job_id)
    script = load_json(case_dir(job_id) / "script.json")
    meta = load_json(case_dir(job_id) / "meta.json")
    images = meta.get("images", [])
    if feedback and not force_gemini and claude.configured():
        brief = (_custom_material(job)[0] if job.get("kind") == "custom"
                 else _article_block(meta["source_title"], limit=40000))
        link, why = claude.fire(state, f"REVISE {job_id}\n{feedback}\n\n" + brief)
        if link is not None:
            job.update({"status": "writing", "writer": "Claude", "pending_notes": feedback,
                        "requested_at": now_local().isoformat(timespec="seconds")})
            state.save()
            telegram.send(f"✏️ Claude is applying your notes:\n<i>{esc(feedback)}</i>\n"
                          "Rewrite in about 10 minutes, then about 25 minutes for the video."
                          + (f"\n<a href=\"{link}\">Watch Claude work</a>" if link else ""),
                          [[("⚡ Use Gemini instead", f"gemrev:{job_id}")]])
            return
        if why:
            telegram.send(f"ℹ️ {esc(why)} — Gemini will apply these notes.")
    job["status"] = "producing"
    job["revisions"] = job.get("revisions", 0) + 1
    job.pop("pending_notes", None)
    state.save()
    if feedback:
        telegram.send(f"✏️ Applying your notes:\n<i>{esc(feedback)}</i>\nNew version in ~20–35 minutes.")
        kind, fmt = _job_kind(job)
        source = _custom_material(job)[1] if kind == "custom" else research.article(meta["source_title"])
        script = writer.revise_script(script, feedback, source, images, kind, fmt)
        _check_script(script, fmt)
        save_json(case_dir(job_id) / "script.json", script)
        note = f"Revision {job['revisions']} — your notes applied (Gemini)."
    else:
        script["picture_salt"] = f"v{job['revisions']}"   # new AI pictures, not the cached ones
        save_json(case_dir(job_id) / "script.json", script)
        telegram.send("🎞 Same script, new pictures and footage. New version in ~20–30 minutes.")
        note = f"Revision {job['revisions']} — new footage."
    _render_and_send(state, job_id, script, images, note)


# ── 2b. Claude's deliveries ──────────────────────────────────────────────────

def auto_place_photos(script: dict, images: list[dict]):
    """Put each real case photo on the sentence that talks about what it shows."""
    shots = [sh for sc in script["scenes"] for sh in sc["shots"]]
    taken = {sh.get("image") for sh in shots if isinstance(sh.get("image"), int) and sh["image"] >= 0}
    for i, im in enumerate(images):
        if i in taken:
            continue
        about = f"{im.get('caption', '')} {im.get('file', '').replace('File:', '').rsplit('.', 1)[0]}"
        kws = [k for k in keywords(about.replace("_", " ")) if len(k) > 3][:12]
        best = max(((match({"tags": sh["text"]}, kws), n) for n, sh in enumerate(shots)
                    if sh.get("image", -1) < 0), default=(0, -1))
        if kws and best[0] * len(kws) >= 2:   # at least two shared words
            shots[best[1]]["image"] = i


def _topic_from_claude(t: dict) -> dict:
    title = t["wiki_title"].strip()
    return {"wiki_title": title,
            "url": t.get("url") or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            "working_title": t.get("working_title") or title, "hook": t.get("hook", ""),
            "why_now": t.get("why_now", ""), "summary": t.get("summary", "")}


def cmd_deliver(state: State, folder: Path):
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        log("Nothing delivered.")
        return
    done = state.data.setdefault("delivered", [])
    for f in files:
        data = load_json(f)
        did = str(data.get("id") or f.stem)
        if did in done:
            log(f"{did} already used — skipping")
            continue
        done.append(did)
        del done[:-200]
        state.save()
        kind = data.get("kind")
        log(f"Claude delivered {kind}: {did}")
        if kind == "topics":
            topics = [_topic_from_claude(t) for t in data.get("topics", [])[:3]]
            if len(topics) < 3:
                raise RuntimeError("Claude sent fewer than 3 topics.")
            send_topics(state, topics, "Claude")
        elif kind == "script":
            _deliver_script(state, data)
        elif kind == "error":
            job_id = str(data.get("job") or "")
            job = state.data["jobs"].get(job_id)
            rows = None
            if job and job["status"] == "writing":
                rows = [[("⚡ Use Gemini instead",
                          f"gemrev:{job_id}" if job.get("pending_notes") else f"gem:{job_id}:{job.get('topic_index', 0)}")]]
            elif (state.data.get("claude_pending") or {}).get("kind") == "topics":
                state.data.pop("claude_pending", None)
                rows = [[("⚡ Topics from Gemini", "gemtopics:0")]]
            state.save()
            telegram.send(f"⚠️ Claude couldn't finish: {esc(str(data.get('message', 'no reason given')))}", rows)
        else:
            raise RuntimeError(f"Unknown delivery kind: {kind}")


def _deliver_script(state: State, data: dict):
    job_id = str(data["job"]).zfill(3)
    job = state.job(job_id)
    if job["status"] != "writing":
        telegram.send(f"ℹ️ Claude finished case #{job['case_no']:03d}, but it's already "
                      f"{job['status'].replace('_', ' ')} — I kept the current version.")
        return
    script = writer.normalize(data["script"])
    _check_script(script, job.get("format", "both"))
    revision = bool(job.get("pending_notes")) and (case_dir(job_id) / "script.json").exists()
    topic = job["topic"]
    if revision:
        meta = load_json(case_dir(job_id) / "meta.json")
        images = meta.get("images", [])
        job["revisions"] = job.get("revisions", 0) + 1
        note = f"Revision {job['revisions']} — your notes applied by Claude."
    else:
        images = research.free_images(topic["wiki_title"]) if topic.get("wiki_title") else []
        meta = {"source_url": topic.get("url", ""), "source_title": topic.get("wiki_title", ""), "images": images}
        note = ("Here's your Short, researched and written by Claude." if job.get("format") == "short"
                else "Here's your draft, researched and written by Claude.")
    meta["extra_sources"] = [s for s in data.get("sources", []) if isinstance(s, dict) and s.get("url")][:12]
    auto_place_photos(script, images)
    save_json(case_dir(job_id) / "script.json", script)
    save_json(case_dir(job_id) / "meta.json", meta)
    job.pop("pending_notes", None)
    job["status"] = "producing"
    state.save()
    telegram.send(f"🧠 Claude's script is in: <b>{esc(script['title'])}</b>\n"
                  "Recording the voice and editing the video now (about 25 minutes).")
    try:
        _render_and_send(state, job_id, script, images, note)
    except Exception:
        job["status"] = "awaiting_review"
        state.data["retry_payload"] = {"kind": "button", "data": f"redo:{job_id}"}
        state.save()
        raise


# ── 3. Publish ───────────────────────────────────────────────────────────────

def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def build_description(script: dict, meta: dict) -> str:
    parts = [script["description"].strip()]
    if meta.get("chapters"):
        parts.append("⏱ Chapters\n" + "\n".join(f"{_fmt_ts(t)} {n}" for t, n in meta["chapters"]))
    src = ["📁 Sources"]
    if meta.get("source_title") and "wikipedia.org" in meta.get("source_url", ""):
        src.append(f"Based on the Wikipedia article “{meta['source_title']}” — {meta['source_url']} "
                   "(text licensed CC BY-SA 4.0).")
    for x in meta.get("extra_sources", [])[:10]:
        if x["url"] != meta.get("source_url"):
            src.append(f"Research: {x.get('title', x['url'])} — {x['url']}")
    for im in meta.get("images", []):
        src.append(f"Photo: {im['file'].replace('File:', '')} by {im['artist']} ({im['license']}) {im['page']}")
    if meta.get("credits"):
        simple = [c for c in meta["credits"] if "\u2014" not in c]
        licensed = [c for c in meta["credits"] if "\u2014" in c]
        if simple:
            src.append("Stock footage: " + ", ".join(simple[:25]))
        src += [f"Image: {c}" for c in licensed[:20]]
    src.append("Narration uses an AI voice; pictures are AI-generated illustrations."
               + (" Theories discussed are unproven." if script.get("kind", "case") == "case" else ""))
    parts.append("\n".join(src))
    parts.append(" ".join(script.get("hashtags", [])))
    return "\n\n".join(parts)


def cmd_publish(state: State, job_id: str):
    job = state.job(job_id)
    if job["status"] == "published":
        telegram.send("This one is already published ✅")
        return
    script = load_json(case_dir(job_id) / "script.json")
    meta = load_json(case_dir(job_id) / "meta.json")
    done = job.setdefault("published", {})
    job["status"] = "publishing"
    state.save()
    telegram.send("🚀 Publishing… I'll send the links when it's live.")
    drafts = publish.load_draft(job_id, job_dir(job_id) / "draft")
    report, problems = [], []

    short_only = job.get("format") == "short"
    if short_only:
        done.setdefault("youtube", {"skipped": True})   # there is no long video
    if "youtube" not in done:
        try:
            res = publish.youtube_upload(drafts / "video.mp4", script["title"], build_description(script, meta),
                                         script.get("tags", []), drafts / "thumbnail.jpg")
            done["youtube"] = res
            state.save()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"YouTube: {exc}")
    if "youtube" in done and not short_only:
        r = done["youtube"]
        report.append(f"▶️ YouTube: {r['url']} ({r['privacy']})")
        if r.get("locked") and not done.get("locked_notice"):
            done["locked_notice"] = True
            telegram.send(
                "🔒 YouTube kept this upload <b>private</b> because your free API audit isn't approved yet "
                "(SETUP.md, step 9). Open YouTube Studio → Content and try switching it to Public. "
                f"If Studio won't allow it, delete that copy and upload the <a href=\"{meta['links']['video.mp4']}\">"
                "full video</a> yourself with the text below.")
            telegram.send(f"<b>Title</b>\n<code>{esc(script['title'])}</code>")
            telegram.send(f"<b>Description</b>\n<code>{esc(build_description(script, meta))[:3800]}</code>")
            telegram.send(f"<b>Tags</b>\n<code>{esc(', '.join(script.get('tags', [])))}</code>")

    sh = script["short"]
    hashtags = " ".join(script.get("hashtags", []))
    if (short_only or CFG["publish"]["youtube"].get("also_upload_short")) and "youtube_short" not in done:
        try:
            if short_only:
                desc = f"{build_description(script, meta)} #shorts"
            else:
                desc = f"{sh['caption']}\n\nFull video: {done.get('youtube', {}).get('url', '')}\n\n{hashtags} #shorts"
            done["youtube_short"] = publish.youtube_upload(drafts / "short.mp4", f"{script['title'][:88]} #shorts",
                                                           desc, script.get("tags", []))
            state.save()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"YouTube Short: {exc}")
    if "youtube_short" in done:
        report.append(f"📱 YouTube Short: {done['youtube_short']['url']}")

    if CFG["publish"]["instagram"].get("enabled") and "instagram" not in done:
        try:
            more = "" if short_only else f"\n\nFull story on YouTube: {CFG['channel']['handle']}"
            cap = f"{sh['caption']}{more}\n\n{hashtags}"
            done["instagram"] = publish.instagram_reel(meta["links"]["short.mp4"], cap)
            state.save()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Instagram: {exc}")
    if "instagram" in done:
        report.append(f"📸 Instagram Reel: {done['instagram']['url']}")

    if problems:
        job["status"] = "awaiting_review"
        state.save()
        telegram.send("⚠️ <b>Partly published</b>\n" + "\n".join(report) + "\n\n" + "\n".join(problems) +
                      "\n\nTap Retry to try the missing parts again (finished parts won't be re-posted).",
                      [[("🔁 Retry publish", f"pub:{job_id}")]])
        if any(p.startswith("Instagram") for p in problems):
            telegram.send_video(drafts / "short.mp4", "Here's the Reel file in case you'd rather post it by hand.")
        return
    job["status"] = "published"
    state.data["history"].append({"wiki_title": job["topic"].get("wiki_title") or job["topic"].get("request", ""),
                                  "title": script["title"], "kind": job.get("kind", "case"),
                                  "case_no": job["case_no"], "date": now_local().date().isoformat(),
                                  **{k: v.get("url") for k, v in done.items() if isinstance(v, dict) and v.get("url")}})
    state.data.pop("review_job", None)
    state.save()
    publish.mark_published(job_id, "\n".join(report))
    telegram.send(f"✅ <b>#{job['case_no']:03d} is live!</b>\n" + "\n".join(report))


# ── 4. Telegram router ───────────────────────────────────────────────────────

HELP = ("<b>Commands</b>\n"
        "/video <i>topic</i> — a researched video on any topic, plus a Short\n"
        "/short <i>topic</i> — only a Short (70–100 s) on any topic\n"
        "/topics — 3 new mystery case ideas now\n/status — what's in progress\n/help — this message\n\n"
        "Examples:\n<code>/video how the StoryVaultFiles pipeline works</code>\n"
        "<code>/short the history of Morse code</code>\n\n"
        "While a video is waiting for review, any message you type is treated as change notes. "
        "Otherwise I'll ask what you want to make from your message.")


REQ_PREFIX = re.compile(
    r"^(please\s+)?(can you\s+)?(make|create|generate|produce|do|give me|i want|build)(\s+me)?\s+"
    r"(a|an|one)?\s*(only\s+|just\s+)?(quick\s+|full\s+|long\s+)?(short|reel|video|explainer)?s?\s*"
    r"(video\s+)?(only\s+)?(on|about|explaining|that explains|of|for)?\s*", re.I)


def _parse_request(text: str) -> tuple[str | None, str]:
    """('short'|'both'|None, topic). None = unclear, so ask with buttons."""
    low = text.lower().strip()
    for cmd, fmt in (("/short", "short"), ("/video", "both")):
        if low.startswith(cmd):
            return fmt, text[len(cmd):].strip(" :-")
    m = REQ_PREFIX.match(text)
    if m and m.group(3):
        fmt = "short" if re.search(r"\b(shorts?|reels?)\b", low) else "both"
        return fmt, text[m.end():].strip(" .:-") or text
    return None, text


def cmd_custom(state: State, request: str, fmt: str):
    request = request.strip()
    if len(request) < 4:
        return telegram.send("Tell me the topic too, e.g. <code>/video how the StoryVaultFiles pipeline works</code>")
    title = request[0].upper() + request[1:]
    topic = {"wiki_title": "", "url": "", "working_title": title[:70], "hook": "", "request": request}
    job_id = state.new_job([topic])
    state.job(job_id).update({"kind": "custom", "format": fmt, "topics_by": "you"})
    state.data.pop("pending_request", None)
    state.save()
    cmd_produce(state, job_id, 0)


def _ask_what_to_make(state: State, text: str):
    state.data["pending_request"] = text[:500]
    state.save()
    telegram.send(f"What should I make from <i>“{esc(text[:200])}”</i>?", [
        [("🎬 Video + Short", "req:both"), ("📱 Short only", "req:short")],
        [("🔎 3 mystery cases about it", "req:cases")]])


def cmd_status(state: State):
    rows = [f"#{v['case_no']:03d} · {v['status'].replace('_', ' ')} · "
            f"{esc(v.get('topic', {}).get('working_title', 'choosing topic'))}"
            for k, v in sorted(state.data["jobs"].items())[-8:]]
    extra = ""
    if claude.configured():
        extra = f"\n\n🧠 Claude runs left today: {max(claude.runs_left(state), 0)}"
    telegram.send("📋 <b>Recent cases</b>\n" + ("\n".join(rows) or "Nothing yet.") + extra)


def handle(state: State, payload: dict):
    try:
        return _handle(state, payload)
    except KeyError as exc:
        if "not found" in str(exc):
            return telegram.send("That button belongs to an older case that's been cleared. "
                                 "Send /topics for new ideas, or /video or /short with a topic.")
        raise


def _handle(state: State, payload: dict):
    kind = payload.get("kind")
    if kind == "button":
        data = payload.get("data", "")
        action, _, rest = data.partition(":")
        if action == "retry":
            failed = state.data.get("last_failed")
            if not failed:
                telegram.send("Nothing to retry.")
                return
            return _handle(state, failed)
        if action == "req":
            req = state.data.pop("pending_request", "")
            if not req:
                return telegram.send("That request has expired. Send it again, or use /video or /short.")
            if rest == "cases":
                pend = state.latest_job("awaiting_topic")
                if pend:
                    state.job(pend)["status"] = "skipped"
                return cmd_topics(state, wish=req)
            return cmd_custom(state, _parse_request(req)[1], "short" if rest == "short" else "both")
        job_id = rest.split(":")[0]
        if action == "pick":
            return cmd_produce(state, job_id, int(rest.split(":")[1]))
        if action == "gem":
            return cmd_produce(state, job_id, int(rest.split(":")[1]), force_gemini=True)
        if action == "gemrev":
            job = state.job(job_id)
            if job["status"] != "writing":
                return telegram.send(f"Case #{job['case_no']:03d} is already {job['status'].replace('_', ' ')}.")
            return cmd_revise(state, job_id, job.get("pending_notes"), force_gemini=True)
        if action == "gemtopics":
            state.data.pop("claude_pending", None)
            return cmd_topics(state, force_gemini=True)
        if action == "new":
            if job_id in state.data["jobs"]:
                state.data["jobs"][job_id]["status"] = "skipped"
            return cmd_topics(state)
        if action == "pub":
            return cmd_publish(state, job_id)
        if action == "redo":
            return cmd_revise(state, job_id, None)
        if action in ("aipics", "stockpics"):
            return cmd_rerender(state, job_id, fallback=action == "stockpics")
        if action == "drop":
            state.job(job_id)["status"] = "discarded"
            state.data.pop("review_job", None)
            state.save()
            return telegram.send("🗑 Discarded. Send /topics for new ideas, or wait for tomorrow's.")
        return telegram.send("I didn't understand that button. Send /help.")

    text = (payload.get("text") or "").strip()
    if not text:
        return
    low = text.lower()
    if low.startswith("/start") or low.startswith("/help"):
        return telegram.send(HELP)
    if low.startswith("/topics"):
        return cmd_topics(state)
    if low.startswith("/status"):
        return cmd_status(state)
    if low.startswith(("/video", "/short")):
        fmt, topic = _parse_request(text)
        return cmd_custom(state, topic, fmt)
    writing = state.latest_job("writing")
    if writing:
        job = state.job(writing)
        btn = f"gemrev:{writing}" if job.get("pending_notes") else f"gem:{writing}:{job.get('topic_index', 0)}"
        return telegram.send(f"✍️ Claude is still writing case #{job['case_no']:03d}. "
                             "I'll send it as soon as it's ready.", [[("⚡ Use Gemini instead", btn)]])
    review = state.data.get("review_job")
    if review and state.data["jobs"].get(review, {}).get("status") == "awaiting_review":
        return cmd_revise(state, review, text)
    pending = state.latest_job("awaiting_topic")
    if pending and low in {"1", "2", "3"} and state.job(pending).get("kind", "case") == "case":
        return cmd_produce(state, pending, int(low) - 1)
    fmt, topic = _parse_request(text)
    if fmt:
        return cmd_custom(state, topic, fmt)
    return _ask_what_to_make(state, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["topics", "handle", "deliver", "refresh-instagram"])
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--scheduled", action="store_true")
    ap.add_argument("--wish")
    args = ap.parse_args()

    if args.command == "refresh-instagram":
        print(publish.refresh_instagram_token())
        return

    state = State()
    payload = {"kind": "command", "text": "/topics"}
    try:
        if args.command == "topics":
            cmd_topics(state, scheduled=args.scheduled, wish=args.wish)
        elif args.command == "deliver":
            payload = {"kind": "command", "text": "/status"}
            cmd_deliver(state, Path(args.folder or "inbox"))
        else:
            payload = json.loads(os.environ.get("SVF_PAYLOAD") or "{}")
            log("Payload:", payload)
            handle(state, payload)
        state.data.pop("last_failed", None)
        state.save()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        # put a stuck job back so the buttons work again
        for v in state.data["jobs"].values():
            if v["status"] == "producing":
                v["status"] = ("awaiting_pictures" if v.get("pending_render_note")
                               else "awaiting_review" if "revisions" in v else "awaiting_topic")
            if v["status"] == "publishing":
                v["status"] = "awaiting_review"
        state.data["last_failed"] = state.data.pop("retry_payload", None) or payload
        state.save()
        try:
            telegram.send(f"⚠️ Something went wrong:\n<code>{esc(str(exc))[:900]}</code>",
                          [[("🔁 Retry", "retry:last")]])
        except Exception:  # noqa: BLE001
            pass
        sys.exit(0 if FAKE else 1)


if __name__ == "__main__":
    main()

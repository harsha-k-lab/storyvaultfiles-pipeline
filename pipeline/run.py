"""Entry point. GitHub Actions calls:  python -m pipeline.run <command>

  topics [--scheduled] [--wish "idea"]   find 3 cases and send them to Telegram
  handle                                 react to a Telegram button/message (payload in SVF_PAYLOAD)
  refresh-instagram                      print a refreshed Instagram token
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from . import publish, render, research, telegram, writer
from .core import CFG, FAKE, STATE_DIR, State, job_dir, load_json, log, now_local, save_json
from .stock import download_image
from .telegram import esc


def case_dir(job_id: str) -> Path:
    d = STATE_DIR / "cases" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── 1. Topics ────────────────────────────────────────────────────────────────

def cmd_topics(state: State, scheduled: bool = False, wish: str | None = None):
    today = now_local().date().isoformat()
    if scheduled:
        hour = int(CFG["channel"]["daily_topics_hour"])
        if now_local().hour < hour or state.data.get("last_topics_date") == today:
            log("Not time yet / already sent today — skipping.")
            return
    if wish:
        telegram.send(f"🔎 Looking for cases about <b>{esc(wish)}</b>…")
    cands = research.candidates(state.used_titles(), query=wish)
    if len(cands) < 3:
        telegram.send("I couldn't find enough well-documented cases for that. Try another idea, or send /topics.")
        return
    recent = [h["wiki_title"] for h in state.data["history"]]
    topics = writer.pitch_topics(cands, recent, wish)
    job_id = state.new_job(topics)
    state.data["last_topics_date"] = today
    state.save()
    case_no = state.job(job_id)["case_no"]
    lines = [f"🗂 <b>Case file #{case_no:03d} — pick today's story</b>\n"]
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


def _render_and_send(state: State, job_id: str, script: dict, images: list[dict], note: str):
    job = state.job(job_id)
    work = job_dir(job_id)
    script = writer.normalize(script)   # also upgrades drafts written in the older format
    photos = _photos(images, work)
    long = render.render_long(script, work, job["case_no"], photos)
    short = render.render_short(script, work)
    prev = render.preview(long["video"], work / "preview.mp4")
    links = publish.save_draft(job_id, [long["video"], short["video"], long["thumbnail"]], script["title"])
    meta = load_json(case_dir(job_id) / "meta.json")
    meta.update({"chapters": long["chapters"], "credits": long["credits"], "links": links,
                 "minutes": round(long["seconds"] / 60, 1)})
    save_json(case_dir(job_id) / "meta.json", meta)
    job["status"] = "awaiting_review"
    job["revisions"] = job.get("revisions", 0)
    state.data["review_job"] = job_id
    state.save()

    cap = (f"🎬 <b>{esc(script['title'])}</b>\n{note}\n"
           f"Length: {meta['minutes']} min · Case #{job['case_no']:03d}\n\n"
           f"<b>Description</b>\n{esc(script['description'][:600])}")
    telegram.send_photo(long["thumbnail"], cap)
    review_rows = [[("✅ Publish", f"pub:{job_id}"), ("🎞 New footage", f"redo:{job_id}")],
                   [("🗑 Discard", f"drop:{job_id}")]]
    sent = telegram.send_video(prev, "▶️ Preview (small copy). Full quality is saved for upload.")
    if not sent:
        telegram.send(f"▶️ Watch the full video: <a href=\"{links['video.mp4']}\">video.mp4</a>")
    short_file = short["video"]
    if short_file.stat().st_size > 48 * 1024 * 1024:
        short_file = render.preview(short_file, work / "short_preview.mp4", vertical=True)
    if not telegram.send_video(short_file, "📱 Short / Reel version"):
        telegram.send(f"📱 Short / Reel: <a href=\"{links['short.mp4']}\">short.mp4</a>")
    telegram.send(
        "👀 <b>Your review</b>\n"
        "• Tap <b>Publish</b> to post to YouTube + Instagram\n"
        "• Or <b>type your changes</b> (e.g. <i>“make the intro creepier and shorten chapter 2”</i>) "
        "and I'll rewrite and re-render it\n"
        f"• Full quality: <a href=\"{links['video.mp4']}\">video</a> · "
        f"<a href=\"{links['short.mp4']}\">short</a>", review_rows)


def cmd_produce(state: State, job_id: str, index: int):
    job = state.job(job_id)
    if job["status"] != "awaiting_topic":
        telegram.send(f"Case #{job['case_no']:03d} is already {job['status'].replace('_', ' ')}.")
        return
    topic = job["topics"][index]
    job.update({"status": "producing", "topic": topic})
    state.save()
    telegram.send(f"🎬 Great choice: <b>{esc(topic['working_title'])}</b>\n"
                  "Researching, writing, recording the voice and editing. This usually takes "
                  "20–35 minutes — I'll send the preview here.")
    source = research.article(topic["wiki_title"])
    images = research.free_images(source["title"])
    script = writer.write_script(topic, source, images, job["case_no"])
    _check_script(script)
    save_json(case_dir(job_id) / "script.json", script)
    save_json(case_dir(job_id) / "meta.json", {"source_url": source["url"], "source_title": source["title"],
                                                "images": images})
    _render_and_send(state, job_id, script, images, "Here's your draft.")


def _check_script(script: dict):
    missing = [k for k in ("title", "description", "scenes", "short") if not script.get(k)]
    if missing or len(script["scenes"]) < 3:
        raise RuntimeError(f"The AI returned an incomplete script (missing {missing}). Tap Retry.")


def cmd_revise(state: State, job_id: str, feedback: str | None):
    job = state.job(job_id)
    script = load_json(case_dir(job_id) / "script.json")
    meta = load_json(case_dir(job_id) / "meta.json")
    images = meta.get("images", [])
    job["status"] = "producing"
    job["revisions"] = job.get("revisions", 0) + 1
    state.save()
    if feedback:
        telegram.send(f"✏️ Applying your notes:\n<i>{esc(feedback)}</i>\nNew version in ~20–35 minutes.")
        source = research.article(meta["source_title"])
        script = writer.revise_script(script, feedback, source, images)
        _check_script(script)
        save_json(case_dir(job_id) / "script.json", script)
        note = f"Revision {job['revisions']} — your notes applied."
    else:
        telegram.send("🎞 Same script, fresh footage. New version in ~20–30 minutes.")
        note = f"Revision {job['revisions']} — new footage."
    _render_and_send(state, job_id, script, images, note)


# ── 3. Publish ───────────────────────────────────────────────────────────────

def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def build_description(script: dict, meta: dict) -> str:
    parts = [script["description"].strip()]
    if meta.get("chapters"):
        parts.append("⏱ Chapters\n" + "\n".join(f"{_fmt_ts(t)} {n}" for t, n in meta["chapters"]))
    src = [f"📁 Sources\nBased on the Wikipedia article “{meta['source_title']}” — {meta['source_url']} "
           "(text licensed CC BY-SA 4.0)."]
    for im in meta.get("images", []):
        src.append(f"Photo: {im['file'].replace('File:', '')} by {im['artist']} ({im['license']}) {im['page']}")
    if meta.get("credits"):
        simple = [c for c in meta["credits"] if "\u2014" not in c]
        licensed = [c for c in meta["credits"] if "\u2014" in c]
        if simple:
            src.append("Stock footage: " + ", ".join(simple[:25]))
        src += [f"Image: {c}" for c in licensed[:20]]
    src.append("Narration uses an AI voice. Theories discussed are unproven.")
    parts.append("\n".join(src))
    parts.append(" ".join(script.get("hashtags", [])))
    return "\n\n".join(parts)


def cmd_publish(state: State, job_id: str):
    job = state.job(job_id)
    if job["status"] == "published":
        telegram.send("This case is already published ✅")
        return
    script = load_json(case_dir(job_id) / "script.json")
    meta = load_json(case_dir(job_id) / "meta.json")
    done = job.setdefault("published", {})
    job["status"] = "publishing"
    state.save()
    telegram.send("🚀 Publishing… I'll send the links when it's live.")
    drafts = publish.load_draft(job_id, job_dir(job_id) / "draft")
    report, problems = [], []

    if "youtube" not in done:
        try:
            res = publish.youtube_upload(drafts / "video.mp4", script["title"], build_description(script, meta),
                                         script.get("tags", []), drafts / "thumbnail.jpg")
            done["youtube"] = res
            state.save()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"YouTube: {exc}")
    if "youtube" in done:
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
    if CFG["publish"]["youtube"].get("also_upload_short") and "youtube_short" not in done:
        try:
            desc = f"{sh['caption']}\n\nFull case file: {done.get('youtube', {}).get('url', '')}\n\n{hashtags} #shorts"
            done["youtube_short"] = publish.youtube_upload(drafts / "short.mp4", f"{script['title'][:88]} #shorts",
                                                           desc, script.get("tags", []))
            state.save()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"YouTube Short: {exc}")
    if "youtube_short" in done:
        report.append(f"📱 YouTube Short: {done['youtube_short']['url']}")

    if CFG["publish"]["instagram"].get("enabled") and "instagram" not in done:
        try:
            cap = f"{sh['caption']}\n\nFull story on YouTube: {CFG['channel']['handle']}\n\n{hashtags}"
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
    state.data["history"].append({"wiki_title": job["topic"]["wiki_title"], "title": script["title"],
                                  "case_no": job["case_no"], "date": now_local().date().isoformat(),
                                  **{k: v.get("url") for k, v in done.items()}})
    state.data.pop("review_job", None)
    state.save()
    publish.mark_published(job_id, "\n".join(report))
    telegram.send(f"✅ <b>Case #{job['case_no']:03d} is live!</b>\n" + "\n".join(report))


# ── 4. Telegram router ───────────────────────────────────────────────────────

HELP = ("<b>Commands</b>\n/topics — 3 new topic ideas now\n/status — what's in progress\n"
        "/help — this message\n\nWhile a video is waiting for review, any message you type is treated "
        "as change notes. Otherwise, a message is treated as a topic idea.")


def cmd_status(state: State):
    rows = [f"#{v['case_no']:03d} · {v['status'].replace('_', ' ')} · "
            f"{esc(v.get('topic', {}).get('working_title', 'choosing topic'))}"
            for k, v in sorted(state.data["jobs"].items())[-8:]]
    telegram.send("📋 <b>Recent cases</b>\n" + ("\n".join(rows) or "Nothing yet."))


def handle(state: State, payload: dict):
    kind = payload.get("kind")
    if kind == "button":
        data = payload.get("data", "")
        action, _, rest = data.partition(":")
        if action == "retry":
            failed = state.data.get("last_failed")
            if not failed:
                telegram.send("Nothing to retry.")
                return
            return handle(state, failed)
        job_id = rest.split(":")[0]
        if action == "pick":
            return cmd_produce(state, job_id, int(rest.split(":")[1]))
        if action == "new":
            if job_id in state.data["jobs"]:
                state.data["jobs"][job_id]["status"] = "skipped"
            return cmd_topics(state)
        if action == "pub":
            return cmd_publish(state, job_id)
        if action == "redo":
            return cmd_revise(state, job_id, None)
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
    review = state.data.get("review_job")
    if review and state.data["jobs"].get(review, {}).get("status") == "awaiting_review":
        return cmd_revise(state, review, text)
    pending = state.latest_job("awaiting_topic")
    if pending and low in {"1", "2", "3"}:
        return cmd_produce(state, pending, int(low) - 1)
    if pending:
        state.job(pending)["status"] = "skipped"
    return cmd_topics(state, wish=text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["topics", "handle", "refresh-instagram"])
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
                v["status"] = "awaiting_review" if "revisions" in v else "awaiting_topic"
            if v["status"] == "publishing":
                v["status"] = "awaiting_review"
        state.data["last_failed"] = payload
        state.save()
        try:
            telegram.send(f"⚠️ Something went wrong:\n<code>{esc(str(exc))[:900]}</code>",
                          [[("🔁 Retry", "retry:last")]])
        except Exception:  # noqa: BLE001
            pass
        sys.exit(0 if FAKE else 1)


if __name__ == "__main__":
    main()

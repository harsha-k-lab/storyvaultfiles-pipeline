"""Draft storage (GitHub Releases), YouTube upload, Instagram Reels."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from .core import CFG, FAKE, log, retry, run, secret

REPO = os.environ.get("GITHUB_REPOSITORY", "")
YT = CFG["publish"]["youtube"]
IG = CFG["publish"]["instagram"]


# ── drafts: stored as a GitHub Release so they survive between runs ──────────

def release_tag(job_id: str) -> str:
    return f"case-{job_id}"


def save_draft(job_id: str, files: list[Path], title: str) -> dict:
    tag = release_tag(job_id)
    if FAKE:
        return {f.name: f"https://example.com/{tag}/{f.name}" for f in files}
    try:
        run(["gh", "release", "delete", tag, "--yes", "--cleanup-tag", "-R", REPO])
    except RuntimeError:
        pass
    run(["gh", "release", "create", tag, *files, "-R", REPO, "--prerelease",
         "--title", f"Case {job_id} draft: {title[:80]}",
         "--notes", "Draft video waiting for approval on Telegram."], timeout=1800)
    return {f.name: f"https://github.com/{REPO}/releases/download/{tag}/{f.name}" for f in files}


def load_draft(job_id: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if not FAKE:
        run(["gh", "release", "download", release_tag(job_id), "-R", REPO, "-D", dest, "--clobber"],
            timeout=1800)
    return dest


def restore_images(job_id: str, dest: Path):
    """Bring back this case's AI pictures from its draft, so a revision only makes new ones."""
    dest.mkdir(parents=True, exist_ok=True)
    if FAKE:
        return
    tmp = dest.parent / "_restore"
    try:
        run(["gh", "release", "download", release_tag(job_id), "-R", REPO, "-p", "images.tar",
             "-D", tmp, "--clobber"], timeout=600)
        run(["tar", "-xf", tmp / "images.tar", "-C", dest])
        log(f"Restored {len(list(dest.glob('*.jpg')))} AI pictures from the last draft")
    except RuntimeError:
        pass   # first draft, or no pictures yet


def bundle_images(src: Path, out: Path) -> Path | None:
    pics = sorted(p.name for p in src.glob("*.jpg")) if src.exists() else []
    if not pics:
        return None
    run(["tar", "-cf", out, "-C", src, *pics])
    return out


def mark_published(job_id: str, notes: str):
    if FAKE:
        return
    try:
        run(["gh", "release", "edit", release_tag(job_id), "-R", REPO, "--prerelease=false",
             "--title", f"Case {job_id} (published)", "--notes", notes])
    except RuntimeError as exc:
        log("Could not update release:", exc)


# ── YouTube ──────────────────────────────────────────────────────────────────

def _youtube():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=secret("YOUTUBE_REFRESH_TOKEN"),
        client_id=secret("YOUTUBE_CLIENT_ID"),
        client_secret=secret("YOUTUBE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def youtube_upload(video: Path, title: str, description: str, tags: list[str],
                   thumbnail: Path | None = None) -> dict:
    if FAKE:
        return {"id": "FAKE", "url": "https://youtu.be/FAKE", "privacy": YT["privacy"], "locked": False}
    from googleapiclient.http import MediaFileUpload

    yt = _youtube()
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": [t[:60] for t in tags][:30], "categoryId": str(YT["category_id"]),
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": YT["privacy"], "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": bool(YT.get("ai_disclosure", True)),
                   "embeddable": True},
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=16 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = retry(req.next_chunk, attempts=5, what="YouTube upload")
        if status:
            log(f"YouTube upload {int(status.progress() * 100)}%")
    vid = resp["id"]
    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
        except Exception as exc:  # noqa: BLE001
            log("Thumbnail not set (verify your channel with a phone number to allow custom thumbnails):", exc)
    privacy = resp.get("status", {}).get("privacyStatus", YT["privacy"])
    locked = YT["privacy"] != "private" and privacy == "private"
    return {"id": vid, "url": f"https://youtu.be/{vid}", "privacy": privacy, "locked": locked}


# ── Instagram (Instagram API with Instagram Login — no Facebook Page needed) ──

def _ig(path: str) -> str:
    return f"https://graph.instagram.com/{IG['api_version']}/{path}"


def instagram_reel(video_url: str, caption: str) -> dict:
    if FAKE:
        return {"id": "FAKE", "url": "https://instagram.com/p/FAKE"}
    token = secret("INSTAGRAM_ACCESS_TOKEN")
    me = requests.get(_ig("me"), params={"fields": "user_id,username", "access_token": token}, timeout=30).json()
    if "error" in me:
        raise RuntimeError(f"Instagram login problem: {me['error'].get('message')}")
    uid = me.get("user_id") or me.get("id")
    r = requests.post(_ig(f"{uid}/media"), data={
        "media_type": "REELS", "video_url": video_url, "caption": caption[:2200],
        "share_to_feed": "true", "access_token": token}, timeout=60).json()
    if "id" not in r:
        raise RuntimeError(f"Instagram rejected the Reel: {r.get('error', {}).get('message', r)}")
    container = r["id"]
    for _ in range(60):  # up to ~10 minutes for Instagram to process the video
        time.sleep(10)
        st = requests.get(_ig(container), params={"fields": "status_code,status", "access_token": token},
                          timeout=30).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {st.get('status')}")
    else:
        raise RuntimeError("Instagram took too long processing the video.")
    pub = requests.post(_ig(f"{uid}/media_publish"), data={"creation_id": container, "access_token": token},
                        timeout=60).json()
    if "id" not in pub:
        raise RuntimeError(f"Instagram publish failed: {pub.get('error', {}).get('message', pub)}")
    link = requests.get(_ig(pub["id"]), params={"fields": "permalink", "access_token": token}, timeout=30).json()
    return {"id": pub["id"], "url": link.get("permalink", "https://instagram.com")}


def refresh_instagram_token() -> str:
    token = secret("INSTAGRAM_ACCESS_TOKEN")
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30).json()
    if "access_token" not in r:
        raise RuntimeError(f"Instagram token refresh failed: {r}")
    return r["access_token"]

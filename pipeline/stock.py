"""Free visuals: Pixabay (main), Openverse (no key needed), Pexels (only if you already have a key)."""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

import requests

from .core import FAKE, log, retry, run, secret
from .research import HEADERS

PEXELS = "https://api.pexels.com"
PIXABAY = "https://pixabay.com/api"
OPENVERSE = "https://api.openverse.org/v1"


class Footage:
    """Finds and downloads clips, never reusing the same clip twice in one video."""

    def __init__(self, cache: Path, orientation: str = "landscape"):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.orientation = orientation
        self.used: set[str] = set()
        self.pexels_key = secret("PEXELS_API_KEY", required=False)
        self.pixabay_key = secret("PIXABAY_API_KEY", required=False)
        self._search_cache: dict[str, list[dict]] = {}

    # ── search ────────────────────────────────────────────────────────────
    def _pexels_videos(self, query: str) -> list[dict]:
        if not self.pexels_key:
            return []
        r = requests.get(f"{PEXELS}/videos/search", headers={"Authorization": self.pexels_key},
                         params={"query": query, "orientation": self.orientation,
                                 "per_page": 20, "size": "medium"}, timeout=30)
        if r.status_code != 200:
            log(f"Pexels {r.status_code} for '{query}'")
            return []
        out = []
        want_w = 1920 if self.orientation == "landscape" else 1080
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                     and (f.get("width") or 0) >= (1280 if self.orientation == "landscape" else 720)]
            if not files:
                continue
            best = min(files, key=lambda f: abs((f.get("width") or 0) - want_w))
            out.append({"id": f"pexels-{v['id']}", "url": best["link"], "kind": "video",
                        "duration": v.get("duration", 10), "credit": v.get("user", {}).get("name", "Pexels")})
        return out

    def _pixabay_videos(self, query: str) -> list[dict]:
        if not self.pixabay_key:
            return []
        r = requests.get(f"{PIXABAY}/videos/", timeout=30, params={
            "key": self.pixabay_key, "q": query[:100], "per_page": 30, "safesearch": "true",
            "video_type": "film", "min_width": 1280 if self.orientation == "landscape" else 0})
        if r.status_code != 200:
            log(f"Pixabay videos {r.status_code} for '{query}'")
            return []
        out = []
        for h in r.json().get("hits", []):
            vids = h.get("videos", {})
            f = next((vids[k] for k in ("large", "medium") if vids.get(k, {}).get("url")), None)
            if not f:
                continue
            portrait = (f.get("height") or 0) > (f.get("width") or 0)
            out.append({"id": f"pixabay-{h['id']}", "url": f["url"], "kind": "video",
                        "duration": h.get("duration", 10), "credit": f"{h.get('user', 'Pixabay')} (Pixabay)",
                        "fits": portrait == (self.orientation == "portrait")})
        # Pixabay is mostly landscape; vertical Shorts still use landscape clips (center-cropped),
        # but genuinely vertical clips go first.
        out.sort(key=lambda i: not i["fits"])
        return out

    def _pixabay_photos(self, query: str) -> list[dict]:
        if not self.pixabay_key:
            return []
        r = requests.get(f"{PIXABAY}/", timeout=30, params={
            "key": self.pixabay_key, "q": query[:100], "image_type": "photo", "per_page": 30,
            "safesearch": "true",
            "orientation": "horizontal" if self.orientation == "landscape" else "vertical"})
        if r.status_code != 200:
            return []
        return [{"id": f"pixabay-photo-{h['id']}", "url": h.get("largeImageURL") or h["webformatURL"],
                 "kind": "image", "credit": f"{h.get('user', 'Pixabay')} (Pixabay)"}
                for h in r.json().get("hits", []) if h.get("largeImageURL") or h.get("webformatURL")]

    def _openverse_photos(self, query: str) -> list[dict]:
        """No key needed. Only licenses that allow commercial use AND editing."""
        r = requests.get(f"{OPENVERSE}/images/", headers=HEADERS, timeout=30, params={
            "q": query[:200], "page_size": 20, "mature": "false", "size": "large",
            "license_type": "commercial,modification", "extension": "jpg,png",
            "aspect_ratio": "wide" if self.orientation == "landscape" else "tall"})
        if r.status_code != 200:
            log(f"Openverse {r.status_code} for '{query}'")
            return []
        out = []
        for p in r.json().get("results", []):
            if not p.get("url"):
                continue
            lic = f"CC {p.get('license', '').upper()} {p.get('license_version', '')}".strip()
            if p.get("license") in ("cc0", "pdm"):
                lic = "public domain"
            out.append({"id": f"openverse-{p['id']}", "url": p["url"], "kind": "image",
                        "credit": f"\u201c{(p.get('title') or 'Untitled')[:60]}\u201d by {p.get('creator') or 'unknown'}"
                                  f", {lic} \u2014 {p.get('foreign_landing_url') or p['url']}"})
        return out

    def _pexels_photos(self, query: str) -> list[dict]:
        if not self.pexels_key:
            return []
        r = requests.get(f"{PEXELS}/v1/search", headers={"Authorization": self.pexels_key},
                         params={"query": query, "orientation": self.orientation, "per_page": 15},
                         timeout=30)
        if r.status_code != 200:
            return []
        return [{"id": f"pexels-photo-{p['id']}", "url": p["src"]["large2x"], "kind": "image",
                 "credit": p.get("photographer", "Pexels")} for p in r.json().get("photos", [])]

    def search(self, query: str) -> list[dict]:
        if query in self._search_cache:
            return self._search_cache[query]
        results: list[dict] = []
        if not FAKE:
            for fn in (self._pixabay_videos, self._pexels_videos):
                try:
                    results += fn(query)
                except Exception as exc:  # noqa: BLE001
                    log(f"Footage search error '{query}': {exc}")
            if len(results) < 3:
                for fn in (self._pixabay_photos, self._pexels_photos, self._openverse_photos):
                    try:
                        results += fn(query)
                    except Exception as exc:  # noqa: BLE001
                        log(f"Photo search error '{query}': {exc}")
                    if len(results) >= 6:
                        break
        videos = [r for r in results if r["kind"] == "video"]
        photos = [r for r in results if r["kind"] != "video"]
        random.shuffle(videos)
        random.shuffle(photos)
        videos.sort(key=lambda i: not i.get("fits", True))  # keeps the shuffle within each group
        results = videos + photos  # moving footage first, still images as backup
        self._search_cache[query] = results
        return results

    # ── download ──────────────────────────────────────────────────────────
    def download(self, item: dict) -> Path:
        ext = ".mp4" if item["kind"] == "video" else ".jpg"
        path = self.cache / (hashlib.md5(item["url"].encode()).hexdigest()[:16] + ext)
        if path.exists() and path.stat().st_size > 10_000:
            return path

        def go():
            with requests.get(item["url"], headers=HEADERS, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(path, "wb") as fh:
                    for block in r.iter_content(1 << 20):
                        fh.write(block)
            return path

        return retry(go, what="Download")

    def fake_clip(self, label: str) -> Path:
        """Generated placeholder footage for offline tests."""
        path = self.cache / f"fake-{hashlib.md5(label.encode()).hexdigest()[:8]}.mp4"
        if not path.exists():
            w, h = (1280, 720) if self.orientation == "landscape" else (720, 1280)
            hue = int(hashlib.md5(label.encode()).hexdigest()[:2], 16)
            run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                 f"gradients=s={w}x{h}:c0=0x{hue:02x}3040:c1=0x101820:speed=0.02:d=12:r=30",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path])
        return path

    def get(self, queries: list[str], fallback_queries: list[str]) -> tuple[Path, dict] | None:
        """Best unused clip for the first query that returns something."""
        for q in [*queries, *fallback_queries]:
            if FAKE:
                item = {"id": f"fake-{q}-{len(self.used)}", "kind": "video", "credit": "Test"}
                self.used.add(item["id"])
                return self.fake_clip(f"{q}-{len(self.used)}"), item
            for item in self.search(q):
                if item["id"] in self.used:
                    continue
                try:
                    path = self.download(item)
                except Exception as exc:  # noqa: BLE001
                    log(f"Skip clip {item['id']}: {exc}")
                    continue
                self.used.add(item["id"])
                return path, item
        return None


def download_image(url: str, dest: Path) -> Path | None:
    if FAKE:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest
    except Exception as exc:  # noqa: BLE001
        log(f"Image download failed: {exc}")
        return None


MOOD_FALLBACKS = ["dark forest fog", "rain window night", "old documents desk", "empty road night",
                  "flickering candle dark", "abandoned house", "clouds moving dark sky",
                  "typewriter close up", "night city lights blur", "ocean waves storm"]

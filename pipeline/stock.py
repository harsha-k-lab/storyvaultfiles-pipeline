"""Free visuals: Pixabay (main), Openverse (no key needed), Pexels (only if you already have a key)."""
from __future__ import annotations

import hashlib
import re
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
        self.used: dict[str, int] = {}   # clip id → shot number it was used at
        self.shot_no = 0
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
                        "duration": v.get("duration", 10), "credit": v.get("user", {}).get("name", "Pexels"),
                        "tags": " ".join([v.get("url", "").replace("-", " "), *map(str, v.get("tags") or [])])})
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
                        "fits": portrait == (self.orientation == "portrait"), "tags": h.get("tags", "")})
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
                 "kind": "image", "credit": f"{h.get('user', 'Pixabay')} (Pixabay)", "tags": h.get("tags", "")}
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
                                  f", {lic} \u2014 {p.get('foreign_landing_url') or p['url']}",
                        "tags": " ".join([p.get("title") or "", *[t.get("name", "") for t in p.get("tags") or []
                                                                  if isinstance(t, dict)]])})
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
                 "credit": p.get("photographer", "Pexels"), "tags": p.get("alt") or p.get("url", "").replace("-", " ")}
                for p in r.json().get("photos", [])]

    def _run(self, fns, query: str) -> list[dict]:
        out = []
        for fn in fns:
            try:
                out += fn(query)
            except Exception as exc:  # noqa: BLE001
                log(f"Footage search error '{query}': {exc}")
        return out

    def search(self, query: str) -> list[dict]:
        """Results in the sites' own relevance order (no shuffling — the best match comes first).
        Photos are only fetched when there isn't enough matching video."""
        if query in self._search_cache:
            return self._search_cache[query]
        results: list[dict] = []
        if not FAKE:
            kws = keywords(query)
            results = self._run((self._pixabay_videos, self._pexels_videos), query)
            if sum(1 for r in results if match(r, kws) >= 0.5) < 3:
                results += self._run((self._pixabay_photos, self._pexels_photos), query)
            if not any(match(r, kws) >= 0.5 for r in results):
                results += self._run((self._openverse_photos,), query)
        for rank, r in enumerate(results):
            r["rank"] = rank
        self._search_cache[query] = results
        return results

    def _score(self, item: dict, kws: list[str]) -> float:
        rel = match(item, kws)
        score = rel + 0.08 / (1 + item.get("rank", 0) / 5)  # sites rank good matches first
        if item["kind"] == "video":
            score += 0.12                                     # moving footage beats a still
        if item.get("fits") is False:
            score -= 0.05                                     # needs heavy cropping
        return score

    def get(self, ladder: list[str], mood: list[str]) -> tuple[Path, dict] | None:
        """Clip that best shows what's being said.

        ladder = searches from most specific ("airplane taking off night") to most general
        ("airplane"). A clip only counts if it is actually tagged with the search words.
        Order of preference: matching clip → the story's mood shots → generic dark shots."""
        self.shot_no += 1
        if FAKE:
            q = (ladder or mood or ["test"])[0]
            item = {"id": f"fake-{q}-{self.shot_no}", "kind": "video", "credit": "Test", "query": q}
            return self.fake_clip(f"{q}-{self.shot_no}"), item

        ranked: dict[str, tuple[float, dict]] = {}
        for q in ladder:
            kws = keywords(q)
            for item in self.search(q):
                if match(item, kws) == 0:
                    continue
                last = self.used.get(item["id"])
                if last is not None and self.shot_no - last < 12:   # never repeat a clip close together
                    continue
                sc = self._score(item, kws) - (0.3 if last is not None else 0)
                if item["id"] not in ranked or sc > ranked[item["id"]][0]:
                    ranked[item["id"]] = (sc, {**item, "query": q})
            if ranked and max(v[0] for v in ranked.values()) >= 0.6:
                break   # found a clear match — don't drift to vaguer searches
        # Prefer clips that show the sentence's main subject (the last, one-word search),
        # so "night" alone can't win a shot about an airplane taking off at night.
        subject = keywords(ladder[-1]) if ladder else []
        with_subject = {k: v for k, v in ranked.items() if match(v[1], subject) > 0}
        pool = with_subject or ranked
        if ranked and not with_subject:
            # nothing tagged with the subject yet — ask the sites for the subject alone
            for item in self.search(ladder[-1]):
                if item["id"] not in self.used and match(item, subject) > 0:
                    pool = {item["id"]: (self._score(item, subject), {**item, "query": ladder[-1]})}
                    break
        tries = [v[1] for v in sorted(pool.values(), key=lambda v: v[0], reverse=True)[:4]]
        if not tries:
            for q in [*mood, *MOOD_FALLBACKS[:3]]:
                tries = [{**i, "query": q} for i in self.search(q) if i["id"] not in self.used][:3]
                if tries:
                    log(f"No clip matched {ladder[:1]} — using story mood shot '{q}'")
                    break
        for item in tries:
            try:
                path = self.download(item)
            except Exception as exc:  # noqa: BLE001
                log(f"Skip clip {item['id']}: {exc}")
                continue
            self.used[item["id"]] = self.shot_no
            return path, item
        return None

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


STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "into", "with", "and", "or", "for", "from",
        "by", "is", "are", "was", "his", "her", "their", "its", "up", "off", "out", "over", "close"}


def _stem(w: str) -> str:
    for suf in ("ing", "ers", "er", "es", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


# Different words stock sites use for the same thing.
SAME = {"plane": "airplane", "aircraft": "airplane", "jet": "airplane", "airliner": "airplane",
        "aeroplane": "airplane", "cop": "police", "officer": "police", "detective": "police",
        "woods": "forest", "sea": "ocean", "automobile": "car", "vehicle": "car", "kid": "child",
        "photograph": "photo", "boat": "ship", "vessel": "ship", "mountains": "mountain"}
PHRASES = [(r"\b(taking|takes|took|take) off\b", "takeoff"), (r"\b(landing|lands|landed)\b", "landing"),
           (r"\bnews ?paper", "newspaper"), (r"\bsearch(ing|es|ed)?\b", "search")]


def _words(text: str) -> list[str]:
    text = text.lower()
    for pat, rep in PHRASES:
        text = re.sub(pat, rep, text)
    return [SAME.get(w, _stem(SAME.get(w, w))) for w in re.findall(r"[a-z]+", text)]


def keywords(query: str) -> list[str]:
    return [w for w in _words(query) if w not in STOP and len(w) > 1]


def match(item: dict, kws: list[str]) -> float:
    """Share of the search words that the clip is actually tagged with (0–1)."""
    if not kws:
        return 0.0
    tag_words = set(_words(item.get("tags") or ""))
    hits = sum(1 for k in kws if k in tag_words or any(t.startswith(k) or k.startswith(t)
                                                       for t in tag_words if len(t) > 3 and len(k) > 3))
    return hits / len(kws)


MOOD_FALLBACKS = ["dark forest fog", "rain window night", "old documents desk", "empty road night",
                  "flickering candle dark", "abandoned house", "clouds moving dark sky",
                  "typewriter close up", "night city lights blur", "ocean waves storm"]

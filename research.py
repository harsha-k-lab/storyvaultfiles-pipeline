"""Find real, well-documented cases on Wikipedia (free, no key, reusable license)."""
from __future__ import annotations

import html
import os
import random
import re
from datetime import date, timedelta
from urllib.parse import quote

import requests

from .core import CFG, FAKE, log, retry

WIKI = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
REPO = os.environ.get("GITHUB_REPOSITORY", "storyvaultfiles-pipeline")
HEADERS = {"User-Agent": f"StoryVaultFilesBot/1.0 (https://github.com/{REPO})"}

FREE_LICENSES = ("cc0", "public domain", "pd", "cc by", "cc-by", "attribution", "no restrictions")


def _get(url, params):
    params = {"format": "json", "formatversion": "2", **params}
    r = retry(lambda: requests.get(url, params=params, headers=HEADERS, timeout=40), what="Wikipedia")
    r.raise_for_status()
    return r.json()


def category_pages(category: str, depth: int = 1) -> list[str]:
    titles, subcats, cont = [], [], {}
    while True:
        data = _get(WIKI, {"action": "query", "list": "categorymembers",
                           "cmtitle": f"Category:{category}", "cmlimit": "500",
                           "cmtype": "page|subcat", **cont})
        for m in data.get("query", {}).get("categorymembers", []):
            if m["ns"] == 0:
                titles.append(m["title"])
            elif m["ns"] == 14:
                subcats.append(m["title"].split(":", 1)[1])
        if "continue" not in data or len(titles) > 1500:
            break
        cont = data["continue"]
    if depth > 0:
        for sub in subcats[:12]:
            titles += category_pages(sub, depth - 1)
    return titles


def search_pages(query: str, limit: int = 20) -> list[str]:
    data = _get(WIKI, {"action": "query", "list": "search", "srsearch": f"{query} mystery",
                       "srlimit": str(limit)})
    return [s["title"] for s in data.get("query", {}).get("search", [])]


def page_views(title: str, days: int = 60) -> int:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
           f"all-access/user/{quote(title.replace(' ', '_'), safe='')}/daily/"
           f"{start:%Y%m%d}/{end:%Y%m%d}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return sum(i["views"] for i in r.json().get("items", []))
    except Exception:  # noqa: BLE001
        return 0


def summaries(titles: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        data = _get(WIKI, {"action": "query", "prop": "extracts|info", "exintro": "1",
                           "explaintext": "1", "titles": "|".join(chunk), "inprop": "url"})
        for p in data.get("query", {}).get("pages", []):
            if p.get("missing"):
                continue
            out.append({"wiki_title": p["title"], "summary": p.get("extract", "")[:1200],
                        "url": p.get("fullurl", ""), "length": p.get("length", 0)})
    return out


def _too_recent(text: str) -> bool:
    years = [int(y) for y in re.findall(r"\b(1[5-9]\d\d|20[0-4]\d)\b", text[:600])]
    if not years:
        return False
    return min(years) > date.today().year - CFG["research"]["avoid_recent_years"]


def candidates(used: set[str], query: str | None = None) -> list[dict]:
    """Return a ranked shortlist of cases not used before."""
    if FAKE:
        return [{"wiki_title": f"Fake Case {i}", "summary": "A test mystery.", "url": "", "views": 100}
                for i in range(1, 6)]
    rc = CFG["research"]
    if query:
        pool = search_pages(query, 30)
    else:
        pool = []
        cats = list(rc["categories"])
        random.shuffle(cats)
        for cat in cats[:6]:
            try:
                pool += category_pages(cat)
            except Exception as exc:  # noqa: BLE001
                log(f"Category {cat} skipped: {exc}")
    pool = [t for t in dict.fromkeys(pool)
            if t not in used and not t.startswith(("List of", "Lists of"))]
    random.shuffle(pool)
    info = [s for s in summaries(pool[:120]) if s["length"] >= rc["min_article_chars"]]
    info = [s for s in info if not _too_recent(s["summary"])]
    random.shuffle(info)
    shortlist = info[: rc["candidates_per_day"] * 2]
    for s in shortlist:
        s["views"] = page_views(s["wiki_title"])
    shortlist.sort(key=lambda s: s["views"], reverse=True)
    # Mix popular and lesser-known cases so the channel isn't only the famous ones.
    top = shortlist[: rc["candidates_per_day"] // 2]
    rest = shortlist[rc["candidates_per_day"] // 2:]
    random.shuffle(rest)
    return top + rest[: rc["candidates_per_day"] - len(top)]


def article(title: str) -> dict:
    """Full plain text of the article, plus related sections for grounding the script."""
    if FAKE:
        return {"title": title, "text": "Fake article text for testing. " * 40, "url": ""}
    data = _get(WIKI, {"action": "query", "prop": "extracts|info", "explaintext": "1",
                       "titles": title, "inprop": "url", "redirects": "1"})
    page = data["query"]["pages"][0]
    text = page.get("extract", "")
    text = re.split(r"\n==\s*(See also|References|Notes|External links|Further reading|Citations|Sources)\s*==",
                    text)[0]
    return {"title": page["title"], "text": text[:60000], "url": page.get("fullurl", "")}


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def free_images(title: str, limit: int = 8) -> list[dict]:
    """Freely licensed photos used on the article (public domain / Creative Commons)."""
    if FAKE:
        return []
    try:
        data = _get(WIKI, {"action": "query", "prop": "images", "titles": title, "imlimit": "50",
                           "redirects": "1"})
        files = [i["title"] for i in data["query"]["pages"][0].get("images", [])]
    except Exception:  # noqa: BLE001
        return []
    files = [f for f in files if re.search(r"\.(jpe?g|png|tif?f|webp)$", f, re.I)
             and not re.search(r"(icon|logo|flag|symbol|map_marker|commons-logo|question_book|edit-clear|ambox|wiki)",
                               f, re.I)]
    out = []
    for i in range(0, len(files), 20):
        info = _get(COMMONS, {"action": "query", "titles": "|".join(files[i:i + 20]),
                              "prop": "imageinfo", "iiprop": "url|size|extmetadata",
                              "iiurlwidth": "2400"})
        for p in info.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
            if not lic or not any(lic.lower().startswith(x) for x in FREE_LICENSES):
                continue
            if re.search(r"\b(nc|nd)\b", lic.lower()):
                continue
            if ii.get("width", 0) < 700 or ii.get("height", 0) < 450:
                continue
            out.append({
                "url": ii.get("thumburl") or ii.get("url"),
                "page": ii.get("descriptionurl", ""),
                "license": lic,
                "artist": _strip_html(meta.get("Artist", {}).get("value", ""))[:80] or "Unknown",
                "caption": _strip_html(meta.get("ImageDescription", {}).get("value", ""))[:200],
                "file": p["title"],
            })
    return out[:limit]

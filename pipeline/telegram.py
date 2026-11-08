"""Telegram messages and buttons (free Bot API)."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .core import FAKE, log, retry, secret

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, data: dict | None = None, files: dict | None = None) -> dict:
    if FAKE:
        log(f"[telegram:{method}]", json.dumps(data, ensure_ascii=False)[:600])
        return {"ok": True, "result": {"message_id": 1}}
    url = API.format(token=secret("TELEGRAM_BOT_TOKEN"), method=method)
    payload = dict(data or {})
    for key in ("reply_markup",):
        if key in payload and not isinstance(payload[key], str):
            payload[key] = json.dumps(payload[key])

    def go():
        r = requests.post(url, data=payload, files=files, timeout=300)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description')}")
        return body

    return retry(go, what=f"Telegram {method}")


def chat_id() -> str:
    return secret("TELEGRAM_CHAT_ID")


def buttons(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def send(text: str, rows: list[list[tuple[str, str]]] | None = None, html: bool = True) -> dict:
    data = {"chat_id": chat_id(), "text": text[:4000], "disable_web_page_preview": "true"}
    if html:
        data["parse_mode"] = "HTML"
    if rows:
        data["reply_markup"] = buttons(rows)
    return _call("sendMessage", data)


def send_photo(path: Path, caption: str, rows=None) -> dict:
    data = {"chat_id": chat_id(), "caption": caption[:1000], "parse_mode": "HTML"}
    if rows:
        data["reply_markup"] = buttons(rows)
    if FAKE:
        return _call("sendPhoto", data)
    with open(path, "rb") as fh:
        return _call("sendPhoto", data, files={"photo": fh})


def send_video(path: Path, caption: str, rows=None) -> dict | None:
    """Bots can upload videos up to 50 MB."""
    if not path.exists() or path.stat().st_size > 49 * 1024 * 1024:
        return None
    data = {"chat_id": chat_id(), "caption": caption[:1000], "parse_mode": "HTML",
            "supports_streaming": "true"}
    if rows:
        data["reply_markup"] = buttons(rows)
    if FAKE:
        return _call("sendVideo", data)
    with open(path, "rb") as fh:
        return _call("sendVideo", data, files={"video": fh})


def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

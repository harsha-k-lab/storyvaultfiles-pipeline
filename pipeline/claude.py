"""Hands research and writing to Claude, through a Claude Code routine on your Claude plan.

GitHub starts the routine with a short command ("TOPICS", "SCRIPT 004", "REVISE 004 …").
Claude follows ROUTINE.md, then pushes its result as a JSON file to a `claude/…` branch,
which starts the "Claude delivery" workflow (pipeline.run deliver).
If the routine isn't set up, is over its daily limit, or fails, Gemini takes over.
"""
from __future__ import annotations

import os

import requests

from .core import CFG, FAKE, log, now_local, secret

CC = CFG.get("claude", {})
API_BASE = "https://api.anthropic.com/v1/claude_code/routines"


def configured() -> bool:
    if FAKE:
        return os.environ.get("SVF_FAKE_CLAUDE") == "1"
    return bool(CC.get("enabled", True) and secret("CLAUDE_ROUTINE_URL", required=False)
                and secret("CLAUDE_ROUTINE_TOKEN", required=False))


def _usage(state) -> dict:
    today = now_local().date().isoformat()
    u = state.data.setdefault("claude_runs", {})
    if u.get("date") != today:
        u.clear()
        u.update({"date": today, "count": 0})
    return u


def runs_left(state) -> int:
    return int(CC.get("daily_runs", 5)) - _usage(state)["count"]


def fire(state, text: str, reserve: int = 0) -> tuple[str | None, str]:
    """Start Claude. Returns (link to watch the session, "") or (None, reason to use Gemini)."""
    if not configured():
        return None, ""
    if runs_left(state) <= reserve:
        return None, ("Claude's daily runs are used up for today" if runs_left(state) <= 0
                      else "Saving Claude's last runs today for scripts")
    if FAKE:
        _usage(state)["count"] += 1
        log(f"[claude fire] {text[:80]!r}")
        return "https://claude.ai/code/session_fake", ""
    url = secret("CLAUDE_ROUTINE_URL").strip()
    if not url.startswith("http"):
        url = f"{API_BASE}/{url}/fire"
    try:
        r = requests.post(url, timeout=40, json={"text": text[:60000]}, headers={
            "Authorization": f"Bearer {secret('CLAUDE_ROUTINE_TOKEN').strip()}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "experimental-cc-routine-2026-04-01",
            "Content-Type": "application/json",
        })
    except requests.RequestException as exc:
        return None, f"Couldn't reach Claude ({exc.__class__.__name__})"
    if r.status_code == 200:
        _usage(state)["count"] += 1
        return r.json().get("claude_code_session_url", ""), ""
    reasons = {401: "Claude routine token is wrong (CLAUDE_ROUTINE_TOKEN)",
               404: "Claude routine not found (CLAUDE_ROUTINE_URL)",
               429: "Claude's routine limit is reached for now",
               400: "Claude routine is paused or the request was refused"}
    why = reasons.get(r.status_code, f"Claude routine returned HTTP {r.status_code}")
    log(why, r.text[:300])
    return None, why

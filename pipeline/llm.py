"""Free script writing with Google's Gemini API (free tier, no billing needed)."""
from __future__ import annotations

import json
import re
import time

import requests

from .core import CFG, FAKE, log, secret

BASE = "https://generativelanguage.googleapis.com/v1beta"
_chosen: list[str] = []


def _headers():
    return {"x-goog-api-key": secret("GEMINI_API_KEY"), "Content-Type": "application/json"}


def _discover_models() -> list[str]:
    """Find free 'flash' text models on this key, newest first."""
    try:
        r = requests.get(f"{BASE}/models?pageSize=200", headers=_headers(), timeout=30)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log("Could not list Gemini models:", exc)
        return []
    names = []
    for m in r.json().get("models", []):
        name = m["name"].split("/", 1)[-1]
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if "flash" not in name or any(x in name for x in ("image", "tts", "live", "audio", "embed", "thinking-exp")):
            continue
        names.append(name)

    def version_key(n: str):
        nums = re.findall(r"\d+(?:\.\d+)?", n)
        v = float(nums[0]) if nums else 0
        return (("preview" not in n and "exp" not in n), v, "lite" not in n)

    return sorted(names, key=version_key, reverse=True)


def _models() -> list[str]:
    if _chosen:
        return _chosen
    configured = list(CFG["writing"]["models"])
    discovered = [m for m in _discover_models() if m not in configured]
    _chosen.extend(configured + discovered)
    return _chosen


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def ask_json(system: str, prompt: str, temperature: float = 0.8, max_tokens: int = 20000,
             fake_response=None):
    """Send a prompt and get JSON back. Falls through free models on errors/limits."""
    if FAKE:
        return fake_response
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    errors = []
    for model in _models():
        for attempt in range(3):
            try:
                r = requests.post(f"{BASE}/models/{model}:generateContent",
                                  headers=_headers(), json=body, timeout=300)
            except requests.RequestException as exc:
                errors.append(f"{model}: {exc}")
                time.sleep(5)
                continue
            if r.status_code in (404, 400) and "not found" in r.text.lower():
                errors.append(f"{model}: not available")
                break
            if r.status_code == 429 or r.status_code >= 500:
                wait = 20 * (attempt + 1)
                log(f"Gemini {model} busy/limited ({r.status_code}); waiting {wait}s")
                errors.append(f"{model}: HTTP {r.status_code}")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                errors.append(f"{model}: HTTP {r.status_code} {r.text[:200]}")
                break
            data = r.json()
            try:
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                result = _extract_json(text)
                if model != _chosen[0]:
                    _chosen.remove(model)
                    _chosen.insert(0, model)
                log(f"Gemini model used: {model}")
                return result
            except Exception as exc:  # noqa: BLE001 — malformed output, try again
                errors.append(f"{model}: bad JSON ({exc})")
                body["generationConfig"]["temperature"] = max(0.3, temperature - 0.2)
                continue
    raise RuntimeError("All free Gemini models failed:\n" + "\n".join(errors[-8:]))

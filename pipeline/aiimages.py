"""One AI-generated picture per sentence, through your Cloudflare Worker's free Workers AI
allowance (10,000 neurons a day ≈ 170 FLUX.1-schnell images). See SETUP.md step 13.

Pictures are cached by prompt, so a revision only pays for sentences that changed. When the
day's allowance runs out, or the Worker isn't set up, callers fall back to stock footage.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import requests

from .core import CFG, FAKE, log, retry, secret

IC = CFG.get("images", {})


class Images:
    def __init__(self, cache: Path, salt: str = ""):
        self.salt = salt          # changed by "New pictures" so every picture is made fresh
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.url = secret("CLOUDFLARE_WORKER_URL", required=False).rstrip("/")
        self.key = secret("WEBHOOK_SECRET", required=False)
        self.out_of_quota = False
        self.made = self.reused = self.failed = 0

    @property
    def enabled(self) -> bool:
        return bool(IC.get("enabled", True)) and (FAKE or bool(self.url and self.key)) and not self.out_of_quota

    @staticmethod
    def full_prompt(prompt: str, look: str = "", variant: int = 0) -> str:
        parts = [prompt.strip().rstrip(".")]
        if variant:
            parts.append(["", "a different angle, closer detail", "wide establishing view",
                          "low angle, shallow depth of field"][variant % 4])
        if look:
            parts.append(look.strip().rstrip("."))
        parts.append(IC.get("house_style", ""))
        return ". ".join(p for p in parts if p)[:1900]

    def get(self, prompt: str, look: str = "", variant: int = 0) -> Path | None:
        """Path to the picture for this prompt, generating it if needed. None = use stock instead."""
        if not prompt or not self.enabled:
            return None
        full = self.full_prompt(prompt, look, variant)
        key = hashlib.sha1(f"{IC.get('model')}|{self.salt}|{full}".encode()).hexdigest()[:20]
        path = self.cache / f"{key}.jpg"
        if path.exists() and path.stat().st_size > 5000:
            self.reused += 1
            return path
        if FAKE:
            return self._fake(path, prompt)
        seed = int(key[:8], 16) % 1_000_000_000      # same prompt → same picture

        def call():
            r = requests.post(f"{self.url}/image", timeout=120, headers={"X-SVF-Secret": self.key},
                              json={"prompt": full, "model": IC.get("model"), "seed": seed,
                                    "width": IC.get("width", 1024), "height": IC.get("height", 1024)})
            if r.status_code == 429:
                return r
            if r.status_code >= 500 and r.status_code != 501:
                raise RuntimeError(f"image service {r.status_code}: {r.text[:200]}")
            return r

        try:
            r = retry(call, attempts=3, wait=3, what="AI image")
        except Exception as exc:  # noqa: BLE001
            log(f"AI image failed, using stock: {exc}")
            self.failed += 1
            return None
        if r.status_code == 429:
            log("Cloudflare's free image allowance for today is used up — stock footage from here on.")
            self.out_of_quota = True
            return None
        if r.status_code != 200:
            log(f"AI image unavailable ({r.status_code}): {r.text[:200]}")
            if r.status_code in (403, 501):
                self.out_of_quota = True   # not set up correctly: stop trying for this video
            self.failed += 1
            return None
        try:
            path.write_bytes(base64.b64decode(r.json()["image"]))
        except Exception as exc:  # noqa: BLE001
            log(f"AI image unreadable: {exc}")
            self.failed += 1
            return None
        self.made += 1
        return path

    def _fake(self, path: Path, prompt: str) -> Path:
        from PIL import Image, ImageDraw
        hue = int(hashlib.md5(prompt.encode()).hexdigest()[:2], 16)
        img = Image.new("RGB", (1024, 1024), (40 + hue // 4, 45, 55))
        ImageDraw.Draw(img).text((40, 480), prompt[:60], fill=(230, 220, 200))
        img.save(path, quality=90)
        self.made += 1
        return path

    def summary(self) -> str:
        if not FAKE and not (self.url and self.key):
            return ("AI pictures are off (stock footage used) — add the CLOUDFLARE_WORKER_URL secret "
                    "and the Workers AI binding: SETUP.md step 13")
        return (f"{self.made} new AI images, {self.reused} reused"
                + (f", {self.failed} fell back to stock" if self.failed else "")
                + (" — today's free image allowance ran out" if self.out_of_quota else ""))

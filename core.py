"""Shared helpers: settings, secrets, saved state, logging, shell commands."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("SVF_STATE_DIR", ROOT / "state"))
WORK_DIR = Path(os.environ.get("SVF_WORK_DIR", ROOT / "work"))
ASSETS = ROOT / "assets"

# FAKE mode runs the whole pipeline offline with placeholder text, voice and
# footage. Used for testing without any accounts: SVF_FAKE=1
FAKE = os.environ.get("SVF_FAKE") == "1"


def log(*parts):
    print(f"[{datetime.now().strftime('%H:%M:%S')}]", *parts, flush=True)


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


CFG = load_config()


def secret(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "").strip()
    if not value and required and not FAKE:
        raise RuntimeError(
            f"Missing secret {name}. Add it in GitHub → Settings → Secrets and variables → Actions."
        )
    return value


def now_local() -> datetime:
    return datetime.now(ZoneInfo(CFG["channel"]["timezone"]))


def slugify(text: str, limit: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:limit].strip("-") or "case"


def run(cmd: list[str], quiet: bool = True, timeout: int | None = None) -> str:
    """Run a command, raising a readable error if it fails."""
    proc = subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-1500:]
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd[:6]))} …\n{tail}")
    if not quiet:
        print(proc.stdout)
    return proc.stdout


def media_duration(path: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ])
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def retry(fn, attempts: int = 3, wait: float = 4.0, what: str = "request"):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — we re-raise after retries
            last = exc
            log(f"{what} failed (try {i + 1}/{attempts}): {exc}")
            time.sleep(wait * (i + 1))
    raise last  # type: ignore[misc]


# ── Saved state (committed back to the repo by the workflow) ──────────────────

class State:
    """Small JSON database living in state/ so it survives between runs."""

    path = STATE_DIR / "state.json"

    def __init__(self):
        STATE_DIR.mkdir(exist_ok=True)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"next_case": 1, "jobs": {}, "history": [], "last_topics_date": ""}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    # jobs ---------------------------------------------------------------
    def new_job(self, topics: list[dict]) -> str:
        case_no = self.data["next_case"]
        self.data["next_case"] = case_no + 1
        job_id = f"{case_no:03d}"
        self.data["jobs"][job_id] = {
            "case_no": case_no,
            "status": "awaiting_topic",
            "topics": topics,
            "created": now_local().isoformat(timespec="minutes"),
        }
        self.data["active_job"] = job_id
        return job_id

    def job(self, job_id: str) -> dict:
        if job_id not in self.data["jobs"]:
            raise KeyError(f"Case {job_id} not found")
        return self.data["jobs"][job_id]

    def latest_job(self, *statuses: str) -> str | None:
        ids = sorted(
            (j for j, v in self.data["jobs"].items() if not statuses or v["status"] in statuses),
            reverse=True,
        )
        return ids[0] if ids else None

    def used_titles(self) -> set[str]:
        return {h["wiki_title"] for h in self.data["history"]} | {
            t["wiki_title"] for j in self.data["jobs"].values() for t in j.get("topics", [])
            if j["status"] != "awaiting_topic"
        }


def job_dir(job_id: str) -> Path:
    d = WORK_DIR / f"case-{job_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(msg: str):
    log("ERROR:", msg)
    sys.exit(1)

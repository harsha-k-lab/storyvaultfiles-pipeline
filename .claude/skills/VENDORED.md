# Vendored skills

These four skills are copied, unchanged, from
**jakeschincariol/youtube-agent-skill** (MIT licence, see `LICENSE-youtube-agent-skill`),
pinned at commit `a2feb21` (16 Sep 2026).

| Skill | Used for |
|---|---|
| `yt-script` | Hook formulas (`hooks.json`) and `hookscore.py` to score the cold open |
| `yt-package` | `title.py` to lint the title + thumbnail-text pairing |
| `yt-seo` | Description and tag rules |
| `yt-shorts` | Rules for the Short's opening line and loop |

Reviewed before adding: the Python tools use only the standard library, read only the
files you pass them, and make no network calls. Nothing here publishes anything.

They are a copy, not a live link, so updates upstream can't change how this pipeline
behaves. To update, review the new version and copy it in again. How the unattended
writer applies them is in `ROUTINE.md`, section 3a.

"""Turns researched cases into pitches and storytelling scripts."""
from __future__ import annotations

from .core import CFG
from .llm import ask_json

CH = CFG["channel"]
W = CFG["writing"]

STYLE_RULES = f"""
You write for "{CH['name']}", a faceless YouTube channel about {CH['niche']}.
The narrator is calm, low and intimate, like a late-night documentary. Second person
is used sparingly ("Imagine standing..."). Short sentences for tension, longer ones
for atmosphere. No cheesy horror clichés, no exclamation marks, no emojis.

NON-NEGOTIABLE ACCURACY AND RESPECT RULES:
- Use ONLY facts found in the SOURCE text. Never invent names, dates, numbers,
  quotes, places or evidence. If the source doesn't say it, don't say it.
- Clearly label theories as theories ("one theory suggests…").
- Never state or imply that a living, uncharged person committed a crime.
- Treat victims and families with dignity. No graphic gore or lingering on injuries.
- No made-up dialogue presented as real quotes.
"""


def pitch_topics(cands: list[dict], recent_titles: list[str], wish: str | None = None):
    listing = "\n\n".join(
        f"[{i}] {c['wiki_title']} (Wikipedia views last 60 days: {c.get('views', 0)})\n{c['summary'][:700]}"
        for i, c in enumerate(cands)
    )
    prompt = f"""Here are candidate cases from Wikipedia{' matching the viewer request: ' + wish if wish else ''}.

{listing}

Recently covered (avoid similar ones): {', '.join(recent_titles[-15:]) or 'none'}

Pick the 3 cases that would make the most gripping 10-minute story videos. Prefer:
genuinely unresolved, strong hook, rich documented detail, advertiser-friendly,
a mix of famous and little-known. Avoid cases centred on violence against children.

Return JSON: {{"topics": [{{"index": <number from the list>,
  "working_title": "<YouTube title, under 65 characters, curiosity-driven, not clickbait lies>",
  "hook": "<one-sentence pitch of why it is fascinating>",
  "why_now": "<one short reason this will perform>"}}]}}"""
    fake = {"topics": [{"index": i, "working_title": f"The Vanishing of Test Case {i + 1}",
                        "hook": "A test pitch.", "why_now": "Testing."} for i in range(3)]}
    result = ask_json(STYLE_RULES, prompt, temperature=0.9, max_tokens=4000, fake_response=fake)
    topics = []
    for t in result["topics"][:3]:
        c = cands[int(t["index"])]
        topics.append({**c, **{k: t[k] for k in ("working_title", "hook", "why_now")}})
    return topics


def _script_schema(minutes: int, short_s: int, image_count: int) -> str:
    words = minutes * W["words_per_minute"]
    short_words = int(short_s * 2.4)
    return f"""Return JSON with exactly these keys:
{{
 "title": "<YouTube title under 70 chars>",
 "thumbnail_text": "<2-4 punchy words for the thumbnail, ALL CAPS>",
 "description": "<3 short paragraphs for the YouTube description: hook, what the video covers, a question for the comments. No hashtags here.>",
 "tags": ["<12-18 search tags>"],
 "hashtags": ["#unsolvedmysteries", "<3 more>"],
 "scenes": [
   {{"chapter": "<optional chapter name — only on the first scene of each chapter, else empty string>",
     "narration": "<40-90 words of narration>",
     "visuals": ["<stock-footage search, 2-4 plain words>", "<alternative search>", "<another>"],
     "image": <index of a source photo to show (0-{max(image_count - 1, 0)}) or -1 for stock footage>}}
 ],
 "short": {{
   "narration": "<{short_words - 15}-{short_words} words. Standalone vertical video. First sentence must hook in under 2 seconds. End on the unresolved question, then: 'The full case file is on {CH['name']}.'>",
   "visuals": ["<4-6 stock-footage searches suited to vertical video>"],
   "caption": "<Instagram caption: 2 short lines + a question>"
 }}
}}

Total narration across all scenes: about {words} words ({minutes} minutes).
Structure: cold open hook (no greeting), then "This is case file number <N>." then 4-6 chapters:
the setting/people, the event, the investigation & evidence, the theories, what remains unknown.
End with a quiet reflective line, a question for viewers to answer in the comments,
and one short line asking them to subscribe for more case files.
Stock-footage searches must be generic, filmable things (e.g. "foggy forest night",
"old police files", "rain on window") — never names of real people or specific places that
stock sites won't have. Use the source photos (image index) for about 1 in 6 scenes when they fit."""


def write_script(topic: dict, source: dict, images: list[dict], case_no: int) -> dict:
    img_list = "\n".join(f"[{i}] {im['caption'] or im['file']}" for i, im in enumerate(images)) or "(none)"
    prompt = f"""Write the full story video script for case file number {case_no}.

TOPIC: {topic['wiki_title']}
WORKING TITLE: {topic.get('working_title', '')}
ANGLE: {topic.get('hook', '')}

SOURCE PHOTOS AVAILABLE:
{img_list}

SOURCE (Wikipedia, the only facts you may use):
\"\"\"{source['text']}\"\"\"

{_script_schema(W['target_minutes'], W['short_seconds'], len(images))}"""
    return ask_json(STYLE_RULES, prompt, temperature=0.85, fake_response=fake_script(case_no))


def revise_script(script: dict, feedback: str, source: dict, images: list[dict]) -> dict:
    import json
    prompt = f"""The channel owner reviewed this video and asked for changes:

OWNER FEEDBACK: \"\"\"{feedback}\"\"\"

Apply the feedback faithfully. Keep everything else that works. Keep all accuracy rules.

CURRENT SCRIPT JSON:
{json.dumps(script, ensure_ascii=False)}

SOURCE (only facts you may use):
\"\"\"{source['text'][:40000]}\"\"\"

{_script_schema(W['target_minutes'], W['short_seconds'], len(images))}"""
    return ask_json(STYLE_RULES, prompt, temperature=0.7, fake_response=script)


def fake_script(case_no: int) -> dict:
    lines = [
        "On a cold night in the winter of nineteen fifty nine, nine hikers set out into the mountains.",
        "They were experienced. They were prepared. And not one of them came home.",
        f"This is case file number {case_no}.",
        "The search party found their tent weeks later, cut open from the inside.",
        "Footprints led away into the snow, as if everyone had left at once, in the dark.",
        "Investigators had questions. The records they left behind raise even more.",
        "One theory points to the weather. Another to something no one has explained.",
        "What would make nine people run from shelter into a freezing night?",
        "Tell me what you think in the comments, and subscribe for more case files.",
    ]
    scenes = []
    for i in range(0, len(lines), 2):
        scenes.append({"chapter": ["", "The Expedition", "", "The Theories", ""][i // 2] if i // 2 < 5 else "",
                       "narration": " ".join(lines[i:i + 2]),
                       "visuals": ["snowy mountain night", "tent in snow", "old documents"],
                       "image": -1})
    return {
        "title": "The Night Nine Hikers Ran Into the Snow",
        "thumbnail_text": "WHY DID THEY RUN?",
        "description": "Test description.",
        "tags": ["mystery", "unsolved"],
        "hashtags": ["#unsolvedmysteries", "#mystery"],
        "scenes": scenes,
        "short": {"narration": " ".join(lines[:2] + lines[3:5] + lines[7:8]) +
                  f" The full case file is on {CH['name']}.",
                  "visuals": ["snowy mountain night", "tent in snow"],
                  "caption": "Nine hikers. One tent. No answers.\nWhat do you think happened?"},
    }

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


STYLE_CUSTOM = f"""
You write for "{CH['name']}", a faceless YouTube storytelling channel. This video is on a topic
the channel owner asked for, which may not be a mystery. Tell it as a story with a documentary
narrator: calm, clear, warm and confident. Make complex things simple through concrete details
and examples. Short sentences for punch, longer ones for flow. No hype words, no exclamation
marks, no emojis.

NON-NEGOTIABLE ACCURACY RULES:
- Use ONLY facts found in the SOURCES. Never invent names, dates, numbers, quotes, places,
  features or results. If the sources don't say it, don't say it.
- Label opinions and predictions as such.
- If the topic is this channel's own pipeline, describe only what its documentation says it
  does, and never mention keys, tokens, passwords, secret names or private addresses.
- No made-up dialogue presented as real quotes.
"""


def style_for(kind: str) -> str:
    return STYLE_CUSTOM if kind == "custom" else STYLE_RULES


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


def _script_schema(minutes: int, short_s: int, image_count: int, kind: str = "case", fmt: str = "both") -> str:
    words = minutes * W["words_per_minute"]
    short_words = int(short_s * 2.3)
    img = f"0-{image_count - 1}" if image_count else "none available, always -1"
    if kind == "custom":
        kicker = "<2-4 words, ALL CAPS, e.g. 'BEHIND THE SCENES' or 'A TRUE STORY'>"
        title_eg, sub_eg = "HOW A VIDEO MAKES ITSELF", "— FROM ONE IDEA TO YOUTUBE"
        label = '{"name": "<the subject, ALL CAPS>", "detail": "<a short descriptor, ALL CAPS, e.g. \'AN EXPLAINER · 2026\'>"}'
        end_eg, tag0 = "NOW YOU KNOW.", "#storyvaultfiles"
        arc = (f"Structure: a cold-open hook that makes the viewer need the answer (no greeting), then 3-6\n"
               f"chapters that suit the topic, each building on the last, then the payoff stated clearly.\n"
               f"End with a quiet closing line, a question for the comments, and one short line asking them\n"
               f"to subscribe to {CH['name']}.")
        short_end = f'end on the payoff or an open question, then "The full story is on {CH["name"]}."'
    else:
        kicker = "AN UNSOLVED CASE"
        title_eg, sub_eg = "THE DEATH SHIP", "— EVERY MAN ABOARD WAS DEAD"
        label = '{"name": "<the case\'s name, ALL CAPS, e.g. \'SS OURANG MEDAN\'>", "detail": "<PLACE · YEAR, ALL CAPS>"}'
        end_eg, tag0 = "STILL UNSOLVED.", "#unsolvedmysteries"
        arc = ('Structure: cold open hook (no greeting), then "This is case file number <N>.", then chapters:\n'
               "the setting/people, the event, the investigation & evidence, the theories, what remains unknown.\n"
               "End with a quiet reflective line, a question for viewers to answer in the comments,\n"
               "and one short line asking them to subscribe for more case files.")
        short_end = ('end on the unresolved question, then "Tell me what you think happened." and '
                     f'"The full case file is on {CH["name"]}."')

    scenes = "" if fmt == "short" else f"""
 "scenes": [
   {{"chapter": "<chapter name on the first scene of each chapter, else empty string>",
     "shots": [
       {{"text": "<ONE sentence of narration, 6-22 words>",
         "image_prompt": "<the picture for THIS sentence — see VISUALS>",
         "search": ["<2-3 word stock-footage backup search>", "<1 word: the main subject>"],
         "image": <index of a real source photo that shows exactly this ({img}), or -1>}}
     ]}}
 ],"""
    if fmt == "short":
        structure = f"""ONLY A SHORT: there is no long video. Leave out "scenes" — "short" is the whole video.
SHORT: {short_words - 30}-{short_words + 30} words ({short_s - 15}-{short_s + 20} seconds) in 18-32 shots,
a complete standalone story: the first shot hooks in under 2 seconds with the most striking fact;
build through the key moments to a clear payoff; end with a question for the comments, then
"Follow {CH['name']} for more." """
    else:
        structure = f"""NARRATION: the narration is the shots' "text" read in order — there is no other narration.
Total about {words} words ({minutes} minutes) across 4-6 chapters, 3-8 shots per scene.
{arc}
SHORT: {short_words - 30}-{short_words + 20} words ({short_s - 15}-{short_s + 15} seconds) in 18-30 shots,
a complete standalone story: the first shot hooks in under 2 seconds with the most striking fact;
build through the key moments; {short_end}"""

    return f"""Return JSON with exactly these keys:
{{
 "title": "<YouTube title under 70 chars; a date, name or number helps; subject in the first 40 chars>",
 "thumbnail_text": "<2-3 punchy words for the thumbnail, ALL CAPS, not repeating the title's words>",
 "description": "<3 short paragraphs for the YouTube description: hook, what the video covers, a question for the comments. No hashtags here.>",
 "tags": ["<up to 15 search tags>"],
 "hashtags": ["{tag0}", "<3 more>"],
 "look": "<the era, place and setting every picture shares, e.g. '1947, rusting Dutch cargo steamer, Strait of Malacca, tropical haze'>",
 "title_card": {{"kicker": "{kicker}", "title": "<2-5 words, ALL CAPS, e.g. '{title_eg}'>",
                "subtitle": "<— one short hook line, ALL CAPS, e.g. '{sub_eg}'>"}},
 "label": {label},
 "end_line": "<2-4 words for the black end card, ALL CAPS, e.g. '{end_eg}'>",
 "mood": ["<3 backup stock-footage searches that fit this story's world>"],{scenes}
 "short": {{
   "shots": [{{"text": "<one sentence>", "image_prompt": "<picture for it>", "search": ["<2-3 words>", "<1 word>"]}}],
   "caption": "<Instagram caption: 2 short lines + a question>"
 }}
}}

{structure}

VISUALS — the channel's style is one cinematic, photoreal, period-accurate AI picture per sentence,
showing exactly what is being said at that moment:
- "image_prompt" describes ONE concrete scene a camera could film: subject, action, setting, era
  details (clothes, vehicles, equipment), lighting, framing (wide / medium / close-up).
  "The radio operator tapped out his last message" → "close-up of a 1940s ship's radio operator's
  hand on a brass Morse key, cramped radio room, single bulb, sweat on the wood desk"
  "They found the crew on deck, staring at the sky" → "empty steel deck of an old cargo steamer at
  noon, scattered sailors' caps and a fallen chair, harsh sun, eerie stillness"
- Vary framing from sentence to sentence (wide, medium, close detail) like a film editor would.
- Abstract sentences ("No one knows why.") → a concrete, moody image of the thing discussed.
- REAL PEOPLE: never name a real person in a prompt and never ask for a recognisable face of one.
  Show them from behind, in silhouette, at a distance, as hands, or through objects they used.
  Their real photos (the "image" index) are used where they exist.
- No gore and no visible dead bodies: imply death through empty places and left-behind objects.
- No text, signs, newspapers with readable words or logos in pictures.
- "search" is only a backup if the AI picture can't be made: plain common nouns, no names."""


def write_script(topic: dict, source: dict, images: list[dict], case_no: int,
                 kind: str = "case", fmt: str = "both") -> dict:
    img_list = "\n".join(f"[{i}] {im['caption'] or im['file']}" for i, im in enumerate(images)) or "(none)"
    what = (f"a video the channel owner asked for: \"{topic.get('request') or topic.get('working_title')}\""
            if kind == "custom" else f"case file number {case_no}")
    prompt = f"""Write the full {'Short' if fmt == 'short' else 'story video'} script for {what}.

TOPIC: {topic.get('wiki_title') or topic.get('working_title')}
WORKING TITLE: {topic.get('working_title', '')}
ANGLE: {topic.get('hook', '')}

SOURCE PHOTOS AVAILABLE:
{img_list}

SOURCES (the only facts you may use):
\"\"\"{source['text']}\"\"\"

{_script_schema(W['target_minutes'], W['short_seconds'], len(images), kind, fmt)}"""
    fake = fake_script(case_no)
    if fmt == "short":
        fake["scenes"] = []
    return normalize(ask_json(style_for(kind), prompt, temperature=0.85, fake_response=fake))


def revise_script(script: dict, feedback: str, source: dict, images: list[dict],
                  kind: str = "case", fmt: str = "both") -> dict:
    import json
    prompt = f"""The channel owner reviewed this video and asked for changes:

OWNER FEEDBACK: \"\"\"{feedback}\"\"\"

Apply the feedback faithfully. Keep everything else that works. Keep all accuracy rules.

CURRENT SCRIPT JSON:
{json.dumps(script, ensure_ascii=False)}

SOURCES (only facts you may use):
\"\"\"{source['text'][:40000]}\"\"\"

{_script_schema(W['target_minutes'], W['short_seconds'], len(images), kind, fmt)}"""
    return normalize(ask_json(style_for(kind), prompt, temperature=0.7, fake_response=script))


def fake_script(case_no: int) -> dict:
    lines = [
        ("On a cold night in the winter of nineteen fifty nine, nine hikers set out into the mountains.",
         ["hikers snowy mountain", "mountain hikers", "mountain"]),
        ("They were experienced. They were prepared. And not one of them came home.",
         ["empty snowy trail", "snow trail", "snow"]),
        (f"This is case file number {case_no}.", ["old case files", "case files", "files"]),
        ("The search party found their tent weeks later, cut open from the inside.",
         ["torn tent snow", "tent snow", "tent"]),
        ("Footprints led away into the snow, as if everyone had left at once, in the dark.",
         ["footprints in snow", "footprints snow", "footprints"]),
        ("One theory points to the weather. Another to something no one has explained.",
         ["blizzard mountain night", "blizzard", "storm"]),
        ("What would make nine people run from shelter into a freezing night?",
         ["frozen forest night", "frozen forest", "forest"]),
        ("Tell me what you think in the comments, and subscribe for more case files.",
         ["old case files", "case files", "files"]),
    ]
    shots = [{"text": t, "search": q, "image": -1, "image_prompt": f"{q[0]}, 1959, wide cinematic shot"}
             for t, q in lines]
    scenes = [{"chapter": "", "shots": shots[:3]}, {"chapter": "The Expedition", "shots": shots[3:5]},
              {"chapter": "The Theories", "shots": shots[5:]}]
    return normalize({
        "title": "The Night Nine Hikers Ran Into the Snow",
        "thumbnail_text": "WHY THEY RAN",
        "description": "Test description.",
        "tags": ["mystery", "unsolved"],
        "hashtags": ["#unsolvedmysteries", "#mystery"],
        "mood": ["snowy mountain night", "frozen forest", "old documents"],
        "look": "1959, Ural mountains, deep winter",
        "title_card": {"kicker": "AN UNSOLVED CASE", "title": "THE DYATLOV PASS",
                       "subtitle": "— NINE HIKERS. ONE TORN TENT."},
        "label": {"name": "DYATLOV PASS INCIDENT", "detail": "URAL MOUNTAINS · 1959"},
        "end_line": "STILL UNSOLVED.",
        "scenes": scenes,
        "short": {"shots": [shots[0], shots[3], shots[4], shots[6],
                            {"text": f"The full case file is on {CH['name']}.",
                             "search": ["old case files", "case files", "files"], "image": -1}],
                  "caption": "Nine hikers. One tent. No answers.\nWhat do you think happened?"},
    })


def _sentences(text: str) -> list[str]:
    import re
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _clean_search(search, fallback: list[str]) -> list[str]:
    if isinstance(search, str):
        search = [search]
    out = [str(q).strip() for q in (search or []) if str(q).strip()]
    for q in fallback:
        if q not in out:
            out.append(q)
    return out[:5] or ["mystery"]


def normalize(script: dict) -> dict:
    """Make every scene (and the short) a list of shots with text + search ladder.
    Also accepts the older format (scene narration + visuals) so old drafts still render."""
    for sc in script.get("scenes", []):
        if not sc.get("shots"):
            vis = sc.get("visuals") or []
            sents = _sentences(sc.get("narration", ""))
            sc["shots"] = [{"text": t, "search": [vis[i % len(vis)]] if vis else [],
                            "image": sc.get("image", -1) if i == 0 else -1}
                           for i, t in enumerate(sents)]
        shots = []
        for sh in sc["shots"]:
            text = str(sh.get("text", "")).strip()
            if not text:
                continue
            img = sh.get("image", -1)
            shots.append({"text": text, "search": _clean_search(sh.get("search"), sc.get("visuals") or []),
                          "image_prompt": str(sh.get("image_prompt") or "").strip(),
                          "image": img if isinstance(img, int) else -1})
        sc["shots"] = shots
        sc["narration"] = " ".join(s["text"] for s in shots)
    script["scenes"] = [sc for sc in script.get("scenes", []) if sc.get("shots")]
    short = script.get("short") or {}
    if not short.get("shots"):
        vis = short.get("visuals") or ["mystery"]
        short["shots"] = [{"text": t, "search": [vis[i % len(vis)]]}
                          for i, t in enumerate(_sentences(short.get("narration", "")))]
    short["shots"] = [{"text": str(s["text"]).strip(), "search": _clean_search(s.get("search"), []),
                       "image_prompt": str(s.get("image_prompt") or "").strip(),
                       "image": -1} for s in short["shots"] if str(s.get("text", "")).strip()]
    short["narration"] = " ".join(s["text"] for s in short["shots"])
    script["short"] = short
    script["mood"] = [m for m in (script.get("mood") or []) if isinstance(m, str)][:4]
    script["look"] = str(script.get("look") or "").strip()
    tc = script.get("title_card") if isinstance(script.get("title_card"), dict) else {}
    script["title_card"] = {"kicker": str(tc.get("kicker") or "AN UNSOLVED CASE").upper(),
                            "title": str(tc.get("title") or script.get("title", "")).upper(),
                            "subtitle": str(tc.get("subtitle") or "").upper()}
    lb = script.get("label") if isinstance(script.get("label"), dict) else {}
    script["label"] = {"name": str(lb.get("name") or "").upper(), "detail": str(lb.get("detail") or "").upper()}
    script["end_line"] = str(script.get("end_line") or "STILL UNSOLVED.").upper()
    script["picture_salt"] = str(script.get("picture_salt") or "")
    return script

"""Tell the owner on Telegram when GitHub's machine couldn't even set up, so a request never
goes silent. Standard library only: the pipeline's packages may not have installed."""
import json
import os
import sys
import urllib.request

token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not token or not chat:
    sys.exit(0)
what = sys.argv[1] if len(sys.argv) > 1 else "that request"
try:
    payload = json.loads(os.environ.get("SVF_PAYLOAD") or "{}") or {}
except ValueError:
    payload = {}
run_url = os.environ.get("RUN_URL", "")
text = (f"⚠️ GitHub's machine couldn't set up its video tools (a network problem on GitHub's side), "
        f"so nothing happened with {what}. Nothing was lost.\n\n")
body = {"chat_id": chat, "parse_mode": "HTML", "disable_web_page_preview": True}
data = payload.get("data", "") if payload.get("kind") == "button" else ""
if data and len(data.encode()) <= 64:
    text += "Tap below to try again."
    body["reply_markup"] = {"inline_keyboard": [[{"text": "🔁 Try again", "callback_data": data}]]}
elif payload.get("text"):
    text += f"Send <code>{payload['text'][:200]}</code> again to retry."
else:
    text += (f"To retry, open <a href=\"{run_url}\">this run</a> on GitHub and tap <b>Re-run jobs</b>."
             if run_url else "Please try again in a few minutes.")
body["text"] = text
req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=30).read()
except Exception as exc:  # noqa: BLE001
    print("Couldn't reach Telegram:", exc)

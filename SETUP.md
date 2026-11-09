# StoryVaultFiles — Setup Guide

This sets up a pipeline that, **every day at 12:00 PM (Toronto time)**:

1. Sends you 3 unsolved-mystery story ideas on Telegram.
2. When you tap one, Claude (or Gemini as a backup) writes a researched script, records an AI narrator, edits a
   ~10-minute video plus a ~55-second vertical Short, and sends you a preview.
3. When you type notes, rewrites and re-renders. When you tap **Publish**, uploads
   the video to YouTube, the Short to YouTube Shorts, and the Short to Instagram Reels.

**Cost: $0.** Everything below uses free tiers. No credit card is needed anywhere.
**Your time:** about 60–90 minutes, once. After that, two taps a day.

> 💡 Do the steps in order. Keep a note open (Notepad, Notes app) to paste each
> key/token into as you go — you'll need them in step 7.

---

## What you'll create (all free)

| # | Account | What it does |
|---|---------|--------------|
| 1 | Gmail + YouTube channel | Your channel |
| 2 | GitHub | Free cloud computers that build the videos |
| 3 | Google AI Studio | Free AI script writer (Gemini) |
| 4 | Pixabay | Free stock footage (Openverse photos are a no-key backup) |
| 5 | Telegram bot | Where you approve topics and videos |
| 6 | Cloudflare | Free bridge that passes your taps to GitHub |
| 9 | Google Cloud | Lets the pipeline upload to YouTube |
| 10 | Instagram professional account + Meta developer app | Lets it post Reels |
| 12 | Claude routine (your Claude plan) | Claude researches and writes; Gemini is the backup |
| 13 | Workers AI on your Cloudflare Worker | Free AI picture for every sentence |

---

## Step 1 — YouTube channel (10 min)

1. Create a new Gmail account just for the channel (recommended).
2. Go to **youtube.com** → profile picture → **Create a channel**. Name it
   **StoryVaultFiles**, handle **@storyvaultfiles**.
3. Go to **youtube.com/verify** and verify with your phone number.
   This unlocks custom thumbnails and videos longer than 15 minutes.

## Step 2 — GitHub (10 min)

1. Sign up at **github.com** (free).
2. Click **+** (top right) → **New repository**.
   - Name: `storyvaultfiles-pipeline`
   - Choose **Public**. Public repositories get unlimited free build minutes.
     Your passwords stay private in "Secrets" (step 7). Only the code and topic
     list are visible.
   - Click **Create repository**.
3. Put the code in it. Either:
   - **Easiest:** tell Claude "my repo is `<your-username>/storyvaultfiles-pipeline`, push the code", or
   - Click **uploading an existing file**, then drag in **all** files and folders
     from the zip, including the `.github` folder (on a Mac, press
     **Cmd + Shift + .** in Finder to see it). Then click **Commit changes**.
4. Open the repo's **Actions** tab and click **I understand my workflows, go ahead and enable them**
   if you see that button.

## Step 3 — Free AI writer: Gemini key (3 min)

1. Go to **aistudio.google.com** and sign in with your channel Gmail.
2. Click **Get API key** → **Create API key**. Copy it → this is `GEMINI_API_KEY`.

No billing needed. Note: on the free tier, Google may use prompts to improve its
models. Here that's only public Wikipedia facts and scripts.

## Step 4 — Free stock footage (5 min)

1. Sign up at **pixabay.com** (free) and confirm your email.
2. While logged in, open **pixabay.com/api/docs**. Your key is shown in green under
   **Parameters → key**. Copy it → `PIXABAY_API_KEY`.

Pexels has paused new API keys, so it's not needed. If Pixabay finds nothing for a scene,
the pipeline uses freely licensed photos from **Openverse**, which needs no key. If you
ever get a Pexels key, add it as `PEXELS_API_KEY` for extra variety.

## Step 5 — Telegram bot (3 min)

1. Install Telegram and open a chat with **@BotFather** (blue tick).
2. Send `/newbot`. Name: `StoryVaultFiles Studio`. Username: something ending in
   `bot`, e.g. `storyvault_studio_bot`.
3. BotFather replies with a token like `7123456789:AAH…` → `TELEGRAM_BOT_TOKEN`.
4. You don't sign up anywhere for this. Invent a password of 20–40 characters using only
   letters and numbers (no spaces or symbols), or use any password generator, and save it in
   your notes. You'll paste the same text in step 6b and step 7 → `WEBHOOK_SECRET`.

## Step 6 — Cloudflare Worker bridge (15 min)

### 6a. A GitHub token for the bridge
1. GitHub → your profile picture → **Settings** → **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name: `storyvault-bridge`. Expiration: the longest offered (set a calendar
   reminder to renew it).
3. **Repository access** → **Only select repositories** → `storyvaultfiles-pipeline`.
4. **Permissions → Repository permissions:**
   - **Contents:** Read and write
   - **Secrets:** Read and write (lets the pipeline keep Instagram connected)
5. **Generate token**. Copy it → `GH_PAT`.

### 6b. The Worker
1. Sign up at **dash.cloudflare.com** (free).
2. **Workers & Pages** → **Create** → **Create Worker** (Hello World) → name it
   `storyvault-bridge` → **Deploy**.
3. Click **Edit code**. Delete everything, paste the whole contents of
   `worker/telegram-webhook.js`, then click **Deploy**.
4. Copy the Worker's address (like `https://storyvault-bridge.yourname.workers.dev`).
5. Go back to the Worker → **Settings** → **Variables and Secrets** → **Add**:

   | Name | Type | Value |
   |------|------|-------|
   | `TELEGRAM_BOT_TOKEN` | Secret | from step 5 |
   | `WEBHOOK_SECRET` | Secret | from step 5 |
   | `GITHUB_TOKEN` | Secret | `GH_PAT` from 6a |
   | `GITHUB_REPO` | Text | `your-username/storyvaultfiles-pipeline` |

   Leave `TELEGRAM_CHAT_ID` out for now. Click **Deploy** / save.

## Step 7 — Add your secrets to GitHub (10 min)

In your repo: **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Add each one (exact names):

| Secret | From |
|--------|------|
| `GEMINI_API_KEY` | Step 3 |
| `PIXABAY_API_KEY` | Step 4 |
| `TELEGRAM_BOT_TOKEN` | Step 5 |
| `WEBHOOK_SECRET` | Step 5 |
| `GH_PAT` | Step 6a |

You'll add `TELEGRAM_CHAT_ID` (step 8) and the YouTube and Instagram secrets
(steps 9–10) after.

## Step 8 — Connect Telegram (5 min)

1. In GitHub: **Actions** → **Connect Telegram** → **Run workflow** → paste your
   Worker URL → **Run workflow**. Wait for the green tick.
2. In Telegram, open your bot and send `/start`. It replies:
   **"Your chat ID is 123456789"**.
3. Add that number:
   - In Cloudflare: Worker → Settings → Variables → add **Text** `TELEGRAM_CHAT_ID`, then Deploy.
   - In GitHub: secret `TELEGRAM_CHAT_ID`.
4. Run **Connect Telegram** once more. You should get "✅ StoryVaultFiles is connected".

✅ **You can test now:** send `/topics` to your bot. After about 2 minutes you'll get 3 ideas.
Tapping one makes a full video and preview. Publishing will fail until steps 9–10 are done,
which is fine.

## Step 9 — YouTube uploads (20 min)

### 9a. Google Cloud project
1. Go to **console.cloud.google.com** (channel Gmail) → project dropdown →
   **New project** → name `storyvault` → **Create**.
2. Search **YouTube Data API v3** → **Enable**.
3. **APIs & Services** → **OAuth consent screen** (or "Google Auth Platform") →
   **Get started**:
   - App name `StoryVaultFiles Uploader`, your email, **Audience: External**, finish.
   - Under **Audience**, click **Publish app** → confirm, so it says **In production**.
     ⚠️ **Don't skip this.** In "Testing" mode, Google expires your login every 7 days
     and uploads stop. An unverified app in production is fine for personal use.
4. **Clients** (or Credentials) → **Create client** → **Web application**.
   - Under **Authorized redirect URIs** add: `https://developers.google.com/oauthplayground`
   - **Create**. Copy **Client ID** → `YOUTUBE_CLIENT_ID` and
     **Client secret** → `YOUTUBE_CLIENT_SECRET`.

### 9b. Get the permanent upload token
1. Open **developers.google.com/oauthplayground**.
2. Click the ⚙️ gear (top right) → tick **Use your own OAuth credentials** → paste
   the Client ID and secret.
3. In the left box, type these two scopes (press Enter after each):
   `https://www.googleapis.com/auth/youtube.upload`
   `https://www.googleapis.com/auth/youtube`
   then **Authorize APIs**.
4. Sign in with the **channel's** Google account. If you see "Google hasn't verified
   this app", click **Advanced** → **Go to StoryVaultFiles Uploader** → allow. If asked,
   pick the StoryVaultFiles channel.
5. Click **Exchange authorization code for tokens**. Copy the **Refresh token**
   → `YOUTUBE_REFRESH_TOKEN`.
6. Add all three as GitHub secrets.

### 9c. The free API audit (so uploads can be public)
Google forces uploads from new, un-audited API projects to **private**. The pipeline
still uploads; when that happens, Telegram tells you and sends the title, description and
tags so you can finish in YouTube Studio. To lift the limit, apply for the free audit:

1. Search "YouTube API Services audit and quota extension form". It's on
   **support.google.com/youtube/contact/yt_api_form**.
2. Say it's an **internal tool** that uploads videos only to your own channel, with a
   human approving each upload. Link this GitHub repo. Approval usually takes a few weeks.

## Step 10 — Instagram Reels (20 min)

1. In the Instagram app: create the account (e.g. **@storyvaultfiles**) →
   **Settings** → **Account type and tools** → **Switch to professional account** →
   **Creator**.
2. Go to **developers.facebook.com** → log in with Facebook → **My Apps** →
   **Create app** → choose the use case **Manage messaging & content on Instagram**
   (wording may vary) → finish.
3. In the app: **Instagram** → **API setup with Instagram login**.
   - **Generate access tokens** → **Add account** → log in to the Instagram account → allow.
   - Make sure `instagram_business_content_publish` is included.
   - Copy the token → GitHub secret `INSTAGRAM_ACCESS_TOKEN`.
4. Instagram tokens last 60 days. The **Keep Instagram connected** workflow renews it
   twice a month automatically, using `GH_PAT`.

You don't need a Facebook Page and you don't need to submit the app for review. It
stays in development mode, which works for accounts you own.

## Step 11 — Final check

1. GitHub → **Actions** → **Test run (no accounts needed)** → **Run workflow**. After it
   finishes (~10 min), download **sample-videos** to see the video engine works.
2. Telegram: send `/topics` → tap an idea → wait for the preview → tap **Publish**.

From now on it runs by itself every day at noon. 🎉

## Step 12 — Let Claude research and write (10 min, uses your Claude plan)

With this step, **Claude** picks the daily topics, researches each case across several
sources, writes the script, and applies your notes. Gemini stays as the automatic backup.
It uses your existing Claude plan, with no extra cost: each topic list, script or
revision is one "routine run". Pro allows 5 runs a day, Max 15.

1. Open **claude.ai/code/routines** → **New routine**.
2. **Name:** `StoryVaultFiles writer`
3. **Prompt** — paste exactly:
   ```
   You are the StoryVaultFiles writer. Follow ROUTINE.md in this repository exactly.
   The run text tells you the command (TOPICS, SCRIPT <job> or REVISE <job>).
   ```
4. **Repository:** `harsha-k-lab/storyvaultfiles-pipeline`. Leave the default environment.
5. **Trigger:** remove any schedule trigger (GitHub already runs the daily schedule). Click
   **Add another trigger** → **API** → **Generate token**. Copy **both** the URL and the token.
   The token is shown only once.
6. **Save** the routine.
7. In GitHub → **Settings → Secrets and variables → Actions**, add:
   - `CLAUDE_ROUTINE_URL` = the URL from step 5
   - `CLAUDE_ROUTINE_TOKEN` = the token from step 5
8. If you're on **Max**, edit `config.yaml` and set `daily_runs: 15` under `claude:`.

Test it: send `/topics` to your bot. You'll get "🧠 Claude is researching…" with a
link to watch, and the 3 ideas arrive in about 10–15 minutes.

How runs add up per day: topics (1) + script (1) + each revision (1). If Claude's runs
for the day are used up, Gemini writes automatically and the bot tells you.
`/status` shows Claude's runs left today.

## Step 13 — Free AI pictures for every sentence (5 min)

This gives each sentence its own photoreal, period-accurate picture, in the style of the
reference channel. It uses Cloudflare's free Workers AI allowance on the account you already
made in step 6: about 170 pictures a day, enough for one long video plus its Short. If the
day's allowance runs out, the rest of that video uses stock footage automatically.

1. **Update the Worker code.** Open `worker/telegram-webhook.js` in your GitHub repo, click
   **Copy raw file**, then in Cloudflare go to your Worker → **Edit code**, paste over
   everything, and click **Deploy**.
2. **Switch on Workers AI.** In the Worker, go to **Settings → Bindings → Add binding →
   Workers AI**. Set **Variable name** to `AI` and click **Add binding** (then **Deploy** if asked).
3. **Tell GitHub where the Worker is.** In GitHub → **Settings → Secrets and variables →
   Actions**, add `CLOUDFLARE_WORKER_URL` = your Worker address, e.g.
   `https://storyvault-bridge.yourname.workers.dev` (no slash at the end).
4. **Check it.** Open the Worker address in your browser. The settings check should now
   include **✅ Workers AI binding (AI) is connected**.

Each draft's Telegram message says how many AI pictures were made. Real people are never
drawn as recognisable faces: they appear from behind, in silhouette or through objects,
and their real photos are used where Wikipedia has them.

---

## Daily use

| You see… | You do… |
|----------|---------|
| 🗂 3 ideas at noon | Tap ✅ 1, 2 or 3 — or type your own idea ("ghost ships", "D.B. Cooper") |
| 🎬 Preview + Short | Watch. Tap **Publish**, or **type notes** like "intro is too slow, add more about the theories" |
| 🎞 New pictures | Same script, freshly made pictures and clips |
| ⚠️ Something went wrong | Tap **Retry** (most errors are a free service being briefly busy) |

Commands: `/topics` (new ideas now), `/status`, `/help`.

## Changing things

Edit **`config.yaml`** in GitHub (pencil icon → Commit). For example:
- `voice.name` — try `en-GB-RyanNeural` for a British documentary narrator
- `writing.target_minutes` — video length
- `channel.daily_topics_hour` — when ideas arrive
- `publish.youtube.also_upload_short: false` — Shorts only on Instagram
- Drop your own royalty-free `.mp3` tracks into `assets/music/` (e.g. from the
  YouTube Audio Library) to replace the built-in generated soundtrack.

## Staying monetized (important)

YouTube's "inauthentic content" rule targets channels that look mass-produced. This
pipeline is built to stay on the right side of it: original researched scripts, real
case photos, chapters, varied footage, and **you** reviewing every video. To keep it that way:

- **Actually review.** Use the notes feature. Personal touches are your edge.
- **Quality over quantity.** If daily feels like a grind, 4–5 strong videos a week beats 7 weak ones.
- **Stay accurate.** Scripts use only Wikipedia facts, but skim them anyway.
- Shorts bring subscribers. The long videos are what earn money once you're in the Partner Program.

## Free-tier limits (you won't hit these at 1 video/day)

| Service | Free limit |
|---------|-----------|
| GitHub Actions (public repo) | Unlimited minutes; each job up to 6 h |
| Gemini API | Daily request limit per project. If you hit it, tap Retry later |
| Pixabay | 100 requests per minute |
| Cloudflare Workers | 100,000 requests per day |
| YouTube API | Around 100 uploads per day |
| edge-tts voice | Free, unofficial service. If it ever stops, change voice settings or ask Claude for an alternative |

## Troubleshooting

- **No noon message:** GitHub sometimes delays scheduled runs 10–30 minutes. Check
  **Actions → Daily topics**. Run it by hand to test.
- **Buttons do nothing:** re-run **Connect Telegram**. Check the Worker variables,
  and that `GH_PAT` hasn't expired.
- **"Missing secret …":** the named secret isn't in GitHub → Settings → Secrets.
- **YouTube "invalid_grant":** the consent screen is still in Testing, or the token was
  revoked. Redo step 9a(3) and 9b.
- **Instagram fails:** the bot sends the Reel file so you can post it by hand. Then
  check the token (step 10).

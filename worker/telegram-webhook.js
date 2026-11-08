// StoryVaultFiles — Telegram → GitHub bridge (runs free on Cloudflare Workers).
//
// Paste this whole file into a Cloudflare Worker, then add these
// Settings → Variables and Secrets:
//   TELEGRAM_BOT_TOKEN  (secret)  from @BotFather
//   WEBHOOK_SECRET      (secret)  any long random password, same as the GitHub secret
//   GITHUB_TOKEN        (secret)  fine-grained GitHub token for your pipeline repo
//   GITHUB_REPO         (text)    e.g. yourname/storyvaultfiles-pipeline
//   TELEGRAM_CHAT_ID    (text)    leave empty at first — message your bot and it replies with it

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response(await healthCheck(env), {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (env.WEBHOOK_SECRET || "").trim()) {
      return new Response("forbidden", { status: 403 });
    }

    const update = await request.json();
    const cb = update.callback_query;
    const msg = update.message;
    const chatId = String(cb?.message?.chat?.id ?? msg?.chat?.id ?? "");
    if (!chatId) return new Response("ok");

    const tg = (method, body) =>
      fetch(`https://api.telegram.org/bot${(env.TELEGRAM_BOT_TOKEN || "").trim()}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

    // First-time setup: tell the owner their chat ID.
    const ownerChat = (env.TELEGRAM_CHAT_ID || "").trim();
    if (!ownerChat) {
      await tg("sendMessage", {
        chat_id: chatId,
        text: `Your chat ID is ${chatId}\nAdd it as TELEGRAM_CHAT_ID in the Cloudflare Worker and in GitHub secrets.`,
      });
      return new Response("ok");
    }
    // Ignore everyone except the channel owner.
    if (chatId !== ownerChat) return new Response("ok");

    let payload;
    if (cb) {
      payload = { kind: "button", data: cb.data };
      await tg("answerCallbackQuery", { callback_query_id: cb.id, text: "Got it — working on it ⏳" });
      // Remove the buttons so they can't be tapped twice.
      await tg("editMessageReplyMarkup", {
        chat_id: chatId,
        message_id: cb.message.message_id,
        reply_markup: { inline_keyboard: [] },
      });
    } else if (msg?.text) {
      payload = { kind: "text", text: msg.text.slice(0, 3000) };
      await tg("sendChatAction", { chat_id: chatId, action: "typing" });
    } else {
      return new Response("ok");
    }

    const gh = await fetch(`https://api.github.com/repos/${(env.GITHUB_REPO || "").trim()}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${(env.GITHUB_TOKEN || "").trim()}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "storyvaultfiles-bridge",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ event_type: "telegram", client_payload: payload }),
    });
    if (!gh.ok) {
      await tg("sendMessage", {
        chat_id: chatId,
        text: `⚠️ Couldn't start the pipeline (GitHub said ${gh.status}). Check GITHUB_TOKEN and GITHUB_REPO in the Worker.`,
      });
    } else if (!cb) {
      await tg("sendMessage", { chat_id: chatId, text: "⏳ Got it — on it." });
    }
    return new Response("ok");
  },
};

// Opening the Worker's address in a browser runs this check, so setup problems
// show up in plain words. It never prints the secrets themselves.
async function healthCheck(env) {
  const lines = ["StoryVaultFiles bot bridge is running ✅", "", "Settings check:"];
  const clean = (v) => (v || "").trim();

  const token = clean(env.TELEGRAM_BOT_TOKEN);
  if (!token) {
    lines.push("❌ TELEGRAM_BOT_TOKEN is missing. Add it (from @BotFather) and click Deploy.");
  } else {
    try {
      const me = await (await fetch(`https://api.telegram.org/bot${token}/getMe`)).json();
      lines.push(me.ok
        ? `✅ TELEGRAM_BOT_TOKEN works (bot @${me.result.username})`
        : "❌ TELEGRAM_BOT_TOKEN is wrong — Telegram rejected it. Copy it again from @BotFather.");
    } catch (e) {
      lines.push("⚠️ Couldn't reach Telegram to test the token. Refresh in a minute.");
    }
  }

  lines.push(clean(env.WEBHOOK_SECRET)
    ? "✅ WEBHOOK_SECRET is set"
    : "❌ WEBHOOK_SECRET is missing. Add the same password you put in GitHub.");

  const chat = clean(env.TELEGRAM_CHAT_ID);
  lines.push(chat
    ? (/^-?\d+$/.test(chat)
        ? "✅ TELEGRAM_CHAT_ID is set — the bot only answers that chat"
        : "❌ TELEGRAM_CHAT_ID must be only digits. Fix it, or delete it and send /start to the bot.")
    : "ℹ️ TELEGRAM_CHAT_ID not set yet — send /start to your bot and it replies with it");

  const repo = clean(env.GITHUB_REPO);
  const gh = clean(env.GITHUB_TOKEN);
  if (!repo || !/^[\w.-]+\/[\w.-]+$/.test(repo)) {
    lines.push("❌ GITHUB_REPO is missing or not in the form yourname/storyvaultfiles-pipeline");
  } else if (!gh) {
    lines.push("❌ GITHUB_TOKEN is missing. Add your GH_PAT and click Deploy.");
  } else {
    try {
      const r = await fetch(`https://api.github.com/repos/${repo}`, {
        headers: { Authorization: `Bearer ${gh}`, "User-Agent": "storyvaultfiles-bridge",
                   Accept: "application/vnd.github+json" },
      });
      if (r.ok) {
        lines.push(`✅ GITHUB_TOKEN works and can open ${repo} (it also needs Contents: Read and write)`);
      } else if (r.status === 401) {
        lines.push("❌ GITHUB_TOKEN is wrong or expired. Make a new one (SETUP step 6a).");
      } else {
        lines.push(`❌ GITHUB_TOKEN can't open ${repo} (GitHub said ${r.status}). Check the repo name and the token's repository access.`);
      }
    } catch (e) {
      lines.push("⚠️ Couldn't reach GitHub to test the token. Refresh in a minute.");
    }
  }
  return lines.join("\n");
}

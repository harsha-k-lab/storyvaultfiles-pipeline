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
      return new Response("StoryVaultFiles bot bridge is running ✅");
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    const update = await request.json();
    const cb = update.callback_query;
    const msg = update.message;
    const chatId = String(cb?.message?.chat?.id ?? msg?.chat?.id ?? "");
    if (!chatId) return new Response("ok");

    const tg = (method, body) =>
      fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

    // First-time setup: tell the owner their chat ID.
    if (!env.TELEGRAM_CHAT_ID) {
      await tg("sendMessage", {
        chat_id: chatId,
        text: `Your chat ID is ${chatId}\nAdd it as TELEGRAM_CHAT_ID in the Cloudflare Worker and in GitHub secrets.`,
      });
      return new Response("ok");
    }
    // Ignore everyone except the channel owner.
    if (chatId !== String(env.TELEGRAM_CHAT_ID)) return new Response("ok");

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

    const gh = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
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

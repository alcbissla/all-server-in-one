import os
import re
import tempfile
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from main import download_video  # reuse the main download logic

from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
FB_COOKIES = os.getenv("FACEBOOK_COOKIES", "").strip()
TW_COOKIES = os.getenv("TWITTER_COOKIES", "").strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download. Private videos supported!")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not re.match(r"^https?://", url):
        await update.message.reply_text("❌ Please send a valid link.")
        return

    msg = await update.message.reply_text("⏳ Downloading...")

    try:
        # Pass cookies/session info to download_video
        info, file_path = download_video(
            url,
            IG_SESSIONID=IG_SESSIONID,
            FB_COOKIES=FB_COOKIES,
            TW_COOKIES=TW_COOKIES
        )

        caption = info.get("title","Video") if isinstance(info, dict) else getattr(info,"title","Video")
        with open(file_path, "rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)

        try: os.remove(file_path)
        except: pass
        await msg.edit_text("✅ Done!")

    except Exception as e:
        try: await msg.edit_text(f"❌ Failed: {e}")
        except: pass

async def main():
    if not BOT_TOKEN:
        print("No TELEGRAM_BOT_TOKEN set. Exiting.")
        return
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    await app_bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())

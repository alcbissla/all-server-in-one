import os
import re
import asyncio
import tempfile
import requests
import certifi
from uuid import uuid4

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from main import download_video, safe_edit_message  # import your download functions from main.py

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))

# ------------------ Telegram Handlers ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not re.match(r"^https?://", url):
        await update.message.reply_text("❌ Please send a valid link.")
        return

    msg = await update.message.reply_text("⏳ Starting download...")

    try:
        info, file_path = download_video(url, context, update.message.chat_id, msg)
        caption = info.get('title','Video') if isinstance(info, dict) else getattr(info,'title','Video')
        with open(file_path,"rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
        try: os.remove(file_path)
        except: pass
        safe_edit_message(context, update.message.chat_id, msg.message_id, "✅ Done.")
    except Exception as e:
        try: await msg.edit_text(f"❌ Failed: {e}")
        except: pass

# ------------------ Run Bot ------------------
def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set")
        return

    # Create bot application
    app_bot = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    print("Telegram bot started...")
    app_bot.run_polling()  # <-- this works on Render workers

if __name__ == "__main__":
    main()

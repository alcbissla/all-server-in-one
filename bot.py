import os
import re
import threading
from uuid import uuid4
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
load_dotenv()
from main import download_video  # Reuse main.py download logic

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not re.match(r"^https?://", url):
        await update.message.reply_text("❌ Please send a valid link.")
        return
    msg = await update.message.reply_text("⏳ Downloading...")
    try:
        info, file_path = download_video(url)
        caption = info.get('title','Video') if isinstance(info, dict) else getattr(info,'title','Video')
        with open(file_path,"rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
        try: os.remove(file_path)
        except: pass
        await msg.edit_text("✅ Done.")
    except Exception as e:
        try: await msg.edit_text(f"❌ Failed: {e}")
        except: pass

def run_bot():
    if not BOT_TOKEN: return
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app_bot.run_polling()

if __name__=="__main__":
    threading.Thread(target=run_bot).start()

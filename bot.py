import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from main import download_video, safe_edit_message

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("❌ Invalid URL")
        return
    msg = await update.message.reply_text("⏳ Downloading...")
    try:
        info, file_path = download_video(url, context, update.message.chat_id, msg)
        caption = info.get("title", "Video") if isinstance(info, dict) else getattr(info, "title", "Video")
        with open(file_path, "rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
        try: os.remove(file_path)
        except: pass
        safe_edit_message(context, update.message.chat_id, msg.message_id, "✅ Done.")
    except Exception as e:
        try: await msg.edit_text(f"❌ Failed: {e}")
        except: pass

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("Bot is running...")
    app.run_polling()  # <-- must be blocking

if __name__ == "__main__":
    main()

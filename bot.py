import os
import re
import tempfile
import threading
import certifi
import requests
from uuid import uuid4
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from pytube import YouTube

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIKTOK_API = os.getenv("TIKTOK_API")
FACEBOOK_API = os.getenv("FACEBOOK_API")
TWITTER_API = os.getenv("TWITTER_API")
IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
FB_COOKIES = os.getenv("FACEBOOK_CUSER", "").strip()
FB_XS = os.getenv("FACEBOOK_XS", "").strip()
TW_COOKIES = os.getenv("TWITTER_COOKIES", "").strip()

def download_video(url):
    ydl_opts = {"format":"bestvideo+bestaudio/best", "outtmpl":"downloads/%(id)s.%(ext)s", "merge_output_format":"mp4","quiet":True,"noplaylist":True}
    if "instagram.com" in url and IG_SESSIONID:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(f"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tFALSE\t2147483647\tsessionid\t{IG_SESSIONID}")
            f.flush()
            ydl_opts["cookiefile"] = f.name
    if "facebook.com" in url and FB_COOKIES and FB_XS:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(f"c_user={FB_COOKIES}\nxs={FB_XS}")
            f.flush()
            ydl_opts["cookiefile"] = f.name
    if "twitter.com" in url and TW_COOKIES:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(TW_COOKIES)
            f.flush()
            ydl_opts["cookiefile"] = f.name
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"): filename = os.path.splitext(filename)[0]+".mp4"
            return info, filename
    except:
        if "tiktok.com" in url and TIKTOK_API:
            resp = requests.get(f"{TIKTOK_API}{url}", timeout=15, verify=certifi.where()).json()
            if resp.get("code")==0:
                filename=f"downloads/{uuid4()}.mp4"
                return {"title":resp['data'].get("title","TikTok Video")}, filename
        if "youtube.com" in url or "youtu.be" in url:
            yt = YouTube(url)
            filename=f"downloads/{uuid4()}.mp4"
            yt.streams.get_highest_resolution().download(filename=filename)
            return {"title":yt.title}, filename
        raise Exception("Download failed")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not re.match(r"^https?://", url):
        await update.message.reply_text("❌ Invalid URL.")
        return
    msg = await update.message.reply_text("⏳ Downloading...")
    try:
        info, file_path = download_video(url)
        caption = info.get('title','Video') if isinstance(info, dict) else getattr(info,'title','Video')
        with open(file_path,"rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
        os.remove(file_path)
        await msg.edit_text("✅ Done.")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {e}")

def run_bot():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app_bot.run_polling()

if __name__=="__main__":
    run_bot()

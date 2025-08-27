import os, re, time, asyncio, requests, threading, logging
from uuid import uuid4
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, render_template_string, send_file, abort, Response
import yt_dlp
from pytube import YouTube
import instaloader

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, events, utils, errors

# -------- CONFIG ----------
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TELETHON_BOT_TOKEN = os.getenv("TELETHON_BOT_TOKEN", "").strip()  # use bot token

TIKTOK_API = os.getenv("TIKTOK_API", "").strip()
FACEBOOK_API = os.getenv("FACEBOOK_API", "").strip()
TWITTER_API = os.getenv("TWITTER_API", "").strip()

IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "").strip()
FACEBOOK_XS = os.getenv("FACEBOOK_XS", "").strip()
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
os.makedirs("downloads", exist_ok=True)

# Telethon client using BOT TOKEN
telethon_client = TelegramClient("telethon", API_ID, API_HASH).start(bot_token=TELETHON_BOT_TOKEN)

# ---------------- HTML TEMPLATE ----------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>All-in-One Video Downloader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
<style>
/* ... keep your full CSS from above ... */
</style>
</head>
<body>
<header>
<h1><i class="bi bi-download"></i> All-in-One Video Downloader</h1>
<p>#TikTok #YouTube #Facebook #MP4 #M3U8 #HD</p>
</header>
<form class="form-box" action="/" method="post">
<input type="text" name="url" placeholder="Paste your video link here..." required autocomplete="off"/>
<button type="submit"><i class="bi bi-cloud-arrow-down-fill"></i> Download</button>
</form>
{% if error %}<p class="error-msg">{{ error }}</p>{% endif %}
{% if filename %}
<div class="video-preview">
<video autoplay muted controls playsinline>
<source src="/video/{{ filename }}" type="video/mp4"/>
Your browser does not support the video tag.
</video>
<div class="video-title">{{ title }}</div>
<div class="hashtags">{{ hashtags or "No hashtags found" }}</div>
<div style="display:flex;justify-content:center;margin-top:1rem;">
<a href="/video/{{ filename }}" download>
<button><i class="bi bi-cloud-arrow-down-fill"></i> Download Video</button>
</a>
</div>
{% endif %}
<div class="ads-container">
<div class="ad-box"><h3><i class="bi bi-megaphone-fill"></i> Ad Spot 1</h3><p>Promote your service or product here.</p></div>
<div class="ad-box"><h3><i class="bi bi-rocket-takeoff-fill"></i> Ad Spot 2</h3><p>Boost visibility and drive more clicks.</p></div>
</div>
<footer>
&copy; 2025 Smart Downloader.
<div class="social-icons">
<a href="https://t.me/Alcboss112" target="_blank" title="Telegram"><img src="https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg" alt="Telegram"/></a>
<a href="https://www.facebook.com/Alcboss112" target="_blank" title="Facebook"><img src="https://upload.wikimedia.org/wikipedia/commons/1/1b/Facebook_icon.svg" alt="Facebook"/></a>
</div>
</footer>
<script>
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
if(prefersDark){document.documentElement.setAttribute('data-theme','dark');}
</script>
</body>
</html>"""

# ---------------- CLEANUP ----------------
def cleanup_old_files():
    while True:
        now = datetime.now()
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                try:
                    if now - datetime.fromtimestamp(os.path.getmtime(path)) > timedelta(hours=AUTO_CLEANUP_HOURS):
                        os.remove(path)
                        logger.info("🧹 Removed old file: %s", path)
                except Exception as e:
                    logger.debug("cleanup error: %s", e)
        time.sleep(3600)

# ---------------- DOWNLOAD ----------------
def download_video(url, progress_hook=None):
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "noplaylist": True,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook] if progress_hook else []
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not filename.endswith(".mp4"):
            filename = os.path.splitext(filename)[0] + ".mp4"
        return info, filename

# ---------------- FLASK ----------------
@app.route("/", methods=["GET","POST"])
def index():
    title = None
    filename = None
    error = None
    if request.method == "POST":
        url = request.form["url"].strip()
        if not re.match(r"^https?://", url):
            error = "❌ Invalid URL"
        else:
            try:
                info, filename = download_video(url)
                title = info.get("title", "Video")
            except Exception as e:
                error = str(e)
    return render_template_string(HTML_TEMPLATE,
                                  title=title,
                                  filename=os.path.basename(filename) if filename else None,
                                  error=error)

@app.route("/video/<path:filename>")
def serve_video(filename):
    path = os.path.join("downloads", os.path.basename(filename))
    if not os.path.exists(path):
        abort(404)
    def generate():
        with open(path, "rb") as f:
            yield from f
        try:
            os.remove(path)
            logger.info("🗑️ Deleted after serve: %s", path)
        except Exception as e:
            logger.warning("Failed to delete %s: %s", path, e)
    return Response(generate(), mimetype="video/mp4")

# ---------------- TELEGRAM BOT ----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link. I’ll download & upload up to 2 GB.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    url = update.message.text.strip()
    msg = await update.message.reply_text("⏳ Downloading...")
    file_path = None

    def download_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes') or 0
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            percent = downloaded / total * 100
            speed = (d.get('speed') or 0) / 1024 / 1024
            asyncio.run_coroutine_threadsafe(
                msg.edit_text(f"⬇️ Downloading: {percent:.1f}% @ {speed:.2f} MB/s"),
                asyncio.get_event_loop()
            )

    try:
        info, file_path = download_video(url, progress_hook=download_hook)
        caption = info.get("title", "Video")
        sent = await telethon_client.send_file(
            CHANNEL_ID,
            file_path,
            caption=caption,
            progress_callback=lambda sent_bytes, total_bytes: asyncio.run_coroutine_threadsafe(
                msg.edit_text(f"⬆️ Uploading: {sent_bytes / total_bytes * 100:.1f}%"), asyncio.get_event_loop()
            )
        )
        await context.bot.forward_message(
            chat_id=update.message.chat_id,
            from_chat_id=CHANNEL_ID,
            message_id=sent.id
        )
        await msg.edit_text("✅ Done (uploaded to channel & forwarded).")
    except Exception as e:
        logger.exception("handle_link error: %s", e)
        await msg.edit_text(f"❌ Failed: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info("🗑️ Deleted after Telegram upload: %s", file_path)
            except Exception as e:
                logger.warning("Could not delete %s: %s", file_path, e)

def run_telegram_bot():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start_cmd))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app_bot.run_polling()  # blocking, async-safe

# ---------------- MAIN ----------------
if __name__ == "__main__":
    # Start cleanup
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    # Start Flask server
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True
    ).start()
    # Start Telegram bot
    run_telegram_bot()

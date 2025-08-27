import os
import re
import time
import asyncio
import threading
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, render_template_string, abort, Response
import yt_dlp

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from telethon import TelegramClient
from telethon.errors import FloodWaitError

# ========= CONFIG =========
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TELETHON_BOT_TOKEN = os.getenv("TELETHON_BOT_TOKEN", "").strip()

# optional helpers (unused in core file, kept for parity with .env)
TIKTOK_API = os.getenv("TIKTOK_API", "").strip()
FACEBOOK_API = os.getenv("FACEBOOK_API", "").strip()
TWITTER_API = os.getenv("TWITTER_API", "").strip()

IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "").strip()
FACEBOOK_XS = os.getenv("FACEBOOK_XS", "").strip()
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "").strip()

# Backoff guard to avoid frequent ImportBotAuthorization (FloodWait on restarts)
TELETHON_LOGIN_BACKOFF_SECONDS = int(os.getenv("TELETHON_LOGIN_BACKOFF_SECONDS", "600"))
TELETHON_SESSION_NAME = os.getenv("TELETHON_SESSION_NAME", "telethon")  # session file name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========= APP BOOT =========
app = Flask(__name__)
os.makedirs("downloads", exist_ok=True)

# Telethon client instance (not connected yet). Persistent session file name used.
telethon_client = TelegramClient(TELETHON_SESSION_NAME, API_ID, API_HASH)

# ========= HTML TEMPLATE =========
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>All-in-One Video Downloader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
<style>
:root{--bg-light:#f4f4f9;--text-light:#1a1a1a;--bg-dark:#181818;--text-dark:#f5f5f5;--card-light:#fff;--card-dark:#2b2b2b;--accent:#3b82f6}
[data-theme="light"]{--bg:var(--bg-light);--text:var(--text-light);--card:var(--card-light)}
[data-theme="dark"]{--bg:var(--bg-dark);--text:var(--text-dark);--card:var(--card-dark)}
body{margin:0;padding:0;font-family:'Inter',sans-serif;background-color:var(--bg);color:var(--text);display:flex;flex-direction:column;align-items:center;min-height:100vh;transition:background-color .3s,color .3s}
header{text-align:center;margin-top:2rem}
header h1{font-size:2.5rem;margin-bottom:.5rem}
header p{color:var(--accent);font-weight:500}
.video-preview{margin:2rem auto;width:90%;max-width:720px;border-radius:16px;overflow:hidden;box-shadow:0 10px 25px rgba(0,0,0,.1);text-align:center}
video{width:100%;border-radius:16px;max-height:400px}
.form-box{margin-top:1rem;display:flex;flex-direction:column;align-items:center;width:90%;max-width:500px;gap:10px}
input[type="text"]{width:100%;padding:14px 18px;font-size:1rem;border-radius:12px;border:2px solid var(--accent);background-color:var(--card);color:var(--text)}
button{background-color:var(--accent);color:white;font-weight:bold;padding:14px 22px;font-size:1rem;border-radius:12px;border:none;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background-color .3s}
button:hover{background-color:#2563eb}
.ads-container{display:flex;flex-wrap:wrap;justify-content:center;gap:20px;padding:2rem 1rem;width:100%;box-sizing:border-box}
.ad-box{background-color:var(--card);color:var(--text);padding:20px;border-radius:16px;box-shadow:0 4px 12px rgba(0,0,0,.1);width:280px;text-align:center;transition:transform .2s ease}
.ad-box:hover{transform:translateY(-5px)}
footer{margin-top:auto;padding:1.5rem;text-align:center}
.social-icons a{margin:0 10px;Display:inline-block}
.social-icons img{width:32px;height:32px;transition:transform .3s}
.social-icons img:hover{transform:scale(1.1)}
.error-msg{margin-top:1rem;color:#e53e3e;font-weight:700;text-align:center}
.video-title{margin-top:1rem;font-weight:700;font-size:1.25rem;color:var(--text)}
.hashtags{margin-top:.25rem;color:var(--accent);font-weight:600}
@media(min-width:768px){.form-box{flex-direction:row}input[type="text"]{flex:1}button{flex-shrink:0}}
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

# ========= HOUSEKEEPING =========
def cleanup_old_files():
    """Delete files older than AUTO_CLEANUP_HOURS from ./downloads."""
    while True:
        try:
            now = datetime.now()
            for f in os.listdir("downloads"):
                path = os.path.join("downloads", f)
                if os.path.isfile(path):
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(path))
                        if now - mtime > timedelta(hours=AUTO_CLEANUP_HOURS):
                            os.remove(path)
                            logger.info("🧹 Removed old file: %s", path)
                    except Exception as e:
                        logger.debug("cleanup error for %s: %s", path, e)
        except Exception as e:
            logger.debug("cleanup loop error: %s", e)
        time.sleep(3600)

# ========= DOWNLOADER =========
def download_video(url, progress_hook=None):
    """Blocking download via yt-dlp. Returns (info, mp4_path)."""
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "noplaylist": True,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook] if progress_hook else [],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not filename.endswith(".mp4"):
            root, _ = os.path.splitext(filename)
            filename = root + ".mp4"
        return info, filename

# ========= FLASK =========
@app.route("/", methods=["GET", "POST"])
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
    return render_template_string(
        HTML_TEMPLATE,
        title=title,
        filename=os.path.basename(filename) if filename else None,
        error=error,
    )

@app.route("/video/<path:filename>")
def serve_video(filename):
    path = os.path.join("downloads", os.path.basename(filename))
    if not os.path.exists(path):
        abort(404)

    def generate():
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                yield chunk
        try:
            os.remove(path)
            logger.info("🗑️ Deleted after serve: %s", path)
        except Exception as e:
            logger.warning("Failed to delete %s: %s", path, e)

    return Response(generate(), mimetype="video/mp4")

# ========= TELEGRAM (PTB + Telethon) =========
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link. I’ll download & upload up to 2 GB.")

def _make_download_hook(message, loop):
    """Create a yt-dlp progress hook that edits the Telegram message from any thread."""
    def hook(d):
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            percent = downloaded / total * 100
            speed = (d.get("speed") or 0) / 1024 / 1024
            asyncio.run_coroutine_threadsafe(
                message.edit_text(f"⬇️ Downloading: {percent:.1f}% @ {speed:.2f} MB/s"),
                loop,
            )
    return hook

def _make_upload_cb(message, loop):
    """Telethon upload progress -> edit Telegram message (thread-safe)."""
    def cb(sent_bytes: int, total_bytes: int):
        try:
            pct = (sent_bytes / max(total_bytes, 1)) * 100
        except Exception:
            pct = 0.0
        asyncio.run_coroutine_threadsafe(
            message.edit_text(f"⬆️ Uploading: {pct:.1f}%"),
            loop,
        )
    return cb

async def handle_link(telethon_client: TelegramClient, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single handler implementation; wrapped with PTB to inject telethon_client."""
    if not update.message or not update.message.text:
        return
    url = update.message.text.strip()
    msg = await update.message.reply_text("⏳ Downloading...")
    loop = asyncio.get_running_loop()
    file_path = None

    try:
        # run blocking yt-dlp in a thread, but still show progress back to the bot chat
        info, file_path = await loop.run_in_executor(
            None,
            lambda: download_video(url, progress_hook=_make_download_hook(msg, loop)),
        )
        caption = info.get("title", "Video")

        # Upload to channel with Telethon (progress callback edits same message)
        await telethon_client.send_file(
            entity=CHANNEL_ID,
            file=file_path,
            caption=caption,
            progress_callback=_make_upload_cb(msg, loop),
        )

        # Forward from channel to the user via Bot API
        # get last message from channel (the one we just uploaded)
        msgs = await telethon_client.get_messages(CHANNEL_ID, limit=1)
        if msgs:
            last_msg_id = msgs[0].id
            await context.bot.forward_message(
                chat_id=update.message.chat_id,
                from_chat_id=CHANNEL_ID,
                message_id=last_msg_id,
            )
        await msg.edit_text("✅ Done (uploaded to channel & forwarded).")

    except Exception as e:
        logger.exception("handle_link error: %s", e)
        try:
            await msg.edit_text(f"❌ Failed: {e}")
        except Exception:
            pass
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info("🗑️ Deleted after Telegram upload: %s", file_path)
            except Exception as e:
                logger.warning("Could not delete %s: %s", file_path, e)

# ========= RUNNERS =========
def run_flask():
    # Use built-in server for simplicity (Render will proxy). This runs in a thread.
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

async def ensure_telethon_bot_session(client: TelegramClient):
    """
    Start Telethon bot session safely:
    - Connect
    - Only sign_in(bot_token=...) if not authorized
    - Catch FloodWaitError and back off (avoid crashing app)
    """
    await client.connect()
    try:
        if not await client.is_user_authorized():
            # simple file timestamp guard to avoid repeated sign_in on rapid restarts
            stamp_file = ".telethon_login_stamp"
            now = time.time()
            last = 0
            try:
                if os.path.exists(stamp_file):
                    last = os.path.getmtime(stamp_file)
            except Exception:
                pass
            if now - last < TELETHON_LOGIN_BACKOFF_SECONDS:
                logger.warning(
                    "Skipping Telethon sign_in to avoid FloodWait (last login %.0fs ago).",
                    now - last,
                )
            else:
                await client.sign_in(bot_token=TELETHON_BOT_TOKEN)
                try:
                    with open(stamp_file, "a"):
                        os.utime(stamp_file, None)
                except Exception:
                    pass
        else:
            logger.info("Telethon session already authorized.")
    except FloodWaitError as fw:
        # Don't crash the service; log and continue (uploads disabled until next restart)
        logger.error("Telethon FloodWait: wait %s seconds. Continuing without re-login.", fw.seconds)
    except Exception as e:
        logger.exception("Telethon init error: %s", e)

async def run_ptb_and_telethon():
    # Ensure Telethon session is ready
    await ensure_telethon_bot_session(telethon_client)

    # PTB Application (v20+). Using run_polling to avoid low-level Updater usage.
    app_bot = Application.builder().token(BOT_TOKEN).build()

    # Handler wrapper injecting telethon_client
    async def _handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await handle_link(telethon_client, update, context)

    app_bot.add_handler(CommandHandler("start", start_cmd))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_link))

    # Start PTB polling loop (this will run until termination)
    # close_loop=False ensures we don't close the outer asyncio loop when PTB finishes.
    await app_bot.run_polling(close_loop=False)

async def main():
    # Start background maintenance threads
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()

    # Run PTB + Telethon in this loop
    try:
        await run_ptb_and_telethon()
    finally:
        # Gracefully disconnect Telethon when shutting down
        try:
            if telethon_client and getattr(telethon_client, "is_connected", None):
                # if real method available
                await telethon_client.disconnect()
            else:
                await telethon_client.disconnect()
        except Exception as e:
            logger.warning("Telethon disconnect failed: %s", e)

if __name__ == "__main__":
    asyncio.run(main())

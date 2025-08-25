import os
import re
import time
import asyncio
import requests
import threading
from uuid import uuid4
from datetime import datetime, timedelta
import tempfile
import certifi

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, render_template_string, send_file, abort
import yt_dlp
from pytube import YouTube
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ================= CONFIG =================
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
PORT = int(os.getenv("PORT", "10000"))

TIKTOK_API = os.getenv("TIKTOK_API", "https://www.tikwm.com/api/?url=").strip()
FACEBOOK_API = os.getenv("FACEBOOK_API", "").strip()
TWITTER_API = os.getenv("TWITTER_API", "").strip()

IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "").strip()
FACEBOOK_XS = os.getenv("FACEBOOK_XS", "").strip()

app = Flask(__name__)
os.makedirs("downloads", exist_ok=True)

# ================= HTML TEMPLATE =================
HTML_TEMPLATE = """ 
<!DOCTYPE html>
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
.social-icons a{margin:0 10px;display:inline-block}
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
</html>
"""

# ================= UTIL =================
def _get_loop_from_context(context: ContextTypes.DEFAULT_TYPE):
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        pass
    return getattr(getattr(context, "application", None), "loop", None) or getattr(getattr(context, "application", None), "_loop", None)

def safe_edit_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text: str):
    if not context:
        return
    try:
        loop = _get_loop_from_context(context)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text),
                loop
            )
        else:
            asyncio.run(context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text))
    except Exception as e:
        print(f"[safe_edit_message] Failed: {e}")

# ================= AUTO CLEANUP =================
def cleanup_old_files():
    while True:
        now = datetime.now()
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if now - datetime.fromtimestamp(mtime) > timedelta(hours=AUTO_CLEANUP_HOURS):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
        time.sleep(3600)

# ================= DOWNLOAD VIDEO =================
def download_video(url, context=None, chat_id=None, message=None):
    try:
        def progress_hook(d):
            if d.get("status") == "downloading" and context and chat_id and message:
                percent = d.get("_percent_str","").strip()
                speed = d.get("_speed_str","").strip()
                eta = d.get("_eta_str","")
                safe_edit_message(context, chat_id, message.message_id,
                                  f"⬇️ Downloading...\nProgress: {percent}\nSpeed: {speed}\nETA: {eta}")

        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "progress_hooks": [progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                base, _ = os.path.splitext(filename)
                alt = base + ".mp4"
                if os.path.exists(alt):
                    filename = alt
            meta = {"title": info.get("title") or "Video"}
            return meta, filename
    except Exception as e:
        print("yt-dlp failed:", e)

    try:
        if "youtube.com" in url or "youtu.be" in url:
            yt = YouTube(url)
            stream = yt.streams.get_highest_resolution()
            filename = f"downloads/{uuid4()}.mp4"
            stream.download(filename=filename)
            return {"title": yt.title}, filename
    except Exception as e:
        print("pytube fallback failed:", e)

    raise Exception("All download methods failed")

# ================= FLASK =================
@app.route("/", methods=["GET","POST"])
def index():
    title = None
    hashtags = None
    filename = None
    error = None
    if request.method=="POST":
        url = request.form["url"].strip()
        if not re.match(r"^https?://", url):
            error="❌ Invalid URL. Please enter a proper video link."
        else:
            try:
                info, filename = download_video(url)
                title = (info or {}).get("title","No Title")
                tags = (info or {}).get("tags") or []
                hashtags = " ".join(f"#{tag}" for tag in tags[:5])
            except Exception as e:
                error=f"❌ Error: {e}"
    return render_template_string(HTML_TEMPLATE, title=title, hashtags=hashtags,
                                  filename=os.path.basename(filename) if filename else None,
                                  error=error)

@app.route("/video/<path:filename>")
def serve_video(filename):
    safe_path = os.path.join("downloads", os.path.basename(filename))
    if not os.path.exists(safe_path):
        abort(404)
    return send_file(safe_path, as_attachment=False)

# ================= TELEGRAM =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()
    if not re.match(r"^https?://", url):
        await update.message.reply_text("❌ Please send a valid link.")
        return

    msg = await update.message.reply_text("⏳ Starting download...")
    file_path = None
    try:
        info, file_path = download_video(url, context, update.message.chat_id, msg)
        caption = info.get('title','Video')

        try:
            with open(file_path, "rb") as f:
                await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
            safe_edit_message(context, update.message.chat_id, msg.message_id, "✅ Done.")
        except Exception as e:
            if CHANNEL_ID:
                try:
                    with open(file_path, "rb") as f:
                        sent = await context.bot.send_video(chat_id=int(CHANNEL_ID), video=f, caption=caption)
                    await context.bot.forward_message(
                        chat_id=update.message.chat_id,
                        from_chat_id=int(CHANNEL_ID),
                        message_id=sent.message_id
                    )
                    safe_edit_message(context, update.message.chat_id, msg.message_id, "✅ Done (forwarded).")
                except Exception as e2:
                    await msg.edit_text(f"❌ Failed even with channel fallback: {e2}")
            else:
                await msg.edit_text(f"❌ Failed: {e}")
    except Exception as e:
        try: await msg.edit_text(f"❌ Failed: {e}")
        except: pass
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

def run_telegram_bot():
    if not BOT_TOKEN:
        print("No TELEGRAM_BOT_TOKEN set, skipping Telegram bot.")
        return
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app_bot.run_polling()

# ================= MAIN =================
if __name__=="__main__":
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()
    run_telegram_bot()

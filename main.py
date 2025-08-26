# main.py
import os
import re
import time
import asyncio
import threading
from uuid import uuid4
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, render_template_string, send_file, abort
import yt_dlp
from pytube import YouTube

from pyrogram import Client
from pyrogram.types import Message

# ================= CONFIG =================
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
PORT = int(os.getenv("PORT", "10000"))

SESSION_NAME = os.getenv("PYRO_SESSION_FILE", "pyro_session")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))

TIKTOK_API = os.getenv("TIKTOK_API", "").strip()
FACEBOOK_API = os.getenv("FACEBOOK_API", "").strip()
TWITTER_API = os.getenv("TWITTER_API", "").strip()

IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "").strip()
FACEBOOK_XS = os.getenv("FACEBOOK_XS", "").strip()

# ================= FLASK =================
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
body{margin:0;padding:0;font-family:'Inter',sans-serif;background:#f4f4f9;color:#1a1a1a;display:flex;flex-direction:column;align-items:center;min-height:100vh}
header{text-align:center;margin-top:2rem}
header h1{font-size:2.5rem;margin-bottom:.5rem}
header p{color:#3b82f6;font-weight:500}
.video-preview{margin:2rem auto;width:90%;max-width:720px;border-radius:16px;overflow:hidden;text-align:center}
video{width:100%;border-radius:16px;max-height:400px}
.form-box{margin-top:1rem;display:flex;flex-direction:column;align-items:center;width:90%;max-width:500px;gap:10px}
input[type="text"]{width:100%;padding:14px 18px;font-size:1rem;border-radius:12px;border:2px solid #3b82f6;background:#fff;color:#1a1a1a}
button{background-color:#3b82f6;color:white;font-weight:bold;padding:14px 22px;font-size:1rem;border-radius:12px;border:none;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background-color .3s}
button:hover{background-color:#2563eb}
.error-msg{margin-top:1rem;color:#e53e3e;font-weight:700;text-align:center}
.video-title{margin-top:1rem;font-weight:700;font-size:1.25rem;color:#1a1a1a}
.hashtags{margin-top:.25rem;color:#3b82f6;font-weight:600}
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
</div>
{% endif %}
</body>
</html>
"""

# ================= UTILS =================
def download_video(url):
    try:
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "merge_output_format": "mp4",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                base, _ = os.path.splitext(filename)
                alt = base + ".mp4"
                if os.path.exists(alt):
                    filename = alt
            meta = {"title": info.get("title") or "Video", "tags": info.get("tags", [])}
            return meta, filename
    except Exception as e:
        # fallback pytube
        if "youtube.com" in url or "youtu.be" in url:
            yt = YouTube(url)
            stream = yt.streams.get_highest_resolution()
            filename = f"downloads/{uuid4()}.mp4"
            stream.download(filename=filename)
            return {"title": yt.title, "tags": []}, filename
    raise Exception("Download failed")

# ================= AUTO CLEANUP =================
def cleanup_old_files():
    while True:
        now = datetime.now()
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if now - datetime.fromtimestamp(mtime) > timedelta(hours=AUTO_CLEANUP_HOURS):
                    try: os.remove(path)
                    except: pass
        time.sleep(3600)

# ================= FLASK ROUTES =================
@app.route("/", methods=["GET","POST"])
def index():
    title, hashtags, filename, error = None, None, None, None
    if request.method == "POST":
        url = request.form["url"].strip()
        if not re.match(r"^https?://", url):
            error = "❌ Invalid URL"
        else:
            try:
                info, filename = download_video(url)
                title = info.get("title","No Title")
                tags = info.get("tags") or []
                hashtags = " ".join(f"#{tag}" for tag in tags[:5])
            except Exception as e:
                error = f"❌ {e}"
    return render_template_string(HTML_TEMPLATE, title=title, hashtags=hashtags,
                                  filename=os.path.basename(filename) if filename else None,
                                  error=error)

@app.route("/video/<path:filename>")
def serve_video(filename):
    safe_path = os.path.join("downloads", os.path.basename(filename))
    if not os.path.exists(safe_path):
        abort(404)
    return send_file(safe_path, as_attachment=False)

# ================= PYROGRAM BOT =================
app_pyro = Client(
    SESSION_NAME,
    api_id=int(os.getenv("TELEGRAM_API_ID",0)),
    api_hash=os.getenv("TELEGRAM_API_HASH",""),
    phone_number=os.getenv("TELEGRAM_PHONE","")
)

async def handle_message(client: Client, message: Message):
    url = message.text.strip()
    if not re.match(r"^https?://", url):
        await message.reply_text("❌ Please send a valid link.")
        return
    msg = await message.reply_text("⏳ Downloading video...")
    try:
        info, file_path = download_video(url)
        caption = info.get("title","Video")
        # always upload to channel first
        sent = await client.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=file_path, caption=caption)
        await client.forward_messages(chat_id=message.chat.id, from_chat_id=TELEGRAM_CHANNEL_ID, message_ids=sent.message_id)
        await msg.edit_text("✅ Done (via channel).")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {e}")
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

def run_pyrogram():
    app_pyro.start()
    app_pyro.add_handler(app_pyro.on_message()(handle_message))
    print("Pyrogram bot started")
    app_pyro.idle()

# ================= MAIN =================
if __name__ == "__main__":
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()
    run_pyrogram()

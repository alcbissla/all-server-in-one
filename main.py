import os
import re
import time
import requests
import threading
from uuid import uuid4
from datetime import datetime, timedelta

from flask import Flask, request, render_template_string, send_file
import yt_dlp
from pytube import YouTube
import instaloader
import snscrape.modules.twitter as sntwitter

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ================= CONFIG =================
AUTO_CLEANUP_HOURS = 12
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", None)

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
.social-icons img{width:32px;height:32px;transition:transform .3s ease}
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

# ================= AUTO CLEANUP =================
def cleanup_old_files():
    while True:
        now = datetime.now()
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                if now - mtime > timedelta(hours=AUTO_CLEANUP_HOURS):
                    os.remove(path)
        time.sleep(3600)


# ================= GENERIC STREAM DOWNLOAD WITH PROGRESS =================
def stream_download(file_url, filename, context=None, chat_id=None, message=None):
    resp = requests.get(file_url, stream=True)
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    start_time = time.time()

    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=256*1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)

                if context and chat_id and message and total > 0:
                    percent = (downloaded / total) * 100
                    elapsed = time.time() - start_time
                    speed = (downloaded / 1024 / 1024) / elapsed
                    eta = (total - downloaded) / (downloaded / elapsed) if downloaded else 0
                    eta_str = time.strftime("%M:%S", time.gmtime(eta))
                    text = f"⬇️ Downloading...\nProgress: {percent:.1f}%\nSpeed: {speed:.2f} MB/s\nETA: {eta_str}"
                    try:
                        context.bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text=text)
                    except Exception:
                        pass
    return filename


# ================= UNIFIED DOWNLOAD VIDEO =================
def download_video(url, context=None, chat_id=None, message=None):
    try:
        # TikTok
        if "tiktok.com" in url:
            api = f"https://www.tikwm.com/api/?url={url}"
            resp = requests.get(api).json()
            if resp["code"] != 0:
                raise Exception("TikTok API failed")
            video_url = resp["data"]["play"]
            filename = f"downloads/{uuid4()}.mp4"
            return {"title": resp["data"]["title"], "tags": resp["data"].get("tags", [])}, \
                   stream_download(video_url, filename, context, chat_id, message)

        # Instagram
        if "instagram.com" in url:
            L = instaloader.Instaloader(dirname_pattern="downloads", download_videos=True, save_metadata=False)
            shortcode = url.split("/")[-2]
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            filename = f"downloads/{shortcode}.mp4"
            if context and chat_id and message:
                context.bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text="⏳ Downloading Instagram...")
            L.download_post(post, target="downloads")
            return {"title": post.title or "Instagram Video"}, filename

        # Twitter/X
        if "twitter.com" in url or "x.com" in url:
            tweet_id = url.split("/")[-1].split("?")[0]
            for tweet in sntwitter.TwitterTweetScraper(tweet_id).get_items():
                media_url = tweet.media[0].variants[-1].url
                filename = f"downloads/{uuid4()}.mp4"
                return {"title": tweet.content[:50]}, \
                       stream_download(media_url, filename, context, chat_id, message)
            raise Exception("No media found in tweet")

        # YouTube / Facebook / others via yt-dlp
        def progress_hook(d):
            if d['status'] == 'downloading' and context and chat_id and message:
                percent = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '').strip()
                eta = d.get('_eta_str', '')
                text = f"⬇️ Downloading...\nProgress: {percent}\nSpeed: {speed}\nETA: {eta}"
                try:
                    context.bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text=text)
                except Exception:
                    pass
            elif d['status'] == 'finished' and context and chat_id and message:
                try:
                    context.bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text="📦 Processing...")
                except Exception:
                    pass

        ydl_opts = {
            "format": "mp4",
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "progress_hooks": [progress_hook],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return info, filename

    except Exception as e:
        # Fallback YouTube via pytube
        if "youtube.com" in url or "youtu.be" in url:
            yt = YouTube(url)
            if context and chat_id and message:
                def on_progress(stream, chunk, bytes_remaining):
                    total = stream.filesize
                    downloaded = total - bytes_remaining
                    percent = (downloaded / total) * 100
                    elapsed = time.time() - start_time
                    speed = (downloaded / 1024 / 1024) / elapsed
                    eta = (total - downloaded) / (downloaded / elapsed) if downloaded else 0
                    eta_str = time.strftime("%M:%S", time.gmtime(eta))
                    text = f"⬇️ Downloading...\nProgress: {percent:.1f}%\nSpeed: {speed:.2f} MB/s\nETA: {eta_str}"
                    try:
                        context.bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text=text)
                    except Exception:
                        pass

                yt.register_on_progress_callback(on_progress)
                start_time = time.time()
            stream = yt.streams.get_highest_resolution()
            filename = f"downloads/{uuid4()}.mp4"
            stream.download(filename=filename)
            return {"title": yt.title}, filename
        else:
            raise e


# ================= FLASK ROUTES =================
@app.route("/", methods=["GET", "POST"])
def index():
    title = None
    hashtags = None
    filename = None
    error = None

    if request.method == "POST":
        url = request.form["url"].strip()
        if not re.match(r"^https?://", url):
            error = "❌ Invalid URL. Please enter a proper video link."
        else:
            try:
                info, filename = download_video(url)
                title = info.get("title", "No Title")
                hashtags = " ".join(f"#{tag}" for tag in info.get("tags", [])[:5])
            except Exception as e:
                error = f"❌ Error: {str(e)}"

    return render_template_string(HTML_TEMPLATE, title=title, hashtags=hashtags, filename=filename, error=error)


@app.route("/video/<filename>")
def serve_video(filename):
    return send_file(f"downloads/{filename}", as_attachment=False)


# ================= TELEGRAM BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video link to download.")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    msg = await update.message.reply_text("⏳ Starting download...")
    try:
        info, file_path = download_video(url, context, update.message.chat_id, msg)
        caption = f"{info.get('title','Video')}"
        with open(file_path, "rb") as f:
            await context.bot.send_video(chat_id=update.message.chat_id, video=f, caption=caption)
        os.remove(file_path)
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {e}")


def run_telegram_bot():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app_bot.run_polling()


# ================= MAIN START =================
if __name__ == "__main__":
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    run_telegram_bot()

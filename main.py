import os
import re
import time
import threading
from uuid import uuid4
from datetime import datetime, timedelta
import tempfile
import certifi
import requests

from flask import Flask, request, render_template_string, send_file, abort
from dotenv import load_dotenv
import yt_dlp
from pytube import YouTube

load_dotenv()

# ================= CONFIG =================
AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
PORT = int(os.getenv("PORT", "10000"))

TIKTOK_API = os.getenv("TIKTOK_API", "https://www.tikwm.com/api/?url=")
FACEBOOK_API = os.getenv("FACEBOOK_API", "")
TWITTER_API = os.getenv("TWITTER_API", "")
IG_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "").strip()
FB_COOKIES = os.getenv("FACEBOOK_CUSER", "").strip()
FB_XS = os.getenv("FACEBOOK_XS", "").strip()
TW_COOKIES = os.getenv("TWITTER_COOKIES", "").strip()

app = Flask(__name__)
os.makedirs("downloads", exist_ok=True)

# ================= HTML =================
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
.error-msg{margin-top:1rem;color:#e53e3e;font-weight:700;text-align:center}
.video-title{margin-top:1rem;font-weight:700;font-size:1.25rem;color:var(--text)}
.hashtags{margin-top:.25rem;color:var(--accent);font-weight:600}
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

<script>
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
if(prefersDark){document.documentElement.setAttribute('data-theme','dark');}
</script>
</body>
</html>
"""

# ================= UTIL =================
def cleanup_old_files():
    while True:
        now = datetime.now()
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path) and now - datetime.fromtimestamp(os.path.getmtime(path)) > timedelta(hours=AUTO_CLEANUP_HOURS):
                try: os.remove(path)
                except: pass
        time.sleep(3600)

def stream_download(file_url, filename):
    resp = requests.get(file_url, stream=True, timeout=30, verify=certifi.where())
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=256*1024):
            if chunk: f.write(chunk)
    return filename

# ================= DOWNLOAD VIDEO =================
def download_video(url):
    ydl_opts = {"format":"bestvideo+bestaudio/best", "outtmpl":"downloads/%(id)s.%(ext)s", "merge_output_format":"mp4","quiet":True,"noplaylist":True}
    
    # Instagram cookies
    if "instagram.com" in url and IG_SESSIONID:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(f"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tFALSE\t2147483647\tsessionid\t{IG_SESSIONID}")
            f.flush()
            ydl_opts["cookiefile"] = f.name
    # Facebook cookies
    if "facebook.com" in url and FB_COOKIES and FB_XS:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(f"c_user={FB_COOKIES}\nxs={FB_XS}")
            f.flush()
            ydl_opts["cookiefile"] = f.name
    # Twitter cookies
    if "twitter.com" in url and TW_COOKIES:
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(TW_COOKIES)
            f.flush()
            ydl_opts["cookiefile"] = f.name

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"
            return info, filename
    except Exception as e:
        print("yt-dlp failed:", e)
    
    # Fallback TikTok API
    if "tiktok.com" in url and TIKTOK_API:
        try:
            resp = requests.get(f"{TIKTOK_API}{url}", timeout=15, verify=certifi.where()).json()
            if resp.get("code")==0:
                video_url = resp["data"]["play"]
                filename = f"downloads/{uuid4()}.mp4"
                return {"title":resp['data'].get("title","TikTok Video")}, stream_download(video_url, filename)
        except: pass
    
    # Fallback YouTube
    if "youtube.com" in url or "youtu.be" in url:
        try:
            from pytube import YouTube
            yt = YouTube(url)
            stream = yt.streams.get_highest_resolution()
            filename = f"downloads/{uuid4()}.mp4"
            stream.download(filename=filename)
            return {"title":yt.title}, filename
        except: pass

    raise Exception("All download methods failed")

# ================= FLASK =================
@app.route("/", methods=["GET","POST"])
def index():
    filename = None
    title = None
    hashtags = None
    error = None
    if request.method=="POST":
        url = request.form.get("url","").strip()
        if not re.match(r"^https?://", url):
            error="❌ Invalid URL."
        else:
            try:
                info, filename = download_video(url)
                title = info.get("title","No Title") if isinstance(info, dict) else getattr(info,"title","No Title")
                tags = info.get("tags",[]) if isinstance(info, dict) else []
                hashtags = " ".join(f"#{t}" for t in tags[:5])
            except Exception as e:
                error=f"❌ Error: {e}"
    return render_template_string(HTML_TEMPLATE, filename=os.path.basename(filename) if filename else None, title=title, hashtags=hashtags, error=error)

@app.route("/video/<path:filename>")
def serve_video(filename):
    safe_path = os.path.join("downloads", os.path.basename(filename))
    if not os.path.exists(safe_path): abort(404)
    return send_file(safe_path, as_attachment=False)

if __name__=="__main__":
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)

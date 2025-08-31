
#!/usr/bin/env python3
"""
All-in-One Social Media Video Downloader Telegram Bot
Supports: YouTube, Facebook, TikTok, Twitter, Instagram, m3u8 streams
Features: HD downloads up to 2GB, fallback mechanisms, progress tracking
"""

import asyncio
import os
import sys
import time
import tempfile
import shutil
import logging
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# Core async libraries
import httpx
import aiohttp
from aiofiles import open as aopen
import nest_asyncio

# Telegram bot
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError

# Video downloaders and processors
import yt_dlp
from instaloader import Instaloader
from instagrapi import Client as InstaClient
import moviepy.editor as mp
from moviepy.video.io.VideoFileClip import VideoFileClip

# Web scraping and automation
from playwright.async_api import async_playwright
import cloudscraper
from bs4 import BeautifulSoup

# Utilities
from tqdm.asyncio import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
import m3u8
from dotenv import load_dotenv

# Flask web server
from flask import Flask, jsonify, render_template_string, request
from werkzeug.middleware.proxy_fix import ProxyFix
import threading

# Load environment variables
load_dotenv()

# Verify bot token is loaded
if not os.getenv("TELEGRAM_BOT_TOKEN"):
    logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment!")
    logger.info("📝 Please check your .env file or environment variables")
else:
    logger.info("✅ Bot token loaded successfully")

# Enable nested async loops
nest_asyncio.apply()

# Configure logging with error handling
logger.remove()
try:
    logger.add(
        sys.stdout, 
        level="INFO", 
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        catch=True,
        backtrace=False,
        diagnose=False
    )
    logger.add(
        "bot.log", 
        rotation="10 MB", 
        retention="7 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        catch=True,
        backtrace=False,
        diagnose=False
    )
except Exception as e:
    # Fallback to basic logging if loguru fails
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    print(f"Loguru setup failed, using basic logging: {e}")

class Config:
    """Configuration management"""
    # Telegram settings
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
    TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
    FOLLOWING_CHANNEL = os.getenv("FOLLOWING_CHANNEL", "@allinonemaker")
    DEVELOPER_CREDIT = "@Alcboss112"  # Developer attribution as requested

    # API endpoints
    TIKTOK_API = os.getenv("TIKTOK_API", "https://www.tikwm.com/api/?url=")
    FACEBOOK_API = os.getenv("FACEBOOK_API", "https://myapi-2f5b.onrender.com/fbvideo/search?url=")
    TWITTER_API = os.getenv("TWITTER_API", "https://twitsave.com/info?url=")

    # Authentication
    INSTAGRAM_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "")
    TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "")
    FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "")
    FACEBOOK_XS = os.getenv("FACEBOOK_XS", "")
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

    # Settings
    AUTO_CLEANUP_HOURS = int(os.getenv("AUTO_CLEANUP_HOURS", "12"))
    PORT = int(os.getenv("PORT", "5000"))
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB (Telegram's limit for bots)
    MAX_VIDEO_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max for full HD videos

# Global variables
user_states = {}
download_stats = {"total_users": 0, "total_downloads": 0}
bot_status = {"running": False, "last_update": None, "bot_instance": None}

# Flask server setup
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# HTML template for status page
STATUS_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Social Media Downloader Bot</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body>
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-md-10">
                <div class="card">
                    <div class="card-header text-center">
                        <h1 class="card-title mb-0">
                            <i class="fab fa-telegram-plane text-info me-2"></i>
                            Social Media Downloader Bot
                        </h1>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <div class="card bg-dark border-secondary">
                                    <div class="card-body text-center">
                                        <h5 class="card-title">
                                            <i class="fas fa-robot me-2"></i>
                                            Bot Status
                                        </h5>
                                        {% if status.running %}
                                            <span class="badge bg-success fs-6">
                                                <i class="fas fa-check-circle me-1"></i>
                                                Running
                                            </span>
                                        {% else %}
                                            <span class="badge bg-danger fs-6">
                                                <i class="fas fa-times-circle me-1"></i>
                                                Stopped
                                            </span>
                                        {% endif %}
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card bg-dark border-secondary">
                                    <div class="card-body text-center">
                                        <h5 class="card-title">
                                            <i class="fas fa-server me-2"></i>
                                            Server Status
                                        </h5>
                                        <span class="badge bg-success fs-6">
                                            <i class="fas fa-check-circle me-1"></i>
                                            Online
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="mt-4">
                            <h5><i class="fas fa-download me-2"></i>Download Statistics</h5>
                            <div class="table-responsive">
                                <table class="table table-dark table-striped">
                                    <tbody>
                                        <tr>
                                            <td><strong>Total Users</strong></td>
                                            <td>{{ stats.total_users }}</td>
                                        </tr>
                                        <tr>
                                            <td><strong>Total Downloads</strong></td>
                                            <td>{{ stats.total_downloads }}</td>
                                        </tr>
                                        <tr>
                                            <td><strong>Supported Platforms</strong></td>
                                            <td>YouTube, TikTok, Instagram, Facebook, Twitter</td>
                                        </tr>
                                        <tr>
                                            <td><strong>Last Update</strong></td>
                                            <td>
                                                {% if status.last_update %}
                                                    {{ status.last_update }}
                                                {% else %}
                                                    Never
                                                {% endif %}
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <div class="mt-4">
                            <h5><i class="fas fa-link me-2"></i>API Endpoints</h5>
                            <div class="list-group">
                                <div class="list-group-item list-group-item-action bg-dark border-secondary">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">/health</h6>
                                        <small class="text-info">GET</small>
                                    </div>
                                    <p class="mb-1">Health check endpoint for monitoring</p>
                                </div>
                                <div class="list-group-item list-group-item-action bg-dark border-secondary">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">/status</h6>
                                        <small class="text-info">GET</small>
                                    </div>
                                    <p class="mb-1">Bot status and statistics</p>
                                </div>
                                <div class="list-group-item list-group-item-action bg-dark border-secondary">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">/wake</h6>
                                        <small class="text-info">GET</small>
                                    </div>
                                    <p class="mb-1">Wake up endpoint to keep service alive</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="card-footer text-center text-muted">
                        <small>
                            <i class="fas fa-cloud me-1"></i>
                            Deployed on Render
                        </small>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main page showing bot status and statistics"""
    return render_template_string(STATUS_PAGE_TEMPLATE, status=bot_status, stats=download_stats)

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy",
        "bot_running": bot_status["running"],
        "last_update": bot_status["last_update"],
        "timestamp": time.time(),
        "stats": download_stats
    })

@app.route('/status')
def status():
    """Status endpoint returning bot information"""
    return jsonify({
        "bot_status": bot_status,
        "download_stats": download_stats,
        "timestamp": time.time()
    })

@app.route('/wake')
def wake():
    """Wake endpoint to keep the service alive"""
    try:
        logger.info("Wake endpoint called - service is alive")
        return jsonify({
            "message": "Service is awake",
            "bot_status": bot_status["running"],
            "timestamp": time.time(),
            "stats": download_stats
        })
    except Exception as e:
        logger.error(f"Wake endpoint error: {e}")
        return jsonify({
            "message": "Service is awake but encountered an error",
            "error": str(e),
            "timestamp": time.time()
        }), 500

def run_flask_server():
    """Run Flask server in a separate thread"""
    try:
        logger.info(f"🌐 Starting Flask server on port {Config.PORT}")
        app.run(host='0.0.0.0', port=Config.PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

class ProgressTracker:
    """Enhanced progress tracker with speed monitoring"""
    def __init__(self, message_id: int, chat_id: int, bot: Bot):
        self.message_id = message_id
        self.chat_id = chat_id
        self.bot = bot
        self.last_update = 0
        self.start_time = time.time()
        self.last_bytes = 0
        self.speed_samples = []

    async def update_progress(self, current: int, total: int, speed: str = "", stage: str = "Downloading"):
        """Enhanced progress update with speed calculation"""
        now = time.time()
        if now - self.last_update < 1.5:  # Update every 1.5 seconds
            return

        percentage = (current / total) * 100 if total > 0 else 0
        progress_bar = "█" * int(percentage // 5) + "░" * (20 - int(percentage // 5))

        # Calculate speed if not provided
        if not speed and current > self.last_bytes:
            elapsed = now - self.last_update if self.last_update > 0 else 1
            bytes_per_sec = (current - self.last_bytes) / elapsed
            self.speed_samples.append(bytes_per_sec)

            # Keep only last 5 samples for smoothing
            if len(self.speed_samples) > 5:
                self.speed_samples.pop(0)

            avg_speed = sum(self.speed_samples) / len(self.speed_samples)
            speed = f"{avg_speed/1024/1024:.1f} MB/s"

        # Calculate ETA
        eta_str = ""
        if total > current and speed and "MB/s" in speed:
            try:
                speed_val = float(speed.split()[0])
                remaining_mb = (total - current) / (1024 * 1024)
                eta_seconds = remaining_mb / speed_val if speed_val > 0 else 0
                if eta_seconds > 0:
                    eta_str = f" • ETA: {int(eta_seconds)}s"
            except:
                pass

        text = f"{'📥' if stage == 'Downloading' else '📤'} **{stage}...**\n\n"
        text += f"`{progress_bar}` {percentage:.1f}%\n"
        text += f"📊 **Size:** {self._format_bytes(current)} / {self._format_bytes(total)}\n"
        if speed:
            text += f"🚀 **Speed:** {speed}{eta_str}\n"

        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
            self.last_update = now
            self.last_bytes = current
        except Exception as e:
            logger.warning(f"Failed to update progress: {e}")

    async def update_compression_progress(self, stage: str, details: str = ""):
        """Update progress for compression operations"""
        text = f"🔄 **{stage}**\n\n"
        if details:
            text += f"{details}\n\n"
        text += f"⏱️ Please wait, this may take a few minutes..."

        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Failed to update compression progress: {e}")

    @staticmethod
    def _format_bytes(bytes_num: int) -> str:
        """Format bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_num < 1024.0:
                return f"{bytes_num:.1f} {unit}"
            bytes_num /= 1024.0
        return f"{bytes_num:.1f} TB"

class SocialMediaDownloader:
    """Enhanced downloader with faster compression and better progress tracking"""

    def __init__(self):
        self.session = None
        self.playwright_browser = None
        self.temp_dir = tempfile.mkdtemp(prefix="telegram_bot_")

    async def __aenter__(self):
        self.session = httpx.AsyncClient(timeout=120.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()
        if self.playwright_browser:
            await self.playwright_browser.close()
        # Cleanup temp directory
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    async def get_platform(self, url: str) -> str:
        """Detect platform from URL"""
        url_lower = url.lower()
        if any(domain in url_lower for domain in ['youtube.com', 'youtu.be']):
            return 'youtube'
        elif any(domain in url_lower for domain in ['facebook.com', 'fb.com']):
            return 'facebook'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif any(domain in url_lower for domain in ['twitter.com', 'x.com']):
            return 'twitter'
        elif 'instagram.com' in url_lower:
            return 'instagram'
        elif url_lower.endswith('.m3u8'):
            return 'm3u8'
        elif any(ext in url_lower for ext in ['.mp4', '.mkv', '.avi', '.webm', '.mov']):
            return 'direct'
        else:
            return 'unknown'

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def download_with_yt_dlp(self, url: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced yt-dlp download with progressive quality selection for YouTube"""
        try:
            platform = await self.get_platform(url)

            # For YouTube, try different quality levels progressively
            if platform == 'youtube':
                quality_levels = [
                    ('4K', 'best[height<=2160][ext=mp4]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]'),
                    ('1440p', 'best[height<=1440][ext=mp4]/bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]'),
                    ('1080p', 'best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]'),
                    ('720p', 'best[height<=720][ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]'),
                    ('480p', 'best[height<=480][ext=mp4]/bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]'),
                ]

                for quality_name, format_selector in quality_levels:
                    try:
                        logger.info(f"Trying YouTube quality: {quality_name}")

                        await progress_tracker.update_compression_progress(
                            f"YouTube Download - {quality_name}",
                            f"Attempting to download in {quality_name} quality..."
                        )

                        result = await self._download_youtube_quality(url, format_selector, progress_tracker)
                        if result[0]:
                            logger.info(f"Successfully downloaded YouTube at {quality_name}")
                            return result

                    except Exception as e:
                        logger.warning(f"YouTube {quality_name} failed: {e}")
                        continue

                # If all qualities failed, try fallback
                logger.warning("All YouTube qualities failed, trying fallback")
                return await self._download_youtube_fallback(url, progress_tracker)

            else:
                # For non-YouTube platforms, use enhanced format with compression
                return await self._download_with_enhanced_compression(url, progress_tracker)

        except Exception as e:
            logger.error(f"yt-dlp download failed: {e}")
            raise

    async def _download_youtube_quality(self, url: str, format_selector: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Download YouTube video with specific quality and progress tracking"""
        import subprocess
        import json

        # Get video info first
        info_cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            '--format', format_selector,
            '--no-check-certificates',
            '--no-warnings',
            '--socket-timeout', '60',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            url
        ]

        info_result = subprocess.run(
            info_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False
        )

        if info_result.returncode != 0:
            raise Exception(f"Info extraction failed: {info_result.stderr}")

        # Parse info
        info = None
        for line in info_result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    info = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        if not info:
            raise Exception("No video info found")

        # Download with progress tracking
        output_template = f'{self.temp_dir}/%(title)s.%(ext)s'

        def run_download():
            download_cmd = [
                'yt-dlp',
                '--format', format_selector,
                '--output', output_template,
                '--write-info-json',
                '--no-check-certificates',
                '--socket-timeout', '120',
                '--fragment-retries', '10',
                '--retries', '5',
                '--merge-output-format', 'mp4',
                '--prefer-ffmpeg',
                '--embed-thumbnail',
                '--add-metadata',
                '--progress',
                '--newline',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                url
            ]

            return subprocess.run(
                download_cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for YouTube
                check=False
            )

        # Run download in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_download)
            download_result = future.result(timeout=320)

        if download_result.returncode != 0:
            raise Exception(f"Download failed: {download_result.stderr}")

        # Find downloaded file
        for file in Path(self.temp_dir).glob("*"):
            if file.suffix in ['.mp4', '.mkv', '.webm', '.avi'] and file.stat().st_size > 0:
                file_size = file.stat().st_size

                # For YouTube, only compress if larger than 2GB (not 50MB limit)
                if file_size > 2 * 1024 * 1024 * 1024:  # 2GB
                    logger.warning(f"YouTube file too large: {file_size/1024/1024:.1f} MB")
                    return None, None
                elif file_size > Config.MAX_FILE_SIZE:
                    # Compress for Telegram's 50MB limit
                    compressed_file = await self._compress_video_ultra_fast(str(file), progress_tracker)
                    if compressed_file:
                        file = Path(compressed_file)

                metadata = {
                    'title': info.get('title', 'YouTube Video'),
                    'description': info.get('description', ''),
                    'duration': info.get('duration'),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'view_count': info.get('view_count'),
                    'like_count': info.get('like_count'),
                    'platform': 'youtube'
                }

                return str(file), metadata

        return None, None

    async def _download_youtube_fallback(self, url: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Fallback YouTube download with basic format"""
        import subprocess
        import json

        cmd = [
            'yt-dlp',
            '--format', 'best[ext=mp4]/best/worst',
            '--output', f'{self.temp_dir}/%(title)s.%(ext)s',
            '--write-info-json',
            '--merge-output-format', 'mp4',
            '--prefer-ffmpeg',
            url
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False
        )

        if result.returncode == 0:
            for file in Path(self.temp_dir).glob("*"):
                if file.suffix in ['.mp4', '.mkv', '.webm', '.avi'] and file.stat().st_size > 0:
                    metadata = {
                        'title': 'YouTube Video (Fallback)',
                        'platform': 'youtube'
                    }
                    return str(file), metadata

        return None, None

    async def _download_with_enhanced_compression(self, url: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced download with smart compression for large files"""
        import subprocess
        import json

        # First get video info
        info_cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            '--format', 'best[height<=1080]/best/worst',
            '--no-check-certificates',
            '--no-warnings',
            '--socket-timeout', '60',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '--extractor-args', 'facebook:api_version=v18.0',
            url
        ]

        try:
            info_result = subprocess.run(
                info_cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False
            )

            info = None
            if info_result.returncode == 0:
                for line in info_result.stdout.strip().split('\n'):
                    if line.strip():
                        try:
                            info = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue

            # Enhanced download with better format selection
            download_cmd = [
                'yt-dlp',
                '--format', 'best[height<=2160][ext=mp4]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440][ext=mp4]/bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
                '--output', f'{self.temp_dir}/%(title)s.%(ext)s',
                '--write-info-json',
                '--no-check-certificates',
                '--socket-timeout', '120',
                '--fragment-retries', '10',
                '--retries', '10',
                '--merge-output-format', 'mp4',
                '--prefer-ffmpeg',
                '--embed-thumbnail',
                '--add-metadata',
                '--progress',
                '--newline',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--extractor-args', 'facebook:api_version=v18.0',
                url
            ]

            download_result = subprocess.run(
                download_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                check=False
            )

            if download_result.returncode != 0:
                raise Exception(f"Download failed: {download_result.stderr}")

            # Find downloaded file and handle compression
            for file in Path(self.temp_dir).glob("*"):
                if file.suffix in ['.mp4', '.mkv', '.webm', '.avi'] and file.stat().st_size > 0:
                    file_size = file.stat().st_size

                    # Enhanced compression for large files
                    if file_size > Config.MAX_FILE_SIZE:
                        logger.info(f"File size {file_size/1024/1024:.1f} MB > {Config.MAX_FILE_SIZE/1024/1024:.1f} MB, using smart compression...")

                        await progress_tracker.update_compression_progress(
                            "Smart Compression",
                            f"Original size: {file_size/1024/1024:.1f} MB\nOptimizing for fast upload..."
                        )

                        compressed_file = await self._compress_video_smart(str(file), progress_tracker)
                        if compressed_file and os.path.exists(compressed_file):
                            compressed_size = os.path.getsize(compressed_file)
                            if compressed_size <= Config.MAX_FILE_SIZE:
                                logger.info(f"Smart compression: {file_size/1024/1024:.1f} MB → {compressed_size/1024/1024:.1f} MB")
                                file = Path(compressed_file)
                            else:
                                logger.warning(f"Compressed file still too large: {compressed_size/1024/1024:.1f} MB")
                                return None, None
                        else:
                            logger.warning("Smart compression failed")
                            return None, None

                    metadata = {
                        'title': info.get('title', 'Downloaded Video') if info else 'Downloaded Video',
                        'description': info.get('description', '') if info else '',
                        'duration': info.get('duration') if info else None,
                        'uploader': info.get('uploader', '') if info else '',
                        'upload_date': info.get('upload_date', '') if info else '',
                        'view_count': info.get('view_count') if info else None,
                        'like_count': info.get('like_count') if info else None,
                        'platform': info.get('extractor_key', '').lower() if info else 'unknown'
                    }

                    return str(file), metadata

            return None, None

        except subprocess.TimeoutExpired as e:
            logger.error(f"Download timed out: {e}")
            raise Exception(f"Download timed out: {e}")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise Exception(f"Download failed: {e}")

    async def download_with_api(self, url: str, platform: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced API download with progress tracking"""
        try:
            api_url = None
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            if platform == 'tiktok':
                api_url = Config.TIKTOK_API + url
            elif platform == 'facebook':
                api_url = Config.FACEBOOK_API + url
            elif platform == 'twitter':
                api_url = Config.TWITTER_API + url

            if not api_url:
                return None, None

            logger.info(f"Trying API download from: {api_url}")

            response = await self.session.get(api_url, headers=headers, timeout=60.0)
            if response.status_code != 200:
                logger.warning(f"API returned status {response.status_code}")
                return None, None

            try:
                data = response.json()
            except Exception as e:
                logger.error(f"Failed to parse API response as JSON: {e}")
                return None, None

            # Extract download URL based on platform
            download_url = None
            metadata = {}

            if platform == 'tiktok' and 'data' in data:
                tik_data = data['data']
                download_url = tik_data.get('hdplay') or tik_data.get('play')
                metadata = {
                    'title': tik_data.get('title', 'TikTok Video'),
                    'description': tik_data.get('title', ''),
                    'uploader': tik_data.get('author', {}).get('nickname', '') if tik_data.get('author') else '',
                    'duration': tik_data.get('duration'),
                    'platform': 'tiktok'
                }
            elif platform == 'facebook' and 'links' in data:
                links = data['links']
                download_url = links.get('Download High Quality') or links.get('Download Low Quality')
                metadata = {
                    'title': data.get('title', 'Facebook Video'),
                    'description': data.get('title', ''),
                    'platform': 'facebook'
                }
            elif platform == 'twitter':
                # Handle Twitter API response
                if 'url' in data:
                    download_url = data['url']
                    metadata = {
                        'title': data.get('title', 'Twitter Video'),
                        'description': data.get('description', ''),
                        'platform': 'twitter'
                    }

            if download_url:
                return await self._download_direct_url_enhanced(download_url, progress_tracker, metadata)

        except asyncio.TimeoutError:
            logger.error(f"API request timed out for {platform}")
        except Exception as e:
            logger.error(f"API download failed: {e}")

        return None, None

    async def download_with_cookies(self, url: str, platform: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced cookie-based download"""
        try:
            logger.info(f"Trying cookie-based download for {platform}")

            # Prepare cookies for different platforms
            cookies = {}
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            if platform == 'instagram' and Config.INSTAGRAM_SESSIONID:
                cookies['sessionid'] = Config.INSTAGRAM_SESSIONID
                headers['X-IG-App-ID'] = '936619743392459'

            elif platform == 'facebook' and Config.FACEBOOK_CUSER and Config.FACEBOOK_XS:
                cookies['c_user'] = Config.FACEBOOK_CUSER
                cookies['xs'] = Config.FACEBOOK_XS

            elif platform == 'twitter' and Config.TWITTER_AUTH_TOKEN:
                cookies['auth_token'] = Config.TWITTER_AUTH_TOKEN

            if not cookies:
                logger.warning(f"No cookies available for {platform}")
                return None, None

            # Use yt-dlp with cookies
            cookie_file = f"{self.temp_dir}/cookies.txt"
            with open(cookie_file, 'w') as f:
                for name, value in cookies.items():
                    f.write(f"# Netscape HTTP Cookie File\n")
                    domain = '.instagram.com' if platform == 'instagram' else '.facebook.com' if platform == 'facebook' else '.twitter.com'
                    f.write(f"{domain}\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

            import subprocess
            cmd = [
                'yt-dlp',
                '--cookies', cookie_file,
                '--format', 'best[height<=2160]/best[height<=1440]/best[height<=1080]/best[height<=720]/best',
                '--output', f'{self.temp_dir}/%(title)s.%(ext)s',
                '--write-info-json',
                '--no-check-certificates',
                '--socket-timeout', '120',
                '--fragment-retries', '10',
                '--retries', '10',
                url
            ]

            logger.info(f"Running yt-dlp with cookies: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                check=False
            )

            if result.returncode == 0:
                # Find downloaded file
                for file in Path(self.temp_dir).glob("*"):
                    if file.suffix in ['.mp4', '.mkv', '.webm', '.avi'] and file.stat().st_size > 0:
                        file_size = file.stat().st_size
                        if file_size > Config.MAX_FILE_SIZE:
                            # Compress if needed
                            compressed_file = await self._compress_video_ultra_fast(str(file), progress_tracker)
                            if compressed_file and os.path.exists(compressed_file):
                                file = Path(compressed_file)
                            else:
                                return None, None

                        metadata = {
                            'title': f'{platform.title()} Video',
                            'description': 'Downloaded with cookies',
                            'platform': platform
                        }
                        return str(file), metadata
            else:
                logger.error(f"Cookie-based download failed: {result.stderr}")

            # Cleanup cookie file
            try:
                os.unlink(cookie_file)
            except:
                pass

        except Exception as e:
            logger.error(f"Cookie download failed: {e}")

        return None, None

    async def _compress_video_ultra_fast(self, file_path: str, progress_tracker: ProgressTracker) -> Optional[str]:
        """Ultra-fast compression optimized for speed"""
        try:
            original_size = os.path.getsize(file_path)
            compressed_path = f"{self.temp_dir}/ultra_fast_{int(time.time())}.mp4"

            await progress_tracker.update_compression_progress(
                "Ultra-Fast Compression",
                f"Original: {original_size/1024/1024:.1f} MB\nOptimizing for speed..."
            )

            def compress_ultra_fast():
                try:
                    import subprocess
                    # Ultra-fast compression with minimal CPU usage
                    cmd = [
                        'ffmpeg', '-i', file_path,
                        '-c:v', 'libx264',
                        '-preset', 'superfast',  # Even faster than ultrafast
                        '-crf', '30',           # Faster compression, smaller files
                        '-c:a', 'aac',
                        '-b:a', '64k',          # Even lower audio bitrate for speed
                        '-movflags', '+faststart',
                        '-threads', '0',        # Use all available cores
                        '-y',
                        compressed_path
                    ]

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                    if result.returncode == 0 and os.path.exists(compressed_path):
                        return compressed_path
                    else:
                        logger.error(f"Ultra-fast compression failed: {result.stderr}")
                        return None

                except Exception as e:
                    logger.error(f"Ultra-fast compression error: {e}")
                    return None

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                future = executor.submit(compress_ultra_fast)
                result = future.result(timeout=150)

            if result and os.path.exists(result):
                final_size = os.path.getsize(result)
                logger.info(f"Ultra-fast compression: {original_size/1024/1024:.1f} MB → {final_size/1024/1024:.1f} MB")
                return result

            return None

        except Exception as e:
            logger.error(f"Ultra-fast compression failed: {e}")
            return None

    async def _compress_video_smart(self, file_path: str, progress_tracker: ProgressTracker) -> Optional[str]:
        """Smart compression with multiple strategies for different file types"""
        try:
            original_size = os.path.getsize(file_path)

            # Determine best compression strategy based on file size
            if original_size < 100 * 1024 * 1024:  # < 100MB
                return await self._compress_video_ultra_fast(file_path, progress_tracker)
            else:
                return await self._compress_video_aggressive(file_path, progress_tracker)

        except Exception as e:
            logger.error(f"Smart compression failed: {e}")
            return None

    async def _compress_video_aggressive(self, file_path: str, progress_tracker: ProgressTracker) -> Optional[str]:
        """Aggressive compression for very large files"""
        try:
            original_size = os.path.getsize(file_path)

            # Progressive compression levels for large files
            compression_levels = [
                {"height": 720, "bitrate": "1000k", "audio": "96k", "crf": "28", "preset": "fast"},
                {"height": 480, "bitrate": "600k", "audio": "80k", "crf": "30", "preset": "faster"},
                {"height": 360, "bitrate": "400k", "audio": "64k", "crf": "32", "preset": "veryfast"},
            ]

            for i, level in enumerate(compression_levels):
                compressed_path = f"{self.temp_dir}/aggressive_{level['height']}p_{int(time.time())}.mp4"

                try:
                    await progress_tracker.update_compression_progress(
                        f"Aggressive Compression - {level['height']}p",
                        f"Level {i+1}/{len(compression_levels)}\nTarget size: <50MB"
                    )

                    def compress_level():
                        try:
                            import subprocess
                            cmd = [
                                'ffmpeg', '-i', file_path,
                                '-vf', f"scale=-2:{level['height']}",
                                '-c:v', 'libx264',
                                '-preset', level['preset'],
                                '-crf', level['crf'],
                                '-maxrate', level['bitrate'],
                                '-bufsize', str(int(level['bitrate'][:-1]) * 2) + 'k',
                                '-c:a', 'aac',
                                '-b:a', level['audio'],
                                '-movflags', '+faststart',
                                '-threads', '0',
                                '-y',
                                compressed_path
                            ]

                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

                            if result.returncode == 0 and os.path.exists(compressed_path):
                                compressed_size = os.path.getsize(compressed_path)
                                if compressed_size <= Config.MAX_FILE_SIZE:
                                    return compressed_path
                                else:
                                    try:
                                        os.unlink(compressed_path)
                                    except:
                                        pass
                                    return None
                            else:
                                logger.error(f"Compression level {level['height']}p failed: {result.stderr}")
                                return None

                        except Exception as e:
                            logger.error(f"Compression level {level['height']}p error: {e}")
                            return None

                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                        future = executor.submit(compress_level)
                        result = future.result(timeout=360)

                    if result and os.path.exists(result):
                        final_size = os.path.getsize(result)
                        logger.info(f"Aggressive compression {level['height']}p: {original_size/1024/1024:.1f} MB → {final_size/1024/1024:.1f} MB")
                        return result

                except Exception as e:
                    logger.warning(f"Compression level {level['height']}p failed: {e}")
                    continue

            logger.error("All compression levels failed")
            return None

        except Exception as e:
            logger.error(f"Aggressive compression failed: {e}")
            return None

    async def _download_direct_url_enhanced(self, url: str, progress_tracker: ProgressTracker, metadata: Dict) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced direct URL download with better progress tracking"""
        try:
            # Get file extension from URL
            url_path = urlparse(url).path
            file_ext = os.path.splitext(url_path)[1] or '.mp4'
            filename = f"{self.temp_dir}/video_{int(time.time())}{file_ext}"

            # Enhanced timeout and headers
            timeout = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)  # Faster timeouts
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
                'Range': 'bytes=0-'  # Enable resume support
            }

            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                # Get file size
                try:
                    head_response = await client.head(url, timeout=15.0)
                    if head_response.status_code == 200:
                        total_size = int(head_response.headers.get('content-length', 0))
                    else:
                        total_size = 0
                except:
                    total_size = 0

                async with client.stream('GET', url) as response:
                    if response.status_code not in [200, 206]:
                        logger.warning(f"Direct download returned status {response.status_code}")
                        return None, None

                    if total_size == 0:
                        total_size = int(response.headers.get('content-length', 0))

                    if total_size > 0:
                        logger.info(f"Downloading direct file: {total_size/1024/1024:.1f} MB")

                    downloaded = 0
                    start_time = time.time()

                    async with aopen(filename, 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=1048576):  # 1MB chunks for faster downloads
                            await f.write(chunk)
                            downloaded += len(chunk)

                            # Update progress more frequently
                            await progress_tracker.update_progress(downloaded, total_size or downloaded, stage="Downloading")

                    if os.path.exists(filename) and os.path.getsize(filename) > 0:
                        final_size = os.path.getsize(filename)

                        # Enhanced compression for large files
                        if final_size > Config.MAX_FILE_SIZE:
                            logger.info(f"File too large: {final_size/1024/1024:.1f} MB, using smart compression")
                            compressed_file = await self._compress_video_smart(filename, progress_tracker)
                            if compressed_file and os.path.exists(compressed_file):
                                compressed_size = os.path.getsize(compressed_file)
                                if compressed_size <= Config.MAX_FILE_SIZE:
                                    logger.info(f"Smart compression: {final_size/1024/1024:.1f} MB → {compressed_size/1024/1024:.1f} MB")
                                    try:
                                        os.unlink(filename)
                                    except:
                                        pass
                                    filename = compressed_file
                                else:
                                    logger.warning(f"Compressed file still too large: {compressed_size/1024/1024:.1f} MB")
                                    return None, None
                            else:
                                logger.warning("Smart compression failed")
                                return None, None

                        return filename, metadata

        except asyncio.TimeoutError:
            logger.error("Enhanced direct download timed out")
        except Exception as e:
            logger.error(f"Enhanced direct download failed: {e}")

        return None, None

    async def download_m3u8_enhanced(self, url: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced M3U8 download with better progress tracking"""
        try:
            output_file = f"{self.temp_dir}/stream_{int(time.time())}.mp4"

            await progress_tracker.update_compression_progress(
                "M3U8 Stream Processing",
                "Analyzing stream segments and quality..."
            )

            def run_enhanced_m3u8_download():
                import subprocess

                # Enhanced yt-dlp command for M3U8
                cmd = [
                    'yt-dlp',
                    '--format', 'best[height<=2160][ext=mp4]/best[height<=1440][ext=mp4]/best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[ext=mp4]/best',
                    '--output', output_file,
                    '--write-info-json',
                    '--merge-output-format', 'mp4',
                    '--prefer-ffmpeg',
                    '--socket-timeout', '120',
                    '--fragment-retries', '20',  # Increased retries for M3U8
                    '--retries', '15',
                    '--http-chunk-size', '52428800',  # 50MB chunks for much faster downloads
                    '--progress',
                    '--newline',
                    '--concurrent-fragments', '16',  # Download 16 fragments concurrently for maximum speed
                    url
                ]

                logger.info(f"Running enhanced M3U8 download: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=900  # 15 minute timeout for M3U8
                )

                if result.returncode == 0:
                    info_file = output_file.replace('.mp4', '.info.json')
                    if os.path.exists(info_file):
                        try:
                            with open(info_file, 'r') as f:
                                return json.load(f)
                        except:
                            pass

                    return {
                        'title': 'M3U8 Stream',
                        'description': 'Downloaded M3U8 stream',
                        'platform': 'm3u8'
                    }
                else:
                    logger.error(f"Enhanced M3U8 download failed: {result.stderr}")
                    raise Exception(f"yt-dlp failed: {result.stderr}")

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                future = executor.submit(run_enhanced_m3u8_download)
                info = future.result(timeout=960)

            metadata = {
                'title': info.get('title', 'M3U8 Stream'),
                'description': info.get('description', 'Downloaded M3U8 stream'),
                'duration': info.get('duration'),
                'platform': 'm3u8'
            }

            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                file_size = os.path.getsize(output_file)

                # Enhanced compression for M3U8 files
                if file_size > Config.MAX_FILE_SIZE:
                    logger.info(f"M3U8 file too large: {file_size/1024/1024:.1f} MB, using smart compression")
                    compressed_file = await self._compress_video_smart(output_file, progress_tracker)
                    if compressed_file and os.path.exists(compressed_file):
                        compressed_size = os.path.getsize(compressed_file)
                        if compressed_size <= Config.MAX_FILE_SIZE:
                            logger.info(f"M3U8 smart compression: {file_size/1024/1024:.1f} MB → {compressed_size/1024/1024:.1f} MB")
                            try:
                                os.unlink(output_file)
                            except:
                                pass
                            output_file = compressed_file
                        else:
                            logger.warning(f"Compressed M3U8 file still too large: {compressed_size/1024/1024:.1f} MB")
                            return None, None
                    else:
                        logger.warning("M3U8 compression failed")
                        return None, None

                return output_file, metadata

        except Exception as e:
            logger.error(f"Enhanced M3U8 download failed: {e}")

        return None, None

    async def download_video(self, url: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Enhanced main download method with better fallback system"""
        platform = await self.get_platform(url)
        logger.info(f"Detected platform: {platform} for URL: {url}")

        # Special handling for m3u8
        if platform == 'm3u8':
            return await self.download_m3u8_enhanced(url, progress_tracker)

        # Special handling for direct video URLs
        if platform == 'direct':
            logger.info("Direct video URL detected, downloading directly")
            try:
                metadata = {
                    'title': url.split('/')[-1].split('?')[0],
                    'description': 'Direct video download',
                    'platform': 'direct'
                }
                return await self._download_direct_url_enhanced(url, progress_tracker, metadata)
            except Exception as e:
                logger.error(f"Enhanced direct download failed: {e}")
                return None, None

        # ULTRA SPEED: Try all methods in parallel for fastest possible download
        import asyncio

        async def try_yt_dlp():
            try:
                result = await self.download_with_yt_dlp(url, progress_tracker)
                if result[0]:
                    logger.info("✅ SPEED WIN: yt-dlp method succeeded first!")
                    return result
            except Exception as e:
                logger.warning(f"yt-dlp method failed: {e}")
            return None, None

        async def try_api():
            try:
                result = await self.download_with_api(url, platform, progress_tracker)
                if result[0]:
                    logger.info("✅ SPEED WIN: API method succeeded first!")
                    return result
            except Exception as e:
                logger.warning(f"API method failed: {e}")
            return None, None

        async def try_cookies():
            try:
                result = await self.download_with_cookies(url, platform, progress_tracker)
                if result[0]:
                    logger.info("✅ SPEED WIN: Cookie method succeeded first!")
                    return result
            except Exception as e:
                logger.warning(f"Cookie method failed: {e}")
            return None, None

        # Run all methods simultaneously - first one to succeed wins!
        logger.info("🚀 TURBO MODE: Running all download methods in parallel...")

        tasks = [
            asyncio.create_task(try_yt_dlp()),
            asyncio.create_task(try_api()),
            asyncio.create_task(try_cookies())
        ]

        # Wait for first successful result
        for completed in asyncio.as_completed(tasks):
            try:
                result = await completed
                if result[0]:  # If successful
                    # Cancel remaining tasks to save resources
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    logger.info("🎯 PARALLEL DOWNLOAD SUCCESS!")
                    return result
            except Exception as e:
                logger.warning(f"Parallel task failed: {e}")
                continue

        # If all parallel attempts failed
        logger.error("❌ All parallel download methods failed")

        return None, None

    async def download_video_with_quality(self, url: str, quality_format: str, quality_type: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Download video with quality selection and smart priority system as requested by @Alcboss112"""
        platform = await self.get_platform(url)
        logger.info(f"Quality download - Platform: {platform}, Quality: {quality_type}, Format: {quality_format}")

        # Update progress tracker with priority system info
        await progress_tracker.update_compression_progress(
            "Smart Priority Download",
            f"🎯 **Quality:** {quality_type}\n"
            f"🌐 **Platform:** {platform.title()}\n"
            f"⚡ **Priority System:** packages → API → cookies"
        )

        # Special handling for m3u8 and direct URLs with quality consideration
        if platform == 'm3u8':
            result = await self.download_m3u8_enhanced(url, progress_tracker)
            if result[0]:
                return await self._apply_quality_conversion(result, quality_type, quality_format, progress_tracker)

        if platform == 'direct':
            metadata = {
                'title': self._extract_filename_from_url(url),
                'description': f'Direct video download - {quality_type}',
                'platform': 'direct'
            }
            result = await self._download_direct_url_enhanced(url, progress_tracker, metadata)
            if result[0]:
                return await self._apply_quality_conversion(result, quality_type, quality_format, progress_tracker)

        # Smart Priority System: packages → API → cookies
        # Priority 1: Package-based downloaders (yt-dlp, instaloader)
        logger.info("🔧 Priority 1: Trying package-based downloaders...")
        await progress_tracker.update_compression_progress(
            "Priority 1: Packages",
            "Attempting yt-dlp and platform-specific packages..."
        )

        try:
            if platform == 'instagram':
                # Try instaloader first for Instagram
                result = await self._download_instagram_with_instaloader(url, quality_type, progress_tracker)
                if result[0]:
                    logger.info("✅ Priority 1 SUCCESS: instaloader")
                    return result

            # Try yt-dlp with quality format
            result = await self._download_with_ytdlp_quality(url, quality_format, progress_tracker)
            if result[0]:
                logger.info("✅ Priority 1 SUCCESS: yt-dlp")
                return result

        except Exception as e:
            logger.warning(f"Priority 1 (packages) failed: {e}")

        # Priority 2: API-based methods
        logger.info("🔧 Priority 2: Trying API-based methods...")
        await progress_tracker.update_compression_progress(
            "Priority 2: APIs",
            "Attempting platform-specific APIs with authentication..."
        )

        try:
            result = await self.download_with_api(url, platform, progress_tracker)
            if result[0]:
                result = await self._apply_quality_conversion(result, quality_type, quality_format, progress_tracker)
                if result[0]:
                    logger.info("✅ Priority 2 SUCCESS: API method")
                    return result
        except Exception as e:
            logger.warning(f"Priority 2 (APIs) failed: {e}")

        # Priority 3: Cookie-based authentication
        logger.info("🔧 Priority 3: Trying cookie-based authentication...")
        await progress_tracker.update_compression_progress(
            "Priority 3: Cookies",
            "Attempting downloads with browser authentication..."
        )

        try:
            result = await self.download_with_cookies(url, platform, progress_tracker)
            if result[0]:
                result = await self._apply_quality_conversion(result, quality_type, quality_format, progress_tracker)
                if result[0]:
                    logger.info("✅ Priority 3 SUCCESS: Cookie method")
                    return result
        except Exception as e:
            logger.warning(f"Priority 3 (cookies) failed: {e}")

        # All priorities failed
        logger.error("❌ All priority levels failed for quality download")
        return None, None

    async def _apply_quality_conversion(self, result: Tuple[Optional[str], Optional[Dict]], quality_type: str, quality_format: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Apply quality conversion based on user selection"""
        file_path, metadata = result
        if not file_path or not os.path.exists(file_path):
            return None, None

        # For audio-only downloads, convert to MP3
        if quality_type == "audio":
            await progress_tracker.update_compression_progress(
                "Audio Extraction",
                "Converting video to MP3 format..."
            )
            audio_file = await self._extract_audio_as_mp3(file_path, progress_tracker)
            if audio_file:
                try:
                    os.unlink(file_path)  # Remove original video
                except:
                    pass
                
                # Update metadata for audio
                if metadata:
                    metadata['title'] = f"{metadata.get('title', 'Audio')} [Audio Only]"
                    metadata['format'] = 'mp3'
                
                return audio_file, metadata

        # For video downloads, ensure proper file naming with title and description
        if metadata and metadata.get('title'):
            new_filename = await self._generate_enhanced_filename(metadata, quality_type)
            if new_filename != os.path.basename(file_path):
                new_path = os.path.join(os.path.dirname(file_path), new_filename)
                try:
                    os.rename(file_path, new_path)
                    file_path = new_path
                    logger.info(f"Enhanced filename: {new_filename}")
                except Exception as e:
                    logger.warning(f"Could not rename file: {e}")

        return file_path, metadata

    async def _generate_enhanced_filename(self, metadata: Dict, quality_type: str) -> str:
        """Generate enhanced filename with title and description as requested by @Alcboss112"""
        title = metadata.get('title', 'Video')
        description = metadata.get('description', '')
        platform = metadata.get('platform', 'unknown')
        
        # Sanitize title for filename
        safe_title = self._sanitize_filename(title)[:50]  # Limit title length
        
        # Add quality indicator
        quality_suffix = {
            "hd": "_HD",
            "sd": "_SD", 
            "audio": "_Audio",
            "best": "_Best"
        }.get(quality_type, "")
        
        # Add description if available (limit length)
        desc_part = ""
        if description:
            safe_desc = self._sanitize_filename(description)[:30]
            desc_part = f"_[{safe_desc}]"
        
        # Get file extension
        original_ext = ".mp4"
        if quality_type == "audio":
            original_ext = ".mp3"
        elif metadata.get('format'):
            original_ext = f".{metadata['format']}"
        
        # Construct enhanced filename
        filename = f"{safe_title}{quality_suffix}{desc_part}_{platform.upper()}{original_ext}"
        
        # Ensure filename isn't too long
        if len(filename) > 255:
            filename = f"{safe_title[:30]}{quality_suffix}_{platform.upper()}{original_ext}"
        
        return filename

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename by removing invalid characters"""
        import re
        # Remove invalid characters for filenames
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = re.sub(r'\s+', '_', filename)  # Replace spaces with underscores
        filename = filename.strip('._')  # Remove leading/trailing dots and underscores
        return filename if filename else "video"

    def _extract_filename_from_url(self, url: str) -> str:
        """Extract filename from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            return filename if filename else "direct_video"
        except:
            return "direct_video"

    async def _download_with_ytdlp_quality(self, url: str, quality_format: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Download with yt-dlp using specific quality format"""
        try:
            import subprocess
            import json

            await progress_tracker.update_compression_progress(
                "yt-dlp Quality Download",
                f"Format: {quality_format}"
            )

            # Get video info first
            info_cmd = [
                'yt-dlp', '--dump-json', '--no-download',
                '--format', quality_format,
                '--no-check-certificates', '--no-warnings',
                url
            ]

            info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=60, check=False)
            if info_result.returncode != 0:
                raise Exception(f"Info extraction failed: {info_result.stderr}")

            # Parse video info
            info = None
            for line in info_result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        info = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            if not info:
                raise Exception("No video info found")

            # Generate enhanced filename template with title and description
            title = self._sanitize_filename(info.get('title', 'video'))[:50]
            platform = await self.get_platform(url)
            output_template = f'{self.temp_dir}/{title}_{platform}.%(ext)s'

            # Download with specified quality
            download_cmd = [
                'yt-dlp', '--format', quality_format,
                '--output', output_template,
                '--no-check-certificates',
                '--merge-output-format', 'mp4',
                '--embed-thumbnail', '--add-metadata',
                url
            ]

            result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=300, check=False)
            if result.returncode != 0:
                raise Exception(f"Download failed: {result.stderr}")

            # Find downloaded file
            for file in Path(self.temp_dir).glob("*"):
                if file.suffix in ['.mp4', '.mkv', '.webm', '.avi', '.mp3'] and file.stat().st_size > 0:
                    metadata = {
                        'title': info.get('title', 'Video'),
                        'description': info.get('description', ''),
                        'duration': info.get('duration'),
                        'uploader': info.get('uploader', ''),
                        'platform': platform
                    }
                    return str(file), metadata

            return None, None

        except Exception as e:
            logger.error(f"yt-dlp quality download failed: {e}")
            return None, None

    async def _download_instagram_with_instaloader(self, url: str, quality_type: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
        """Download Instagram content using instaloader package"""
        try:
            import instaloader
            
            await progress_tracker.update_compression_progress(
                "Instagram instaloader",
                "Extracting Instagram content..."
            )

            L = instaloader.Instaloader(
                dirname_pattern=self.temp_dir,
                filename_pattern='{title}_{shortcode}',
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False
            )

            # Extract shortcode from URL
            import re
            shortcode_match = re.search(r'/p/([A-Za-z0-9_-]+)', url)
            if not shortcode_match:
                shortcode_match = re.search(r'/reel/([A-Za-z0-9_-]+)', url)
            
            if not shortcode_match:
                raise Exception("Could not extract Instagram shortcode from URL")

            shortcode = shortcode_match.group(1)
            post = instaloader.Post.from_shortcode(L.context, shortcode)

            # Download the post
            L.download_post(post, target=self.temp_dir)

            # Find downloaded video file
            for file in Path(self.temp_dir).glob("*"):
                if file.suffix in ['.mp4', '.mov'] and file.stat().st_size > 0:
                    metadata = {
                        'title': post.caption[:100] if post.caption else f"Instagram_{shortcode}",
                        'description': post.caption if post.caption else '',
                        'uploader': post.owner_username,
                        'platform': 'instagram',
                        'upload_date': post.date.strftime('%Y%m%d'),
                        'like_count': post.likes,
                        'view_count': post.video_view_count if post.is_video else None
                    }
                    return str(file), metadata

            return None, None

        except Exception as e:
            logger.error(f"Instagram instaloader failed: {e}")
            return None, None

    async def _extract_audio_as_mp3(self, video_path: str, progress_tracker: ProgressTracker) -> Optional[str]:
        """Extract audio from video as MP3"""
        try:
            from moviepy.editor import VideoFileClip
            
            output_path = video_path.rsplit('.', 1)[0] + '.mp3'
            
            await progress_tracker.update_compression_progress(
                "Audio Extraction",
                "Converting to MP3 format..."
            )

            with VideoFileClip(video_path) as video:
                audio = video.audio
                if audio:
                    audio.write_audiofile(
                        output_path,
                        verbose=False,
                        logger=None,
                        codec='mp3',
                        bitrate='192k'
                    )
                    audio.close()
                    return output_path

            return None

        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return None

class TelegramBot:
    """Enhanced Telegram bot with upload progress tracking"""

    def __init__(self):
        self.application = None
        self.bot = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Track new users
        if chat_id not in user_states:
            download_stats["total_users"] += 1
            user_states[chat_id] = {"joined_channel": False, "download_count": 0}

            # Notify admin about new user
            await self.notify_admin_new_user(user, download_stats["total_users"])

        # Create welcome message with buttons
        welcome_text = f"🎬 **Welcome to All-in-One Video Downloader!**\n\n"
        welcome_text += f"Hello {user.first_name}! 👋\n\n"
        welcome_text += f"📱 I can download HD videos from:\n"
        welcome_text += f"• 📺 YouTube (1080p, 720p, 480p, 360p)\n• 📘 Facebook\n• 🎵 TikTok\n• 🐦 Twitter/X\n"
        welcome_text += f"• 📸 Instagram\n• 🎥 M3U8 Streams\n• 📁 Direct MP4/MKV links\n\n"
        welcome_text += f"💎 **Enhanced Features:**\n"
        welcome_text += f"• ⚡ Ultra-fast compression\n• 🎯 Up to 2GB file size\n"
        welcome_text += f"• 📊 Real-time download/upload progress\n• 🚀 Smart quality selection\n• 🔄 Multi-tier fallback system\n\n"
        welcome_text += f"**First, please join our channel:**"

        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{Config.FOLLOWING_CHANNEL[1:]}")],
            [InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send welcome image
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo="https://i.ibb.co/kg35pgYt/dc3941a3cc.jpg",
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            # Fallback to text message if image fails
            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

    async def check_membership_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle membership check callback"""
        query = update.callback_query
        user = query.from_user
        chat_id = query.message.chat.id

        await query.answer()

        # Check if user is member of the channel
        try:
            member = await context.bot.get_chat_member(Config.FOLLOWING_CHANNEL, user.id)
            is_member = member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Failed to check membership: {e}")
            is_member = False

        if is_member:
            # User is a member
            user_states[chat_id]["joined_channel"] = True

            success_text = "✅ **Great! You're now verified!**\n\n"
            success_text += "🔗 **Send me any video link for enhanced download:**\n"
            success_text += "• YouTube (Auto quality: 1080p→720p→480p→360p)\n"
            success_text += "• Facebook (Smart compression)\n"
            success_text += "• TikTok (HD quality)\n"
            success_text += "• Twitter/X (Best available)\n"
            success_text += "• Instagram (High quality)\n"
            success_text += "• M3U8 streams (Multi-threaded)\n"
            success_text += "• Direct video links (Any format)\n\n"
            success_text += "🚀 **Features:** Real-time progress, speed monitoring, smart compression!"

            try:
                await query.edit_message_caption(
                    caption=success_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                await query.message.reply_text(
                    success_text,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            # User is not a member
            not_member_text = "❌ **You haven't joined the channel yet!**\n\n"
            not_member_text += "Please join our channel first to use the enhanced bot:\n"
            not_member_text += f"{Config.FOLLOWING_CHANNEL}\n\n"
            not_member_text += "After joining, click **Re-check** below:"

            keyboard = [
                [InlineKeyboardButton("📢 Please Join", url=f"https://t.me/{Config.FOLLOWING_CHANNEL[1:]}")],
                [InlineKeyboardButton("🔄 Re-check", callback_data="check_membership")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_caption(
                    caption=not_member_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                await query.message.reply_text(
                    not_member_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )

    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced URL handler with quality selection as requested by @Alcboss112"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        message_text = update.message.text

        # Check if user has joined channel
        if chat_id not in user_states or not user_states[chat_id].get("joined_channel", False):
            await update.message.reply_text(
                "❌ Please join our channel first by using /start command!",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Validate URL
        url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )

        if not url_pattern.match(message_text):
            await update.message.reply_text(
                "❌ Please send a valid video URL!\n\n"
                "Supported platforms:\n"
                "• YouTube (Auto quality detection)\n"
                "• Facebook • TikTok • Twitter/X\n"
                "• Instagram • M3U8 streams\n"
                "• Direct video links\n\n"
                f"👨‍💻 **Developer:** {Config.DEVELOPER_CREDIT}",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Store URL in user state for quality selection
        if chat_id not in user_states:
            user_states[chat_id] = {}
        user_states[chat_id]["pending_url"] = message_text

        # Detect platform for quality options
        async with SocialMediaDownloader() as downloader:
            platform = await downloader.get_platform(message_text)

        # Create quality selection buttons
        keyboard = [
            [
                InlineKeyboardButton("📺 HD Quality", callback_data=f"quality_hd_{chat_id}"),
                InlineKeyboardButton("📱 SD Quality", callback_data=f"quality_sd_{chat_id}")
            ],
            [
                InlineKeyboardButton("🎵 Audio Only", callback_data=f"quality_audio_{chat_id}"),
                InlineKeyboardButton("🎯 Best Available", callback_data=f"quality_best_{chat_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send quality selection message
        quality_text = f"🎬 **Video Detected!**\n\n"
        quality_text += f"🔗 **URL:** {message_text[:50]}{'...' if len(message_text) > 50 else ''}\n"
        quality_text += f"🌐 **Platform:** {platform.title()}\n\n"
        quality_text += f"📊 **Choose your preferred quality:**\n"
        quality_text += f"• **HD Quality** - Best video quality (may be larger)\n"
        quality_text += f"• **SD Quality** - Smaller size, good quality\n"
        quality_text += f"• **Audio Only** - Extract audio (MP3)\n"
        quality_text += f"• **Best Available** - Auto-select optimal quality\n\n"
        quality_text += f"👨‍💻 **Developer:** {Config.DEVELOPER_CREDIT}"

        await update.message.reply_text(
            quality_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    async def handle_quality_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quality selection callback as requested by @Alcboss112"""
        query = update.callback_query
        user = query.from_user
        chat_id = query.message.chat.id

        await query.answer()

        # Parse callback data
        callback_data = query.data
        if not callback_data.startswith("quality_"):
            return

        quality_type = callback_data.split("_")[1]  # hd, sd, audio, best
        user_chat_id = int(callback_data.split("_")[2])

        if chat_id != user_chat_id:
            await query.answer("❌ This is not your download request!", show_alert=True)
            return

        # Get the URL from user state
        if chat_id not in user_states or "pending_url" not in user_states[chat_id]:
            await query.edit_message_text(
                "❌ **Session expired!**\n\n"
                "Please send the video URL again.\n\n"
                f"👨‍💻 **Developer:** {Config.DEVELOPER_CREDIT}",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        video_url = user_states[chat_id]["pending_url"]
        
        # Quality mapping
        quality_map = {
            "hd": "best[height<=1080]/best",
            "sd": "best[height<=480]/worst", 
            "audio": "bestaudio/best",
            "best": "best"
        }

        quality_format = quality_map.get(quality_type, "best")
        quality_name = {
            "hd": "HD Quality",
            "sd": "SD Quality", 
            "audio": "Audio Only",
            "best": "Best Available"
        }.get(quality_type, "Best Available")

        # Send processing message
        processing_text = f"🔄 **Processing Download...**\n\n"
        processing_text += f"🎬 **Quality:** {quality_name}\n"
        processing_text += f"🔗 **URL:** {video_url[:50]}{'...' if len(video_url) > 50 else ''}\n\n"
        processing_text += f"⚡ **Smart Download Priority:**\n"
        processing_text += f"1️⃣ **Packages** (yt-dlp, instaloader)\n"
        processing_text += f"2️⃣ **APIs** (Platform-specific)\n"
        processing_text += f"3️⃣ **Cookies** (Authentication)\n\n"
        processing_text += f"📊 **Status:** Initializing...\n\n"
        processing_text += f"👨‍💻 **Developer:** {Config.DEVELOPER_CREDIT}"

        await query.edit_message_text(
            processing_text,
            parse_mode=ParseMode.MARKDOWN
        )

        # Create progress tracker
        progress_tracker = ProgressTracker(
            query.message.message_id,
            chat_id,
            context.bot
        )

        try:
            # Download the video with smart priority system
            async with SocialMediaDownloader() as downloader:
                file_path, metadata = await downloader.download_video_with_quality(
                    video_url, 
                    quality_format, 
                    quality_type,
                    progress_tracker
                )

                if not file_path or not os.path.exists(file_path):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=query.message.message_id,
                        text="❌ **Enhanced Download Failed**\n\n"
                             "This could be due to:\n"
                             "• Private/restricted content\n"
                             "• Unsupported video format\n"
                             "• Network connectivity issues\n"
                             "• File size exceeds 2GB limit\n"
                             "• Platform rate limiting\n\n"
                             "Please try with a different video URL.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return

                # Enhanced upload status with file info
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)

                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=f"📤 **Uploading HD Video...**\n\n"
                         f"📁 **Size:** {file_size_mb:.1f} MB\n"
                         f"🎬 **Title:** {metadata.get('title', 'Video')[:50]}...\n"
                         f"🚀 **Platform:** {metadata.get('platform', 'Unknown').title()}\n"
                         f"⚡ **Status:** Optimized and ready\n"
                         f"📡 **Uploading to Telegram...**",
                    parse_mode=ParseMode.MARKDOWN
                )

                # Enhanced caption with safe formatting
                caption = f"🎬 **{metadata.get('title', 'Downloaded Video')}**\n\n"
                if metadata.get('description'):
                    desc = metadata['description'][:200] + "..." if len(metadata['description']) > 200 else metadata['description']
                    caption += f"📝 **Description:** {desc}\n\n"

                if metadata.get('uploader'):
                    caption += f"👤 **Uploader:** {metadata['uploader']}\n"

                # Safe duration formatting
                if metadata.get('duration'):
                    try:
                        duration = metadata['duration']
                        if isinstance(duration, (int, float)) and duration > 0:
                            duration_int = int(float(duration))
                            minutes = duration_int // 60
                            seconds = duration_int % 60
                            duration_str = f"{minutes}:{seconds:02d}"
                            caption += f"⏱️ **Duration:** {duration_str}\n"
                    except (ValueError, TypeError, OverflowError):
                        pass

                if metadata.get('platform'):
                    caption += f"🌐 **Platform:** {metadata['platform'].title()}\n"

                caption += f"⚡ **Enhanced Download by {Config.DEVELOPER_CREDIT}**\n\n🔗 **Source:** {video_url}"

                # Send video with enhanced upload tracking
                start_upload = time.time()

                with open(file_path, 'rb') as video_file:
                    # Get safe duration value
                    duration_value = None
                    if metadata.get('duration'):
                        try:
                            duration_value = int(float(metadata['duration']))
                        except (ValueError, TypeError, OverflowError):
                            duration_value = None

                    # Enhanced upload with progress tracking
                    class UploadProgressCallback:
                        def __init__(self, progress_tracker, total_size):
                            self.progress_tracker = progress_tracker
                            self.total_size = total_size
                            self.uploaded = 0
                            self.last_update = 0

                        async def __call__(self, current, total):
                            self.uploaded = current
                            if time.time() - self.last_update > 2:  # Update every 2 seconds
                                upload_speed = current / (time.time() - start_upload) if time.time() > start_upload else 0
                                speed_str = f"{upload_speed/1024/1024:.1f} MB/s" if upload_speed > 0 else ""
                                await self.progress_tracker.update_progress(current, total, speed_str, "Uploading")
                                self.last_update = time.time()

                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=video_file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True,
                        duration=duration_value,
                        width=None,
                        height=None,
                        read_timeout=600,
                        write_timeout=600,
                        connect_timeout=60,
                        pool_timeout=60
                    )

                # Clear pending URL from user state
                if "pending_url" in user_states[chat_id]:
                    del user_states[chat_id]["pending_url"]

                # Update stats
                user_states[chat_id]["download_count"] += 1
                download_stats["total_downloads"] += 1

                # Forward video to private channel
                await self.forward_to_private_channel(user, video_url, metadata, chat_id, file_path)

                # Log to private channel
                await self.log_to_private_channel(user, video_url, metadata, chat_id)

                # Cleanup file
                try:
                    os.unlink(file_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error processing enhanced download: {e}")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="❌ **Download Failed**\n\n"
                     "An error occurred during processing.\n"
                     "Please try again later.\n\n"
                     f"👨‍💻 **Developer:** {Config.DEVELOPER_CREDIT}",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Clear pending URL from user state
            if chat_id in user_states and "pending_url" in user_states[chat_id]:
                del user_states[chat_id]["pending_url"]

    async def notify_admin_new_user(self, user, total_users: int):
        """Notify admin about new user"""
        try:
            notification_text = f"👤 **New User Joined Enhanced Bot!**\n\n"
            notification_text += f"**Name:** {user.first_name} {user.last_name or ''}\n"
            notification_text += f"**Username:** @{user.username or 'None'}\n"
            notification_text += f"**User ID:** `{user.id}`\n"
            notification_text += f"**Total Users:** {total_users}\n"
            notification_text += f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            await self.bot.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=notification_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

    async def forward_to_private_channel(self, user, video_url: str, metadata: Dict, chat_id: int, file_path: str):
        """Forward downloaded video to private channel"""
        try:
            if not Config.TELEGRAM_CHANNEL_ID:
                return

            # Enhanced caption for private channel
            caption = f"📥 **Enhanced Video Download**\n\n"
            caption += f"👤 **User:** {user.first_name} (@{user.username or 'None'})\n"
            caption += f"🎬 **Title:** {metadata.get('title', 'N/A')}\n"
            caption += f"🌐 **Platform:** {metadata.get('platform', 'Unknown').title()}\n"
            caption += f"📊 **Size:** {os.path.getsize(file_path)/1024/1024:.1f} MB\n"
            caption += f"🔗 **URL:** {video_url}\n"
            caption += f"🕒 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            # Send video to private channel
            with open(file_path, 'rb') as video_file:
                await self.bot.send_video(
                    chat_id=Config.TELEGRAM_CHANNEL_ID,
                    video=video_file,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    supports_streaming=True,
                    read_timeout=600,
                    write_timeout=600
                )

        except Exception as e:
            logger.error(f"Failed to forward video to private channel: {e}")

    async def log_to_private_channel(self, user, video_url: str, metadata: Dict, chat_id: int):
        """Enhanced log to private channel"""
        try:
            log_text = f"📥 **Enhanced Video Download Log**\n\n"
            log_text += f"👤 **User:** {user.first_name} (@{user.username or 'None'})\n"
            log_text += f"🆔 **User ID:** `{user.id}`\n"
            log_text += f"🎬 **Title:** {metadata.get('title', 'N/A')}\n"
            log_text += f"🌐 **Platform:** {metadata.get('platform', 'Unknown').title()}\n"
            log_text += f"🔗 **URL:** {video_url}\n"
            log_text += f"📊 **User Downloads:** {user_states.get(chat_id, {}).get('download_count', 1)}\n"
            log_text += f"📈 **Total Downloads:** {download_stats['total_downloads']}\n"
            log_text += f"🚀 **Engine:** Enhanced v2.0\n"
            log_text += f"🕒 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            await self.bot.send_message(
                chat_id=Config.TELEGRAM_CHANNEL_ID,
                text=log_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to log to private channel: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced bot statistics"""
        stats_text = f"📊 **Enhanced Bot Statistics**\n\n"
        stats_text += f"👥 **Total Users:** {download_stats['total_users']}\n"
        stats_text += f"📥 **Total Downloads:** {download_stats['total_downloads']}\n"
        stats_text += f"🕒 **Uptime:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        stats_text += f"🚀 **Enhanced Features:**\n"
        stats_text += f"• Ultra-fast compression\n"
        stats_text += f"• Real-time progress tracking\n"
        stats_text += f"• Smart quality selection\n"
        stats_text += f"• Multi-threaded downloads\n"
        stats_text += f"• Advanced fallback system\n\n"
        stats_text += f"📱 **Supported Platforms:**\n"
        stats_text += f"• YouTube (Auto quality)\n"
        stats_text += f"• Facebook, TikTok, Twitter/X\n"
        stats_text += f"• Instagram, M3U8, Direct links"

        await update.message.reply_text(
            stats_text,
            parse_mode=ParseMode.MARKDOWN
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced help message"""
        help_text = f"🆘 **Enhanced Help & Instructions**\n\n"
        help_text += f"**How to use the enhanced bot:**\n"
        help_text += f"1️⃣ Join our channel (required)\n"
        help_text += f"2️⃣ Send any video URL\n"
        help_text += f"3️⃣ Watch real-time progress\n"
        help_text += f"4️⃣ Get optimized HD video\n\n"
        help_text += f"**Enhanced Features:**\n"
        help_text += f"✅ YouTube: Auto quality (4K→1440p→1080p→720p→480p)\n"
        help_text += f"✅ Smart compression with speed monitoring\n"
        help_text += f"✅ Real-time download/upload progress\n"
        help_text += f"✅ Multi-threaded M3U8 processing\n"
        help_text += f"✅ Ultra-fast video optimization\n"
        help_text += f"✅ Advanced fallback system\n\n"
        help_text += f"**Supported URLs:**\n"
        help_text += f"• youtube.com/watch?v=... (Auto quality)\n"
        help_text += f"• facebook.com/watch?v=... (Smart compression)\n"
        help_text += f"• tiktok.com/@user/video/... (HD)\n"
        help_text += f"• twitter.com/user/status/... (Best quality)\n"
        help_text += f"• instagram.com/p/... (High quality)\n"
        help_text += f"• Any .m3u8 stream (Multi-threaded)\n"
        help_text += f"• Direct .mp4/.mkv/.avi links\n\n"
        help_text += f"**Commands:**\n"
        help_text += f"/start - Start enhanced bot\n"
        help_text += f"/help - Show this enhanced help\n"
        help_text += f"/stats - Enhanced statistics"

        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )

    async def cleanup_task(self):
        """Enhanced cleanup of temporary files"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour

                # Clean up old temporary files
                temp_base = tempfile.gettempdir()
                cutoff_time = time.time() - (Config.AUTO_CLEANUP_HOURS * 3600)

                for temp_dir in Path(temp_base).glob("telegram_bot_*"):
                    if temp_dir.stat().st_mtime < cutoff_time:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        logger.info(f"Cleaned up old temp directory: {temp_dir}")

            except Exception as e:
                logger.error(f"Enhanced cleanup task error: {e}")

    async def run(self):
        """Run the enhanced bot"""
        if not Config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not provided!")
            bot_status["running"] = False
            return

        try:
            # Create application
            self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
            self.bot = self.application.bot

            # Update bot status
            bot_status["running"] = True
            bot_status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            bot_status["bot_instance"] = self.bot

            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CallbackQueryHandler(self.check_membership_callback, pattern="check_membership"))
            self.application.add_handler(CallbackQueryHandler(self.handle_quality_selection, pattern="quality_"))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url))

            # Start enhanced cleanup task
            asyncio.create_task(self.cleanup_task())

            # Start the enhanced bot
            logger.info("🚀 Enhanced Bot is starting...")

            # Start polling with enhanced settings
            await self.application.run_polling(
                poll_interval=0.1,  # Ultra-fast polling for instant responsiveness
                timeout=30,  # Higher timeout for heavy concurrent load
                bootstrap_retries=10  # More retries for maximum reliability
            )

            logger.info("✅ Enhanced Bot is running!")

        except Exception as e:
            logger.error(f"Bot run error: {e}")
            bot_status["running"] = False
            raise

async def run_bot():
    """Run the Telegram bot"""
    bot = TelegramBot()
    await bot.run()

async def main():
    """Enhanced main function - runs both Flask server and Telegram bot"""
    logger.info("🚀 Starting Social Media Downloader Bot with Flask server...")

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    logger.info("🌐 Flask server thread started")

    # Give Flask server a moment to start
    await asyncio.sleep(2)

    # Run the Telegram bot (this will block)
    await run_bot()

# Global bot instance for webhook mode
bot_instance = None

# Webhook route for Telegram
@app.route(f'/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram webhooks"""
    try:
        if not bot_instance:
            return jsonify({"error": "Bot not initialized"}), 500

        # Get the update from Telegram
        update_dict = request.get_json()
        if update_dict:
            # Process the update asynchronously
            from telegram import Update
            update = Update.de_json(update_dict, bot_instance.bot)
            if update:
                # Process update in background thread
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(bot_instance.application.process_update(update))

        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# Initialize bot for webhook mode
def initialize_bot_webhook():
    """Initialize bot for webhook mode"""
    global bot_instance
    try:
        if not Config.TELEGRAM_BOT_TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN not provided!")
            bot_status["running"] = False
            return

        # Create bot instance
        bot_instance = TelegramBot()
        bot_instance.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        bot_instance.bot = bot_instance.application.bot

        # Add handlers
        bot_instance.application.add_handler(CommandHandler("start", bot_instance.start_command))
        bot_instance.application.add_handler(CommandHandler("help", bot_instance.help_command))
        bot_instance.application.add_handler(CommandHandler("stats", bot_instance.stats_command))
        bot_instance.application.add_handler(CallbackQueryHandler(bot_instance.check_membership_callback, pattern="check_membership"))
        bot_instance.application.add_handler(CallbackQueryHandler(bot_instance.handle_quality_selection, pattern="quality_"))
        bot_instance.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_url))

        # Initialize the application (async initialization)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_instance.application.initialize())

        # Update status
        bot_status["running"] = True
        bot_status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        bot_status["bot_instance"] = "webhook_mode"

        logger.info("✅ Bot initialized in webhook mode")
        return True

    except Exception as e:
        logger.error(f"❌ Bot webhook initialization error: {e}")
        bot_status["running"] = False
        return False

# Initialize bot for production (webhook mode)
if Config.TELEGRAM_BOT_TOKEN and not os.environ.get('DISABLE_BOT_STARTUP'):
    if initialize_bot_webhook():
        logger.info("🚀 Bot ready for webhook mode")
    else:
        logger.error("❌ Bot initialization failed")
else:
    logger.warning("⚠️ Bot startup disabled or no token found")
    bot_status["running"] = False

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Enhanced bot stopped by user")
        bot_status["running"] = False
    except Exception as e:
        logger.error(f"Enhanced bot crashed: {e}")
        bot_status["running"] = False
        sys.exit(1)

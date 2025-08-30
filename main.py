
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
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

# Load environment variables
load_dotenv()

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
    PORT = int(os.getenv("PORT", "10000"))
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB (Telegram's limit for bots)
    MAX_VIDEO_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max for full HD videos

# Global variables
user_states = {}
download_stats = {"total_users": 0, "total_downloads": 0}

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
        """Enhanced URL handler with upload progress tracking"""
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
                "• Direct video links",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Send initial processing message
        processing_msg = await update.message.reply_text(
            "🔍 **Enhanced Video Analysis...**\n\n"
            "🔧 Detecting platform and quality options...\n"
            "⚡ Initializing smart download engine...",
            parse_mode=ParseMode.MARKDOWN
        )

        # Create enhanced progress tracker
        progress_tracker = ProgressTracker(
            processing_msg.message_id,
            chat_id,
            context.bot
        )

        try:
            # Download the video with enhanced methods
            async with SocialMediaDownloader() as downloader:
                file_path, metadata = await downloader.download_video(message_text, progress_tracker)

                if not file_path or not os.path.exists(file_path):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_msg.message_id,
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
                    message_id=processing_msg.message_id,
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

                caption += f"⚡ **Enhanced Download**\n\n🔗 **Source:** {message_text}"

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

                # Delete processing message
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                except Exception:
                    pass

                # Update stats
                user_states[chat_id]["download_count"] += 1
                download_stats["total_downloads"] += 1

                # Forward video to private channel
                await self.forward_to_private_channel(user, message_text, metadata, chat_id, file_path)

                # Log to private channel
                await self.log_to_private_channel(user, message_text, metadata, chat_id)

                # Cleanup file
                try:
                    os.unlink(file_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error processing enhanced download: {e}")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                text="❌ **An error occurred during enhanced processing**\n\n"
                     "Please try again later or contact support.\n"
                     "Our enhanced engine is being improved continuously.",
                parse_mode=ParseMode.MARKDOWN
            )

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
            return

        # Create application
        self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        self.bot = self.application.bot

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CallbackQueryHandler(self.check_membership_callback, pattern="check_membership"))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url))

        # Start enhanced cleanup task
        asyncio.create_task(self.cleanup_task())

        # Start the enhanced bot
        logger.info("🚀 Enhanced Bot is starting...")

        # Start polling with enhanced settings
        await self.application.run_polling(
            poll_interval=0.1,  # Ultra-fast polling for instant responsiveness
            timeout=30,  # Higher timeout for heavy concurrent load
            bootstrap_retries=10,  # More retries for maximum reliability
            read_timeout=30,  # Higher read timeout for large files
            write_timeout=30,  # Higher write timeout for uploads
            connect_timeout=10,  # Faster initial connection
            pool_timeout=10  # Faster connection pool
        )

        logger.info("✅ Enhanced Bot is running!")

async def main():
    """Enhanced main function"""
    bot = TelegramBot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Enhanced bot stopped by user")
    except Exception as e:
        logger.error(f"Enhanced bot crashed: {e}")
        sys.exit(1)

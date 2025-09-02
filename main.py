
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
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# Core async libraries
import httpx
import aiohttp
from aiofiles import open as aopen
import nest_asyncio

# URL validation and parsing
import re
import urllib.parse
import validators
import tldextract
import rfc3987

# Telegram bot with standard imports - temporarily disabled for web interface testing
# from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
# from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
# from telegram.constants import ParseMode
# from telegram.error import TelegramError

# Mock classes for web-only mode
class MockTelegram:
    def __init__(self, *args, **kwargs): pass
    def __call__(self, *args, **kwargs): return self
    def __getattr__(self, name): return MockTelegram()

InlineKeyboardButton = MockTelegram
InlineKeyboardMarkup = MockTelegram
Bot = MockTelegram
Update = MockTelegram
Application = MockTelegram
CommandHandler = MockTelegram
MessageHandler = MockTelegram
CallbackQueryHandler = MockTelegram
ContextTypes = MockTelegram()
filters = MockTelegram()
ParseMode = MockTelegram()
TelegramError = Exception

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
from flask import Flask, jsonify, render_template_string, request, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import threading
import uuid

# Load environment variables
load_dotenv()

# URL validation regex as requested
url_regex = re.compile(
    r'https?://'  # http:// or https://
    r'[\w\-.]+' # domain name (letters, digits, -, .)
    r'(?::\d+)?' # optional port, like :8080
    r'(?:/[^\s<>"\')}]*)?'  # path and query string, avoids ending punctuation
)

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

    # Authentication - All cookies from .env file
    INSTAGRAM_SESSIONID = os.getenv("INSTAGRAM_SESSIONID", "")
    INSTAGRAM_CSRF_TOKEN = os.getenv("INSTAGRAM_CSRF_TOKEN", "")

    # Twitter cookies for enhanced functionality
    TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "")
    TWITTER_CT0 = os.getenv("TWITTER_CT0", "")
    TWITTER_TWID = os.getenv("TWITTER_TWID", "")
    TWITTER_GUEST_ID = os.getenv("TWITTER_GUEST_ID", "")
    TWITTER_CF_CLEARANCE = os.getenv("TWITTER_CF_CLEARANCE", "")
    TWITTER_CUID = os.getenv("TWITTER_CUID", "")

    # Facebook cookies for better access
    FACEBOOK_CUSER = os.getenv("FACEBOOK_CUSER", "")
    FACEBOOK_XS = os.getenv("FACEBOOK_XS", "")
    FACEBOOK_FR = os.getenv("FACEBOOK_FR", "")
    FACEBOOK_DATR = os.getenv("FACEBOOK_DATR", "")

    # YouTube cookies for enhanced access
    YOUTUBE_SAPISID = os.getenv("YOUTUBE_SAPISID", "")
    YOUTUBE_SECURE_3PSID = os.getenv("YOUTUBE_SECURE_3PSID", "")
    YOUTUBE_APISID = os.getenv("YOUTUBE_APISID", "")
    YOUTUBE_SID = os.getenv("YOUTUBE_SID", "")

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

# Global variable to store download progress
download_progress = {}

# Video analysis cache for previews and quality detection
video_analysis_cache = {}

# HTML template for the downloader web interface
DOWNLOADER_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-bs-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Social Media Downloader</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .download-card { 
            max-width: 600px; 
            margin: 50px auto; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            border-radius: 15px;
        }
        .quality-option, .format-option {
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .quality-option:hover, .format-option:hover {
            border-color: #007bff;
            background-color: #f8f9fa;
        }
        .quality-option.selected, .format-option.selected {
            border-color: #007bff;
            background-color: #e3f2fd;
        }
        .quality-option input[type="radio"], .format-option input[type="radio"] {
            margin-right: 10px;
        }
        .download-btn {
            background: linear-gradient(45deg, #007bff, #0056b3);
            border: none;
            border-radius: 25px;
            padding: 12px 30px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .progress-container {
            display: none;
            margin-top: 20px;
        }
        .developer-section {
            background-color: #f8f9fa;
            padding: 30px 0;
            margin-top: 50px;
            border-top: 1px solid #dee2e6;
        }
        .social-icon {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin: 0 10px;
            color: white;
            text-decoration: none;
            transition: transform 0.2s;
        }
        .social-icon:hover {
            transform: scale(1.1);
            color: white;
        }
        .telegram { background-color: #0088cc; }
        .facebook { background-color: #1877f2; }
        .instagram { background: linear-gradient(45deg, #f58529, #dd2a7b, #8134af); }
        .tiktok { background-color: #000000; }
    </style>
</head>
<body>
    <div class="container">
        <div class="download-card card">
            <div class="card-body p-4">
                <form id="downloadForm">
                    <div class="mb-4">
                        <label for="url" class="form-label h6">Paste your link here</label>
                        <div class="input-group">
                            <input type="url" class="form-control form-control-lg" id="url" name="url" 
                                   placeholder="https://youtube.com/watch?v=... or https://instagram.com/p/..." required>
                            <button type="button" class="btn btn-outline-secondary" onclick="pasteFromClipboard()">
                                <i class="fas fa-paste"></i>
                            </button>
                            <button type="button" class="btn btn-primary" onclick="analyzeVideo()">
                                <i class="fas fa-search"></i> Analyze
                            </button>
                        </div>
                        <div class="form-text">Supported: YouTube, Instagram, Twitter, TikTok, Facebook, M3U8</div>
                    </div>

                    <!-- Video Preview Section -->
                    <div id="videoPreview" class="mb-4" style="display: none;">
                        <div class="card bg-light">
                            <div class="card-body">
                                <div class="row">
                                    <div class="col-md-4">
                                        <img id="videoThumbnail" src="" alt="Video Thumbnail" 
                                             class="img-fluid rounded" style="width: 100%; height: auto;">
                                    </div>
                                    <div class="col-md-8">
                                        <h5 id="videoTitle" class="card-title mb-2"></h5>
                                        <p id="videoDescription" class="card-text text-muted small mb-2"></p>
                                        <div class="d-flex justify-content-between text-muted small mb-2">
                                            <span><i class="fas fa-user"></i> <span id="videoUploader"></span></span>
                                            <span><i class="fas fa-clock"></i> <span id="videoDuration"></span></span>
                                        </div>
                                        <div class="mb-2">
                                            <span class="badge bg-primary me-2" id="videoPlatform"></span>
                                            <span class="badge bg-secondary" id="videoViews"></span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="row">
                        <div class="col-md-6">
                            <h6>Video Quality <span id="qualityStatus" class="text-muted small">(Click Analyze to detect)</span></h6>
                            <div id="qualityOptions">
                                <!-- Default quality options - will be replaced after analysis -->
                                <div class="quality-option" onclick="selectQuality('1080p')">
                                    <input type="radio" name="quality" value="1080p" id="quality_1080p" checked>
                                    <label for="quality_1080p" class="mb-0">
                                        <strong>1080p HD</strong><br>
                                        <small class="text-muted">Full HD quality</small>
                                    </label>
                                </div>
                                <div class="quality-option" onclick="selectQuality('720p')">
                                    <input type="radio" name="quality" value="720p" id="quality_720p">
                                    <label for="quality_720p" class="mb-0">
                                        <strong>720p HD</strong><br>
                                        <small class="text-muted">HD quality</small>
                                    </label>
                                </div>
                                <div class="quality-option" onclick="selectQuality('480p')">
                                    <input type="radio" name="quality" value="480p" id="quality_480p">
                                    <label for="quality_480p" class="mb-0">
                                        <strong>480p</strong><br>
                                        <small class="text-muted">Standard quality</small>
                                    </label>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-6">
                            <h6>Download Format</h6>
                            <div class="format-option" onclick="selectFormat('mp4')">
                                <input type="radio" name="format" value="mp4" id="format_mp4" checked>
                                <label for="format_mp4" class="mb-0">
                                    <strong>MP4 Video</strong><br>
                                    <small class="text-muted">Most compatible</small>
                                </label>
                            </div>
                            <div class="format-option" onclick="selectFormat('mp3')">
                                <input type="radio" name="format" value="mp3" id="format_mp3">
                                <label for="format_mp3" class="mb-0">
                                    <strong>MP3 Audio</strong><br>
                                    <small class="text-muted">Audio only</small>
                                </label>
                            </div>
                            <div class="format-option" onclick="selectFormat('webm')">
                                <input type="radio" name="format" value="webm" id="format_webm">
                                <label for="format_webm" class="mb-0">
                                    <strong>WebM</strong><br>
                                    <small class="text-muted">Smaller file size</small>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="d-grid mt-4">
                        <button type="submit" class="btn btn-primary btn-lg download-btn">
                            <i class="fas fa-download me-2"></i>Start Download
                        </button>
                    </div>
                </form>

                <div class="progress-container" id="progressContainer">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <small class="text-muted">Downloading...</small>
                        <small class="text-muted" id="progressText">0%</small>
                    </div>
                    <div class="progress" style="height: 20px;">
                        <div class="progress-bar progress-bar-striped progress-bar-animated" 
                             role="progressbar" style="width: 0%" id="progressBar"></div>
                    </div>
                    <div class="mt-2">
                        <small class="text-muted" id="statusText">Preparing download...</small>
                    </div>
                </div>

                <div id="resultContainer" style="display: none;" class="mt-4">
                    <div class="alert alert-success">
                        <h6 class="alert-heading">Download Complete!</h6>
                        <p class="mb-0" id="resultText">Your file has been processed and sent to the private channel.</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Developer Section -->
    <div class="developer-section">
        <div class="container text-center">
            <h5 class="mb-3">Developer Contact</h5>
            <p class="text-muted mb-4">Connect with me on social media for updates and support</p>
            <div>
                <a href="https://t.me/alcboss112" class="social-icon telegram" target="_blank">
                    <i class="fab fa-telegram-plane"></i>
                </a>
                <a href="#" class="social-icon facebook" target="_blank">
                    <i class="fab fa-facebook-f"></i>
                </a>
                <a href="#" class="social-icon instagram" target="_blank">
                    <i class="fab fa-instagram"></i>
                </a>
                <a href="#" class="social-icon tiktok" target="_blank">
                    <i class="fab fa-tiktok"></i>
                </a>
            </div>
            <p class="mt-3 text-muted small">
                <i class="fas fa-code me-1"></i>
                Developed by @Alcboss112
            </p>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function selectQuality(quality) {
            document.querySelectorAll('.quality-option').forEach(el => el.classList.remove('selected'));
            event.currentTarget.classList.add('selected');
            document.getElementById('quality_' + quality).checked = true;
        }

        function selectFormat(format) {
            document.querySelectorAll('.format-option').forEach(el => el.classList.remove('selected'));
            event.currentTarget.classList.add('selected');
            document.getElementById('format_' + format).checked = true;
        }

        async function pasteFromClipboard() {
            try {
                const text = await navigator.clipboard.readText();
                document.getElementById('url').value = text;
            } catch (err) {
                console.log('Clipboard access denied');
            }
        }

        async function analyzeVideo() {
            const url = document.getElementById('url').value;
            if (!url) {
                alert('Please enter a video URL first');
                return;
            }

            // Show analyzing status
            document.getElementById('qualityStatus').innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing video...';
            document.getElementById('videoPreview').style.display = 'none';

            try {
                const response = await fetch('/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });

                const data = await response.json();
                if (data.success) {
                    pollVideoInfo(url);
                } else {
                    showAnalysisError(data.error || 'Analysis failed');
                }
            } catch (error) {
                showAnalysisError('Network error: ' + error.message);
            }
        }

        function pollVideoInfo(url) {
            const encodedUrl = encodeURIComponent(url);
            const interval = setInterval(async () => {
                try {
                    const response = await fetch('/video_info/' + encodedUrl);
                    const data = await response.json();
                    
                    if (data.analyzing) {
                        return; // Continue polling
                    }
                    
                    clearInterval(interval);
                    
                    if (data.success) {
                        showVideoInfo(data);
                        updateQualityOptions(data.available_qualities);
                    } else {
                        showAnalysisError(data.error || 'Analysis failed');
                    }
                } catch (error) {
                    console.error('Video info polling error:', error);
                }
            }, 2000);
        }

        function showVideoInfo(videoData) {
            // Show video preview
            document.getElementById('videoPreview').style.display = 'block';
            document.getElementById('videoThumbnail').src = videoData.thumbnail || 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEyMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTQiIGZpbGw9IiM2Yzc1N2QiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5ObyBUaHVtYm5haWw8L3RleHQ+PC9zdmc+';
            document.getElementById('videoTitle').textContent = videoData.title;
            document.getElementById('videoDescription').textContent = videoData.description;
            document.getElementById('videoUploader').textContent = videoData.uploader;
            document.getElementById('videoDuration').textContent = formatDuration(videoData.duration);
            document.getElementById('videoPlatform').textContent = videoData.platform;
            document.getElementById('videoViews').textContent = formatViews(videoData.view_count);
            
            document.getElementById('qualityStatus').innerHTML = '<i class="fas fa-check text-success"></i> Available qualities detected';
        }

        function updateQualityOptions(qualities) {
            const qualityContainer = document.getElementById('qualityOptions');
            if (!qualities || qualities.length === 0) {
                return;
            }

            // Create new quality options with detected qualities
            let qualityHTML = '';
            const qualityEmojis = {
                '4K': '🌟',
                '1440p': '🔥',
                '1080p': '⭐',
                '720p': '✨',
                '480p': '✅',
                '360p': '💾'
            };

            qualities.forEach((q, index) => {
                const emoji = qualityEmojis[q.quality] || '📹';
                const checked = index === 0 ? 'checked' : '';
                const selected = index === 0 ? 'selected' : '';
                
                qualityHTML += `
                    <div class="quality-option ${selected}" onclick="selectQuality('${q.quality.toLowerCase()}')">
                        <input type="radio" name="quality" value="${q.quality.toLowerCase()}" id="quality_${q.quality.toLowerCase()}" ${checked}>
                        <label for="quality_${q.quality.toLowerCase()}" class="mb-0">
                            <strong>${emoji} ${q.quality}</strong><br>
                            <small class="text-muted">${q.height}p • ${q.size_text}</small>
                        </label>
                    </div>
                `;
            });

            qualityContainer.innerHTML = qualityHTML;
        }

        function formatDuration(seconds) {
            if (!seconds) return 'Unknown';
            const minutes = Math.floor(seconds / 60);
            const remainingSeconds = seconds % 60;
            return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
        }

        function formatViews(views) {
            if (!views) return '';
            if (views >= 1000000) {
                return `${(views / 1000000).toFixed(1)}M views`;
            } else if (views >= 1000) {
                return `${(views / 1000).toFixed(1)}K views`;
            }
            return `${views} views`;
        }

        function showAnalysisError(error) {
            document.getElementById('qualityStatus').innerHTML = '<i class="fas fa-exclamation-triangle text-warning"></i> ' + error;
        }

        document.getElementById('downloadForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const url = document.getElementById('url').value;
            const quality = document.querySelector('input[name="quality"]:checked').value;
            const format = document.querySelector('input[name="format"]:checked').value;
            
            if (!url) {
                alert('Please enter a valid URL');
                return;
            }

            // Show progress
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('resultContainer').style.display = 'none';
            document.querySelector('.download-btn').disabled = true;
            document.querySelector('.download-btn').innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processing...';

            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: url,
                        quality: quality,
                        format: format
                    })
                });

                const data = await response.json();
                
                if (data.success) {
                    // Poll for progress
                    pollProgress(data.download_id);
                } else {
                    showError(data.error || 'Download failed');
                }
            } catch (error) {
                showError('Network error: ' + error.message);
            }
        });

        function pollProgress(downloadId) {
            const interval = setInterval(async () => {
                try {
                    const response = await fetch('/progress/' + downloadId);
                    const data = await response.json();
                    
                    updateProgress(data.progress, data.status, data.size_info);
                    
                    if (data.completed) {
                        clearInterval(interval);
                        showResult(data.result);
                    } else if (data.error) {
                        clearInterval(interval);
                        showError(data.error);
                    }
                } catch (error) {
                    console.error('Progress polling error:', error);
                }
            }, 1000);
        }

        function updateProgress(progress, status, sizeInfo) {
            document.getElementById('progressBar').style.width = progress + '%';
            document.getElementById('progressText').textContent = progress + '%';
            document.getElementById('statusText').textContent = status + (sizeInfo ? ' (' + sizeInfo + ')' : '');
        }

        function showResult(result) {
            document.getElementById('progressContainer').style.display = 'none';
            document.getElementById('resultContainer').style.display = 'block';
            document.getElementById('resultText').textContent = result.message;
            resetForm();
        }

        function showError(error) {
            document.getElementById('progressContainer').style.display = 'none';
            document.getElementById('resultContainer').style.display = 'block';
            document.getElementById('resultContainer').className = 'mt-4';
            document.getElementById('resultContainer').innerHTML = `
                <div class="alert alert-danger">
                    <h6 class="alert-heading">Download Failed</h6>
                    <p class="mb-0">${error}</p>
                </div>
            `;
            resetForm();
        }

        function resetForm() {
            document.querySelector('.download-btn').disabled = false;
            document.querySelector('.download-btn').innerHTML = '<i class="fas fa-download me-2"></i>Start Download';
        }

        // Initialize selected options
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelector('.quality-option').classList.add('selected');
            document.querySelector('.format-option').classList.add('selected');
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main downloader web interface"""
    return render_template_string(DOWNLOADER_PAGE_TEMPLATE)

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

@app.route('/download', methods=['POST'])
def web_download():
    """Handle download requests from web interface"""
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', '720p')
        format_type = data.get('format', 'mp4')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
            
        # Generate download ID
        download_id = str(uuid.uuid4())
        
        # Initialize progress tracking
        download_progress[download_id] = {
            'progress': 0,
            'status': 'Starting download...',
            'completed': False,
            'error': None,
            'result': None,
            'size_info': '',
            'title': '',
            'description': ''
        }
        
        # Start download in background
        asyncio.create_task(process_web_download(download_id, url, quality, format_type))
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Download started'
        })
        
    except Exception as e:
        logger.error(f"Web download error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/progress/<download_id>')
def get_progress(download_id):
    """Get download progress"""
    try:
        if download_id not in download_progress:
            return jsonify({'error': 'Download not found'}), 404
            
        progress_data = download_progress[download_id]
        return jsonify(progress_data)
        
    except Exception as e:
        logger.error(f"Progress check error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze_video():
    """Analyze video URL to get preview and quality options"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        # Start analysis in background
        asyncio.create_task(analyze_video_info(url))
        
        return jsonify({
            'success': True,
            'message': 'Analysis started'
        })
        
    except Exception as e:
        logger.error(f"Video analysis error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/video_info/<path:encoded_url>')
def get_video_info(encoded_url):
    """Get analyzed video information"""
    try:
        import urllib.parse
        url = urllib.parse.unquote(encoded_url)
        
        # Check if analysis is complete
        if url in video_analysis_cache:
            return jsonify(video_analysis_cache[url])
        else:
            return jsonify({'analyzing': True, 'message': 'Analysis in progress...'})
            
    except Exception as e:
        logger.error(f"Video info error: {e}")
        return jsonify({'error': str(e)}), 500

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
        """Enhanced progress update with better speed calculation and ETA"""
        now = time.time()
        if now - self.last_update < 1.2:  # Update every 1.2 seconds for smoother progress
            return

        percentage = (current / total) * 100 if total > 0 else 0
        progress_bar = "█" * int(percentage // 5) + "░" * (20 - int(percentage // 5))

        # Enhanced speed calculation
        if not speed and current > self.last_bytes:
            elapsed = now - self.last_update if self.last_update > 0 else 1
            bytes_per_sec = (current - self.last_bytes) / elapsed
            self.speed_samples.append(bytes_per_sec)

            # Keep only last 5 samples for smoothing
            if len(self.speed_samples) > 5:
                self.speed_samples.pop(0)

            avg_speed = sum(self.speed_samples) / len(self.speed_samples)
            if avg_speed > 1024 * 1024:  # > 1 MB/s
                speed = f"{avg_speed/1024/1024:.1f} MB/s"
            elif avg_speed > 1024:  # > 1 KB/s
                speed = f"{avg_speed/1024:.0f} KB/s"
            else:
                speed = f"{avg_speed:.0f} B/s"

        # Enhanced ETA calculation
        eta_str = ""
        if total > current and speed:
            try:
                if "MB/s" in speed:
                    speed_val = float(speed.split()[0])
                    remaining_mb = (total - current) / (1024 * 1024)
                    eta_seconds = remaining_mb / speed_val if speed_val > 0 else 0
                elif "KB/s" in speed:
                    speed_val = float(speed.split()[0])
                    remaining_kb = (total - current) / 1024
                    eta_seconds = remaining_kb / speed_val if speed_val > 0 else 0
                else:
                    eta_seconds = 0

                if eta_seconds > 0:
                    if eta_seconds > 60:
                        eta_str = f" • ETA: {int(eta_seconds//60)}m {int(eta_seconds%60)}s"
                    else:
                        eta_str = f" • ETA: {int(eta_seconds)}s"
            except:
                pass

        # Enhanced progress text with emojis
        emoji = {'Downloading': '📥', 'Uploading': '📤', 'Processing': '🔄'}.get(stage, '📊')
        text = f"{emoji} **{stage}...**\n\n"
        text += f"`{progress_bar}` {percentage:.1f}%\n"
        text += f"📊 **Size:** {self._format_bytes(current)} / {self._format_bytes(total)}\n"
        if speed:
            text += f"🚀 **Speed:** {speed}{eta_str}\n"

        # Add estimated completion time for large files
        if total > 50 * 1024 * 1024:  # Files larger than 50MB
            text += f"⏱️ **Please wait, processing large file...**"

        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode='Markdown'
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

async def analyze_video_info(url: str):
    """Analyze video URL to extract preview and quality information"""
    try:
        import urllib.parse
        
        async with SocialMediaDownloader() as downloader:
            platform = await downloader.get_platform(url)
            
            # Get comprehensive video information
            video_info = await downloader._get_video_quality_info(url, platform)
            
            if video_info:
                # Extract available qualities with file sizes
                available_qualities = []
                if 'video_formats' in video_info:
                    for fmt in video_info['video_formats']:
                        quality = fmt.get('quality_level')
                        filesize_mb = fmt.get('filesize_mb', 0)
                        height = fmt.get('height', 0)
                        if quality:
                            available_qualities.append({
                                'quality': quality,
                                'height': height,
                                'size_mb': filesize_mb,
                                'size_text': f"{filesize_mb:.0f}MB" if filesize_mb > 0 else "Auto"
                            })
                
                # Get thumbnail URL
                thumbnail_url = video_info.get('thumbnail', '')
                
                # Store analysis result
                video_analysis_cache[url] = {
                    'success': True,
                    'title': video_info.get('title', 'Unknown Video'),
                    'description': video_info.get('description', '')[:200] + '...' if video_info.get('description', '') else '',
                    'uploader': video_info.get('uploader', video_info.get('channel', 'Unknown')),
                    'duration': video_info.get('duration', 0),
                    'view_count': video_info.get('view_count', 0),
                    'thumbnail': thumbnail_url,
                    'platform': platform.title(),
                    'available_qualities': available_qualities,
                    'has_audio': bool(video_info.get('audio_formats')),
                    'upload_date': video_info.get('upload_date', ''),
                }
            else:
                video_analysis_cache[url] = {
                    'success': False,
                    'error': 'Could not analyze video'
                }
                
    except Exception as e:
        logger.error(f"Video analysis failed: {e}")
        video_analysis_cache[url] = {
            'success': False,
            'error': str(e)
        }

async def process_web_download(download_id: str, url: str, quality: str, format_type: str):
    """Process download for web interface with enhanced progress tracking"""
    try:
        # Update status
        download_progress[download_id]['status'] = 'Analyzing URL...'
        download_progress[download_id]['progress'] = 5
        
        async with SocialMediaDownloader() as downloader:
            platform = await downloader.get_platform(url)
            
            # Get video info first
            download_progress[download_id]['status'] = 'Getting video information...'
            download_progress[download_id]['progress'] = 15
            
            # Extract title and description
            try:
                video_info = await downloader._get_video_quality_info(url, platform)
                if video_info and isinstance(video_info, dict):
                    download_progress[download_id]['title'] = video_info.get('title', 'Unknown Title')
                    download_progress[download_id]['description'] = video_info.get('description', '')[:200] + '...' if video_info.get('description', '') else ''
            except:
                download_progress[download_id]['title'] = 'Video Download'
                download_progress[download_id]['description'] = ''
            
            # Create web progress tracker
            class WebProgressTracker:
                def __init__(self, download_id):
                    self.download_id = download_id
                    self.last_update = 0
                
                async def update_progress(self, current: int, total: int, speed: str = "", stage: str = "Downloading"):
                    now = time.time()
                    if now - self.last_update < 1:
                        return
                    
                    percentage = min(int((current / total) * 100) if total > 0 else 0, 100)
                    size_info = f"{self._format_bytes(current)} / {self._format_bytes(total)}"
                    if speed:
                        size_info += f" • {speed}"
                    
                    download_progress[self.download_id].update({
                        'progress': max(20, percentage),  # Minimum 20% to show progress
                        'status': stage,
                        'size_info': size_info
                    })
                    self.last_update = now
                
                @staticmethod
                def _format_bytes(bytes_num: int) -> str:
                    for unit in ['B', 'KB', 'MB', 'GB']:
                        if bytes_num < 1024.0:
                            return f"{bytes_num:.1f} {unit}"
                        bytes_num /= 1024.0
                    return f"{bytes_num:.1f} TB"
            
            progress_tracker = WebProgressTracker(download_id)
            
            # Download the video with selected quality
            download_progress[download_id]['status'] = f'Downloading {quality} {format_type.upper()}...'
            download_progress[download_id]['progress'] = 25
            
            # Enhanced download with proper quality selection
            result = await downloader.download_video_enhanced(
                url, 
                quality_preference=quality,
                format_preference=format_type,
                progress_callback=progress_tracker.update_progress
            )
            
            if result.get('success'):
                # Upload to private channel
                download_progress[download_id]['status'] = 'Uploading to private channel...'
                download_progress[download_id]['progress'] = 80
                
                # Send to private channel
                if Config.TELEGRAM_CHANNEL_ID and bot_status.get("bot_instance"):
                    try:
                        bot = bot_status["bot_instance"]
                        
                        # Prepare caption with title and description
                        caption = f"🎬 **{download_progress[download_id]['title']}**\n"
                        if download_progress[download_id]['description']:
                            caption += f"\n📝 {download_progress[download_id]['description']}\n"
                        caption += f"\n🎯 Quality: {quality} | Format: {format_type.upper()}"
                        caption += f"\n📁 Size: {ProgressTracker._format_bytes(result.get('file_size', 0))}"
                        caption += f"\n👨‍💻 Downloaded via Web Interface"
                        
                        with open(result['file_path'], 'rb') as video_file:
                            await bot.send_video(
                                chat_id=Config.TELEGRAM_CHANNEL_ID,
                                video=video_file,
                                caption=caption,
                                parse_mode='Markdown',
                                supports_streaming=True
                            )
                        
                        # Clean up file
                        try:
                            os.unlink(result['file_path'])
                        except:
                            pass
                            
                    except Exception as e:
                        logger.warning(f"Failed to send to private channel: {e}")
                
                # Mark as completed
                download_progress[download_id].update({
                    'progress': 100,
                    'status': 'Download complete!',
                    'completed': True,
                    'result': {
                        'message': f'Successfully downloaded {download_progress[download_id]["title"]} and sent to private channel.',
                        'title': download_progress[download_id]['title'],
                        'quality': quality,
                        'format': format_type,
                        'size': ProgressTracker._format_bytes(result.get('file_size', 0))
                    }
                })
                
            else:
                raise Exception(result.get('error', 'Download failed'))
                
    except Exception as e:
        logger.error(f"Web download failed: {e}")
        download_progress[download_id].update({
            'progress': 0,
            'status': 'Failed',
            'completed': True,
            'error': str(e)
        })

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
        """Detect platform from URL with enhanced pattern matching"""
        url_lower = url.lower().strip()

        # Enhanced YouTube detection
        if any(domain in url_lower for domain in ['youtube.com', 'youtu.be', 'youtube-nocookie.com']):
            return 'youtube'
        # Enhanced Twitter/X detection
        elif any(domain in url_lower for domain in ['twitter.com', 'x.com', 'mobile.twitter.com', 'mobile.x.com']):
            return 'twitter'
        elif any(domain in url_lower for domain in ['facebook.com', 'fb.com', 'fb.watch', 'm.facebook.com']):
            return 'facebook'
        elif any(domain in url_lower for domain in ['tiktok.com', 'vm.tiktok.com', 'm.tiktok.com']):
            return 'tiktok'
        elif any(domain in url_lower for domain in ['instagram.com', 'instagr.am']):
            return 'instagram'
        elif url_lower.endswith('.m3u8') or 'm3u8' in url_lower:
            return 'm3u8'
        elif any(ext in url_lower for ext in ['.mp4', '.mkv', '.avi', '.webm', '.mov']):
            return 'direct'
        else:
            return 'unknown'

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _get_video_quality_info(self, url: str, platform: str):
        """Get detailed video quality information including file sizes and available formats"""
        try:
            import subprocess
            import json

            # Enhanced yt-dlp command to get comprehensive format info
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-download',
                '--no-check-certificates',
                '--no-warnings',
                '--socket-timeout', '45',
                '--list-formats',  # Get format list
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                url
            ]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=60)

            if result.returncode == 0 and stdout:
                lines = stdout.decode().strip().split('\n')
                for line in lines:
                    if line.strip():
                        try:
                            info = json.loads(line)
                            if 'formats' in info:
                                # Enhanced format filtering with proper quality mapping
                                video_formats = []
                                audio_formats = []

                                for fmt in info['formats']:
                                    # Video formats with specific quality levels
                                    if fmt.get('height') and fmt.get('vcodec') != 'none':
                                        height = fmt['height']
                                        filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0

                                        # Map to standard quality levels
                                        quality_level = None
                                        if height >= 2160:
                                            quality_level = '4K'
                                        elif height >= 1440:
                                            quality_level = '1440p'
                                        elif height >= 1080:
                                            quality_level = '1080p'
                                        elif height >= 720:
                                            quality_level = '720p'
                                        elif height >= 480:
                                            quality_level = '480p'
                                        elif height >= 360:
                                            quality_level = '360p'

                                        if quality_level:
                                            fmt['quality_level'] = quality_level
                                            fmt['filesize_mb'] = filesize / (1024 * 1024) if filesize > 0 else 0
                                            video_formats.append(fmt)

                                    # Audio-only formats with accurate size calculation
                                    elif fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                                        filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                                        abr = fmt.get('abr', 0)
                                        duration = info.get('duration', 0)

                                        # Accurate audio size calculation
                                        if filesize:
                                            actual_size = filesize
                                        elif abr and duration:
                                            # Convert kbps to bytes: (kbps * duration_seconds * 1000) / 8
                                            actual_size = (abr * duration * 1000) / 8
                                        else:
                                            # Default estimation for good quality audio
                                            actual_size = (160 * duration * 1000) / 8 if duration else 8 * 1024 * 1024

                                        fmt['filesize'] = max(actual_size, 2 * 1024 * 1024)  # Minimum 2MB for quality
                                        fmt['filesize_mb'] = fmt['filesize'] / (1024 * 1024)
                                        audio_formats.append(fmt)

                                # Remove duplicates and sort by quality
                                unique_video_formats = []
                                seen_qualities = set()

                                for fmt in sorted(video_formats, key=lambda x: x.get('height', 0), reverse=True):
                                    quality = fmt.get('quality_level')
                                    if quality and quality not in seen_qualities:
                                        unique_video_formats.append(fmt)
                                        seen_qualities.add(quality)
                                        if len(unique_video_formats) >= 6:  # Limit to 6 qualities
                                            break

                                info['video_formats'] = unique_video_formats
                                info['audio_formats'] = audio_formats[:3]  # Top 3 audio formats

                                return info
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            logger.error(f"Error getting enhanced quality info: {e}")

        return None

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
        # Enhanced YouTube command with cookie support
        info_cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            '--format', format_selector,
            '--no-check-certificates',
            '--no-warnings',
            '--socket-timeout', '60',
            '--retries', '10',
            '--fragment-retries', '10',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '--extractor-args', 'youtube:player_client=web,mweb',
            url
        ]

        # Add YouTube cookies if available
        if Config.YOUTUBE_SAPISID:
            cookie_file = f"{self.temp_dir}/youtube_cookies.txt"
            with open(cookie_file, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# This is a generated file! Do not edit.\n\n")
                if Config.YOUTUBE_SAPISID:
                    f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\t{Config.YOUTUBE_SAPISID}\n")
                if Config.YOUTUBE_SECURE_3PSID:
                    f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PSID\t{Config.YOUTUBE_SECURE_3PSID}\n")
                if Config.YOUTUBE_APISID:
                    f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\tAPISID\t{Config.YOUTUBE_APISID}\n")
                if Config.YOUTUBE_SID:
                    f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{Config.YOUTUBE_SID}\n")
            info_cmd.extend(['--cookies', cookie_file])

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
                '--extractor-args', 'youtube:player_client=web,mweb',
                url
            ]

            # Add cookies to download command if available
            if Config.YOUTUBE_SAPISID and 'cookie_file' in locals():
                download_cmd.extend(['--cookies', cookie_file])

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

    async def download_video_enhanced(self, url: str, quality_preference: str = "720p", format_preference: str = "mp4", progress_callback=None) -> Dict:
        """Enhanced download method for web interface with quality preferences"""
        try:
            platform = await self.get_platform(url)
            
            # Map web interface quality preferences to yt-dlp format strings
            quality_map = {
                "1080p": "best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
                "720p": "best[height<=720][ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
                "480p": "best[height<=480][ext=mp4]/bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
                "4k": "best[height<=2160][ext=mp4]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]",
            }
            
            # Handle audio format preference
            if format_preference == "mp3":
                format_string = "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best"
            elif format_preference == "webm":
                format_string = f"best[height<={quality_preference[:-1] if quality_preference.endswith('p') else '720'}][ext=webm]/best[ext=webm]"
            else:
                format_string = quality_map.get(quality_preference, quality_map["720p"])
            
            # Create dummy progress tracker if none provided
            class DummyProgressTracker:
                async def update_progress(self, current: int, total: int, speed: str = "", stage: str = "Downloading"):
                    if progress_callback:
                        await progress_callback(current, total, speed, stage)
            
            dummy_tracker = DummyProgressTracker()
            
            # Try enhanced download with proper quality
            try:
                if platform == 'youtube':
                    file_path, metadata = await self._download_youtube_quality(url, format_string, dummy_tracker)
                else:
                    file_path, metadata = await self._download_with_enhanced_compression(url, dummy_tracker)
                
                if file_path and os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    
                    # Ensure file doesn't exceed 2GB limit
                    if file_size > Config.MAX_VIDEO_SIZE:
                        logger.warning(f"File too large: {file_size/1024/1024/1024:.1f} GB > 2GB limit")
                        try:
                            os.unlink(file_path)
                        except:
                            pass
                        return {
                            'success': False,
                            'error': f'File size ({file_size/1024/1024/1024:.1f} GB) exceeds 2GB limit'
                        }
                    
                    return {
                        'success': True,
                        'file_path': file_path,
                        'file_size': file_size,
                        'metadata': metadata or {},
                        'title': metadata.get('title', 'Downloaded Video') if metadata else 'Downloaded Video',
                        'description': metadata.get('description', '') if metadata else ''
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Download failed - no file created'
                    }
                    
            except Exception as e:
                logger.error(f"Enhanced download failed: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
                
        except Exception as e:
            logger.error(f"Download video enhanced failed: {e}")
            return {
                'success': False,
                'error': f'Download failed: {str(e)}'
            }

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
                # Enhanced Twitter URL handling
                cleaned_url = url.replace('x.com', 'twitter.com')
                api_url = Config.TWITTER_API + cleaned_url

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
                # Enhanced Twitter API response handling
                download_url = None
                if 'url' in data:
                    download_url = data['url']
                elif 'download' in data and isinstance(data['download'], list) and len(data['download']) > 0:
                    # Some Twitter APIs return download URLs in an array
                    download_url = data['download'][0].get('url')
                elif 'media' in data and isinstance(data['media'], list):
                    # Handle media array format
                    for media in data['media']:
                        if media.get('type') == 'video' and 'url' in media:
                            download_url = media['url']
                            break

                if download_url:
                    metadata = {
                        'title': data.get('title', data.get('text', 'Twitter Video'))[:100],
                        'description': data.get('description', data.get('text', ''))[:200],
                        'uploader': data.get('author', data.get('user', {}).get('name', '')),
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
        """Enhanced cookie-based download with all .env cookies applied"""
        try:
            logger.info(f"Trying enhanced cookie-based download for {platform}")

            # Prepare enhanced cookies for different platforms from .env
            cookies = {}
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }

            if platform == 'instagram':
                if Config.INSTAGRAM_SESSIONID:
                    cookies['sessionid'] = Config.INSTAGRAM_SESSIONID
                    headers['X-IG-App-ID'] = '936619743392459'
                if Config.INSTAGRAM_CSRF_TOKEN:
                    cookies['csrftoken'] = Config.INSTAGRAM_CSRF_TOKEN

            elif platform == 'facebook':
                if Config.FACEBOOK_CUSER:
                    cookies['c_user'] = Config.FACEBOOK_CUSER
                if Config.FACEBOOK_XS:
                    cookies['xs'] = Config.FACEBOOK_XS
                if Config.FACEBOOK_FR:
                    cookies['fr'] = Config.FACEBOOK_FR
                if Config.FACEBOOK_DATR:
                    cookies['datr'] = Config.FACEBOOK_DATR

            elif platform == 'twitter':
                if Config.TWITTER_AUTH_TOKEN:
                    cookies['auth_token'] = Config.TWITTER_AUTH_TOKEN
                if Config.TWITTER_CT0:
                    cookies['ct0'] = Config.TWITTER_CT0
                if Config.TWITTER_TWID:
                    cookies['twid'] = Config.TWITTER_TWID
                if Config.TWITTER_GUEST_ID:
                    cookies['guest_id'] = Config.TWITTER_GUEST_ID
                if Config.TWITTER_CF_CLEARANCE:
                    cookies['cf_clearance'] = Config.TWITTER_CF_CLEARANCE
                if Config.TWITTER_CUID:
                    cookies['_cuid'] = Config.TWITTER_CUID

            elif platform == 'youtube':
                if Config.YOUTUBE_SAPISID:
                    cookies['SAPISID'] = Config.YOUTUBE_SAPISID
                if Config.YOUTUBE_SECURE_3PSID:
                    cookies['__Secure-3PSID'] = Config.YOUTUBE_SECURE_3PSID
                if Config.YOUTUBE_APISID:
                    cookies['APISID'] = Config.YOUTUBE_APISID
                if Config.YOUTUBE_SID:
                    cookies['SID'] = Config.YOUTUBE_SID

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

                        # Read metadata from info.json file if available
                        info_file = str(file).replace(file.suffix, '.info.json')
                        metadata = {
                            'title': f'{platform.title()} Video',
                            'description': 'Downloaded with enhanced method',
                            'platform': platform
                        }

                        if os.path.exists(info_file):
                            try:
                                with open(info_file, 'r', encoding='utf-8') as f:
                                    info_data = json.load(f)
                                    metadata.update({
                                        'title': info_data.get('title', metadata['title']),
                                        'description': info_data.get('description', metadata['description']),
                                        'uploader': info_data.get('uploader', ''),
                                        'duration': info_data.get('duration'),
                                        'upload_date': info_data.get('upload_date', ''),
                                        'view_count': info_data.get('view_count'),
                                        'like_count': info_data.get('like_count')
                                    })
                                logger.info(f"Enhanced filename: {metadata['title'][:30]}_{platform.upper()}{file.suffix}")
                            except Exception as e:
                                logger.warning(f"Could not read info file: {e}")

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
            result = await self._download_with_ytdlp_quality(url, quality_format, quality_type, progress_tracker)
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

        # Add quality indicator for new quality types
        quality_suffix = {
            "1080p": "_1080p",
            "720p": "_720p",
            "480p": "_480p", 
            "360p": "_360p",
            "audio": "_MP3",
            "hd": "_HD",
            "sd": "_SD",
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

    async def _download_with_ytdlp_quality(self, url: str, quality_format: str, quality_type: str, progress_tracker: ProgressTracker) -> Tuple[Optional[str], Optional[Dict]]:
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

            # Download with specified quality - skip problematic flags for audio
            download_cmd = [
                'yt-dlp', '--format', quality_format,
                '--output', output_template,
                '--no-check-certificates'
            ]

            # Add format and metadata flags only for video downloads to avoid ffmpeg issues
            if not quality_format.startswith('bestaudio') and 'audio' not in quality_type:
                download_cmd.extend(['--merge-output-format', 'mp4', '--embed-thumbnail', '--add-metadata'])

            download_cmd.append(url)

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
        welcome_text += f"• 📊 Real-time download/upload progress\n• 🚀 Smart quality selection\n• 🔄 Multi-tier fallback system\n"
        welcome_text += f"• 📦 Priority: packages → API → cookies\n\n"
        welcome_text += f"👨‍💻 **Bot Developer:** {Config.DEVELOPER_CREDIT}\n\n"
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

            )
        except Exception as e:
            # Fallback to text message if image fails
            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,

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

                )
            except Exception:
                await query.message.reply_text(
                    success_text,

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

                )
            except Exception:
                await query.message.reply_text(
                    not_member_text,
                    reply_markup=reply_markup,

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

            )
            return

        # Better URL validation and normalization
        url_text = message_text.strip()

        # Handle partial URLs (like /eBl_3AB0lCs?si=kPFo3Lca0TVtP4_M)
        if url_text.startswith('/'):
            # Extract video ID from YouTube format
            if re.match(r'^/[a-zA-Z0-9_-]{11}', url_text):  # YouTube video ID pattern
                video_id = url_text[1:].split('?')[0]
                url_text = f"https://www.youtube.com/watch?v={video_id}"
            # Handle Twitter status URLs
            elif '/status/' in url_text:
                url_text = f"https://twitter.com{url_text}"
            # Handle Twitter user/status format
            elif url_text.count('/') >= 2:
                url_text = f"https://twitter.com{url_text}"
            else:
                # Default to YouTube for single video IDs
                video_id = url_text[1:].split('?')[0]
                url_text = f"https://www.youtube.com/watch?v={video_id}"

        # Add https if missing
        if not url_text.startswith(('http://', 'https://')):
            if any(domain in url_text for domain in ['youtube.com', 'youtu.be', 'twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'tiktok.com']):
                url_text = f"https://{url_text}"

        if not url_regex.match(url_text):
            await update.message.reply_text(
                "❌ Please send a valid video URL!\n\n"
                "Supported platforms:\n"
                "• YouTube (Auto quality detection)\n"
                "• Facebook • TikTok • Twitter/X\n"
                "• Instagram • M3U8 streams\n"
                "• Direct video links\n\n"
                f"Developer: {Config.DEVELOPER_CREDIT}"
            )
            return

        # Store URL in user state for quality selection
        if chat_id not in user_states:
            user_states[chat_id] = {}
        user_states[chat_id]["pending_url"] = url_text

        # Detect platform for quality options
        async with SocialMediaDownloader() as downloader:
            platform = await downloader.get_platform(url_text)

        # Dynamic quality selection buttons based on actual available qualities
        keyboard = []

        # Get quality info to show only available qualities
        async with SocialMediaDownloader() as temp_downloader:
            quality_info = await temp_downloader._get_video_quality_info(url_text, platform)

        available_qualities = []
        if quality_info and 'video_formats' in quality_info:
            for fmt in quality_info['video_formats']:
                quality = fmt.get('quality_level')
                filesize_mb = fmt.get('filesize_mb', 0)
                if quality:
                    # Show MB in buttons as requested
                    if filesize_mb > 0:
                        size_text = f" • {filesize_mb:.0f}MB"
                        button_text = f"{quality}{size_text}"
                    else:
                        button_text = f"{quality} • Auto"
                    available_qualities.append((quality, button_text))

        # Fallback to standard qualities if no specific info available
        if not available_qualities:
            available_qualities = [
                ('4K', '4K • Auto'),
                ('1440p', '1440p • Auto'),
                ('1080p', '1080p • Auto'),
                ('720p', '720p • Auto'),
                ('480p', '480p • Auto'),
                ('360p', '360p • Auto')
            ]

        # Create buttons for available video qualities
        quality_buttons = []
        for i in range(0, len(available_qualities), 2):
            row = []
            for j in range(2):
                if i + j < len(available_qualities):
                    quality_code, quality_display = available_qualities[i + j]
                    emoji = {
                        '4K': '🌟',
                        '1440p': '🔥', 
                        '1080p': '⭐',
                        '720p': '✨',
                        '480p': '✅',
                        '360p': '💾'
                    }.get(quality_code, '📹')
                    row.append(InlineKeyboardButton(
                        f"{emoji} {quality_display}", 
                        callback_data=f"quality_{quality_code.lower()}_video"
                    ))
            if row:
                quality_buttons.append(row)

        # Add audio button with size info if available
        audio_size_text = "Auto"
        if quality_info and quality_info.get('audio_formats'):
            audio_fmt = quality_info['audio_formats'][0]
            audio_size = audio_fmt.get('filesize', 0)
            if audio_size > 0:
                audio_mb = audio_size / (1024 * 1024)
                audio_size_text = f"{audio_mb:.0f}MB"

        audio_button = [InlineKeyboardButton(f"🎵 MP3 Audio • {audio_size_text}", callback_data="quality_audio_mp3")]

        keyboard = quality_buttons + [audio_button]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Create enhanced quality selection text with actual available qualities and file sizes
        quality_text = f"🎬 Video Detected!\n\n"
        quality_text += f"🔗 URL: {url_text[:50]}{'...' if len(url_text) > 50 else ''}\n"
        quality_text += f"🌐 Platform: {platform.title()}\n"

        # Add video title if available
        if quality_info and quality_info.get('title'):
            title = quality_info['title'][:60]
            quality_text += f"🎬 Title: {title}\n"

        quality_text += f"\n📊 Available qualities:\n"

        # Show actual quality info with file sizes from enhanced detection
        if quality_info and 'video_formats' in quality_info and quality_info['video_formats']:
            for fmt in quality_info['video_formats']:
                quality = fmt.get('quality_level')
                filesize_mb = fmt.get('filesize_mb', 0)
                height = fmt.get('height', 0)
                if quality:
                    if filesize_mb > 0:
                        quality_text += f"• {quality}: {filesize_mb:.0f}MB\n"
                    else:
                        quality_text += f"• {quality}: Available\n"

            # Add audio info if available
            if quality_info.get('audio_formats'):
                audio_fmt = quality_info['audio_formats'][0]
                audio_size = audio_fmt.get('filesize', 0)
                if audio_size > 0:
                    audio_mb = audio_size / (1024 * 1024)
                    quality_text += f"• MP3 Audio: {audio_mb:.0f}MB\n"
                else:
                    quality_text += f"• MP3 Audio: Available\n"
        else:
            # Fallback to generic quality info
            quality_text += f"• 4K/1440p/1080p/720p/480p/360p: Various HD qualities\n"
            quality_text += f"• MP3: Audio only format\n"

        quality_text += f"\n⚡ Priority System: yt-dlp > API > cookies\n"
        quality_text += f"📁 Download includes: title + description\n"
        quality_text += f"⏱️ Progress tracking: download + upload\n"
        quality_text += f"Developer: {Config.DEVELOPER_CREDIT}"

        await update.message.reply_text(
            quality_text,
            reply_markup=reply_markup
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

        # Parse callback data: quality_1080p_video -> 1080p, video
        parts = callback_data.split("_")
        if len(parts) >= 3:
            quality_type = parts[1]  # 1080p, 720p, 480p, 360p, audio
            format_type = parts[2]   # video, mp3
        else:
            quality_type = "1080p"
            format_type = "video"

        # Remove user chat ID check since we're not including it in callback data anymore

        # Get the URL from user state
        if chat_id not in user_states or "pending_url" not in user_states[chat_id]:
            await query.edit_message_text(
                "❌ Session expired!\n\n"
                "Please send the video URL again.\n\n"
                f"Developer: {Config.DEVELOPER_CREDIT}"
            )
            return

        video_url = user_states[chat_id]["pending_url"]

        # Enhanced quality mapping with proper format selection
        quality_map = {
            "4k": "best[height<=2160][ext=mp4]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]",
            "1440p": "best[height<=1440][ext=mp4]/bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]",
            "1080p": "best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "720p": "best[height<=720][ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "480p": "best[height<=480][ext=mp4]/bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
            "360p": "best[height<=360][ext=mp4]/bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
            "audio": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best"
        }

        quality_format = quality_map.get(quality_type, "best")
        quality_name = {
            "4k": "4K Ultra HD",
            "1440p": "1440p QHD", 
            "1080p": "1080p Full HD",
            "720p": "720p HD",
            "480p": "480p Standard",
            "360p": "360p Compact",
            "audio": "MP3 Audio Only"
        }.get(quality_type, "Best Available")

        # Get video info first to show title and description
        async with SocialMediaDownloader() as temp_downloader:
            video_info = await temp_downloader._get_video_quality_info(video_url, await temp_downloader.get_platform(video_url))

        # Send enhanced processing message with title and description
        processing_text = f"🔄 Processing Download...\n\n"

        # Show video title and description if available
        if video_info:
            title = video_info.get('title', 'Unknown Title')[:60]
            description = video_info.get('description', '')[:100]
            uploader = video_info.get('uploader', video_info.get('channel', ''))[:30]

            processing_text += f"🎬 Title: {title}\n"
            if description:
                processing_text += f"📝 Description: {description}...\n"
            if uploader:
                processing_text += f"👤 By: {uploader}\n"
            processing_text += f"\n"

        processing_text += f"🎯 Quality: {quality_name}\n"
        processing_text += f"🔗 URL: {video_url[:50]}{'...' if len(video_url) > 50 else ''}\n\n"
        processing_text += f"⚡ Smart Download Priority:\n"
        processing_text += f"1. Packages (yt-dlp, instaloader)\n"
        processing_text += f"2. APIs (Platform-specific)\n"
        processing_text += f"3. Cookies (Authentication)\n\n"
        processing_text += f"📊 Status: Starting download...\n\n"
        processing_text += f"Developer: {Config.DEVELOPER_CREDIT}"

        await query.edit_message_text(processing_text)

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
                        text="❌ Enhanced Download Failed\n\n"
                             "This could be due to:\n"
                             "• Private/restricted content\n"
                             "• Unsupported video format\n"
                             "• Network connectivity issues\n"
                             "• File size exceeds 2GB limit\n"
                             "• Platform rate limiting\n\n"
                             "Please try with a different video URL."
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

                # Send video with simplified upload 
                with open(file_path, 'rb') as video_file:
                    # Get safe duration value
                    duration_value = None
                    if metadata.get('duration'):
                        try:
                            duration_value = int(float(metadata['duration']))
                        except (ValueError, TypeError, OverflowError):
                            duration_value = None

                    # Send as audio or video based on format type
                    if format_type == "mp3" or quality_type == "audio" or file_path.endswith(('.mp3', '.m4a', '.aac')):
                        # Enhanced audio caption with metadata
                        audio_caption = f"🎵 **{metadata.get('title', 'Audio Download')}**\n\n"

                        if metadata.get('description'):
                            desc = metadata['description'][:200] + "..." if len(metadata['description']) > 200 else metadata['description']
                            audio_caption += f"📝 **Description:** {desc}\n\n"

                        if metadata.get('uploader'):
                            audio_caption += f"👤 **Artist:** {metadata['uploader']}\n"

                        if metadata.get('platform'):
                            audio_caption += f"🌐 **Platform:** {metadata['platform'].title()}\n"

                        # Safe duration formatting for audio
                        if metadata.get('duration'):
                            try:
                                duration = metadata['duration']
                                if isinstance(duration, (int, float)) and duration > 0:
                                    duration_int = int(float(duration))
                                    minutes = duration_int // 60
                                    seconds = duration_int % 60
                                    duration_str = f"{minutes}:{seconds:02d}"
                                    audio_caption += f"⏱️ **Duration:** {duration_str}\n"
                            except (ValueError, TypeError, OverflowError):
                                pass

                        audio_caption += f"\n⚡ **Enhanced Download by {Config.DEVELOPER_CREDIT}**\n🔗 **Source:** {video_url}"

                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=video_file,
                            caption=audio_caption,
                            duration=duration_value,
                            performer=metadata.get('uploader', 'Unknown Artist'),
                            title=metadata.get('title', 'Audio Download'),
                            read_timeout=300,
                            write_timeout=300
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=video_file,
                            caption=caption,
                            supports_streaming=True,
                            duration=duration_value,
                            read_timeout=300,
                            write_timeout=300
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

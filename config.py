"""Central configuration, paths, and config.json persistence.

Single source of truth for file locations and the mutable settings that the
uploader and web layer share. Kept deliberately small so both the async
uploader service and the FastAPI routes can import it without side effects.
"""
import os
import json
import threading

from dotenv import load_dotenv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# ---- Credentials / deploy-time settings (env) ----
API_ID = int(os.getenv("API_ID", 0) or 0)
API_HASH = os.getenv("API_HASH", "")
# GROUP_ID is now optional: it can be chosen/created from the web UI (Phase 2).
GROUP_ID = int(os.getenv("GROUP_ID", 0) or 0)
DASHBOARD_PIN = os.getenv("DASHBOARD_PIN", "1234")

# Root that "local mode" folder scanning is confined to. On Android/Termux this
# is the shared storage; on a server/cloud it defaults to the project dir so the
# browser-upload staging area is scannable. Override with SCAN_ROOT.
SCAN_ROOT = os.getenv("SCAN_ROOT", os.path.expanduser("~/storage/shared/DCIM"))
if not os.path.isdir(SCAN_ROOT):
    SCAN_ROOT = os.getenv("SCAN_ROOT_FALLBACK", PROJECT_DIR)

# Persistent data directory. On Fly.io/containers, mount a volume here so the
# SQLite DB and Telegram session survive restarts. Defaults to the project dir
# for local self-host.
DATA_DIR = os.getenv("DATA_DIR", PROJECT_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

# Directory where browser-uploaded files are TEMPORARILY staged before being
# sent to Telegram, then deleted. Local-path uploads never touch this — they
# read the original file in place. Created lazily (see ensure_staging), so it
# doesn't clutter storage unless you actually upload from a device.
UPLOAD_STAGING_DIR = os.path.join(DATA_DIR, "uploads_staging")


def ensure_staging():
    os.makedirs(UPLOAD_STAGING_DIR, exist_ok=True)
    return UPLOAD_STAGING_DIR


def cleanup_staging():
    """Remove any leftover staged files (e.g. after a crash mid-upload)."""
    import shutil
    if os.path.isdir(UPLOAD_STAGING_DIR):
        try:
            shutil.rmtree(UPLOAD_STAGING_DIR)
        except Exception:
            pass

# ---- Data files ----
DB_FILE = os.path.join(DATA_DIR, "uploads.db")
SESSION_FILE = os.path.join(DATA_DIR, "backup_session")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "uploader.log")

# ---- Uploader tuning ----
MAX_CONCURRENT_UPLOADS = int(os.getenv("MAX_CONCURRENT_UPLOADS", 3))
DELAY_BETWEEN_UPLOADS = float(os.getenv("DELAY_BETWEEN_UPLOADS", 1.5))
UPLOAD_RETRY_LIMIT = int(os.getenv("UPLOAD_RETRY_LIMIT", 3))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 3))

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg", ".gif"]
VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"]

_DEFAULT_CONFIG = {
    "auto_delete_after_upload": False,
    "turbo_mode": False,
    "compress_media": False,
    "daily_report": True,
    "group_id": GROUP_ID,
    "folders": {},
}

_config_lock = threading.Lock()


def read_config():
    with _config_lock:
        if not os.path.exists(CONFIG_FILE):
            return dict(_DEFAULT_CONFIG)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return dict(_DEFAULT_CONFIG)
    merged = dict(_DEFAULT_CONFIG)
    merged.update(data)
    return merged


def write_config(data):
    with _config_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)


def active_group_id():
    """Group the bot uploads to: config.json overrides the env default."""
    cfg = read_config()
    return int(cfg.get("group_id") or GROUP_ID or 0)


def file_type_for(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "other"

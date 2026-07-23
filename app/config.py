"""Central configuration, paths, and config.json persistence.

Single source of truth for file locations and the mutable settings that the
uploader and web layer share. Kept deliberately small so both the async
uploader service and the FastAPI routes can import it without side effects.
"""
import os
import json
import threading

from dotenv import load_dotenv

# Repo root = the directory that CONTAINS this ``app`` package, so .env, the
# SQLite DB, session file, and static/ all live at the project root — not
# inside app/.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# ---- Credentials / deploy-time settings (env) ----
API_ID = int(os.getenv("API_ID", 0) or 0)
API_HASH = os.getenv("API_HASH", "")

# Optional dashboard password gate. Empty = open (default). When set, the web
# UI, API and WebSocket require this password (a signed cookie).
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()

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

# Telegram's hard per-file limit. Files at/under this go up as a SINGLE file
# (one message). Only files LARGER than this are split into parts, because
# Telegram physically cannot hold >2GB in one message — those parts are
# transparently reassembled into the whole file on download. This is a
# capability limit, NOT a tuning knob: don't lower it, or normal files get
# needlessly split. (Set tiny only to test chunking, e.g. CHUNK_SIZE=5242880.)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1950 * 1024 * 1024))  # ~1.95 GB

# How often the SQLite index is snapshotted into the Telegram Backup topic so
# it survives a lost local DB / a fresh install on another machine. Minutes.
BACKUP_INTERVAL_MIN = int(os.getenv("BACKUP_INTERVAL_MIN", 30))

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg", ".gif"]
VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"]

# ---- "By file type" categories ----
# Each category maps to a Telegram topic (auto-created / reused) whose title is
# CATEGORY_LABELS[key]. Order matters: first matching category wins.
FILE_CATEGORIES = {
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
              ".tiff", ".tif", ".heic", ".heif", ".ico"],
    "video": [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv",
              ".wmv", ".m4v", ".mpeg", ".mpg", ".3gp", ".m2ts"],
    "audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
              ".opus", ".amr", ".aiff", ".mid"],
    "document": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                 ".txt", ".rtf", ".odt", ".ods", ".odp", ".csv", ".epub", ".md"],
    "coding": [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
               ".cc", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
               ".html", ".htm", ".css", ".scss", ".json", ".xml", ".yaml",
               ".yml", ".sh", ".bat", ".ps1", ".sql", ".kt", ".swift", ".dart",
               ".r", ".lua", ".pl"],
    "compressed": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
                   ".tgz", ".iso", ".cab", ".arj"],
    "program": [".exe", ".msi", ".apk", ".deb", ".rpm", ".dmg", ".appimage",
                ".bin", ".app", ".jar"],
}
CATEGORY_LABELS = {
    "image": "Images", "video": "Videos", "audio": "Audios",
    "document": "Documents", "coding": "Coding", "compressed": "Compressed",
    "program": "Programme", "other": "Others",
}


def category_for(name):
    """Return the category key for a filename (falls back to 'other')."""
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in FILE_CATEGORIES.items():
        if ext in exts:
            return cat
    return "other"


_DEFAULT_CONFIG = {
    "auto_delete_after_upload": False,
    "turbo_mode": False,
    "compress_media": False,
    "daily_report": True,
    "group_id": 0,  # set from the web UI (Group & Topic setup); persisted here
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
    """Group the bot uploads to, as chosen in Group & Topic setup."""
    cfg = read_config()
    return int(cfg.get("group_id") or 0)


def file_type_for(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "other"


# ---- persistent secret (used to sign the dashboard cookie + encrypt session) ----
_SECRET_FILE = os.path.join(DATA_DIR, ".secret")


def get_secret():
    """A stable 32-byte secret persisted in DATA_DIR. Auto-created once."""
    import secrets
    try:
        if os.path.exists(_SECRET_FILE):
            data = open(_SECRET_FILE, "rb").read()
            if len(data) >= 16:
                return data
        data = secrets.token_bytes(32)
        with open(_SECRET_FILE, "wb") as f:
            f.write(data)
        return data
    except Exception:
        return b"tgb-fallback-secret-please-set-SECRET"


def dashboard_token():
    """Signed value for the dashboard auth cookie (empty when no password)."""
    import hmac
    import hashlib
    if not DASHBOARD_PASSWORD:
        return ""
    return hmac.new(get_secret(), DASHBOARD_PASSWORD.encode(), hashlib.sha256).hexdigest()


# ---- encrypted Telegram session at rest ----
SESSION_ENC = os.path.join(DATA_DIR, "session.enc")


def fernet():
    """A Fernet cipher keyed by the persisted secret, or None if the
    'cryptography' package isn't available (then we fall back to a plain
    file session)."""
    try:
        import base64
        from cryptography.fernet import Fernet
        return Fernet(base64.urlsafe_b64encode(get_secret()[:32]))
    except Exception:
        return None

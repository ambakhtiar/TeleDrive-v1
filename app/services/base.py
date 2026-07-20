"""Core uploader state + lifecycle. Feature methods live in sibling mixins
(auth, groups, scanning, uploading, downloading, reports) and are assembled
into the concrete ``UploaderService`` in service.py."""
import asyncio
import logging
from collections import deque
from datetime import datetime

from telethon import TelegramClient

from app import config
from app.db import Database

logger = logging.getLogger("uploader")


class UploaderBase:
    """Shared state, event broadcasting, client lifecycle, and start/stop."""

    def __init__(self):
        self.client: TelegramClient | None = None
        self.db = Database(config.DB_FILE)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued_hashes: set[str] = set()
        self.active_uploads = 0
        self.status = "running"  # running | paused
        self.auth_state = "unauthorized"  # unauthorized | authorized
        # Per-file progress keyed by hash (multi-progress list).
        self.progress: dict[str, dict] = {}
        self.logs: deque[str] = deque(maxlen=200)
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []
        self._started = False
        self._login_phone: str | None = None
        self._login_hash: str | None = None
        self.cancel_set: set[str] = set()   # hashes to skip when dequeued
        self.failed: dict[str, dict] = {}    # hash -> {name, path, topic_id, error}

    # ---------- event broadcasting ----------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def emit(self, event_type: str, payload: dict):
        msg = {"type": event_type, "data": payload}
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def log(self, message: str):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        self.logs.append(line)
        logger.info(message)
        self.emit("log", {"line": line})

    # ---------- client lifecycle ----------
    def _make_client(self):
        return TelegramClient(config.SESSION_FILE, config.API_ID, config.API_HASH)

    async def _fresh_client(self):
        """Build and connect a brand-new client. Needed because Telethon
        forbids reusing an instance after log_out()."""
        try:
            if self.client:
                await self.client.disconnect()
        except Exception:
            pass
        self.client = self._make_client()
        await self.client.connect()
        return self.client

    async def start(self):
        if self._started:
            return
        self._started = True
        self.client = self._make_client()
        try:
            await self.client.connect()
            if await self.client.is_user_authorized():
                self.auth_state = "authorized"
                self.log("🤖 Session authorized.")
            else:
                self.auth_state = "unauthorized"
                self.log("🔑 Not logged in. Use the web login (phone → OTP).")
        except Exception as e:
            self.auth_state = "unauthorized"
            self.log(f"⚠️ Could not reach Telegram yet ({e}). Web UI still available.")

        # NOTE: the legacy auto-watch rescanner is intentionally NOT started.
        # Uploads are now explicit via "Add Files / Folder" so nothing uploads
        # by surprise.
        self._tasks = [
            asyncio.create_task(self._daily_report_loop()),
        ]
        for i in range(config.MAX_CONCURRENT_UPLOADS):
            self._tasks.append(asyncio.create_task(self._upload_worker(f"Worker-{i+1}")))
        self.log("🌟 Uploader service started.")

    async def shutdown(self):
        for t in self._tasks:
            t.cancel()
        self.db.close()
        if self.client:
            await self.client.disconnect()
        self.log("🛑 Service stopped.")

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "auth_state": self.auth_state,
            "total_uploaded": self.db.total_count(),
            "queued_files": len(self.queued_hashes),
            "active_uploads": self.active_uploads,
            "progress": list(self.progress.values()),
            "failed": list(self.failed.values()),
            "recent_uploads": self.db.recent(5),
            "group_id": config.active_group_id(),
        }

    def set_status(self, status):
        self.status = "paused" if status == "pause" else "running"
        self.emit("status", {"status": self.status})
        return self.status

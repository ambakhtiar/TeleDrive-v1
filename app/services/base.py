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
        self.cancel_set: set[str] = set()   # hashes to hard-cancel (drop)
        self.failed: dict[str, dict] = {}    # hash -> {name, path, topic_id, error}
        self._active: dict[str, "asyncio.Task"] = {}  # hash -> running upload task
        self.pause_set: set[str] = set()    # per-file paused hashes
        self.pending_items: dict[str, dict] = {}  # hash -> item (for resume/re-enqueue)

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

        # F10: before anything touches the DB, adopt the Telegram backup if the
        # local DB is missing/older (fresh clone, new machine, lost DB).
        if self.auth_state == "authorized":
            try:
                await self._maybe_restore_db()
            except Exception as e:
                self.log(f"⚠️ Startup restore check failed: {e}")

        # NOTE: the legacy auto-watch rescanner is intentionally NOT started.
        # Uploads are now explicit via "Add Files / Folder" so nothing uploads
        # by surprise.
        self._tasks = [
            asyncio.create_task(self._daily_report_loop()),
            asyncio.create_task(self._startup_maintenance()),
            asyncio.create_task(self._backup_loop()),
        ]
        for i in range(config.MAX_CONCURRENT_UPLOADS):
            self._tasks.append(asyncio.create_task(self._upload_worker(f"Worker-{i+1}")))
        self._restore_queue()
        self.log("🌟 Uploader service started.")

    def _restore_queue(self):
        """Re-enqueue any uploads left pending from a previous run so an
        interrupted batch resumes automatically (no re-selecting files)."""
        import os
        restored = 0
        for row in self.db.queue_all():
            path = row.get("path")
            if not path or not os.path.exists(path):
                # source/staged file is gone — can't resume it
                self.db.queue_remove(row["hash"])
                continue
            try:
                stats = os.stat(path)
            except OSError:
                self.db.queue_remove(row["hash"])
                continue
            item = {
                "folder_name": row.get("folder_name") or os.path.dirname(path),
                "path": path, "name": row["name"], "hash": row["hash"],
                "mtime": row.get("mtime") or stats.st_mtime,
                "stats": stats, "topic_id": row["topic_id"],
            }
            self.pending_items[row["hash"]] = item
            if row.get("status") == "paused":
                self.pause_set.add(row["hash"])
            if row["hash"] not in self.queued_hashes:
                self.queued_hashes.add(row["hash"])
                self.queue.put_nowait(item)
                restored += 1
        if restored:
            self.emit("queue", {"queued_files": len(self.queued_hashes)})
            self.log(f"♻️ Resumed {restored} pending upload(s) from last session.")

    async def shutdown(self):
        # Best-effort final DB snapshot so a clean stop always leaves the
        # latest index safe in Telegram.
        try:
            if self.auth_state == "authorized":
                await asyncio.wait_for(self.snapshot_db(), timeout=60)
        except Exception:
            pass
        for t in self._tasks:
            t.cancel()
        self.db.close()
        if self.client:
            await self.client.disconnect()
        self.log("🛑 Service stopped.")

    def queued_list(self):
        """Every not-yet-done item with its state, for the UI's per-file rows."""
        out = []
        for h in list(self.queued_hashes):
            item = self.pending_items.get(h)
            if not item:
                continue
            if h in self.pause_set:
                state = "paused"
            elif h in self.progress:
                state = "uploading"
            else:
                state = "pending"
            out.append({"hash": h, "name": item.get("name"), "state": state})
        return out

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "auth_state": self.auth_state,
            "total_uploaded": self.db.total_count(),
            "queued_files": len(self.queued_hashes),
            "active_uploads": self.active_uploads,
            "progress": list(self.progress.values()),
            "queued": self.queued_list(),
            "failed": list(self.failed.values()),
            "recent_uploads": self.db.recent(5),
            "group_id": config.active_group_id(),
        }

    def set_status(self, status):
        self.status = "paused" if status == "pause" else "running"
        if self.status == "paused":
            # Abort every in-flight upload immediately; the worker re-queues
            # them so Resume continues (chunked files resume from last part).
            for task in list(self._active.values()):
                task.cancel()
        self.emit("status", {"status": self.status})
        return self.status

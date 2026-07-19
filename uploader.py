"""Uploader service: owns the Telethon client and runs the scan/upload loop
as in-process asyncio tasks. Replaces the old two-process + JSON-file IPC.

State (status, progress, logs, queue) lives in memory and is pushed to web
clients over a broadcast channel instead of being polled from disk.
"""
import os
import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta

from telethon import TelegramClient, errors

import config
from database import Database, generate_file_hash

logger = logging.getLogger("uploader")


def _format_metadata(file_name, file_path, stats):
    size_mb = round(stats.st_size / (1024 * 1024), 2)
    created = datetime.fromtimestamp(original_timestamp(file_path, stats))
    dt_created = created.strftime("%d %b %Y, %I:%M %p")
    ext = os.path.splitext(file_name)[1]
    hashtag = f"#{ext[1:].lower()}" if ext else "#unknown"
    caption = f"📄 **{file_name}**\n\n💾 **Size:** {size_mb} MB\n📅 **Created:** {dt_created}"
    device = _get_device_info(file_path)
    if device:
        caption += f"\n📱 **Device:** {device}"
    caption += f"\n\n🏷️ {hashtag}"
    return caption


def original_timestamp(file_path, stats):
    """Best guess at when the file was *created*, not last touched.

    Prefers EXIF DateTimeOriginal for photos, then filesystem creation time
    (st_ctime on Windows / st_birthtime on macOS), then modification time.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff"):
        try:
            from PIL import Image, ExifTags
            with Image.open(file_path) as img:
                exif = img.getexif()
                for tag_id, value in exif.items():
                    if ExifTags.TAGS.get(tag_id) in ("DateTimeOriginal", "DateTime"):
                        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S").timestamp()
        except Exception:
            pass
    birth = getattr(stats, "st_birthtime", None)
    candidates = [t for t in (birth, stats.st_ctime, stats.st_mtime) if t]
    return min(candidates) if candidates else stats.st_mtime


def _fmt_duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _get_device_info(file_path):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp"]:
            from PIL import Image, ExifTags

            with Image.open(file_path) as img:
                exif = img.getexif()
                if not exif:
                    return None
                make, model = "", ""
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == "Make":
                        make = str(value).strip()
                    elif tag == "Model":
                        model = str(value).strip()
                if make or model:
                    if make and make.lower() in model.lower():
                        return model
                    return f"{make} {model}".strip()
        return None
    except Exception:
        return None


class UploaderService:
    """Single-user uploader. Started once from the FastAPI lifespan."""

    def __init__(self):
        self.client: TelegramClient | None = None
        self.db = Database(config.DB_FILE)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued_hashes: set[str] = set()
        self.active_uploads = 0
        self.status = "running"  # running | paused
        self.auth_state = "unauthorized"  # unauthorized | authorized
        # Per-file progress keyed by hash (Phase 4 multi-progress list).
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

    # ---------- lifecycle ----------
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
        # by surprise. (self._rescanner_loop remains for optional future use.)
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

    # ---------- scanning ----------
    def _scan_and_sort(self):
        """Scan configured folders under SCAN_ROOT plus the staging dir."""
        files_to_upload = []
        cfg = config.read_config()
        folder_map = cfg.get("folders", {})

        for folder_name, rules in folder_map.items():
            # A rule "name" may be an absolute path or a name under SCAN_ROOT.
            if os.path.isabs(folder_name) and os.path.isdir(folder_name):
                folder_path = folder_name
            else:
                folder_path = os.path.join(config.SCAN_ROOT, folder_name)
            if not os.path.isdir(folder_path):
                continue

            for root, _, files in os.walk(folder_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    f_type = config.file_type_for(file)
                    topic_id = rules.get(f_type) or rules.get("all")
                    if not topic_id:
                        continue
                    file_hash, stats = generate_file_hash(full_path)
                    if file_hash and not self.db.is_uploaded(file_hash):
                        files_to_upload.append(
                            {
                                "folder_name": folder_name,
                                "path": full_path,
                                "name": file,
                                "hash": file_hash,
                                "mtime": original_timestamp(full_path, stats),
                                "stats": stats,
                                "topic_id": int(topic_id),
                            }
                        )
        files_to_upload.sort(key=lambda x: x["mtime"])
        return files_to_upload

    def enqueue_item(self, item: dict):
        """Directly enqueue a prepared item (used by browser upload / manual add)."""
        if item["hash"] in self.queued_hashes:
            return False
        self.queued_hashes.add(item["hash"])
        self.queue.put_nowait(item)
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        return True

    async def _rescanner_loop(self):
        while True:
            try:
                if self.status == "running" and self.auth_state == "authorized":
                    new_files = await asyncio.to_thread(self._scan_and_sort)
                    added = 0
                    for item in new_files:
                        if item["hash"] not in self.queued_hashes:
                            self.queued_hashes.add(item["hash"])
                            self.queue.put_nowait(item)
                            added += 1
                    if added:
                        self.emit("queue", {"queued_files": len(self.queued_hashes)})
                        self.log(f"📥 Found & queued {added} new file(s).")
                await asyncio.sleep(config.SCAN_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log(f"⚠️ Scan error: {e}")
                await asyncio.sleep(config.SCAN_INTERVAL)

    # ---------- uploading ----------
    async def _upload_worker(self, name):
        while True:
            try:
                if self.status == "paused" or self.auth_state != "authorized":
                    await asyncio.sleep(1)
                    continue

                item = await self.queue.get()
                try:
                    if item["hash"] in self.cancel_set:
                        self.cancel_set.discard(item["hash"])
                        self.queued_hashes.discard(item["hash"])
                        self.emit("queue", {"queued_files": len(self.queued_hashes)})
                        self.log(f"🚫 Cancelled: {item['name']}")
                        continue
                    cfg = config.read_config()
                    # respect concurrency unless turbo mode
                    while not cfg.get("turbo_mode", False) and self.active_uploads > 0:
                        await asyncio.sleep(0.4)
                        cfg = config.read_config()
                    self.active_uploads += 1
                    try:
                        await self._do_upload(name, item, cfg)
                    finally:
                        self.active_uploads -= 1
                        self.queued_hashes.discard(item["hash"])
                        self.progress.pop(item["hash"], None)
                        self.emit("queue", {"queued_files": len(self.queued_hashes)})
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log(f"❌ Worker {name} error: {e}")
                await asyncio.sleep(3)

    async def _do_upload(self, name, item, cfg):
        group_id = config.active_group_id()
        if not group_id:
            self.log("⚠️ No target group set. Configure it in Group Setup.")
            await asyncio.sleep(2)
            return
        if not os.path.exists(item["path"]):
            self.log(f"👻 Skipped missing file: {item['name']}")
            return

        auto_delete = cfg.get("auto_delete_after_upload", False)
        compress_media = cfg.get("compress_media", False)
        caption = _format_metadata(item["name"], item["path"], item["stats"])
        h = item["hash"]
        start_time = [time.time()]

        async def progress_callback(current, total):
            elapsed = max(time.time() - start_time[0], 0.1)
            speed = current / elapsed
            pct = (current / total) * 100 if total else 0
            eta = (total - current) / speed if speed > 0 else 0
            self.progress[h] = {
                "hash": h,
                "status": "uploading",
                "file_name": item["name"],
                "current": current,
                "total": total,
                "percentage": round(pct, 1),
                "speed": speed,
                "eta": round(eta),
            }
            self.emit("progress", self.progress[h])

        for attempt in range(1, config.UPLOAD_RETRY_LIMIT + 1):
            try:
                self.log(f"🚀 [{name}] Uploading: {item['name']}")
                start_time[0] = time.time()
                msg = await self.client.send_file(
                    group_id,
                    item["path"],
                    caption=caption,
                    reply_to=item["topic_id"],
                    force_document=not compress_media,
                    progress_callback=progress_callback,
                )
                elapsed = time.time() - start_time[0]
                group_str = str(group_id).replace("-100", "")
                topic_seg = f"/{item['topic_id']}" if item.get("topic_id") else ""
                msg_link = f"https://t.me/c/{group_str}{topic_seg}/{msg.id}"
                self.db.mark_uploaded(h, item["name"], item["path"], item["topic_id"], msg_link)
                self.log(f"✅ [{name}] Done: {item['name']} in {_fmt_duration(elapsed)}")
                self.emit("uploaded", {"name": item["name"], "link": msg_link,
                                       "duration": round(elapsed, 1),
                                       "duration_text": _fmt_duration(elapsed),
                                       "total_uploaded": self.db.total_count()})
                # Staged (browser-uploaded) files are always removed after send
                # so the data volume doesn't fill up; local files honor the toggle.
                is_staged = os.path.abspath(item["path"]).startswith(
                    os.path.abspath(config.UPLOAD_STAGING_DIR)
                )
                if auto_delete or is_staged:
                    try:
                        os.remove(item["path"])
                    except Exception:
                        pass
                await asyncio.sleep(config.DELAY_BETWEEN_UPLOADS)
                return
            except errors.FloodWaitError as e:
                self.log(f"⏳ [{name}] FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                last_error = str(e)
                self.log(f"❌ [{name}] Error on {item['name']} (try {attempt}): {e}")
                await asyncio.sleep(3)
        # all attempts failed
        self.failed[h] = {
            "hash": h, "name": item["name"], "path": item["path"],
            "topic_id": item["topic_id"], "error": locals().get("last_error", "unknown"),
        }
        self.emit("failed", {"failed": list(self.failed.values())})

    # ---------- queue controls (Phase 4) ----------
    def cancel_item(self, file_hash: str):
        self.cancel_set.add(file_hash)
        return {"status": "cancelling"}

    def clear_queue(self):
        drained = 0
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                self.queued_hashes.discard(item["hash"])
                self.queue.task_done()
                drained += 1
            except asyncio.QueueEmpty:
                break
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        self.log(f"🧹 Cleared {drained} queued file(s).")
        return {"cleared": drained}

    def retry_failed(self):
        n = 0
        for h, info in list(self.failed.items()):
            file_hash, stats = generate_file_hash(info["path"])
            if not file_hash or not stats:
                continue
            if self.enqueue_item({
                "folder_name": os.path.dirname(info["path"]),
                "path": info["path"], "name": info["name"],
                "hash": file_hash, "mtime": stats.st_mtime,
                "stats": stats, "topic_id": int(info["topic_id"]),
            }):
                n += 1
        self.failed.clear()
        self.emit("failed", {"failed": []})
        self.log(f"🔁 Re-queued {n} failed file(s).")
        return {"requeued": n}

    # ---------- web login (phone → OTP → 2FA) ----------
    async def send_login_code(self, phone: str):
        """Step 1: request an OTP be sent to the phone number."""
        if self.client is None:
            await self._fresh_client()
        elif not self.client.is_connected():
            try:
                await self.client.connect()
            except Exception:
                await self._fresh_client()
        try:
            sent = await self.client.send_code_request(phone)
        except Exception as e:
            # A client that was logged out cannot be reused — rebuild once.
            if "reused" in str(e).lower() or "logged out" in str(e).lower():
                await self._fresh_client()
                sent = await self.client.send_code_request(phone)
            else:
                raise
        self._login_phone = phone
        self._login_hash = sent.phone_code_hash
        self.log(f"📲 OTP requested for {phone}")
        return {"status": "code_sent"}

    async def verify_login_code(self, code: str):
        """Step 2: sign in with the OTP. May require a 2FA password."""
        from telethon.errors import SessionPasswordNeededError

        if not getattr(self, "_login_hash", None):
            raise ValueError("Request an OTP first.")
        try:
            await self.client.sign_in(
                phone=self._login_phone, code=code, phone_code_hash=self._login_hash
            )
        except SessionPasswordNeededError:
            self.log("🔐 2FA password required.")
            return {"status": "password_needed"}
        return self._after_login()

    async def verify_login_password(self, password: str):
        """Step 3 (optional): complete sign-in with the 2FA password."""
        await self.client.sign_in(password=password)
        return self._after_login()

    def _after_login(self):
        self.auth_state = "authorized"
        self._login_hash = None
        self.log("✅ Logged in to Telegram successfully.")
        self.emit("auth", {"auth_state": self.auth_state})
        return {"status": "authorized"}

    async def logout(self):
        try:
            await self.client.log_out()
        except Exception:
            pass
        # Telethon can't reuse a logged-out client, so stand up a fresh one
        # immediately — a new phone/OTP login then works without a restart.
        try:
            await self._fresh_client()
        except Exception as e:
            self.log(f"⚠️ Could not reset client after logout: {e}")
        self.auth_state = "unauthorized"
        self.emit("auth", {"auth_state": self.auth_state})
        self.log("👋 Logged out of Telegram.")
        return {"status": "unauthorized"}

    async def me(self):
        if self.auth_state != "authorized":
            return None
        try:
            u = await self.client.get_me()
            return {"id": u.id, "first_name": u.first_name,
                    "username": u.username, "phone": u.phone}
        except Exception:
            return None

    # ---------- folder scan & manual enqueue (Phase 3) ----------
    def scan_path(self, path: str):
        """Recursively inspect a path: subfolder + extension breakdown."""
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            raise ValueError("Path is not an existing directory.")
        ext_counts: dict[str, int] = {}
        subfolders: dict[str, int] = {}
        total_files = 0
        total_size = 0
        for root, _, files in os.walk(path):
            for f in files:
                total_files += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
                ext = os.path.splitext(f)[1].lower() or "(none)"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                rel = os.path.relpath(root, path)
                top = "." if rel == "." else rel.split(os.sep)[0]
                subfolders[top] = subfolders.get(top, 0) + 1
        return {
            "path": path,
            "total_files": total_files,
            "total_size": total_size,
            "extensions": sorted(
                [{"ext": k, "count": v} for k, v in ext_counts.items()],
                key=lambda x: -x["count"],
            ),
            "subfolders": sorted(
                [{"name": k, "count": v} for k, v in subfolders.items()],
                key=lambda x: -x["count"],
            ),
        }

    def _topic_for(self, filename, rel_root, routing):
        mode = routing.get("mode")
        if mode == "topic":
            return routing.get("topic_id")
        if mode == "extension":
            emap = routing.get("ext_map", {})
            cat = config.category_for(filename)
            return emap.get(cat) or emap.get("other") or emap.get("all")
        if mode == "folder":
            top = "." if rel_root in ("", ".") else rel_root.split(os.sep)[0]
            fmap = routing.get("folder_map", {})
            return fmap.get(top) or routing.get("default_topic")
        return None

    def enqueue_path(self, path: str, routing: dict):
        """Walk a directory and enqueue files according to a routing spec."""
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            raise ValueError("Path is not an existing directory.")
        added, skipped = 0, 0
        pending = []
        for root, _, files in os.walk(path):
            rel_root = os.path.relpath(root, path)
            for f in files:
                topic_id = self._topic_for(f, rel_root, routing)
                if not topic_id:
                    skipped += 1
                    continue
                full = os.path.join(root, f)
                file_hash, stats = generate_file_hash(full)
                if not file_hash or self.db.is_uploaded(file_hash):
                    skipped += 1
                    continue
                pending.append({
                    "folder_name": path, "path": full, "name": f,
                    "hash": file_hash, "mtime": original_timestamp(full, stats),
                    "stats": stats, "topic_id": int(topic_id),
                })
        # Upload oldest-created first so the timeline reads chronologically.
        pending.sort(key=lambda x: x["mtime"])
        for item in pending:
            if self.enqueue_item(item):
                added += 1
        self.log(f"➕ Queued {added} file(s) from {path} ({skipped} skipped).")
        return {"added": added, "skipped": skipped}

    def enqueue_staged_file(self, full_path: str, topic_id: int):
        """Enqueue a single already-staged (browser-uploaded) file."""
        file_hash, stats = generate_file_hash(full_path)
        if not file_hash:
            return False
        if self.db.is_uploaded(file_hash):
            return False
        return self.enqueue_item({
            "folder_name": os.path.dirname(full_path),
            "path": full_path, "name": os.path.basename(full_path),
            "hash": file_hash, "mtime": stats.st_mtime,
            "stats": stats, "topic_id": int(topic_id),
        })

    # ---------- groups & topics (Phase 2) ----------
    async def list_groups(self):
        """Groups/supergroups where the user is the creator or an admin."""
        out = []
        async for d in self.client.iter_dialogs():
            ent = d.entity
            is_group = getattr(d, "is_group", False)
            is_channel = getattr(d, "is_channel", False)
            megagroup = getattr(ent, "megagroup", False)
            if not (is_group or (is_channel and megagroup)):
                continue
            # Only groups the user owns or administers.
            is_creator = bool(getattr(ent, "creator", False))
            is_admin = getattr(ent, "admin_rights", None) is not None
            if not (is_creator or is_admin):
                continue
            out.append(
                {
                    "id": d.id,
                    "title": d.name,
                    "is_forum": bool(getattr(ent, "forum", False)),
                    "role": "owner" if is_creator else "admin",
                }
            )
        return out

    async def create_group(self, title: str, enable_topics: bool = True):
        """Create a supergroup and (optionally) enable Topics/forum mode."""
        from telethon.tl import functions

        res = await self.client(
            functions.channels.CreateChannelRequest(
                title=title, about="Created by Telegram Uploader", megagroup=True
            )
        )
        channel = res.chats[0]
        peer_id = int(f"-100{channel.id}")
        if enable_topics:
            try:
                await self.client(
                    functions.channels.ToggleForumRequest(channel=channel, enabled=True)
                )
            except Exception as e:
                self.log(f"⚠️ Could not enable Topics: {e}")
        self.select_group(peer_id)
        self.log(f"✅ Created group '{title}' ({peer_id}).")
        return {"id": peer_id, "title": title}

    def select_group(self, group_id: int):
        cfg = config.read_config()
        cfg["group_id"] = int(group_id)
        config.write_config(cfg)
        self.emit("group", {"group_id": int(group_id)})
        return {"group_id": int(group_id)}

    async def _resolve_entity(self, group_id: int):
        """Resolve a group entity robustly (falls back to scanning dialogs)."""
        gid = int(group_id)
        try:
            return await self.client.get_entity(gid)
        except Exception:
            async for d in self.client.iter_dialogs():
                if d.id == gid:
                    return d.entity
            raise ValueError("Group not found or not accessible.")

    async def list_topics(self, group_id: int):
        from telethon.tl import functions

        entity = await self._resolve_entity(group_id)
        if not getattr(entity, "forum", False):
            return {"is_forum": False, "topics": []}
        res = await self.client(
            functions.channels.GetForumTopicsRequest(
                channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
            )
        )
        topics = []
        for t in res.topics:
            # Skip deleted-topic markers; keep real topics.
            if hasattr(t, "title") and hasattr(t, "id"):
                topics.append({"id": t.id, "title": t.title})
        return {"is_forum": True, "topics": topics}

    async def create_topic(self, group_id: int, title: str):
        from telethon.tl import functions

        entity = await self._resolve_entity(group_id)
        if not getattr(entity, "forum", False):
            # Enable Topics automatically so the created topic works.
            try:
                await self.client(
                    functions.channels.ToggleForumRequest(channel=entity, enabled=True)
                )
                entity = await self._resolve_entity(group_id)
            except Exception as e:
                raise ValueError(f"Group has no Topics and enabling failed: {e}")
        res = await self.client(
            functions.channels.CreateForumTopicRequest(channel=entity, title=title)
        )
        # A forum topic's id == the id of the service message that opened it,
        # delivered inside an UpdateNewChannelMessage.
        topic_id = None
        for u in getattr(res, "updates", []):
            msg = getattr(u, "message", None)
            if msg is not None and hasattr(msg, "id"):
                topic_id = msg.id
                break
        if topic_id is None:  # fallback for other update shapes
            for u in getattr(res, "updates", []):
                if getattr(u, "id", None) is not None:
                    topic_id = u.id
                    break
        self.log(f"✅ Created topic '{title}' (id={topic_id}).")
        return {"id": topic_id, "title": title}

    async def create_topics_for_folders(self, group_id: int, folder_names: list[str],
                                        max_topics: int = 30):
        """Auto-create one topic per folder name; return {name: topic_id}.

        Reuses existing topics with the same title. Caps at max_topics.
        """
        existing = {}
        info = await self.list_topics(group_id)
        for t in info.get("topics", []):
            existing[t["title"].lower()] = t["id"]
        mapping = {}
        created = 0
        capped = False
        for raw in folder_names:
            name = "General" if raw in (".", "", None) else raw
            key = name.lower()
            if key in existing:
                mapping[raw] = existing[key]
                continue
            if created >= max_topics:
                capped = True
                continue
            made = await self.create_topic(group_id, name[:128])
            if made.get("id"):
                mapping[raw] = made["id"]
                existing[key] = made["id"]
                created += 1
        return {"mapping": mapping, "created": created, "capped": capped,
                "max_topics": max_topics}

    # ---------- controls ----------
    def set_status(self, status):
        self.status = "paused" if status == "pause" else "running"
        self.emit("status", {"status": self.status})
        return self.status

    # ---------- daily report ----------
    async def _daily_report_loop(self):
        while True:
            try:
                now = datetime.now()
                target = datetime(now.year, now.month, now.day, 23, 59, 0)
                if now >= target:
                    target += timedelta(days=1)
                await asyncio.sleep((target - now).total_seconds())
                cfg = config.read_config()
                if cfg.get("daily_report", True) and self.auth_state == "authorized":
                    await self.send_report(manual=False)
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(300)

    async def send_report(self, manual=True):
        group_id = config.active_group_id()
        if not group_id or self.auth_state != "authorized":
            return False
        count = self.db.count_on()
        today = datetime.now().strftime("%d %B %Y")
        kind = "Manual" if manual else "Daily"
        if count > 0:
            body = f"📊 **{kind} Upload Report**\n\n📅 {today}\n✅ Uploaded: **{count}** files."
        else:
            body = f"📊 **{kind} Upload Report**\n\n📅 {today}\n💤 No files uploaded."
        await self.client.send_message(group_id, body)
        self.log(f"📈 {kind} report sent.")
        return True

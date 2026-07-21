"""Upload workers, the per-file upload routine, and queue controls."""
import os
import time
import asyncio

from telethon import errors

from app import config
from app.db import generate_file_hash, file_sha256
from app.services.helpers import format_metadata, fmt_duration


class UploadMixin:
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
        caption = format_metadata(item["name"], item["path"], item["stats"])
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
                "elapsed": round(elapsed),
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
                # Content hash + size for integrity / download-back.
                try:
                    file_size = item["stats"].st_size
                    file_sha = await asyncio.to_thread(file_sha256, item["path"])
                except Exception:
                    file_size, file_sha = None, None
                self.db.mark_uploaded(
                    h, item["name"], item["path"], item["topic_id"], msg_link,
                    message_id=msg.id, size=file_size, sha256=file_sha,
                    chat_id=group_id, duration=round(elapsed, 1),
                )
                self.log(f"✅ [{name}] Done: {item['name']} in {fmt_duration(elapsed)}")
                self.emit("uploaded", {"name": item["name"], "link": msg_link,
                                       "duration": round(elapsed, 1),
                                       "duration_text": fmt_duration(elapsed),
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

    # ---------- queue controls ----------
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

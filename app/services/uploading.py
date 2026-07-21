"""Upload workers, the per-file upload routine, and queue controls."""
import os
import math
import time
import hashlib
import asyncio

from telethon import errors

from app import config
from app.db import generate_file_hash, file_sha256
from app.services.helpers import format_metadata, fmt_duration


class UploadMixin:
    def _drop_from_queue(self, item, note=None):
        """Remove an item from every queue view (memory + persistent DB)."""
        h = item["hash"]
        self.queued_hashes.discard(h)
        self.pause_set.discard(h)
        self.pending_items.pop(h, None)
        self.progress.pop(h, None)
        self.db.queue_remove(h)
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        if note:
            self.log(note)

    async def _upload_worker(self, name):
        while True:
            try:
                if self.auth_state != "authorized":
                    await asyncio.sleep(1)
                    continue

                item = await self.queue.get()
                h = item["hash"]
                try:
                    # hard cancel → drop and delete any staged copy
                    if h in self.cancel_set:
                        self.cancel_set.discard(h)
                        self._delete_staged(item)
                        self._drop_from_queue(item, f"🚫 Cancelled: {item['name']}")
                        continue
                    # globally paused or this file paused → leave queued, wait
                    if self.status == "paused" or h in self.pause_set:
                        self.queue.put_nowait(item)
                        await asyncio.sleep(0.5)
                        continue

                    cfg = config.read_config()
                    while not cfg.get("turbo_mode", False) and self.active_uploads > 0:
                        if self.status == "paused" or h in self.pause_set:
                            break
                        await asyncio.sleep(0.4)
                        cfg = config.read_config()
                    if self.status == "paused" or h in self.pause_set:
                        self.queue.put_nowait(item)
                        await asyncio.sleep(0.4)
                        continue

                    self.active_uploads += 1
                    task = asyncio.ensure_future(self._do_upload(name, item, cfg))
                    self._active[h] = task
                    try:
                        await task
                    except asyncio.CancelledError:
                        # aborted mid-upload by pause or per-file cancel
                        if h in self.cancel_set:
                            self.cancel_set.discard(h)
                            self._delete_staged(item)
                            self._drop_from_queue(item, f"🚫 Cancelled: {item['name']}")
                        else:
                            self.progress.pop(h, None)
                            self.queue.put_nowait(item)  # re-try / stay paused
                            self.emit("queue", {"queued_files": len(self.queued_hashes)})
                    finally:
                        self.active_uploads -= 1
                        self._active.pop(h, None)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log(f"❌ Worker {name} error: {e}")
                await asyncio.sleep(3)

    def _delete_staged(self, item):
        """Delete a browser-upload staged copy (safe no-op for local files)."""
        path = item.get("path", "")
        try:
            if os.path.abspath(path).startswith(os.path.abspath(config.UPLOAD_STAGING_DIR)):
                os.remove(path)
        except OSError:
            pass

    def _emit_progress(self, item, current, total, start_ts, label=None):
        elapsed = max(time.time() - start_ts, 0.1)
        speed = current / elapsed
        pct = (current / total) * 100 if total else 0
        eta = (total - current) / speed if speed > 0 else 0
        self.progress[item["hash"]] = {
            "hash": item["hash"],
            "status": "uploading",
            "file_name": label or item["name"],
            "current": current,
            "total": total,
            "percentage": round(pct, 1),
            "speed": speed,
            "eta": round(eta),
            "elapsed": round(elapsed),
        }
        self.emit("progress", self.progress[item["hash"]])

    def _record_failure(self, item, error):
        h = item["hash"]
        self.failed[h] = {
            "hash": h, "name": item["name"], "path": item["path"],
            "topic_id": item["topic_id"], "error": error,
        }
        # No longer pending — it's in the failed list (retryable via retry_failed).
        self.queued_hashes.discard(h)
        self.pending_items.pop(h, None)
        self.db.queue_remove(h)
        self.emit("failed", {"failed": list(self.failed.values())})
        self.emit("queue", {"queued_files": len(self.queued_hashes)})

    async def _finalize_success(self, name, item, group_id, msg_id, msg_link,
                                elapsed, size, sha, auto_delete,
                                chunked=0, total_parts=1):
        self.db.mark_uploaded(
            item["hash"], item["name"], item["path"], item["topic_id"], msg_link,
            message_id=msg_id, size=size, sha256=sha, chat_id=group_id,
            duration=round(elapsed, 1), chunked=chunked, total_parts=total_parts,
            original_mtime=item.get("mtime"),
        )
        self.log(f"✅ [{name}] Done: {item['name']} in {fmt_duration(elapsed)}")
        self.emit("uploaded", {"name": item["name"], "link": msg_link,
                               "duration": round(elapsed, 1),
                               "duration_text": fmt_duration(elapsed),
                               "total_uploaded": self.db.total_count()})
        # Staged (browser-uploaded) files are always removed after send so the
        # data volume doesn't fill up; local files honor the toggle.
        is_staged = os.path.abspath(item["path"]).startswith(
            os.path.abspath(config.UPLOAD_STAGING_DIR)
        )
        if auto_delete or is_staged:
            try:
                os.remove(item["path"])
            except Exception:
                pass
        # Done — clear from every queue view.
        self.queued_hashes.discard(item["hash"])
        self.pending_items.pop(item["hash"], None)
        self.progress.pop(item["hash"], None)
        self.db.queue_remove(item["hash"])
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        await asyncio.sleep(config.DELAY_BETWEEN_UPLOADS)

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
        h = item["hash"]
        size = item["stats"].st_size

        # Large files exceed Telegram's per-file cap → split into parts.
        if size > config.CHUNK_SIZE:
            await self._do_chunked_upload(name, item, group_id, auto_delete, size)
            return

        try:
            rel_path = os.path.relpath(os.path.dirname(item["path"]), item["folder_name"])
        except Exception:
            rel_path = None
        caption = format_metadata(item["name"], item["path"], item["stats"],
                                  rel_path=rel_path, original_mtime=item.get("mtime"))
        start_time = [time.time()]

        async def progress_callback(current, total):
            self._emit_progress(item, current, total, start_time[0])

        last_error = "unknown"
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
                try:
                    file_sha = await asyncio.to_thread(file_sha256, item["path"])
                except Exception:
                    file_sha = None
                await self._finalize_success(
                    name, item, group_id, msg.id, msg_link, elapsed, size, file_sha,
                    auto_delete,
                )
                return
            except errors.FloodWaitError as e:
                self.log(f"⏳ [{name}] FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                last_error = str(e)
                self.log(f"❌ [{name}] Error on {item['name']} (try {attempt}): {e}")
                await asyncio.sleep(3)
        self._record_failure(item, last_error)

    @staticmethod
    def _write_part(src, start, length, dest):
        """Copy a byte range [start, start+length) of src into dest,
        returning the part's SHA-256. Runs in a worker thread."""
        h = hashlib.sha256()
        with open(src, "rb") as f, open(dest, "wb") as out:
            f.seek(start)
            remaining = length
            while remaining > 0:
                block = f.read(min(1024 * 1024, remaining))
                if not block:
                    break
                out.write(block)
                h.update(block)
                remaining -= len(block)
        return h.hexdigest()

    async def _do_chunked_upload(self, name, item, group_id, auto_delete, size):
        """Split a large file into CHUNK_SIZE parts, upload each as its own
        message, and record parts in file_chunks. Resumable: parts already
        recorded are skipped, so a restart only re-sends what's missing."""
        h = item["hash"]
        path = item["path"]
        total_parts = math.ceil(size / config.CHUNK_SIZE)
        self.log(f"🧩 [{name}] Large file ({size} bytes) → {total_parts} parts: {item['name']}")

        try:
            whole_sha = await asyncio.to_thread(file_sha256, path)
            done = self.db.done_chunk_indices(h)
            completed = [sum(c["size"] for c in self.db.get_chunks(h))]
            start_time = time.time()
            config.ensure_staging()
            group_str = str(group_id).replace("-100", "")
            topic_seg = f"/{item['topic_id']}" if item.get("topic_id") else ""

            for i in range(total_parts):
                if i in done:
                    continue
                start = i * config.CHUNK_SIZE
                length = min(config.CHUNK_SIZE, size - start)
                part_path = os.path.join(config.UPLOAD_STAGING_DIR, f"{h}.part{i}")
                part_sha = await asyncio.to_thread(
                    self._write_part, path, start, length, part_path)

                base = completed[0]
                label = f"{item['name']} (part {i+1}/{total_parts})"

                async def pcb(current, total, _base=base, _label=label):
                    self._emit_progress(item, _base + current, size, start_time, _label)

                msg = None
                last_error = "unknown"
                for attempt in range(1, config.UPLOAD_RETRY_LIMIT + 1):
                    try:
                        msg = await self.client.send_file(
                            group_id, part_path,
                            caption=f"{item['name']} • part {i+1}/{total_parts}",
                            reply_to=item["topic_id"], force_document=True,
                            progress_callback=pcb,
                        )
                        break
                    except errors.FloodWaitError as e:
                        self.log(f"⏳ [{name}] FloodWait {e.seconds}s (part {i+1})")
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        last_error = str(e)
                        self.log(f"❌ [{name}] part {i+1} error (try {attempt}): {e}")
                        await asyncio.sleep(3)
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                if msg is None:
                    raise RuntimeError(f"part {i+1}/{total_parts} failed: {last_error}")
                self.db.add_chunk(h, i, msg.id, length, part_sha)
                completed[0] += length
                await asyncio.sleep(config.DELAY_BETWEEN_UPLOADS)

            chunks = self.db.get_chunks(h)
            first_id = chunks[0]["message_id"] if chunks else None
            first_link = f"https://t.me/c/{group_str}{topic_seg}/{first_id}"
            elapsed = time.time() - start_time
            await self._finalize_success(
                name, item, group_id, first_id, first_link, elapsed, size,
                whole_sha, auto_delete, chunked=1, total_parts=total_parts,
            )
        except Exception as e:
            self._record_failure(item, str(e))
            self.log(f"❌ [{name}] Chunked upload failed: {e}")

    # ---------- queue controls ----------
    def cancel_item(self, file_hash: str):
        """Hard-cancel: abort now if uploading, drop from the queue either way."""
        self.cancel_set.add(file_hash)
        self.pause_set.discard(file_hash)  # so a paused item gets dequeued+dropped
        task = self._active.get(file_hash)
        if task:
            task.cancel()
        return {"status": "cancelling"}

    def pause_item(self, file_hash: str):
        """Pause one file — abort it if uploading; it stays queued for resume."""
        self.pause_set.add(file_hash)
        self.db.queue_set_status(file_hash, "paused")
        task = self._active.get(file_hash)
        if task:
            task.cancel()
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        return {"status": "paused"}

    def resume_item(self, file_hash: str):
        self.pause_set.discard(file_hash)
        self.db.queue_set_status(file_hash, "pending")
        # make sure it's actually in the working queue
        if file_hash not in self.queued_hashes:
            item = self.pending_items.get(file_hash)
            if item:
                self.queued_hashes.add(file_hash)
                self.queue.put_nowait(item)
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        return {"status": "resumed"}

    def clear_queue(self):
        """Cancel everything (active + pending + paused) and empty the queue."""
        for task in list(self._active.values()):
            task.cancel()
        drained = 0
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                self._delete_staged(item)
                self.queue.task_done()
                drained += 1
            except asyncio.QueueEmpty:
                break
        for h in list(self.queued_hashes):
            self.db.queue_remove(h)
        self.queued_hashes.clear()
        self.pause_set.clear()
        self.pending_items.clear()
        self.progress.clear()
        self.emit("queue", {"queued_files": 0})
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

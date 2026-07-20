"""Folder scanning, routing decisions, and enqueuing work items."""
import os
import asyncio

from app import config
from app.db import generate_file_hash
from app.services.helpers import original_timestamp


class ScanMixin:
    def enqueue_item(self, item: dict):
        """Directly enqueue a prepared item (used by browser upload / manual add)."""
        if item["hash"] in self.queued_hashes:
            return False
        self.queued_hashes.add(item["hash"])
        self.queue.put_nowait(item)
        self.emit("queue", {"queued_files": len(self.queued_hashes)})
        return True

    def _scan_and_sort(self):
        """Scan configured folders under SCAN_ROOT (legacy auto-watch source)."""
        files_to_upload = []
        cfg = config.read_config()
        folder_map = cfg.get("folders", {})

        for folder_name, rules in folder_map.items():
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
                        files_to_upload.append({
                            "folder_name": folder_name,
                            "path": full_path,
                            "name": file,
                            "hash": file_hash,
                            "mtime": original_timestamp(full_path, stats),
                            "stats": stats,
                            "topic_id": int(topic_id),
                        })
        files_to_upload.sort(key=lambda x: x["mtime"])
        return files_to_upload

    async def _rescanner_loop(self):
        """Kept for optional future use; not started by default."""
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

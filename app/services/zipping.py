"""Zip-a-folder upload option.

A folder can be sent as individual files (default), as a single .zip, or
both. The .zip is queued like any other file, so if it exceeds Telegram's
per-file cap it is transparently split into parts (F3) and reassembled on
download (F4).

Zipping uses ZIP_STORED (no compression): media is already compressed, so
deflating it burns CPU for ~0% size gain while STORED keeps a large folder
byte-lossless and near-instant to archive. Building runs off the event loop
with live progress ('zip' WS events) so a large (e.g. ~10GB) folder never
blocks the HTTP request or times out the browser.

The zip's filename and its Telegram topic are both derived from what it
actually represents (a named folder + the date range of its contents, or a
single file's own name) rather than an opaque staging-session id, and it is
routed the same way any file of that folder/type would be — not hardcoded
to the General topic."""
import os
import shutil
import zipfile
import asyncio
from datetime import datetime

from app import config
from app.services.helpers import _sanitize_tag


class ZipMixin:
    def _zip_dir_sync(self, src_dir, zip_path, counter):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for root, _, files in os.walk(src_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.abspath(fp) == os.path.abspath(zip_path):
                        continue  # never zip the zip itself
                    z.write(fp, os.path.relpath(fp, src_dir))
                    try:
                        counter[0] += os.path.getsize(fp)
                    except OSError:
                        pass
        return zip_path

    def _dir_size(self, src_dir, zip_path):
        total = 0
        for root, _, files in os.walk(src_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.abspath(fp) == os.path.abspath(zip_path):
                    continue
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    def _dir_date_range(self, root):
        lo = hi = None
        for r, _, files in os.walk(root):
            for f in files:
                try:
                    m = os.path.getmtime(os.path.join(r, f))
                except OSError:
                    continue
                if lo is None or m < lo:
                    lo = m
                if hi is None or m > hi:
                    hi = m
        return (lo, hi) if lo is not None else None

    def _fmt_date_range(self, rng):
        if not rng:
            return ""
        lo, hi = rng
        d1 = datetime.fromtimestamp(lo).strftime("%Y-%m-%d")
        d2 = datetime.fromtimestamp(hi).strftime("%Y-%m-%d")
        return d1 if d1 == d2 else f"{d1}_to_{d2}"

    def _is_browser_session_dir(self, src_dir):
        name = os.path.basename(os.path.normpath(src_dir))
        parent = os.path.dirname(os.path.normpath(src_dir))
        return name.startswith("session_") and os.path.normpath(parent) == os.path.normpath(
            config.UPLOAD_STAGING_DIR)

    def _detect_zip_source(self, src_dir):
        """What this zip represents, used for BOTH its readable filename and
        (in folder-routing mode) picking the same topic that folder's own
        files would use.

        Local-path folders (typed path, always a real named folder) are used
        as-is. Browser staging dirs are opaque session ids, so we look one
        level in: a lone subfolder means a device folder-pick (name = that
        folder, e.g. "Camera"); a lone file means a single-file pick (name =
        that file's own name); anything else (several loose files with no
        common folder) falls back to a generic multi-file label."""
        if not self._is_browser_session_dir(src_dir):
            name = os.path.basename(os.path.normpath(src_dir))
            return {"kind": "folder", "name": name, "root": src_dir}
        try:
            entries = os.listdir(src_dir)
        except OSError:
            entries = []
        dirs = [e for e in entries if os.path.isdir(os.path.join(src_dir, e))]
        files = [e for e in entries if os.path.isfile(os.path.join(src_dir, e))]
        if len(dirs) == 1 and not files:
            return {"kind": "folder", "name": dirs[0], "root": os.path.join(src_dir, dirs[0])}
        if len(files) == 1 and not dirs:
            return {"kind": "file", "name": os.path.splitext(files[0])[0], "root": src_dir}
        return {"kind": "multi", "name": "Files", "root": src_dir}

    def _zip_label(self, src_dir):
        info = self._detect_zip_source(src_dir)
        if info["kind"] == "file":
            label = info["name"]
        else:
            date_part = self._fmt_date_range(self._dir_date_range(info["root"]))
            label = f"{info['name']}_{date_part}" if date_part else info["name"]
        return (_sanitize_tag(label) or "archive")[:80]

    async def resolve_zip_topic(self, routing, group_id, src_dir=None):
        """Route the .zip the same way any file of its folder/type would be
        routed under the chosen 'Organize into topics by' mode, instead of
        hardcoding it to the General/main-chat topic."""
        routing = routing or {}
        mode = routing.get("mode")
        if mode == "topic":
            return int(routing.get("topic_id") or 0)
        if mode == "extension":
            emap = routing.get("ext_map") or {}
            topic = emap.get("compressed")
            if not topic:
                label = config.CATEGORY_LABELS["compressed"]
                res = await self.create_topics_for_folders(group_id, [label])
                topic = res["mapping"].get(label)
            return int(topic or 0)
        if mode == "folder":
            fmap = routing.get("folder_map") or {}
            name = None
            if src_dir is not None:
                info = self._detect_zip_source(src_dir)
                if info["kind"] == "folder":
                    name = info["name"]
            topic = (fmap.get(name) if name else None) or fmap.get(".") or routing.get("default_topic")
            return int(topic or 0)
        return 0

    async def _prepare_zip(self, src_dir, custom_name=None):
        """Pick a collision-free, readable zip path and precheck size/disk
        space. Raises ValueError with a clean message on any precondition
        failure. custom_name: user-typed override for the auto-generated
        folder/file + date-range label, sanitized the same way."""
        src_dir = os.path.expanduser(src_dir)
        if not os.path.isdir(src_dir):
            raise ValueError("Folder not found.")
        config.ensure_staging()
        if custom_name and custom_name.strip():
            base = (_sanitize_tag(custom_name.strip()) or "archive")[:80]
        else:
            base = self._zip_label(src_dir)
        zip_path = os.path.join(config.UPLOAD_STAGING_DIR, f"{base}.zip")
        n = 1
        while os.path.exists(zip_path):
            zip_path = os.path.join(config.UPLOAD_STAGING_DIR, f"{base}_{n}.zip")
            n += 1
        total_size = await asyncio.to_thread(self._dir_size, src_dir, zip_path)
        if total_size == 0:
            raise ValueError("Nothing to zip — folder is empty.")
        free = shutil.disk_usage(config.UPLOAD_STAGING_DIR).free
        if free < total_size * 1.05:
            gb = total_size / (1024 ** 3)
            raise ValueError(f"Not enough free disk space to zip ({gb:.1f} GB needed).")
        return zip_path, total_size

    async def _build_and_queue_zip(self, src_dir, zip_path, topic_id, total_size,
                                    delete_src, label):
        """Build the zip off-thread with live progress, then queue it. Cleans up
        the partial file on any failure so nothing orphaned is left behind."""
        counter = [0]
        build = asyncio.ensure_future(
            asyncio.to_thread(self._zip_dir_sync, src_dir, zip_path, counter))
        try:
            while not build.done():
                pct = round(min(counter[0] / total_size, 1.0) * 100, 1) if total_size else 0
                self.emit("zip", {"status": "zipping", "name": label, "percentage": pct})
                await asyncio.sleep(0.5)
            await build
        except Exception as e:
            build.cancel()
            try:
                os.remove(zip_path)
            except OSError:
                pass
            self.emit("zip", {"status": "error", "name": label, "error": str(e)})
            self.log(f"❌ Zip failed for {label}: {e}")
            return {"queued": False, "zip": label, "error": str(e)}

        self.emit("zip", {"status": "queuing", "name": label, "percentage": 100})
        ok = self.enqueue_staged_file(zip_path, int(topic_id))
        if not ok:
            try:
                os.remove(zip_path)
            except OSError:
                pass
        if delete_src:
            try:
                shutil.rmtree(src_dir)
            except OSError:
                pass
        self.emit("zip", {"status": "done", "name": label, "queued": bool(ok)})
        self.log(f"📦 {'Queued' if ok else 'Skipped (dup)'} zip: {label}")
        return {"queued": bool(ok), "zip": label}

    async def zip_and_enqueue(self, src_dir, topic_id, delete_src=False, custom_name=None):
        """Zip src_dir into staging and queue the .zip. Returns immediately once
        the zip is validated (size/disk checked) — the actual archiving runs in
        the background with live 'zip' progress events so the caller never
        blocks/times out on a large folder.
        delete_src: remove the source dir after zipping (browser staged files).
        custom_name: user-typed override for the auto-generated name."""
        zip_path, total_size = await self._prepare_zip(src_dir, custom_name=custom_name)
        label = os.path.basename(zip_path)
        asyncio.create_task(self._build_and_queue_zip(
            src_dir, zip_path, topic_id, total_size, delete_src, label))
        return {"status": "zipping", "zip": label}

    def _topic_for_individual(self, filename, rel_root, routing):
        """Resolve a topic for one file via the shared ScanMixin._topic_for,
        except 'topic' mode is returned as-is (0 is a legitimate value there —
        the non-forum-group main chat, not "unset") while extension/folder
        fall back to General (1) when unmapped, mirroring the browser
        individual-upload JS fallback exactly (never drops a file silently)."""
        if routing.get("mode") == "topic":
            return self._topic_for(filename, rel_root, routing)
        return self._topic_for(filename, rel_root, routing) or 1

    def _enqueue_dir_individually(self, session_dir, routing):
        """Queue every staged file under session_dir on its own, using the same
        folder/extension/topic routing as local-path individual uploads."""
        routing = routing or {}
        added, skipped = 0, 0
        for root, _, files in os.walk(session_dir):
            rel_root = os.path.relpath(root, session_dir)
            for f in files:
                full = os.path.join(root, f)
                topic = self._topic_for_individual(f, rel_root, routing)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = None
                if self.enqueue_staged_file(full, int(topic), session_dir, client_mtime=mtime):
                    added += 1
                else:
                    skipped += 1
                    try:
                        os.remove(full)
                    except OSError:
                        pass
        return added, skipped

    def _sweep_empty_dirs(self, session_dir):
        for root, _, _files in os.walk(session_dir, topdown=False):
            if root == session_dir:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    async def _finalize_both(self, session_dir, routing, custom_name=None):
        """'Both' orchestration: build the zip SNAPSHOT to completion first (so
        it reads every original byte before anything can delete them), then
        queue the originals individually — each half self-deletes its own
        staged copy after a successful send, so they never contend."""
        gid = config.active_group_id()
        try:
            zip_topic_id = await self.resolve_zip_topic(routing, gid, src_dir=session_dir)
            zip_path, total_size = await self._prepare_zip(session_dir, custom_name=custom_name)
            label = os.path.basename(zip_path)
            await self._build_and_queue_zip(
                session_dir, zip_path, zip_topic_id, total_size,
                delete_src=False, label=label)
        except Exception as e:
            self.log(f"❌ Zip snapshot failed for 'Both' session, continuing with "
                     f"individual files only: {e}")

        added, skipped = self._enqueue_dir_individually(session_dir, routing)
        self.log(f"➕ Queued {added} individual file(s) from browser 'Both' "
                 f"session ({skipped} skipped).")
        self._sweep_empty_dirs(session_dir)

    async def finalize_session(self, session_dir, send_mode, routing=None, custom_name=None):
        """Browser-upload session finalize, dispatched by send_mode:
        'zip' -> one background zip (originals deleted once queued).
        'both' -> zip snapshot first, then individuals — run as one background
                  task so the HTTP caller never blocks on a large folder.
        The zip's topic is resolved from routing (folder/extension/topic mode)
        the same way individual files are, not hardcoded to General.
        custom_name: user-typed override for the auto-generated zip name."""
        routing = routing or {}
        if send_mode == "both":
            asyncio.create_task(self._finalize_both(session_dir, routing, custom_name=custom_name))
            return {"status": "processing"}
        gid = config.active_group_id()
        zip_topic_id = await self.resolve_zip_topic(routing, gid, src_dir=session_dir)
        return await self.zip_and_enqueue(
            session_dir, zip_topic_id, delete_src=True, custom_name=custom_name)

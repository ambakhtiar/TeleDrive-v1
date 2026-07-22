"""DB self-backup to Telegram.

The local SQLite DB is the source of truth (file -> message/chunk mapping).
If it's lost, or you start fresh on another machine, everything is
unrecoverable — so we snapshot the DB into a reserved "Backup" topic in the
group. F10 (startup restore) reads the newest snapshot back.
"""
import os
import re
import json
import asyncio
from datetime import datetime, timedelta

from app import config
from app.db import file_sha256, Database

BACKUP_TOPIC_TITLE = "🗄️ Backup"
BACKUP_CAPTION_TAG = "TELEDRIVE_DB_BACKUP"


class BackupMixin:
    async def ensure_backup_topic(self):
        """Find or create the reserved Backup topic; persist its id. Returns
        the topic id, or None when the group has no Topics (→ General)."""
        gid = config.active_group_id()
        if not gid:
            return None
        cfg = config.read_config()
        if cfg.get("backup_topic_configured"):
            return cfg.get("backup_topic_id") or None
        topic_id = None
        try:
            entity = await self._resolve_entity(gid)
            if getattr(entity, "forum", False):
                # reuse if a topic with this title already exists
                info = await self.list_topics(gid)
                for t in info.get("topics", []):
                    if t["title"].strip() == BACKUP_TOPIC_TITLE:
                        topic_id = t["id"]
                        break
                if topic_id is None:
                    made = await self.create_topic(gid, BACKUP_TOPIC_TITLE)
                    topic_id = made.get("id")
        except Exception as e:
            self.log(f"⚠️ Could not set up Backup topic: {e}")
            return None
        cfg = config.read_config()
        cfg["backup_topic_id"] = topic_id or 0
        cfg["backup_topic_configured"] = True
        config.write_config(cfg)
        self.log(f"🗄️ Backup topic ready (id={topic_id or 'General'}).")
        return topic_id

    async def snapshot_db(self):
        """Upload a consistent DB snapshot to the Backup topic. Atomic: the
        previous snapshot is untouched until this one fully uploads, so an
        interrupted backup never destroys the last good copy."""
        if self.auth_state != "authorized":
            return False
        gid = config.active_group_id()
        if not gid:
            return False
        topic_id = await self.ensure_backup_topic()

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = os.path.join(config.DATA_DIR, f"teledrive_db_{stamp}.sqlite")
        try:
            meta = await asyncio.to_thread(self.db.backup_to, tmp)
            sha = await asyncio.to_thread(file_sha256, tmp)
            # Machine-parseable metadata (F10 reads this to pick the newest).
            manifest = {"tag": BACKUP_CAPTION_TAG, "version": stamp,
                        "rows": meta["rows"], "last": meta["last"], "sha256": sha}
            caption = (f"🗄️ **DB Backup** — {meta['rows']} files\n"
                       f"🕒 {stamp}\n\n```\n{json.dumps(manifest)}\n```")
            await self.client.send_file(
                gid, tmp, caption=caption,
                reply_to=topic_id or None, force_document=True,
            )
            self.log(f"🗄️ DB backup uploaded ({meta['rows']} files, {sha[:8]}).")
            return True
        except Exception as e:
            self.log(f"⚠️ DB backup failed: {e}")
            return False
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    async def _backup_loop(self):
        """Periodic DB snapshot. Waits for auth, does one soon after startup,
        then repeats every BACKUP_INTERVAL_MIN."""
        try:
            for _ in range(150):  # wait up to ~5 min for login
                if self.auth_state == "authorized":
                    break
                await asyncio.sleep(2)
            await asyncio.sleep(20)  # let startup settle (size backfill etc.)
            await self.snapshot_db()
            while True:
                await asyncio.sleep(max(60, config.BACKUP_INTERVAL_MIN * 60))
                if self.auth_state == "authorized":
                    await self.snapshot_db()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(f"⚠️ Backup loop error: {e}")

    # ---------- F10: startup restore / reconcile ----------
    async def _find_latest_backup(self):
        """Newest DB snapshot in the Backup topic → (message, manifest) or None."""
        gid = config.active_group_id()
        if not gid:
            return None
        cfg = config.read_config()
        topic_id = cfg.get("backup_topic_id") or None
        entity = await self._resolve_entity(gid)
        kwargs = {"limit": 100}
        if topic_id:
            kwargs["reply_to"] = topic_id
        best = None
        async for m in self.client.iter_messages(entity, **kwargs):
            cap = m.message or ""
            if BACKUP_CAPTION_TAG not in cap or not m.file:
                continue
            match = re.search(r"\{.*\}", cap, re.S)
            if not match:
                continue
            try:
                manifest = json.loads(match.group(0))
            except Exception:
                continue
            version = manifest.get("version", "")
            if best is None or version > best[0]:
                best = (version, m, manifest)
        return (best[1], best[2]) if best else None

    async def _maybe_restore_db(self):
        """On startup, adopt the Telegram backup if the local DB is empty or
        older. Never blindly overwrites — a safety copy of the local DB is
        kept, and the download is SHA-256 verified before swapping in."""
        try:
            found = await self._find_latest_backup()
        except Exception as e:
            self.log(f"⚠️ Backup lookup failed ({e}); using local DB.")
            return
        if not found:
            return
        msg, manifest = found
        local = self.db.stats_meta()
        local_rows, local_last = local["rows"], (local["last"] or "")
        remote_rows = manifest.get("rows", 0)
        remote_last = manifest.get("last", "") or ""

        if local_rows == 0 and remote_rows > 0:
            reason = "local DB empty"
        elif remote_last > local_last:
            reason = "Telegram backup is newer"
        else:
            self.log(f"🗄️ Local DB up to date ({local_rows} files); backup not restored.")
            return

        tmp = os.path.join(config.DATA_DIR, f"_restore_{manifest.get('version', 'tmp')}.sqlite")
        try:
            await self.client.download_media(msg, file=tmp)
            sha = await asyncio.to_thread(file_sha256, tmp)
            if manifest.get("sha256") and sha != manifest["sha256"]:
                self.log("⚠️ Downloaded backup failed integrity check; keeping local DB.")
                os.remove(tmp)
                return
            # swap the DB file (keep a timestamped safety copy of the old one)
            self.db.close()
            if os.path.exists(config.DB_FILE):
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    os.replace(config.DB_FILE, config.DB_FILE + f".local-{stamp}.bak")
                except OSError:
                    pass
            os.replace(tmp, config.DB_FILE)
            self.db = Database(config.DB_FILE)
            self.log(f"♻️ Restored DB from Telegram backup — {remote_rows} files ({reason}).")
        except Exception as e:
            self.log(f"⚠️ DB restore failed ({e}); keeping local DB.")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            # make sure we still have a usable connection
            try:
                self.db.total_count()
            except Exception:
                self.db = Database(config.DB_FILE)

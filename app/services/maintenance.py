"""Background maintenance: backfill missing file sizes from Telegram
message metadata (no downloads — just reads message.file.size in batches)."""
import asyncio

from telethon import errors

from app import config


class MaintenanceMixin:
    async def backfill_sizes(self, batch=100):
        """Fill `size` for old rows that predate size tracking, by reading the
        size attribute off each stored message (batched; metadata only)."""
        if self.auth_state != "authorized":
            return 0
        rows = self.db.rows_missing_size()
        if not rows:
            return 0
        gid = config.active_group_id()
        if not gid:
            return 0
        try:
            entity = await self._resolve_entity(gid)
        except Exception:
            return 0

        hash_by_id = {int(mid): h for (h, mid) in rows if mid is not None}
        ids = list(hash_by_id.keys())
        updated = 0
        self.log(f"📏 Backfilling size for {len(ids)} file(s)…")
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            try:
                msgs = await self.client.get_messages(entity, ids=chunk)
            except errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
                continue
            except Exception:
                await asyncio.sleep(2)
                continue
            for m in msgs:
                if not m:
                    continue
                size = None
                try:
                    if m.file is not None:
                        size = m.file.size
                except Exception:
                    size = None
                h = hash_by_id.get(m.id)
                if size and h:
                    self.db.set_size(h, size)
                    updated += 1
            await asyncio.sleep(1)  # gentle pacing to avoid FloodWait
        if updated:
            self.log(f"📏 Size backfilled for {updated} file(s).")
        return updated

    async def _startup_maintenance(self):
        """Run once shortly after startup: wait for auth, then backfill sizes."""
        try:
            for _ in range(120):  # wait up to ~4 min for login
                if self.auth_state == "authorized":
                    break
                await asyncio.sleep(2)
            await self.backfill_sizes()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(f"⚠️ Size backfill skipped: {e}")

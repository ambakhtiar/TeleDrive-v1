"""Download / restore: stream a stored file back from Telegram.

Handles both single-message files and chunked (large) files, verifying
SHA-256 integrity per part and for the whole file as it streams.
"""
import hashlib

from app import config


class DownloadMixin:
    def _file_group(self, rec):
        return rec.get("chat_id") or config.active_group_id()

    async def download_check(self, file_hash: str):
        """Cheap pre-flight before a browser download so the UI can show a
        clean error instead of navigating to a raw JSON error page."""
        rec = self.db.get_upload(file_hash)
        if not rec:
            raise ValueError("File not found in history.")
        if self.auth_state != "authorized":
            raise ValueError("Not connected to Telegram. Log in first.")

        if rec.get("chunked"):
            chunks = self.db.get_chunks(file_hash)
            expected = rec.get("total_parts") or len(chunks)
            if not chunks or len(chunks) < expected:
                raise ValueError("This large file is incomplete — some parts are missing.")
            entity = await self._resolve_entity(self._file_group(rec))
            first = await self.client.get_messages(entity, ids=int(chunks[0]["message_id"]))
            if not first or not getattr(first, "media", None):
                raise ValueError("This file is no longer available in Telegram (parts were deleted).")
            return {"ok": True, "name": rec["file_name"], "size": rec.get("size")}

        if not rec.get("message_id"):
            raise ValueError("This older upload has no stored message id — open its Telegram link instead.")
        entity = await self._resolve_entity(self._file_group(rec))
        msg = await self.client.get_messages(entity, ids=int(rec["message_id"]))
        if not msg or not getattr(msg, "media", None):
            raise ValueError("This file is no longer available in Telegram (the message was deleted).")
        return {"ok": True, "name": rec["file_name"], "size": rec.get("size")}

    async def download_file(self, file_hash: str):
        """Return (file_name, async_byte_iterator) for a stored upload."""
        rec = self.db.get_upload(file_hash)
        if not rec:
            raise ValueError("File not found in history.")
        if self.auth_state != "authorized":
            raise ValueError("Log in to Telegram first.")
        entity = await self._resolve_entity(self._file_group(rec))

        if rec.get("chunked"):
            return rec["file_name"], self._stream_chunked(entity, file_hash, rec)

        if not rec.get("message_id"):
            raise ValueError(
                "This older upload has no stored message id, so it can't be "
                "downloaded through the app. Open its Telegram link instead."
            )
        msg = await self.client.get_messages(entity, ids=int(rec["message_id"]))
        if not msg or not getattr(msg, "media", None):
            raise ValueError("The original message no longer exists in Telegram.")

        async def stream():
            async for chunk in self.client.iter_download(msg.media):
                yield chunk

        return rec["file_name"], stream()

    async def _stream_chunked(self, entity, file_hash, rec):
        """Stream a chunked file's parts in order, verifying SHA-256 of each
        part and of the whole file. A mismatch aborts the stream (the client
        gets a failed/incomplete download rather than silent corruption)."""
        chunks = self.db.get_chunks(file_hash)
        if not chunks:
            raise ValueError("No parts recorded for this file.")
        whole = hashlib.sha256()
        for c in chunks:
            msg = await self.client.get_messages(entity, ids=int(c["message_id"]))
            if not msg or not getattr(msg, "media", None):
                raise ValueError(f"Part {c['part_index'] + 1} is missing in Telegram.")
            part = hashlib.sha256()
            async for block in self.client.iter_download(msg.media):
                part.update(block)
                whole.update(block)
                yield block
            if c.get("sha256") and part.hexdigest() != c["sha256"]:
                raise ValueError(f"Integrity check failed on part {c['part_index'] + 1}.")
        if rec.get("sha256") and whole.hexdigest() != rec["sha256"]:
            raise ValueError("Whole-file integrity check failed after reassembly.")

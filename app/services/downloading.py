"""Download / restore: stream a stored file back from Telegram."""
from app import config


class DownloadMixin:
    async def download_check(self, file_hash: str):
        """Cheap pre-flight before a browser download: confirms the file can
        actually be fetched, so the UI can show a clean error instead of the
        browser navigating to a raw JSON error page."""
        rec = self.db.get_upload(file_hash)
        if not rec:
            raise ValueError("File not found in history.")
        if not rec.get("message_id"):
            raise ValueError("This older upload has no stored message id — open its Telegram link instead.")
        if self.auth_state != "authorized":
            raise ValueError("Not connected to Telegram. Log in first.")
        entity = await self._resolve_entity(config.active_group_id())
        msg = await self.client.get_messages(entity, ids=int(rec["message_id"]))
        if not msg or not getattr(msg, "media", None):
            raise ValueError("This file is no longer available in Telegram (the message was deleted).")
        return {"ok": True, "name": rec["file_name"], "size": rec.get("size")}

    async def download_file(self, file_hash: str):
        """Return (file_name, async_byte_iterator) for a stored upload.

        Fetches the original message by id and streams its media back. Raises
        ValueError with a clear message if the file can't be restored.
        """
        rec = self.db.get_upload(file_hash)
        if not rec:
            raise ValueError("File not found in history.")
        if not rec.get("message_id"):
            raise ValueError(
                "This older upload has no stored message id, so it can't be "
                "downloaded through the app. Open its Telegram link instead."
            )
        if self.auth_state != "authorized":
            raise ValueError("Log in to Telegram first.")

        group_id = config.active_group_id()
        entity = await self._resolve_entity(group_id)
        msg = await self.client.get_messages(entity, ids=int(rec["message_id"]))
        if not msg or not getattr(msg, "media", None):
            raise ValueError("The original message no longer exists in Telegram.")

        async def stream():
            async for chunk in self.client.iter_download(msg.media):
                yield chunk

        return rec["file_name"], stream()

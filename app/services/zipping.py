"""Zip-a-folder upload option.

A folder can be sent as individual files (default), as a single .zip, or
both. The .zip is queued like any other file, so if it exceeds Telegram's
per-file cap it is transparently split into parts (F3) and reassembled on
download (F4)."""
import os
import shutil
import zipfile
import asyncio

from app import config
from app.services.helpers import _sanitize_tag


class ZipMixin:
    def _zip_dir_sync(self, src_dir, zip_path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for root, _, files in os.walk(src_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.abspath(fp) == os.path.abspath(zip_path):
                        continue  # never zip the zip itself
                    z.write(fp, os.path.relpath(fp, src_dir))
        return zip_path

    async def zip_and_enqueue(self, src_dir, topic_id, delete_src=False):
        """Zip src_dir into staging and queue the .zip as one upload.
        delete_src: remove the source dir after zipping (browser staged files)."""
        src_dir = os.path.expanduser(src_dir)
        if not os.path.isdir(src_dir):
            raise ValueError("Folder not found.")
        config.ensure_staging()
        base = _sanitize_tag(os.path.basename(os.path.normpath(src_dir))) or "folder"
        zip_path = os.path.join(config.UPLOAD_STAGING_DIR, f"{base}.zip")
        n = 1
        while os.path.exists(zip_path):
            zip_path = os.path.join(config.UPLOAD_STAGING_DIR, f"{base}_{n}.zip")
            n += 1
        # Zipping is blocking + can be large — run off the event loop.
        await asyncio.to_thread(self._zip_dir_sync, src_dir, zip_path)
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
        return {"queued": bool(ok), "zip": os.path.basename(zip_path)}

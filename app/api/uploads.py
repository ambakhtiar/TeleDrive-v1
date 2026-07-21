"""/api — folder scan, queue add (with topic auto-create), browser upload."""
import os
import uuid
import asyncio

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app import config
from app.deps import get_service, require_auth, ScanItem, QueueAddItem, EnsureFolders

router = APIRouter(tags=["uploads"])


@router.post("/scan")
async def scan(item: ScanItem):
    try:
        return await asyncio.to_thread(get_service().scan_path, item.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/queue/add")
async def queue_add(item: QueueAddItem):
    require_auth()
    svc = get_service()
    routing = dict(item.routing)
    try:
        info = {}
        gid = config.active_group_id()
        if routing.get("mode") == "folder" and routing.get("auto_create"):
            scan = await asyncio.to_thread(svc.scan_path, item.path)
            names = [s["name"] for s in scan["subfolders"]]
            res = await svc.create_topics_for_folders(gid, names)
            routing["folder_map"] = res["mapping"]
            routing.setdefault("default_topic", res["mapping"].get("."))
            info = {"topics_created": res["created"], "capped": res["capped"],
                    "max_topics": res["max_topics"]}
        elif routing.get("mode") == "extension" and routing.get("auto_create"):
            scan = await asyncio.to_thread(svc.scan_path, item.path)
            present = {config.category_for("x" + e["ext"]) for e in scan["extensions"]}
            labels = config.CATEGORY_LABELS
            wanted = [labels[t] for t in present]
            res = await svc.create_topics_for_folders(gid, wanted)
            routing["ext_map"] = {t: res["mapping"].get(labels[t]) for t in present}
            info = {"topics_created": res["created"]}
        # enqueue_path walks + hashes every file — keep it off the event loop.
        result = await asyncio.to_thread(svc.enqueue_path, item.path, routing)
        result.update(info)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/topics/ensure_folders")
async def ensure_folders(item: EnsureFolders):
    """Create (or reuse) one topic per folder name; return {name: topic_id}."""
    require_auth()
    try:
        return await get_service().create_topics_for_folders(item.group_id, item.folders)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    topic_id: int = Form(0),
    rel_path: str = Form(""),
    last_modified: float = Form(0),
):
    """Stage ONE browser-uploaded file and queue it. Called once per file so a
    dropped connection never loses a whole batch."""
    require_auth()
    svc = get_service()
    config.ensure_staging()
    rel = (rel_path or file.filename).replace("\\", "/").lstrip("/")
    batch_dir = os.path.join(config.UPLOAD_STAGING_DIR, uuid.uuid4().hex[:12])
    dest = os.path.normpath(os.path.join(batch_dir, rel))
    if not dest.startswith(os.path.normpath(batch_dir)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    # Restore the original file mtime from the browser's File.lastModified
    # so that original_timestamp()'s filesystem fallback returns the real
    # creation date even for file types without EXIF/QuickTime metadata.
    client_ts = None
    if last_modified > 0:
        try:
            client_ts = last_modified / 1000.0
            os.utime(dest, (client_ts, client_ts))
        except Exception:
            pass
    ok = svc.enqueue_staged_file(dest, int(topic_id), batch_dir, client_mtime=client_ts)
    if not ok:
        # Duplicate or bad file — don't leave the copy sitting around.
        try:
            os.remove(dest)
        except OSError:
            pass
    return {"queued": bool(ok), "name": os.path.basename(rel)}

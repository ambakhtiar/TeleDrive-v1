"""FastAPI entrypoint. One process owns the uploader service, the web API,
the WebSocket live feed, and serves the dashboard UI.

Run:  uvicorn main:app --host 0.0.0.0 --port 8000
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, APIRouter, Header, HTTPException, Depends, WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from uploader import UploaderService

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)

service: UploaderService | None = None
STATIC_DIR = os.path.join(config.PROJECT_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = UploaderService()
    await service.start()
    yield
    await service.shutdown()


app = FastAPI(title="Telegram Uploader", lifespan=lifespan)
api = APIRouter()


def verify_pin(x_pin: str = Header(None)):
    if x_pin != config.DASHBOARD_PIN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------- models ----------
class FolderRule(BaseModel):
    name: str
    file_type: str
    topic_id: int


class SettingsItem(BaseModel):
    auto_delete: bool
    turbo_mode: bool
    compress_media: bool
    daily_report: bool


class PhoneItem(BaseModel):
    phone: str


class CodeItem(BaseModel):
    code: str


class PasswordItem(BaseModel):
    password: str


# ---------- auth (Telegram web login) ----------
@api.get("/auth/status")
async def auth_status():
    return {"auth_state": service.auth_state, "me": await service.me()}


@api.post("/auth/send_code")
async def auth_send_code(item: PhoneItem):
    try:
        return await service.send_login_code(item.phone.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/auth/verify_code")
async def auth_verify_code(item: CodeItem):
    from telethon.errors import PhoneCodeInvalidError, PhoneCodeExpiredError

    try:
        return await service.verify_login_code(item.code.strip())
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/auth/verify_password")
async def auth_verify_password(item: PasswordItem):
    from telethon.errors import PasswordHashInvalidError

    try:
        return await service.verify_login_password(item.password)
    except PasswordHashInvalidError:
        raise HTTPException(status_code=400, detail="Wrong 2FA password.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/auth/logout")
async def auth_logout():
    return await service.logout()


# ---------- groups & topics ----------
class GroupSelect(BaseModel):
    group_id: int


class GroupCreate(BaseModel):
    title: str
    enable_topics: bool = True


class TopicCreate(BaseModel):
    group_id: int
    title: str


def _require_auth():
    if service.auth_state != "authorized":
        raise HTTPException(status_code=403, detail="Log in to Telegram first.")


@api.get("/groups")
async def groups():
    _require_auth()
    return await service.list_groups()


@api.post("/groups/create")
async def groups_create(item: GroupCreate):
    _require_auth()
    try:
        return await service.create_group(item.title.strip(), item.enable_topics)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/groups/select")
async def groups_select(item: GroupSelect):
    _require_auth()
    return service.select_group(item.group_id)


@api.get("/groups/{group_id}/topics")
async def group_topics(group_id: int):
    _require_auth()
    try:
        return await service.list_topics(group_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/topics/create")
async def topics_create(item: TopicCreate):
    _require_auth()
    try:
        return await service.create_topic(item.group_id, item.title.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- folder scan / manual queue / browser upload (Phase 3) ----------
import json as _json
import uuid
from typing import List
from fastapi import UploadFile, File, Form


class ScanItem(BaseModel):
    path: str


class QueueAddItem(BaseModel):
    path: str
    routing: dict


@api.post("/scan")
def scan(item: ScanItem):
    try:
        return service.scan_path(item.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/queue/add")
def queue_add(item: QueueAddItem):
    _require_auth()
    try:
        return service.enqueue_path(item.path, item.routing)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/upload")
async def upload(
    files: List[UploadFile] = File(...),
    routing: str = Form(...),
    paths: str = Form("[]"),
):
    _require_auth()
    routing_spec = _json.loads(routing)
    rel_paths = _json.loads(paths)
    batch_dir = os.path.join(config.UPLOAD_STAGING_DIR, uuid.uuid4().hex[:12])
    os.makedirs(batch_dir, exist_ok=True)
    added = 0
    for idx, up in enumerate(files):
        rel = rel_paths[idx] if idx < len(rel_paths) else up.filename
        rel = rel.replace("\\", "/").lstrip("/")
        dest = os.path.normpath(os.path.join(batch_dir, rel))
        if not dest.startswith(os.path.normpath(batch_dir)):
            continue  # path traversal guard
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            while chunk := await up.read(1024 * 1024):
                out.write(chunk)
        rel_root = os.path.dirname(rel)
        topic_id = service._topic_for(os.path.basename(rel), rel_root, routing_spec)
        if topic_id and service.enqueue_staged_file(dest, int(topic_id)):
            added += 1
    return {"added": added, "received": len(files)}


# ---------- endpoints ----------
@api.get("/stats")
def stats():
    return service.snapshot()


@api.get("/history")
def history(query: str = "", limit: int = 20, offset: int = 0):
    return service.db.history(query, limit, offset)


@api.get("/daily_reports")
def daily_reports():
    return service.db.daily_reports()




@api.get("/logs")
def logs():
    return {"logs": "\n".join(service.logs) or "Waiting for logs..."}


@api.post("/action/send_report")
async def send_report():
    ok = await service.send_report(manual=True)
    return {"status": "success" if ok else "failed"}


@api.post("/queue/cancel/{file_hash}")
def queue_cancel(file_hash: str):
    return service.cancel_item(file_hash)


@api.post("/queue/clear")
def queue_clear():
    return service.clear_queue()


@api.post("/queue/retry_failed")
def queue_retry():
    return service.retry_failed()


@api.get("/action/{command}")
def control_bot(command: str):
    if command in ("pause", "resume"):
        return {"status": service.set_status(command)}
    raise HTTPException(status_code=400, detail="Invalid command")


@api.get("/config")
def get_config():
    return config.read_config()


@api.post("/settings")
def update_settings(item: SettingsItem):
    cfg = config.read_config()
    cfg["auto_delete_after_upload"] = item.auto_delete
    cfg["turbo_mode"] = item.turbo_mode
    cfg["compress_media"] = item.compress_media
    cfg["daily_report"] = item.daily_report
    config.write_config(cfg)
    return {"status": "success"}


@api.post("/folders")
def add_folder(item: FolderRule):
    cfg = config.read_config()
    folders = cfg.setdefault("folders", {})
    folders.setdefault(item.name, {})[item.file_type] = item.topic_id
    config.write_config(cfg)
    return {"status": "success"}


@api.delete("/folders/{folder_name:path}")
def delete_folder(folder_name: str):
    cfg = config.read_config()
    if folder_name in cfg.get("folders", {}):
        del cfg["folders"][folder_name]
        config.write_config(cfg)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Not found")


app.include_router(api, prefix="/api", dependencies=[Depends(verify_pin)])


# ---------- websocket (live feed) ----------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    # Auth via query param since browsers can't set headers on WS.
    if websocket.query_params.get("pin") != config.DASHBOARD_PIN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    q = service.subscribe()
    try:
        await websocket.send_json({"type": "snapshot", "data": service.snapshot()})
        while True:
            msg = await q.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(q)


# ---------- CSV export (pin via query param for direct browser download) ----------
@app.get("/export.csv")
def export_csv(pin: str = ""):
    import csv, io
    from fastapi.responses import StreamingResponse

    if pin != config.DASHBOARD_PIN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rows = service.db.history(limit=100000, offset=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["file_name", "uploaded_at", "message_link"])
    for r in rows:
        w.writerow([r["name"], r["time"], r["link"] or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=upload_history.csv"},
    )


# ---------- UI ----------
@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>UI missing</h1>")


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

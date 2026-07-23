"""FastAPI app: wires the uploader service, REST API, WebSocket live feed,
CSV export, and the dashboard/history UI + static files.

Run:  uvicorn main:app --host 0.0.0.0 --port 8000
"""
import os
import csv
import io
import logging
from contextlib import asynccontextmanager

from fastapi import (FastAPI, WebSocket, WebSocketDisconnect, Request, Response,
                     HTTPException, Depends)
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config, deps
from app.deps import require_dashboard
from app.services import UploaderService
from app.api import api_router

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
              logging.StreamHandler()],
)

STATIC_DIR = os.path.join(config.PROJECT_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # NOTE: staging is NOT wiped on startup anymore — browser-uploaded files
    # still pending in the persistent queue must survive a restart so they can
    # resume. They're removed individually on success/cancel.
    service = UploaderService()
    deps.set_service(service)
    await service.start()
    yield
    await service.shutdown()


app = FastAPI(title="Telegram Uploader", lifespan=lifespan)
app.include_router(api_router, dependencies=[Depends(require_dashboard)])


# ---------- optional dashboard login ----------
@app.get("/dashboard-status")
def dashboard_status():
    return {"required": bool(config.DASHBOARD_PASSWORD)}


@app.post("/dashboard-login")
async def dashboard_login(request: Request, response: Response):
    if not config.DASHBOARD_PASSWORD:
        return {"ok": True}
    body = await request.json()
    if body.get("password") == config.DASHBOARD_PASSWORD:
        response.set_cookie("tgb_auth", config.dashboard_token(), httponly=True,
                            samesite="lax", max_age=60 * 60 * 24 * 30)
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Wrong password.")


# ---------- websocket (live feed) ----------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    if config.DASHBOARD_PASSWORD and websocket.cookies.get("tgb_auth") != config.dashboard_token():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    service = deps.get_service()
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


# ---------- CSV export ----------
@app.get("/export.csv", dependencies=[Depends(require_dashboard)])
def export_csv(query: str = "", ext: str = "", date_from: str = "",
               date_to: str = "", sort: str = "desc"):
    rows = deps.get_service().db.history(
        query, limit=1000000, offset=0, ext=ext,
        date_from=date_from, date_to=date_to, sort=sort,
    )
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
def _page(name):
    path = os.path.join(STATIC_DIR, name)
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>UI missing</h1>")


@app.get("/", response_class=HTMLResponse)
def index():
    return _page("index.html")


@app.get("/history", response_class=HTMLResponse)
def history_page():
    return _page("history.html")


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

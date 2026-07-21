"""/api — stats, logs, queue controls, pause/resume, settings, reports."""
from fastapi import APIRouter, HTTPException

from app import config
from app.deps import get_service, SettingsItem

router = APIRouter(tags=["system"])


@router.get("/stats")
def stats():
    return get_service().snapshot()


@router.get("/logs")
def logs():
    return {"logs": "\n".join(get_service().logs) or "Waiting for logs..."}


@router.post("/action/send_report")
async def send_report():
    ok = await get_service().send_report(manual=True)
    return {"status": "success" if ok else "failed"}


@router.post("/action/backup_now")
async def backup_now():
    ok = await get_service().snapshot_db()
    return {"status": "success" if ok else "failed"}


@router.post("/queue/cancel/{file_hash}")
def queue_cancel(file_hash: str):
    return get_service().cancel_item(file_hash)


@router.post("/queue/clear")
def queue_clear():
    return get_service().clear_queue()


@router.post("/queue/retry_failed")
def queue_retry():
    return get_service().retry_failed()


@router.get("/action/{command}")
def control_bot(command: str):
    if command in ("pause", "resume"):
        return {"status": get_service().set_status(command)}
    raise HTTPException(status_code=400, detail="Invalid command")


@router.get("/config")
def get_config():
    return config.read_config()


@router.post("/settings")
def update_settings(item: SettingsItem):
    cfg = config.read_config()
    cfg["auto_delete_after_upload"] = item.auto_delete
    cfg["turbo_mode"] = item.turbo_mode
    cfg["compress_media"] = item.compress_media
    cfg["daily_report"] = item.daily_report
    config.write_config(cfg)
    return {"status": "success"}

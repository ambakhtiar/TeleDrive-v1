"""Shared dependencies for API routers: the service handle, an auth guard,
and the Pydantic request models used across routers."""
from fastapi import HTTPException
from pydantic import BaseModel

# Set once from the app lifespan (app/server.py). Access via get_service() so
# routers always see the live instance rather than a None captured at import.
_service = None


def set_service(svc):
    global _service
    _service = svc


def get_service():
    return _service


def require_auth():
    svc = get_service()
    if svc is None or svc.auth_state != "authorized":
        raise HTTPException(status_code=403, detail="Log in to Telegram first.")


# ---------- request models ----------
class PhoneItem(BaseModel):
    phone: str


class CodeItem(BaseModel):
    code: str


class PasswordItem(BaseModel):
    password: str


class GroupSelect(BaseModel):
    group_id: int


class GroupCreate(BaseModel):
    title: str
    enable_topics: bool = True


class TopicCreate(BaseModel):
    group_id: int
    title: str


class ScanItem(BaseModel):
    path: str


class QueueAddItem(BaseModel):
    path: str
    routing: dict


class EnsureFolders(BaseModel):
    group_id: int
    folders: list[str]


class SettingsItem(BaseModel):
    auto_delete: bool
    turbo_mode: bool
    compress_media: bool
    daily_report: bool

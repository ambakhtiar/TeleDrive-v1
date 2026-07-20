"""/api/auth — Telegram web login (phone → OTP → 2FA) + logout/status."""
from fastapi import APIRouter, HTTPException

from app.deps import get_service, PhoneItem, CodeItem, PasswordItem

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
async def auth_status():
    svc = get_service()
    return {"auth_state": svc.auth_state, "me": await svc.me()}


@router.post("/send_code")
async def auth_send_code(item: PhoneItem):
    try:
        return await get_service().send_login_code(item.phone.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify_code")
async def auth_verify_code(item: CodeItem):
    from telethon.errors import PhoneCodeInvalidError, PhoneCodeExpiredError

    try:
        return await get_service().verify_login_code(item.code.strip())
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify_password")
async def auth_verify_password(item: PasswordItem):
    from telethon.errors import PasswordHashInvalidError

    try:
        return await get_service().verify_login_password(item.password)
    except PasswordHashInvalidError:
        raise HTTPException(status_code=400, detail="Wrong 2FA password.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/logout")
async def auth_logout():
    return await get_service().logout()

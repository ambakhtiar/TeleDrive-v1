"""/api/history + /api/download — browse, search, and restore files."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.deps import get_service

router = APIRouter(tags=["history"])


@router.get("/history")
def history(query: str = "", limit: int = 20, offset: int = 0, ext: str = "",
            date_from: str = "", date_to: str = "", sort: str = "desc"):
    return get_service().db.history(query, limit, offset, ext, date_from, date_to, sort)


@router.get("/history/extensions")
def history_extensions():
    return get_service().db.distinct_extensions()


@router.get("/daily_reports")
def daily_reports():
    return get_service().db.daily_reports()


@router.get("/download/{file_hash}/check")
async def download_precheck(file_hash: str):
    try:
        return await get_service().download_check(file_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download/{file_hash}")
async def download(file_hash: str):
    try:
        file_name, stream = await get_service().download_file(file_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ascii_name = file_name.encode("ascii", "ignore").decode() or "download"
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; "
        f"filename*=UTF-8''{quote(file_name)}"
    )
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )

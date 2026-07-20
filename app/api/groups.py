"""/api/groups + /api/topics — group selection and topic management."""
from fastapi import APIRouter, HTTPException

from app.deps import get_service, require_auth, GroupSelect, GroupCreate, TopicCreate

router = APIRouter(tags=["groups"])


@router.get("/groups")
async def groups():
    require_auth()
    return await get_service().list_groups()


@router.post("/groups/create")
async def groups_create(item: GroupCreate):
    require_auth()
    try:
        return await get_service().create_group(item.title.strip(), item.enable_topics)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/groups/select")
async def groups_select(item: GroupSelect):
    require_auth()
    return get_service().select_group(item.group_id)


@router.get("/groups/{group_id}/topics")
async def group_topics(group_id: int):
    require_auth()
    try:
        return await get_service().list_topics(group_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/topics/create")
async def topics_create(item: TopicCreate):
    require_auth()
    try:
        return await get_service().create_topic(item.group_id, item.title.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

"""Aggregate all feature routers into one /api router."""
from fastapi import APIRouter

from app.api import auth, groups, uploads, history, system

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(groups.router)
api_router.include_router(uploads.router)
api_router.include_router(history.router)
api_router.include_router(system.router)

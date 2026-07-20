"""Entry point kept at the repo root so existing commands and configs
(`uvicorn main:app`, Dockerfile, fly.toml) keep working unchanged.

The real application lives in the ``app`` package:
  app/config.py    — settings & paths
  app/db.py        — SQLite persistence
  app/services/    — UploaderService, split by feature
  app/api/         — REST routers, one module per feature
  app/server.py    — FastAPI app, WebSocket, UI
"""
from app.server import app

__all__ = ["app"]

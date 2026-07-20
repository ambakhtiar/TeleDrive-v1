"""Telegram Uploader application package.

Layout:
  app/config.py          — settings, paths, file-type categories
  app/db.py              — SQLite persistence + hashing helpers
  app/services/          — the UploaderService, split by feature (mixins)
  app/api/               — FastAPI routers, one module per feature area
  app/server.py          — app factory, lifespan, WebSocket, UI + static
"""

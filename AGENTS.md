# Telegram Uploader — repo guide

## Stack

Python 3.10+ · FastAPI · Uvicorn · Telethon · SQLite · vanilla HTML/JS/CSS (no frontend framework)

## Entry point

`main.py` → `app.server:app` (uvicorn target, Docker CMD, Fly.io all use this).

## Commands

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Optional speedup: `pip install cryptg` (needs Rust + MSVC Build Tools).

## Architecture

- **`app/services/`** — `UploaderService` assembled from 8 mixins via multiple inheritance (`services/__init__.py`). Feature modules: `auth`, `groups`, `scanning`, `uploading`, `downloading`, `reports`, `maintenance`, `base`.
- **`app/api/`** — FastAPI routers under `/api` prefix, aggregated in `api/__init__.py`.
- **`app/server.py`** — app factory + lifespan (starts service, cleans staging dir). Routes: `/ws` (WebSocket live feed), `/export.csv`, `/` (dashboard), `/history`.
- **`app/config.py`** — paths, `.env` loading, file-type categories, `config.json` read/write.
- **`app/db.py`** — SQLite with additive schema migrations (safe on every startup).
- **`app/deps.py`** — global service handle (`set_service`/`get_service`), `require_auth()` guard, Pydantic models.

## Config split

- **`.env`** (gitignored) — deployer credentials only: `API_ID`, `API_HASH`. Copied from `.env.example`.
- **`config.json`** (gitignored, at `DATA_DIR/config.json`) — mutable user settings written by the dashboard: `auto_delete`, `turbo_mode`, `compress_media`, `daily_report`, `group_id`, `folders`.

## Key gotchas

- Telethon forbids reusing a `TelegramClient` after `log_out()`. The service rebuilds it via `_fresh_client()`.
- `DATA_DIR` defaults to project root locally, `/data` on Fly/Docker with the mounted volume.
- No test framework, no linter, no typechecker config found in the repo.
- Frontend is two vanilla HTML files in `static/` — no build step, no bundler. **Never use TailwindCSS**.
- `BrainSync` files (`.brainsync/`, `.cursor/`, `AGENT.md`, `CLAUDE.md`, `.windsurfrules`, etc.) are gitignored — ignore them.
- Schema migrations are additive-only (`ALTER TABLE ADD COLUMN` with try/except). Never drop or rename columns.
- WebSocket `/ws` uses an async-queue pub/sub: sends a snapshot on connect, then streams events.
- Deployment: `Dockerfile` + `fly.toml` for Fly.io, `uvicorn` for local, Termux for Android.

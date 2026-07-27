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

- **`app/services/`** — `UploaderService` assembled from 9 mixins + base via multiple inheritance (`services/__init__.py`). Feature modules: `auth`, `groups`, `scanning`, `uploading`, `downloading`, `reports`, `maintenance`, `backup`, `zipping`, `helpers`, `base`.
- **`app/api/`** — FastAPI routers under `/api` prefix, aggregated in `api/__init__.py`.
- **`app/server.py`** — app factory + lifespan (starts service). Routes: `/ws` (WebSocket live feed), `/export.csv`, `/` (dashboard), `/history`.
- **`app/config.py`** — paths, `.env` loading, file-type categories, `config.json` read/write.
- **`app/db.py`** — SQLite with additive schema migrations (safe on every startup).
- **`app/deps.py`** — global service handle (`set_service`/`get_service`), `require_dashboard()` (password gate), `require_auth()` (Telegram login), Pydantic models.

## Config split

- **`.env`** (gitignored) — deployer credentials + overrides: `API_ID`, `API_HASH`, `DASHBOARD_PASSWORD`, `DATA_DIR`, `SCAN_ROOT`, `MAX_CONCURRENT_UPLOADS`, `CHUNK_SIZE`, etc. Copy from `.env.example`.
- **`config.json`** (gitignored, at `DATA_DIR/config.json`) — mutable user settings written by the dashboard: `auto_delete`, `turbo_mode`, `compress_media`, `daily_report`, `group_id`, `folders`.

## Key gotchas

- Telethon forbids reusing a `TelegramClient` after `log_out()`. The service rebuilds it via `_fresh_client()`.
- Dedup identity = **md5(basename + size + mtime)**, not content hash. SHA-256 is computed separately for integrity (`db.py:generate_file_hash` vs `file_sha256`).
- Session file is encrypted at rest via Fernet (`cryptography` package). Falls back to plain session file if absent (`config.py:fernet`).
- Upload queue is persisted in SQLite (`queue` table) — survives restarts so in-flight files resume.
- Browser uploads go to `uploads_staging/` then are deleted on success. Local-path uploads read files in place.
- `DATA_DIR` defaults to project root locally, `/data` on Fly/Docker (mounted volume).
- Two auth guards in `deps.py`: `require_dashboard()` (gated by `DASHBOARD_PASSWORD` env var) and `require_auth()` (Telegram logged-in check).
- No test framework, no linter, no typechecker config found.
- Frontend is two vanilla HTML files in `static/` — no build step, no bundler. **Never use TailwindCSS**.
- Agent rule files (`.brainsync/`, `.cursor/`, `AGENT.md`, `CLAUDE.md`, `.windsurfrules`, etc.) are gitignored — ignore them.
- Schema migrations are additive-only (`ALTER TABLE ADD COLUMN` with try/except). Never drop or rename columns.
- WebSocket `/ws` uses an async-queue pub/sub: sends a snapshot on connect, then streams events.
- Deployment: `Dockerfile` + `fly.toml` for Fly.io, `uvicorn` for local, Termux for Android (see `android/setup-termux.sh`).
- Desktop launcher at `desktop/launcher.py` — first-run web setup wizard, programmatic uvicorn, Tkinter status window. Bundled via `desktop/launcher.spec` (PyInstaller). CI in `.github/workflows/build-desktop.yml`.

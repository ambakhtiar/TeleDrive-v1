# ✈️ Telegram Uploader

A self-hosted web app that uploads your files to a Telegram group — organized into **Topics** automatically, with live progress, smart routing, and a clean web dashboard. Point it at a folder (or drag files from your device), pick how you want them sorted, and it takes care of the rest: hashing to skip duplicates, retrying failures, and reporting daily upload stats straight to Telegram.

No terminal login, no manual topic-ID lookups — everything is driven from the browser.

---

## ✨ Features

**Telegram connection**
- Web-based login: phone number → OTP → 2FA password (if enabled). No interactive terminal session needed.
- Session persists on the server; reconnect/disconnect from the dashboard anytime.

**Groups & Topics**
- Create a brand-new Telegram group (Topics auto-enabled) or select one you already own/administer — only groups where you have admin rights are shown.
- Create and list topics from the UI; no need to look up topic IDs by hand.

**Adding files**
- **Local path scan** — type a folder path on the server/device; it recursively scans nested folders and previews file counts, sizes, and extensions before queuing.
- **Upload from device** — pick files, pick a whole folder, or drag-and-drop straight into the browser (works from a phone or a different machine than the server).

**Smart routing — three modes**
| Mode | Behavior |
|---|---|
| **Single topic** | Everything goes to one topic (or General). |
| **By file type** *(recommended)* | Sorts into 8 auto-created/reused topics: 🖼️ Images, 🎬 Videos, 🎵 Audios, 📄 Documents, 💻 Coding, 🗜️ Compressed, ⚙️ Programme, 📦 Others. |
| **By folder name** | Each subfolder gets its own topic, auto-created and reused on repeat runs (capped at 30 topics per group, with a warning if exceeded). |

**Uploading**
- Parallel ("Turbo") uploads, or one-at-a-time — your choice.
- Live per-file progress: percentage, speed, bytes transferred, and **estimated time remaining**.
- Cancel an individual in-flight file, clear the whole queue, or retry everything that failed — all without restarting the app.
- Automatic de-duplication — a file already uploaded (by content hash) is never sent twice.
- Optional auto-delete of local files after a successful upload.
- Optional media compression (trade quality for upload speed).

**Monitoring & history**
- Live console — tail the server log directly in the browser (WebSocket-powered, no polling/refresh).
- Dedicated **History** page: search by name, filter by extension or date range, sort newest/oldest, infinite-scroll pagination, and CSV export of exactly what you're viewing.
- Daily automatic report to your Telegram group (upload count for the day) — or trigger one manually.

---

## 📋 Requirements

- **Python 3.10+** (3.11 recommended)
- A **Telegram account** and API credentials (free — see below)
- A **Telegram group you own or administer** (the app will offer to create one for you if you don't have one yet)
- pip packages — all pinned in [requirements.txt](requirements.txt): FastAPI, Uvicorn, Telethon, python-dotenv, Pydantic, python-multipart, Pillow

---

## 🔑 Get your Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.
2. Click **API development tools**.
3. Fill in an app title and short name, then **Create application**.
4. Copy the **App api_id** and **App api_hash** — you'll need these next.

---

## 🛠️ Installation

Pick the section that matches where you're running this.

### Option A — Termux (Android phone)

> **Docker will not run in Termux.** Android doesn't expose the kernel features (cgroups/namespaces) Docker needs, even with root in most cases. On a phone, always run the app directly with Python as shown below — Docker is only for Option C (a real computer/server).

```bash
pkg update && pkg upgrade -y
pkg install python git -y

# Let Termux access your phone's shared storage (needed for local-path scanning)
termux-setup-storage

git clone <your-repo-url>
cd tgb

pip install -r requirements.txt
```

### Option B — Windows / macOS / Linux (direct Python)

```bash
# Install Python 3.10+ first: https://www.python.org/downloads/
git clone <your-repo-url>
cd tgb

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### Option C — Docker (desktop machines & servers only)

Use this on a PC, Mac, or a real Linux server/VPS — **not** on Termux/Android.

```bash
docker build -t telegram-uploader .
docker run -d --name tgb -p 8000:8000 \
  -e API_ID=xxxxxxx -e API_HASH=xxxxxxxxxxxxxxxx \
  -v tgb_data:/data \
  telegram-uploader
```
The `-v tgb_data:/data` volume keeps your database and Telegram session across container restarts — without it, you'd have to log in again every time the container recreates.

---

## ⚙️ Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here

# Optional — you can also create/select a group from the web UI instead
GROUP_ID=-100xxxxxxxxxx
```

Everything else (routing rules, turbo mode, auto-delete, etc.) is configured later from the dashboard and saved automatically — there's nothing else to hand-edit.

---

## 🚀 Running

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — or, from another device on the same network, `http://<this-machine's-IP>:8000`.

> ⚠️ **No dashboard login.** The web UI has no access control — anyone who can reach the URL has full control of the connected Telegram account. This is fine on `localhost` or a private LAN. **Do not expose this port to the public internet** without adding your own protection in front of it (reverse-proxy basic auth, VPN, Cloudflare Access, etc.).

---

## 🎮 First-time setup walkthrough

1. **Connect Telegram** — the dashboard opens straight to a "Connect Telegram" prompt. Enter your phone number, then the OTP code Telegram sends you, then your 2FA password if you have one enabled. This only happens once; the session is saved on the server.
2. **🎯 Group & Topics (Setup button)** — either:
   - **Create a new group** (Topics are enabled automatically), or
   - **Select an existing group** from the list — only groups where you're the **owner or an admin** are shown.
   - Create or browse topics right there; no manual ID lookups.
3. **📥 Add Files / Folder:**
   - **Local Path** tab — type a path, hit **Scan** to preview what's inside, then choose a routing mode.
   - **Upload from Device** tab — pick files, pick a folder, or drag-and-drop.
   - Choose routing: **single topic**, **by file type** (8 categories, auto-created), or **by folder name** (one topic per subfolder, auto-created).
   - Click **Add to Queue** — it queues in the background and drops you straight back to the dashboard; you don't wait around.
4. Watch uploads live: percentage, speed, size, and time remaining per file. Cancel, clear the queue, or retry failures as needed.
5. **🔍 Full History** — its own page with search, extension/date filters, newest/oldest sort, infinite scroll, and filtered CSV export.
6. **🚪 Logout** (top-right, once connected) disconnects the Telegram session on the server — useful for switching accounts.

---

## ☁️ Cloud deployment (Fly.io)

The repo includes a ready-to-use `Dockerfile` and `fly.toml`.

> This app is currently **single-user-per-deployment**: whoever is logged in controls that deployment's Telegram account. If a friend wants to use it too, they deploy their **own** copy with their **own** API credentials — don't share one deployment.

```bash
fly auth login

fly launch --no-deploy          # pick a unique app name when prompted

fly volumes create tgb_data --size 1 --region sin    # persists DB + session

fly secrets set API_ID=xxxx API_HASH=xxxx

fly deploy
```

Fly gives you a public HTTPS URL. On cloud, use the **Upload from Device** tab — the server has no access to your phone's local storage, so "Local Path" scanning only makes sense when self-hosting on the same device your files live on.

Because there's no dashboard login (see the warning above), treat the deployed URL as sensitive, or put your own auth layer in front of it before making it public.

---

## 🤝 Sharing this project with someone else

Send them the **code only** — never these files (all already excluded via `.gitignore`, so a normal `git clone` or `git push` to GitHub is safe by default):

| File | Why it's excluded |
|---|---|
| `.env` | Your API credentials |
| `backup_session.session` | Your **live Telegram login** — equivalent to a password, never share |
| `uploads.db` | Your personal upload history |
| `uploader.log` | Your activity log |

Your friend clones the repo, gets their **own** free API credentials from [my.telegram.org](https://my.telegram.org), creates their own `.env`, and runs their own instance — completely separate from yours, with their own database and Telegram session.

---

## 🧱 Project layout

| File | Responsibility |
|---|---|
| [main.py](main.py) | FastAPI app — REST endpoints, `/ws` WebSocket live feed, serves the UI |
| [uploader.py](uploader.py) | Telethon client, login flow, group/topic management, async scan/upload workers |
| [database.py](database.py) | SQLite-backed upload history, dedup, and history/search queries |
| [config.py](config.py) | Paths, env settings, `config.json` persistence, file-category rules |
| [static/index.html](static/index.html) | Dashboard UI |
| [static/history.html](static/history.html) | Upload history page |

---

## 🩹 Troubleshooting

- **"TelegramClient instance cannot be reused after logging out"** — fixed in current code (the client rebuilds itself automatically). If you still see this, restart the app once to pick up the latest code.
- **Uploads are slow** — install `cryptg` for a large speed boost (`pip install cryptg`); it needs Rust + a C compiler (MSVC Build Tools on Windows) to build, which is why it's commented out by default in `requirements.txt`.
- **Dashboard stuck on "Connecting…"** — usually a stale browser cache after an update; hard-refresh (Ctrl+F5).

---

## 📝 License

For personal and educational use. Use responsibly, and respect Telegram's Terms of Service.

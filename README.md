# 🚀 Telegram Smart Auto-Uploader

A powerful, fully automated, and secure background bot that syncs your local device files to Telegram Topics. It comes with a beautiful Web Dashboard for easy control and monitoring!

---

## ✨ Features

- **🌐 Web Control Panel:** Manage everything from a beautiful, responsive web dashboard.
- **🗂️ Smart Routing:** Automatically send Images to one topic and Videos to another topic from the same folder.
- **🗑️ Auto-Delete (Danger Zone):** Automatically delete files from local storage after a successful upload to save phone memory.
- **🖥️ Live Console:** Watch live terminal logs directly from your browser.
- **🔍 Full History & Search:** Infinite scroll history with instant search functionality.
- **🔒 Secure Access:** PIN-protected dashboard to ensure privacy on your network.

---

## ⚙️ How to Get Telegram API ID & Hash

Before starting, you need your API credentials from Telegram:
1. Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.
2. Click on **"API development tools"**.
3. Fill in the basic details (App title, short name) and click **"Create application"**.
4. Save your **App api_id** and **App api_hash** safely.

---

## 🛠️ Installation & Setup (Termux / Android)

### Step 1: Install Prerequisites
Open Termux and run the following commands:
```bash
pkg update && pkg upgrade -y
pkg install python git rust binutils clang make libffi openssl -y

```
### Step 2: Clone the Repository
```bash
git clone [https://github.com/ambakhtiar/Telegram-File-Uploading-Bot](https://github.com/ambakhtiar/Telegram-File-Uploading-Bot)
cd Telegram-File-Uploading-Bot

```
### Step 3: Install Required Python Packages
```bash
pip install -r requirements.txt
```

### Step 4: Configure the Environment
Copy the example and fill in your credentials:
```bash
cp .env.example .env && nano .env
```
```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
GROUP_ID=-100xxxxxxxxxx    # optional — you can create/select a group in the web UI
DASHBOARD_PIN=1234
```

## 🚀 Running (single process now)
The old two-process design (`bot.py` + `api.py`) has been unified into **one** app:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` (or your device IP, e.g. `http://192.168.0.x:8000`).

## 🎮 How to Use
1. Open the dashboard — it loads directly (no PIN). ⚠️ There is **no access control**, so only run this on a trusted machine/LAN. Do not expose it to the public internet without adding your own protection (reverse-proxy auth, VPN, etc.).
2. **Connect Telegram** — enter your phone → the OTP Telegram sends → your 2FA password (if enabled). The login stays on your server.
3. **🎯 Group Setup** — create a brand-new group (Topics auto-enabled) or select an existing one, then create/list topics and copy their IDs.
4. **📥 Add Files / Folder:**
   - *Local Path* — type a folder path, **Scan** it (nested folders + type breakdown), then choose routing.
   - *Upload from Device* — pick files or a whole folder, or drag & drop; they stream to the server.
   - **Routing:** send everything to one topic, split **by file type** (images/videos/other), or route **by subfolder name**.
5. Watch per-file progress, **cancel** items, **clear** the queue, and **retry** failures live.

## ☁️ Deploy to Fly.io (free, public)
> ⚠️ This is **single-user-per-deployment**: whoever logs in controls that deployment's Telegram session. Each person should deploy their own copy.

```bash
# 1. Install flyctl and sign in
fly auth login

# 2. Launch (uses the included fly.toml + Dockerfile; pick a unique app name)
fly launch --no-deploy

# 3. Create the persistent volume (keeps DB + Telegram session across restarts)
fly volumes create tgb_data --size 1 --region sin

# 4. Set secrets (never commit these)
fly secrets set API_ID=xxxx API_HASH=xxxx DASHBOARD_PIN=your_pin

# 5. Deploy
fly deploy
```
For always-on background folder scanning, set `min_machines_running = 1` in `fly.toml`.
On cloud, use **Upload from Device** (the server has no access to your phone's storage).

## 🧱 Architecture
- **[main.py](main.py)** — FastAPI app: REST API, `/ws` WebSocket live feed, serves the UI.
- **[uploader.py](uploader.py)** — owns the Telethon client + async scan/upload workers + in-memory state.
- **[database.py](database.py)** — SQLite history/dedup. **[config.py](config.py)** — paths & settings.
- **[static/index.html](static/index.html)** — the dashboard.

## 📝 License
This project is for personal use and educational purposes. Use it responsibly.




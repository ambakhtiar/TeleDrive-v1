"""TeleDrive desktop launcher — starts the server, opens the browser,
and shows a status window with a Stop button.

First-run (no .env): starts a mini HTTP server that serves a setup page
in the browser. User enters API_ID/API_HASH/DASHBOARD_PASSWORD, the page
writes .env, then the real server starts.

Works both as `python desktop/launcher.py` and as a PyInstaller bundle.
"""
import io
import json
import os
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from urllib.request import urlopen
import webbrowser


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def project_root():
    """Repo root. In a PyInstaller bundle, this is sys._MEIPASS (where
    main.py, app/, static/ and .env.example get extracted)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROJECT = project_root()
ENV_FILE = os.path.join(PROJECT, ".env")
ENV_EXAMPLE = os.path.join(PROJECT, ".env.example")
PORT = 8000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def port_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def find_free_port(start=8000):
    while not port_free(start):
        start += 1
        if start > 9000:
            raise RuntimeError("No free port found in range 8000-9000")
    return start


def env_ready():
    """True when .env exists and API_ID has a non-empty integer."""
    if not os.path.isfile(ENV_FILE):
        return False
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("API_ID="):
                    val = line.split("=", 1)[1].strip()
                    return bool(val) and val != "0"
    except Exception:
        return False
    return False


def wait_for_server(port, timeout=20):
    url = f"http://127.0.0.1:{port}/dashboard-status"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urlopen(url, timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Mini setup server (first-run wizard)
# ---------------------------------------------------------------------------

SETUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TeleDrive - Setup</title>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:#f5f5f7; display:flex; justify-content:center;
         align-items:center; min-height:100vh; padding:20px; }
  .card { background:#fff; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.08);
          padding:40px; max-width:460px; width:100%; }
  h1 { font-size:24px; margin-bottom:4px; }
  p { color:#555; font-size:14px; margin-bottom:24px; }
  label { display:block; font-size:13px; font-weight:600; margin:12px 0 4px; color:#333; }
  input { width:100%; padding:10px 12px; border:1px solid #d1d1d6; border-radius:8px;
          font-size:15px; outline:none; transition:border-color .2s; }
  input:focus { border-color:#007aff; }
  .hint { font-size:12px; color:#888; margin-top:3px; }
  button { width:100%; padding:12px; background:#007aff; color:#fff; border:none;
           border-radius:8px; font-size:16px; font-weight:600; cursor:pointer;
           margin-top:20px; transition:background .2s; }
  button:hover { background:#005bbf; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .msg { margin-top:16px; padding:12px; border-radius:8px; display:none; }
  .msg.ok { background:#d4edda; color:#155724; display:block; }
  .msg.err { background:#f8d7da; color:#721c24; display:block; }
</style>
</head>
<body>
<div class="card">
  <h1>TeleDrive</h1>
  <p>Enter your Telegram API credentials to get started.</p>
  <p style="font-size:12px;color:#888;margin-bottom:20px">
    Don't have them?
    <a href="https://my.telegram.org" target="_blank">Get API credentials</a>
  </p>
  <form id="form">
    <label for="api_id">API ID</label>
    <input id="api_id" name="api_id" type="text" inputmode="numeric" required placeholder="1234567">
    <label for="api_hash">API Hash</label>
    <input id="api_hash" name="api_hash" type="text" required placeholder="1a2b3c4d5e6f7g8h9i0j...">
    <label for="password">Dashboard Password (optional)</label>
    <input id="password" name="password" type="text" placeholder="Leave empty for no password">
    <div class="hint">Set a password if you want to access the dashboard from another device.</div>
    <button id="btn" type="submit">Save &amp; Start</button>
  </form>
  <div id="msg" class="msg"></div>
</div>
<script>
const form = document.getElementById('form');
const btn = document.getElementById('btn');
const msg = document.getElementById('msg');
form.addEventListener('submit', async e => {
  e.preventDefault();
  btn.disabled = true;
  msg.className = 'msg';
  msg.style.display = 'none';
  try {
    const r = await fetch('/setup', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        api_id: document.getElementById('api_id').value.trim(),
        api_hash: document.getElementById('api_hash').value.trim(),
        password: document.getElementById('password').value.trim(),
      }),
    });
    const data = await r.json();
    if (data.ok) {
      msg.className = 'msg ok';
      msg.textContent = 'Saved! Starting server...';
      setTimeout(() => { window.location.href = '/done'; }, 1200);
    } else {
      throw new Error(data.error || 'Save failed');
    }
  } catch (err) {
    msg.className = 'msg err';
    msg.textContent = err.message || 'Connection lost - close and retry.';
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>"""


def start_setup_server(port):
    """Run a miniature WSGI server that serves the setup page
    and writes .env on POST /setup."""

    def _read_body(environ):
        length = int(environ.get("CONTENT_LENGTH", "0"))
        if length == 0:
            return b""
        return environ["wsgi.input"].read(length)

    def _app(environ, start_response):
        method = environ["REQUEST_METHOD"]
        path = environ["PATH_INFO"]

        if method == "GET" and path == "/":
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [SETUP_HTML.encode("utf-8")]

        if method == "POST" and path == "/setup":
            try:
                body = json.loads(_read_body(environ))
                api_id = body.get("api_id", "").strip()
                api_hash = body.get("api_hash", "").strip()
                password = body.get("password", "").strip()

                if not api_id or not api_hash:
                    resp = json.dumps({"ok": False, "error": "API ID and API Hash are required."})
                    start_response("400 Bad Request", [("Content-Type", "application/json")])
                    return [resp.encode("utf-8")]

                with open(ENV_FILE, "w") as f:
                    f.write(f"API_ID={api_id}\nAPI_HASH={api_hash}\n")
                    if password:
                        f.write(f"DASHBOARD_PASSWORD={password}\n")

                start_response("200 OK", [("Content-Type", "application/json")])
                return [json.dumps({"ok": True}).encode("utf-8")]
            except Exception as exc:
                start_response("500 Internal Server Error", [("Content-Type", "application/json")])
                return [json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")]

        if method == "GET" and path == "/done":
            start_response("200 OK", [("Content-Type", "text/html")])
            return [b"<html><body><p>Setup complete. You can close this tab.</p></body></html>"]

        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"404"]

    from wsgiref.simple_server import make_server
    server = make_server("127.0.0.1", port, _app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

_uvicorn_server = None


def start_uvicorn(port):
    global _uvicorn_server
    from uvicorn import Config, Server

    config = Config(
        "main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        log_level="info",
        workers=1,
    )
    _uvicorn_server = Server(config)

    thread = threading.Thread(target=_uvicorn_server.run, daemon=True)
    thread.start()
    return _uvicorn_server


def stop_uvicorn():
    global _uvicorn_server
    if _uvicorn_server:
        _uvicorn_server.should_exit = True
        _uvicorn_server = None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # ---- Phase 1: setup wizard if needed ----
    if not env_ready():
        # Copy .env.example if it exists and .env doesn't
        if not os.path.isfile(ENV_FILE) and os.path.isfile(ENV_EXAMPLE):
            import shutil
            shutil.copy2(ENV_EXAMPLE, ENV_FILE)

        setup_port = find_free_port(9000)
        server = start_setup_server(setup_port)
        url = f"http://127.0.0.1:{setup_port}"
        webbrowser.open(url)

        # Wait for user to complete setup
        while not env_ready():
            time.sleep(0.5)

        server.shutdown()

    # ---- Phase 2: start the real server ----
    uvicorn_port = PORT if port_free(PORT) else find_free_port(PORT + 1)

    try:
        start_uvicorn(uvicorn_port)
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("TeleDrive", f"Failed to start server:\n{exc}")
        return 1

    if not wait_for_server(uvicorn_port):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "TeleDrive",
            "Server failed to start. Check if the port is in use or another instance is running.",
        )
        stop_uvicorn()
        return 1

    url = f"http://127.0.0.1:{uvicorn_port}"
    webbrowser.open(url)

    # ---- Phase 3: persistent status window ----
    root = tk.Tk()
    root.title("TeleDrive")
    root.geometry("360x150")
    root.resizable(False, False)

    tk.Label(root, text="TeleDrive is running", font=("", 14, "bold")).pack(pady=(14, 2))
    link = tk.Label(root, text=url, fg="#007aff", cursor="hand2", font=("", 11))
    link.pack()

    def open_browser():
        webbrowser.open(url)

    link.bind("<Button-1>", lambda e: open_browser())

    def stop_and_exit():
        stop_uvicorn()
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)
    tk.Button(btn_frame, text="Open Browser", command=open_browser, width=14).pack(
        side=tk.LEFT, padx=4
    )
    tk.Button(
        btn_frame, text="Stop Server", command=stop_and_exit, width=14,
        bg="#ff3b30", fg="white",
    ).pack(side=tk.LEFT, padx=4)

    root.protocol("WM_DELETE_WINDOW", stop_and_exit)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

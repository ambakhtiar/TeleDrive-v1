#!/data/data/com.termux/files/usr/bin/bash
# TeleDrive-v1 — one-time Termux setup.
# Run this ONCE. After this, tap the "TeleDrive" home-screen widget to launch.
#
# Requires these apps installed first (all from F-Droid, NOT Play Store):
#   - Termux
#   - Termux:API
#   - Termux:Widget

set -e

REPO_URL="https://github.com/ambakhtiar/TeleDrive-v1"
REPO_DIR="$HOME/TeleDrive-v1"

echo "== TeleDrive-v1: Termux setup starting =="

echo "[1/6] Updating packages..."
pkg update -y && pkg upgrade -y

echo "[2/6] Installing git, python, termux-api, and build tools..."
pkg install -y git python termux-api clang rust binutils make pkg-config libffi openssl

echo "[3/6] Granting phone storage access (for scanning DCIM etc.)..."
termux-setup-storage || true
sleep 2

echo "[4/6] Fetching source code..."
if [ -d "$REPO_DIR" ]; then
  echo "Already exists — updating..."
  cd "$REPO_DIR" && git pull
else
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
fi

echo "[5/6] Installing Python libraries..."

# Install pre-compiled native packages via pkg first (avoids pip compile failures).
pkg install -y python-cryptography python-pillow

# Set Android API level so Rust/maturin packages (pydantic-core, etc.)
# compile for the correct target instead of failing.
ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
export ANDROID_API_LEVEL
echo "ANDROID_API_LEVEL=$ANDROID_API_LEVEL"

# Allow pip to install system-wide (PEP 668 guard on newer Termux Python).
export PIP_BREAK_SYSTEM_PACKAGES=1

# Termux's `python` package tracks upstream closely and can outrun what
# pydantic-core's Rust build tool (PyO3) supports — e.g. Termux shipping
# Python 3.14 while PyO3 0.24.x only builds against up to 3.13, failing with
# "the configured Python interpreter version (3.14) is newer than PyO3's
# maximum supported version". Unlike Homebrew, Termux has no easy "install
# an older Python" formula, so use the escape hatch PyO3's own error message
# recommends: build against the stable limited ABI instead of the exact
# interpreter version. Safe for pydantic-core specifically (it's built with
# abi3 support).
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

# Upgrade build tools first.
python -m pip install --upgrade pip setuptools wheel

# Use plain uvicorn (NOT uvicorn[standard]) — uvloop/httptools have no Android
# wheels and will fail to compile. cryptg is also omitted; its native speedup
# rarely works on ARM without heavy toolchain hacks.
PY_PKGS="fastapi==0.111.0 uvicorn==0.30.1 telethon==1.36.0 python-dotenv==1.0.1 pydantic==2.11.7 python-multipart==0.0.9 cryptography==43.0.1"

if ! python -m pip install --no-cache-dir $PY_PKGS; then
  echo ""
  echo "Some packages failed to compile. Retrying with full build toolchain..."
  # clang / rust / binutils already installed above — this is a safety net.
  python -m pip install --no-cache-dir $PY_PKGS
fi

echo "[6/6] Creating home-screen shortcuts..."
mkdir -p "$HOME/.shortcuts"

cat > "$HOME/.shortcuts/TeleDrive" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/TeleDrive-v1"
termux-wake-lock
if ! pgrep -f "uvicorn main:app" > /dev/null; then
  nohup uvicorn main:app --host 127.0.0.1 --port 8000 > "$HOME/TeleDrive-v1/uvicorn.out" 2>&1 &
  sleep 3
fi
termux-open-url http://127.0.0.1:8000
EOF
chmod +x "$HOME/.shortcuts/TeleDrive"

cat > "$HOME/.shortcuts/TeleDrive-Stop" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
pkill -f "uvicorn main:app" || true
termux-wake-unlock
termux-toast "TeleDrive stopped"
EOF
chmod +x "$HOME/.shortcuts/TeleDrive-Stop"

cd "$REPO_DIR"
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "WARNING: .env file has been created but is still empty."
  echo "  Run:  nano $HOME/TeleDrive-v1/.env"
  echo "  Fill in API_ID, API_HASH, and DASHBOARD_PASSWORD."
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "What to do next:"
echo "  1) Edit .env with your API_ID/API_HASH/DASHBOARD_PASSWORD"
echo "  2) Long-press your home screen -> Widgets -> Termux:Widget"
echo "  3) Choose the 'TeleDrive' shortcut"
echo "  4) Tap the widget icon to start the server and open the dashboard"

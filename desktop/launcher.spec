# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TeleDrive desktop launcher.

Build (from repo root):
    pyinstaller desktop/launcher.spec

Output in dist/TeleDrive/ (--onedir) or dist/TeleDrive.exe (--onefile).
"""
import os

# PyInstaller provides SPECPATH (the directory containing this .spec file)
# so we derive the repo root as its parent.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

# -- Mode --------------------------------------------------------------------
# onefile  = single executable (slower startup, portable)
# onedir   = folder with deps (faster startup, slightly less portable)
MODE = "onedir"

# -- Data files (bundled alongside the frozen app) ---------------------------
DATAS = [
    (os.path.join(ROOT, "main.py"), "."),
    (os.path.join(ROOT, ".env.example"), "."),
    (os.path.join(ROOT, "app"), "app"),
    (os.path.join(ROOT, "static"), "static"),
]

# -- Hidden imports (packages discovered dynamically or imported via string) --
HIDDEN = [
    # FastAPI / Starlette
    "fastapi",
    "fastapi.responses",
    "fastapi.staticfiles",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "starlette",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.middleware.trustedhost",
    "starlette.datastructures",
    "starlette.responses",
    "starlette.requests",
    "starlette.background",
    "starlette.staticfiles",
    # Uvicorn (imported programmatically from launcher.py)
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.middleware",
    "uvicorn.middleware.wsgi",
    "uvicorn.workers",
    # Pydantic v2 (Rust core)
    "pydantic",
    "pydantic_core",
    "pydantic.color",
    "pydantic.types",
    "pydantic.dataclasses",
    "pydantic.deprecated.json",
    "pydantic.json",
    # Telethon
    "telethon",
    "telethon.client",
    "telethon.network",
    "telethon.crypto",
    "telethon.tl",
    "telethon.tl.functions",
    "telethon.tl.types",
    "telethon.extensions",
    "telethon.sessions",
    "telethon.sync",
    # Cryptography (native extensions)
    "cryptography",
    "cryptography.hazmat",
    "cryptography.hazmat.backends",
    "cryptography.hazmat.primitives",
    "cryptography.fernet",
    "cryptography.x509",
    # Pillow (image processing)
    "PIL",
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.GifImagePlugin",
    "PIL.WebPImagePlugin",
    "PIL.BmpImagePlugin",
    "PIL.TiffImagePlugin",
    "PIL.IcoImagePlugin",
    "PIL.ExifTags",
    "PIL.Image",
    "PIL.ImageFile",
    # python-dotenv
    "dotenv",
    "dotenv.parser",
    # python-multipart
    "multipart",
    "multipart.multipart",
]

# -- Exclusions (reduce bundle size) -----------------------------------------
EXCLUDES = [
    "tkinter.test",
    "unittest",
    "test",
    "distutils",
    "setuptools",
    "pip",
    "pdb",
    "py_compile",
    "doctest",
]

# -- Build -------------------------------------------------------------------
a = Analysis(
    [os.path.join(ROOT, "desktop", "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TeleDrive",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

if MODE == "onedir":
    COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="TeleDrive",
    )

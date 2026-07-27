# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TeleDrive desktop launcher.

Build (from repo root):
    pyinstaller desktop/launcher.spec

Output in dist/TeleDrive/ (--onedir) or dist/TeleDrive.exe (--onefile).
"""
import os
import sys
from pathlib import Path

# -- Mode --------------------------------------------------------------------
# onefile  = single executable (slower startup, portable)
# onedir   = folder with deps (faster startup, slightly less portable)
MODE = "onedir"

# -- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

# -- Collect data files ------------------------------------------------------
# These are the files the frozen app needs at runtime.
DATAS = [
    (str(ROOT / "main.py"), "."),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "app"), "app"),
    (str(ROOT / "static"), "static"),
]

# -- Hidden imports ----------------------------------------------------------
# Packages that PyInstaller might not discover automatically.
HIDDEN = [
    # FastAPI / Starlette internals
    "fastapi",
    "starlette",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    # Uvicorn (imported programmatically)
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
    # Pydantic v2 internals
    "pydantic",
    "pydantic_core",
    "pydantic.color",
    "pydantic.types",
    "pydantic.dataclasses",
    "pydantic._internal",
    "pydantic._internal._config",
    "pydantic._internal._model_construction",
    "pydantic._internal._generate_schema",
    "pydantic._internal._known_annotated_metadata",
    "pydantic._internal._fields",
    "pydantic._internal._validators",
    "pydantic._internal._dataclasses",
    "pydantic.deprecated",
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
    # dotenv
    "dotenv",
    "dotenv.parser",
    # multipart
    "multipart",
    "multipart.multipart",
]

# -- Exclusions (things we don't need) ----------------------------------------
EXCLUDES = [
    "tkinter.test",
    "unittest",
    "email",
    "http.client",
    "http.server",
    "asyncio.test_utils",
    "test",
    "distutils",
    "setuptools",
    "pip",
    "pdb",
    "py_compile",
    "doctest",
    "pdb",
]

# -- Build -------------------------------------------------------------------
a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
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

# Collect all submodules from packages we know we need
for pkg in ("fastapi", "starlette", "uvicorn", "pydantic", "telethon",
            "cryptography", "PIL", "dotenv", "multipart"):
    try:
        a.datas += Tree(os.path.dirname(__import__(pkg).__file__),
                        prefix=pkg.replace(".", os.sep))
    except Exception:
        pass

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
    console=False,          # no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # TODO: add an .ico / .icns
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

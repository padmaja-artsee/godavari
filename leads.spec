# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Leads desktop app.

Build with:
    pyinstaller leads.spec

Output:  dist/leads          (Mac/Linux binary)
         dist/leads.exe      (Windows)
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821  (PyInstaller injects SPECPATH)

block_cipher = None

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle templates, static assets, and the data directory (seed + templates).
        (str(ROOT / "templates"),  "templates"),
        (str(ROOT / "static"),     "static"),
        (str(ROOT / "data"),       "data"),
    ],
    # Note: data/leads.db is intentionally included so the app can copy it to
    # ~/Library/Application Support/GodavariLeads/ on first launch, avoiding
    # slow JSON seed loading.

    hiddenimports=[
        # FastAPI / Starlette internals not always auto-detected.
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "starlette.routing",
        "starlette.staticfiles",
        "starlette.templating",
        "starlette.middleware",
        "starlette.middleware.cors",
        "multipart",
        # App modules.
        "app.main",
        "app.database",
        "app.generate",
        "app.purchase_orders",
        "app.po_exports",
        "app.commission_invoices",
        "app.ci_exports",
        "app.sales_invoices",
        "app.si_exports",
        "app.delivery_notes",
        "app.dn_exports",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "numpy", "pandas", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="leads",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # No terminal window on launch (set True to debug).
    # icon="static/icon.icns",   # Uncomment and add icon file for branded app.
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="leads",
)

# Mac: wrap in a proper .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Leads.app",
        # icon="static/icon.icns",
        bundle_identifier="com.godavari.leads",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the GBInc Leads + Finance desktop app.

Build with:
    pyinstaller leads.spec

Output:  dist/GodavariLeads.app  (macOS)
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
        # ── Leads ──────────────────────────────────────────────────────────
        (str(ROOT / "templates"),              "templates"),
        (str(ROOT / "static"),                 "static"),
        (str(ROOT / "data"),                   "data"),
        (str(ROOT / "app" / "assets"),         "app/assets"),
        # ── Finance sub-app ────────────────────────────────────────────────
        (str(ROOT / "finance" / "templates"),  "finance/templates"),
        (str(ROOT / "finance" / "static"),     "finance/static"),
        (str(ROOT / "finance" / "assets"),     "finance/assets"),
        # finance/__init__.py and app/__init__.py are picked up via hiddenimports
    ],

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
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.utils",
        # ── Leads modules ──────────────────────────────────────────────────
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
        "app.deal_files",
        "app.products",
        "app.exports",
        "app.seed",
        "app.charts",
        "app.xl_style",
        # ── Finance modules ────────────────────────────────────────────────
        "finance",
        "finance.app",
        "finance.app.main",
        "finance.app.database",
        "finance.app.expenses",
        "finance.app.exports",
        "finance.app.commission_exports",
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
    console=False,
    icon=str(ROOT / "src-tauri" / "icons" / "icon.icns"),
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

# macOS: wrap in a proper .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="GodavariLeads.app",
        icon=str(ROOT / "src-tauri" / "icons" / "icon.icns"),
        bundle_identifier="com.godavari.leads",
        info_plist={
            "NSPrincipalClass":         "NSApplication",
            "NSHighResolutionCapable":  True,
            "CFBundleShortVersionString": "1.1.0",
            "CFBundleDisplayName":      "Godavari Leads",
        },
    )

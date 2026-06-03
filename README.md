# GBInc Leads Dashboard

A local web dashboard for managing sales leads — replaces spreadsheet workflows with search, summaries, and activity tracking.

## Run locally

```bash
cd /Users/padmajaganapathy/Documents/Cursor/Leads
python3 -m pip install -r requirements.txt
python3 run.py
```

Open **http://127.0.0.1:8000** in your browser.

## Features

- **Leads** — Contact repository only: company, contact, email, website, phone, products interested in (no PO)
- **Active deals** — Commercial pursuits by date; PO optional; mark **Shipped** to close
- **Dashboard** — Open deals + recent activity
- **Add / Update** — Three flows: contact, deal, activity note
- **Summary** — Group by product or customer for a time period
- **Customer detail** — Edit contact, view deals and timeline

## Data

- SQLite database: `data/leads.db`
- Initial import from your Excel files is in `data/seed.json` (loaded on first startup)
- Re-import from spreadsheets: edit `data/seed.json` or re-run the export script, then delete `data/leads.db` and restart

## GitHub

Remote: [github.com/padmaja-artsee/godavari](https://github.com/padmaja-artsee/godavari)

```bash
git push -u origin main
```

`data/leads.db` and `data/uploads/` are gitignored; the app seeds from `data/seed.json` on first run.

## Generate module

Open **Generate** in the sidebar (`/generate`) to create business documents locally.

### Purchase Orders

- **Create from scratch:** Generate → Purchase Order → Create
- **Create from a deal:** On any deal page, click **Generate Purchase Order**
- **Edit / duplicate / delete:** From the saved PO list at `/generate/purchase-orders`
- **Export Excel:** Saves to `data/exports/purchase_orders/xlsx/` and downloads
- **Export PDF:** Saves to `data/exports/purchase_orders/pdf/` (uses reportlab; install optional WeasyPrint for richer layout)
- **Print:** Use Print view; if PDF export is unavailable, use browser Print → Save as PDF

PO data is stored in the same SQLite database (`data/leads.db`) in `purchase_orders`, `purchase_order_line_items`, and `purchase_order_batches` tables, linked via `generated_documents`.

Internal notes (status, prepared by, etc.) are saved but not included in print, PDF, or Excel exports.

---

## Desktop App Build (feature/app branch)

The app can be packaged as a native desktop app — no Python install required for end users.

### Architecture

```
┌─────────────────────────────────┐
│  Tauri native window (Rust)     │  ← tiny OS-native shell (~5 MB)
│  Loads http://localhost:8000    │
└──────────────┬──────────────────┘
               │ spawns
┌──────────────▼──────────────────┐
│  PyInstaller binary (launcher)  │  ← Python + FastAPI + all deps bundled
│  uvicorn on localhost:8000      │
│  SQLite DB next to executable   │
└─────────────────────────────────┘
```

### Prerequisites

```bash
# Python packaging
pip install pyinstaller

# Rust (required for Tauri)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Tauri CLI
cargo install tauri-cli --version "^2.0"

# Node (only needed to install Tauri CLI via npm as alternative)
# npm install -g @tauri-apps/cli
```

### One-command build (recommended)

```bash
cd /path/to/Leads
./scripts/kill_godavari_leads.sh   # only if apps are stuck / port 8000 busy
./build_app.sh
```

Output: **`GodavariLeads_1.1.0_<arch>.dmg`** — drag **GodavariLeads.app** to Applications.

**Do not distribute** `dist/GodavariLeads.app` from PyInstaller alone — it is missing `Contents/Resources/leads-bin/` and will white-screen when used with Tauri.

The build script:

1. PyInstaller → `dist/leads/`
2. `cargo tauri build`
3. Injects Python into `Contents/Resources/leads-bin/`
4. Smoke-tests `http://127.0.0.1:8000/` before creating the DMG

### If the app white-screens or spawns endlessly

```bash
./scripts/kill_godavari_leads.sh
```

Check log: `~/Library/Application Support/GodavariLeads/leads.log`

### Development mode (no packaging)

```bash
# Terminal 1 — start the Python server
LEADS_NO_BROWSER=1 python3 launcher.py

# Terminal 2 — start Tauri dev window
cd src-tauri && cargo tauri dev
```

### Adding an icon

1. Create a 1024×1024 PNG named `icon.png` and place it in `src-tauri/icons/`.
2. Run `cargo tauri icon src-tauri/icons/icon.png` — this generates all required sizes automatically.
3. Uncomment the `icon` lines in `leads.spec` and `tauri.conf.json`.

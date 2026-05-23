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

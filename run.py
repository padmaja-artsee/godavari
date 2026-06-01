#!/usr/bin/env python3
"""Run the leads dashboard locally (dev server).

On macOS, automatically uses the same database as the desktop app
(~/Library/Application Support/GodavariLeads/) so web dev and desktop
always read/write the same data — no more split databases.
"""
import os
import sys
import sqlite3
import shutil
import datetime
from pathlib import Path

SHARED_APP_NAME = "GodavariLeads"


def _shared_data_dir():
    """Return the desktop app's shared data directory if it exists."""
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / SHARED_APP_NAME
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def _row_count(db_path, table):
    try:
        conn = sqlite3.connect(str(db_path))
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _auto_migrate(local_db: Path, shared_db: Path) -> None:
    """
    If the local repo data/finance.db has rows that the shared DB is missing,
    copy them over automatically so data is never silently lost.
    Only runs when there is a genuine discrepancy.
    """
    if not local_db.exists() or not shared_db.exists():
        return

    local_txns  = _row_count(local_db,  "transactions")
    shared_txns = _row_count(shared_db, "transactions")
    local_vend  = _row_count(local_db,  "vendors")
    shared_vend = _row_count(shared_db, "vendors")

    if local_txns <= shared_txns and local_vend <= shared_vend:
        return   # nothing to migrate

    print(f"[run.py] ⚠️  Local data/ has more rows than shared DB "
          f"(txns: {local_txns} vs {shared_txns}, vendors: {local_vend} vs {shared_vend}).")
    print("[run.py] Auto-merging local data into shared database…")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = str(shared_db) + f".bak_{ts}"
    shutil.copy2(str(shared_db), backup)
    print(f"[run.py] Shared DB backed up → {backup}")

    lc = sqlite3.connect(str(local_db));  lc.row_factory = sqlite3.Row
    sc = sqlite3.connect(str(shared_db)); sc.row_factory = sqlite3.Row
    sc.execute("PRAGMA foreign_keys = OFF")

    # Build line_item id map
    li_id_map = {}
    for r in lc.execute("SELECT * FROM line_items"):
        ex = sc.execute("SELECT id FROM line_items WHERE section=? AND name=?",
                        (r["section"], r["name"])).fetchone()
        if ex:
            li_id_map[r["id"]] = ex["id"]
        else:
            cur = sc.execute(
                "INSERT INTO line_items (section,name,is_calculated,is_system,sort_order) VALUES(?,?,?,?,?)",
                (r["section"],r["name"],r["is_calculated"],r["is_system"],
                 r["sort_order"] if "sort_order" in r.keys() else 0))
            li_id_map[r["id"]] = cur.lastrowid
    sc.commit()

    # Build account id map
    acct_id_map = {}
    for r in lc.execute("SELECT * FROM accounts"):
        ex = sc.execute("SELECT id FROM accounts WHERE name=?", (r["name"],)).fetchone()
        if ex:
            acct_id_map[r["id"]] = ex["id"]
        else:
            mapped_li = li_id_map.get(r["line_item_id"]) if r["line_item_id"] else None
            cur = sc.execute(
                "INSERT INTO accounts (name,section,line_item_id,is_system,sort_order) VALUES(?,?,?,?,?)",
                (r["name"],r["section"],mapped_li,r["is_system"],
                 r["sort_order"] if "sort_order" in r.keys() else 0))
            acct_id_map[r["id"]] = cur.lastrowid
    sc.commit()

    # Build vendor id map
    vendor_id_map = {}
    for r in lc.execute("SELECT * FROM vendors"):
        ex = sc.execute("SELECT id FROM vendors WHERE name=?", (r["name"],)).fetchone()
        if ex:
            vendor_id_map[r["id"]] = ex["id"]
        else:
            cur = sc.execute(
                "INSERT INTO vendors (name,email,phone,notes,created_at) VALUES(?,?,?,?,?)",
                (r["name"],r["email"],r["phone"],r["notes"],r["created_at"]))
            vendor_id_map[r["id"]] = cur.lastrowid
    sc.commit()

    # Merge transactions
    sh_cols = {row[1] for row in sc.execute("PRAGMA table_info(transactions)")}
    added = 0
    for r in lc.execute("SELECT * FROM transactions"):
        mapped_acct = acct_id_map.get(r["account_id"], r["account_id"])
        if sc.execute("SELECT id FROM transactions WHERE date=? AND amount=? AND account_id=?",
                      (r["date"], r["amount"], mapped_acct)).fetchone():
            continue
        mapped_vendor = vendor_id_map.get(r["vendor_id"]) if r["vendor_id"] else None
        data = {"date": r["date"], "account_id": mapped_acct, "amount": r["amount"],
                "payment_account_id": r["payment_account_id"], "vendor_id": mapped_vendor,
                "fiscal_year": r["fiscal_year"], "month": r["month"], "created_at": r["created_at"]}
        for col in ["currency","transaction_type","reference","notes","receipt_filename","updated_at"]:
            if col in sh_cols and col in r.keys():
                data[col] = r[col]
        sc.execute(f"INSERT INTO transactions ({','.join(data)}) VALUES ({','.join(['?']*len(data))})",
                   list(data.values()))
        added += 1
    sc.commit()

    # Merge budget
    badd = 0
    for r in lc.execute("SELECT * FROM budget"):
        mapped_li = li_id_map.get(r["line_item_id"], r["line_item_id"])
        if not sc.execute("SELECT id FROM budget WHERE line_item_id=? AND fiscal_year=? AND month=?",
                          (mapped_li, r["fiscal_year"], r["month"])).fetchone():
            sc.execute("INSERT INTO budget (line_item_id,fiscal_year,month,amount) VALUES(?,?,?,?)",
                       (mapped_li, r["fiscal_year"], r["month"], r["amount"]))
            badd += 1
    sc.commit()

    sc.execute("PRAGMA foreign_keys = ON")
    sc.close(); lc.close()
    print(f"[run.py] ✅ Migrated {added} transactions, {badd} budget rows into shared DB.")


# ── Route both dev server and desktop app to the SAME database ──────────────
if "LEADS_DATA_DIR" not in os.environ:
    shared = _shared_data_dir()
    if shared:
        local_finance = Path(__file__).parent / "data" / "finance.db"
        shared_finance = shared / "finance.db"
        # Auto-merge any data that exists only in local repo data/
        _auto_migrate(local_finance, shared_finance)

        os.environ["LEADS_DATA_DIR"]  = str(shared)
        os.environ["LEADS_DB_PATH"]   = str(shared / "leads.db")
        os.environ["FINANCE_DB_PATH"] = str(shared / "finance.db")
        print(f"[run.py] ✅ Using shared DB: {shared}")
    else:
        print("[run.py] Using local data/ directory")

# ── Start dev server ─────────────────────────────────────────────────────────
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

"""
Finance module database — fully independent from Leads.
Fiscal year = April–March (Indian FY). FY27 = Apr 2026 – Mar 2027.
All monetary values stored in USD to match source.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _get_db_path() -> Path:
    env = os.environ.get("FINANCE_DB_PATH")
    if env:
        return Path(env)
    data_env = os.environ.get("LEADS_DATA_DIR")
    if data_env:
        return Path(data_env) / "finance.db"
    return Path(__file__).resolve().parent.parent.parent / "data" / "finance.db"

DB_PATH = _get_db_path()


def get_receipts_dir() -> Path:
    data_env = os.environ.get("LEADS_DATA_DIR")
    if data_env:
        return Path(data_env) / "finance_receipts"
    return Path(__file__).resolve().parent.parent.parent / "data" / "finance_receipts"


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fiscal year helpers
# ---------------------------------------------------------------------------

FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
MONTH_LABELS = {
    4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep",
    10: "Oct", 11: "Nov", 12: "Dec", 1: "Jan", 2: "Feb", 3: "Mar",
}


def fiscal_year_for_date(date_str: str) -> tuple[int, int]:
    """Return (fiscal_year, calendar_month) for a YYYY-MM-DD date string.
    FY27 = Apr 2026 – Mar 2027.
    """
    year, month, _ = map(int, date_str.split("-"))
    fy = year + 1 if month >= 4 else year
    return fy, month


def calendar_year_for(fiscal_year: int, month: int) -> int:
    if month >= 4:
        return fiscal_year - 1
    return fiscal_year


# ---------------------------------------------------------------------------
# P&L line seeds
# ---------------------------------------------------------------------------

PL_LINES = [
    ("Revenue",                      "income",        0, 10),
    ("Increase / Decrease in Stock", "income",        0, 20),
    ("Other Income",                 "income",        0, 30),
    ("Total Income",                 "income_total",  1, 40),
    ("Raw Material Cost",            "expense",       0, 50),
    ("Power & Fuel Cost",            "expense",       0, 60),
    ("Stores, Spares & Chemicals",   "expense",       0, 70),
    ("Packing Cost",                 "expense",       0, 80),
    ("Repairs & Maintenance",        "expense",       0, 90),
    ("Employee Cost",                "expense",       0, 100),
    ("Selling Expenses",             "expense",       0, 110),
    ("General & Admin Expenses",     "expense",       0, 120),
    ("Total Expenses",               "expense_total", 1, 130),
    ("EBITDA",                       "ebitda",        1, 140),
    ("Interest",                     "below_ebitda",  0, 150),
    ("Depreciation",                 "below_ebitda",  0, 160),
    ("EBT",                          "ebt",           1, 170),
    ("Extraordinary Items",          "below_ebitda",  0, 180),
    ("Net EBT",                      "net_ebt",       1, 190),
]

# Standard US Chart of Accounts → maps to P&L line names above
# (account_name, group_label, pl_line_name_or_None, is_system, sort_order)
ACCOUNTS_SEED = [
    # ── Income ──────────────────────────────────────────────────────────
    ("Sales Revenue",              "Income",              "Revenue",                    1, 10),
    ("Commission Income",          "Income",              "Revenue",                    1, 20),
    ("Other Income",               "Income",              "Other Income",               1, 30),
    # ── Cost of Goods Sold ──────────────────────────────────────────────
    ("Cost of Goods Sold",         "Cost of Goods Sold",  "Raw Material Cost",          1, 40),
    ("Freight & Shipping",         "Cost of Goods Sold",  "Packing Cost",               1, 50),
    # ── Employee ────────────────────────────────────────────────────────
    ("Employee Salary",            "Employee",            "Employee Cost",              1, 60),
    ("Payroll Taxes",              "Employee",            "Employee Cost",              1, 70),
    ("Employee Benefits",          "Employee",            "Employee Cost",              1, 80),
    # ── Facilities ──────────────────────────────────────────────────────
    ("Rent Expense",               "Facilities",          "General & Admin Expenses",   1, 90),
    ("Utilities",                  "Facilities",          "Power & Fuel Cost",          1, 100),
    ("Repairs & Maintenance",      "Facilities",          "Repairs & Maintenance",      1, 110),
    # ── Selling ─────────────────────────────────────────────────────────
    ("Advertising & Marketing",    "Selling",             "Selling Expenses",           1, 120),
    ("Travel Expense",             "Selling",             "Selling Expenses",           1, 130),
    ("Meals & Entertainment",      "Selling",             "Selling Expenses",           1, 140),
    ("Trade Shows & Events",       "Selling",             "Selling Expenses",           1, 150),
    # ── General & Admin ─────────────────────────────────────────────────
    ("Office Supplies",            "General & Admin",     "General & Admin Expenses",   1, 160),
    ("Computer & Software",        "General & Admin",     "General & Admin Expenses",   1, 170),
    ("Professional Fees",          "General & Admin",     "General & Admin Expenses",   1, 180),
    ("Consultant Expense",         "General & Admin",     "General & Admin Expenses",   1, 190),
    ("Accounting & Audit",         "General & Admin",     "General & Admin Expenses",   1, 200),
    ("Legal Fees",                 "General & Admin",     "General & Admin Expenses",   1, 210),
    ("Insurance",                  "General & Admin",     "General & Admin Expenses",   1, 220),
    ("Bank Charges",               "General & Admin",     "General & Admin Expenses",   1, 230),
    ("Subscriptions",              "General & Admin",     "General & Admin Expenses",   1, 240),
    ("Postage & Courier",          "General & Admin",     "General & Admin Expenses",   1, 250),
    ("Miscellaneous Expense",      "General & Admin",     "General & Admin Expenses",   1, 260),
    # ── Stores / Spares ─────────────────────────────────────────────────
    ("Stores & Spares",            "Operations",          "Stores, Spares & Chemicals", 1, 270),
    ("Chemicals",                  "Operations",          "Stores, Spares & Chemicals", 1, 280),
    # ── Below EBITDA ─────────────────────────────────────────────────────
    ("Interest Expense",           "Below EBITDA",        "Interest",                   1, 290),
    ("Depreciation",               "Below EBITDA",        "Depreciation",               1, 300),
    ("Tax",                        "Below EBITDA",        "Extraordinary Items",        1, 310),
    ("Bad Debt",                   "Below EBITDA",        "Extraordinary Items",        1, 320),
]

PAYMENT_ACCOUNTS_SEED = [
    ("Sathgen Therapeutics Bank",  "bank"),
    ("Petty Cash",                 "cash"),
    ("Credit Card",                "credit_card"),
    ("Undeposited Funds",          "other"),
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pl_lines (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                section       TEXT    NOT NULL,
                is_calculated INTEGER NOT NULL DEFAULT 0,
                sort_order    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                group_label   TEXT    NOT NULL DEFAULT '',
                pl_line_id    INTEGER REFERENCES pl_lines(id),
                is_system     INTEGER NOT NULL DEFAULT 0,
                sort_order    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS vendors (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                email      TEXT DEFAULT '',
                phone      TEXT DEFAULT '',
                notes      TEXT DEFAULT '',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS payment_accounts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                account_type TEXT NOT NULL DEFAULT 'bank',
                is_system    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                date                TEXT    NOT NULL,
                account_id          INTEGER NOT NULL REFERENCES accounts(id),
                amount              REAL    NOT NULL,
                currency            TEXT    NOT NULL DEFAULT 'USD',
                payment_account_id  INTEGER REFERENCES payment_accounts(id),
                vendor_id           INTEGER REFERENCES vendors(id),
                reference           TEXT    DEFAULT '',
                notes               TEXT    DEFAULT '',
                receipt_filename    TEXT    DEFAULT '',
                fiscal_year         INTEGER,
                month               INTEGER,
                created_at          TEXT,
                updated_at          TEXT
            );

            CREATE TABLE IF NOT EXISTS budget (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                pl_line_id   INTEGER NOT NULL REFERENCES pl_lines(id),
                fiscal_year  INTEGER NOT NULL,
                month        INTEGER NOT NULL,
                amount       REAL    NOT NULL DEFAULT 0,
                updated_at   TEXT,
                UNIQUE(pl_line_id, fiscal_year, month)
            );

            -- actuals stores MANUAL ADDITIONS only;
            -- true actual = expense rollup + this amount.
            CREATE TABLE IF NOT EXISTS actuals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                pl_line_id   INTEGER NOT NULL REFERENCES pl_lines(id),
                fiscal_year  INTEGER NOT NULL,
                month        INTEGER NOT NULL,
                amount       REAL    NOT NULL DEFAULT 0,
                notes        TEXT    DEFAULT '',
                updated_at   TEXT,
                UNIQUE(pl_line_id, fiscal_year, month)
            );
        """)

        # Seed P&L lines
        if conn.execute("SELECT COUNT(*) FROM pl_lines").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO pl_lines (name, section, is_calculated, sort_order) VALUES (?,?,?,?)",
                PL_LINES,
            )

        # Seed accounts (resolve pl_line_id by name)
        if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
            for name, group, pl_name, is_sys, srt in ACCOUNTS_SEED:
                pl_id = None
                if pl_name:
                    row = conn.execute(
                        "SELECT id FROM pl_lines WHERE name = ?", (pl_name,)
                    ).fetchone()
                    if row:
                        pl_id = row["id"]
                conn.execute(
                    "INSERT INTO accounts (name, group_label, pl_line_id, is_system, sort_order) VALUES (?,?,?,?,?)",
                    (name, group, pl_id, is_sys, srt),
                )

        # Seed payment accounts
        if conn.execute("SELECT COUNT(*) FROM payment_accounts").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO payment_accounts (name, account_type, is_system) VALUES (?,?,1)",
                PAYMENT_ACCOUNTS_SEED,
            )


# ---------------------------------------------------------------------------
# P&L grid queries
# ---------------------------------------------------------------------------

def list_pl_lines() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM pl_lines ORDER BY sort_order"
        ).fetchall()]


def get_grid(table: str, fiscal_year: int) -> dict[tuple, float]:
    assert table in ("budget", "actuals")
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT pl_line_id, month, amount FROM {table} WHERE fiscal_year = ?",
            (fiscal_year,)
        ).fetchall()
    return {(r["pl_line_id"], r["month"]): r["amount"] for r in rows}


def get_expense_rollup(fiscal_year: int) -> dict[tuple, float]:
    """Return {(pl_line_id, month): sum_of_expenses} for all expenses in fiscal_year."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT a.pl_line_id, e.month, SUM(e.amount) AS total
               FROM expenses e
               JOIN accounts a ON e.account_id = a.id
               WHERE e.fiscal_year = ? AND a.pl_line_id IS NOT NULL
               GROUP BY a.pl_line_id, e.month""",
            (fiscal_year,)
        ).fetchall()
    return {(r["pl_line_id"], r["month"]): r["total"] for r in rows}


def save_grid(table: str, fiscal_year: int, values: dict[str, float]) -> None:
    assert table in ("budget", "actuals")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        for key, amount in values.items():
            line_id, month = map(int, key.split("_"))
            conn.execute(
                f"""INSERT INTO {table} (pl_line_id, fiscal_year, month, amount, updated_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(pl_line_id, fiscal_year, month)
                    DO UPDATE SET amount=excluded.amount, updated_at=excluded.updated_at""",
                (line_id, fiscal_year, month, amount, now),
            )


def computed_grid(raw: dict[tuple, float], lines: list[dict]) -> dict[tuple, float]:
    result = dict(raw)
    by_name = {l["name"]: l["id"] for l in lines}
    income_lines  = [l["id"] for l in lines if l["section"] == "income"]
    expense_lines = [l["id"] for l in lines if l["section"] == "expense"]
    ti_id  = by_name.get("Total Income")
    te_id  = by_name.get("Total Expenses")
    eb_id  = by_name.get("EBITDA")
    int_id = by_name.get("Interest")
    dep_id = by_name.get("Depreciation")
    ebt_id = by_name.get("EBT")
    ext_id = by_name.get("Extraordinary Items")
    net_id = by_name.get("Net EBT")
    for month in FY_MONTHS:
        ti  = sum(result.get((lid, month), 0) for lid in income_lines)
        te  = sum(result.get((lid, month), 0) for lid in expense_lines)
        eb  = ti - te
        interest     = result.get((int_id,  month), 0)
        depreciation = result.get((dep_id,  month), 0)
        ebt = eb - interest - depreciation
        ext = result.get((ext_id, month), 0)
        net = ebt - ext
        if ti_id:  result[(ti_id,  month)] = ti
        if te_id:  result[(te_id,  month)] = te
        if eb_id:  result[(eb_id,  month)] = eb
        if ebt_id: result[(ebt_id, month)] = ebt
        if net_id: result[(net_id, month)] = net
    return result


def get_fiscal_years() -> list[int]:
    from datetime import date
    today = date.today()
    current_fy = today.year + 1 if today.month >= 4 else today.year
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT fiscal_year FROM budget
               UNION SELECT DISTINCT fiscal_year FROM actuals
               UNION SELECT DISTINCT fiscal_year FROM expenses"""
        ).fetchall()
    return sorted({r[0] for r in rows} | {current_fy}, reverse=True)


# ---------------------------------------------------------------------------
# Account / Vendor / Payment account queries
# ---------------------------------------------------------------------------

def list_accounts(include_inactive: bool = False) -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT a.*, p.name AS pl_line_name FROM accounts a "
            "LEFT JOIN pl_lines p ON a.pl_line_id = p.id "
            "ORDER BY a.sort_order, a.name"
        ).fetchall()]


def list_vendors() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM vendors ORDER BY name"
        ).fetchall()]


def list_payment_accounts() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM payment_accounts ORDER BY account_type, name"
        ).fetchall()]


def save_vendor(name: str, email: str, phone: str, notes: str, vid: "int | None" = None) -> int:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        if vid:
            conn.execute(
                "UPDATE vendors SET name=?,email=?,phone=?,notes=? WHERE id=?",
                (name, email, phone, notes, vid)
            )
            return vid
        cur = conn.execute(
            "INSERT INTO vendors (name,email,phone,notes,created_at) VALUES (?,?,?,?,?)",
            (name, email, phone, notes, now)
        )
        return cur.lastrowid


def delete_vendor(vid: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE id=?", (vid,))


def save_account(name: str, group_label: str, pl_line_id: "int | None",
                 aid: "int | None" = None) -> int:
    with get_db() as conn:
        if aid:
            conn.execute(
                "UPDATE accounts SET name=?,group_label=?,pl_line_id=? WHERE id=?",
                (name, group_label, pl_line_id, aid)
            )
            return aid
        # sort at end
        max_sort = conn.execute("SELECT MAX(sort_order) FROM accounts").fetchone()[0] or 0
        cur = conn.execute(
            "INSERT INTO accounts (name,group_label,pl_line_id,is_system,sort_order) VALUES (?,?,?,0,?)",
            (name, group_label, pl_line_id, max_sort + 10)
        )
        return cur.lastrowid


def delete_account(aid: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM accounts WHERE id=? AND is_system=0", (aid,))


def save_payment_account(name: str, account_type: str, paid: "int | None" = None) -> int:
    with get_db() as conn:
        if paid:
            conn.execute(
                "UPDATE payment_accounts SET name=?,account_type=? WHERE id=?",
                (name, account_type, paid)
            )
            return paid
        cur = conn.execute(
            "INSERT INTO payment_accounts (name,account_type,is_system) VALUES (?,?,0)",
            (name, account_type)
        )
        return cur.lastrowid


def delete_payment_account(paid: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM payment_accounts WHERE id=? AND is_system=0", (paid,))

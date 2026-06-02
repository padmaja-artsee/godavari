"""
Finance module database.
Structure matches 'Budget vs Actuals.xlsx' — expense categories with line items.
Fiscal year = April–March (FY27 = Apr 2026 – Mar 2027).
Months stored as calendar integers (1–12).
"""
from __future__ import annotations
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
# Fiscal year helpers  (Apr–Mar, FY stored as ending year)
# ---------------------------------------------------------------------------

FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
MONTH_LABELS = {
    4:"Apr", 5:"May", 6:"Jun", 7:"Jul", 8:"Aug", 9:"Sep",
    10:"Oct", 11:"Nov", 12:"Dec", 1:"Jan", 2:"Feb", 3:"Mar",
}


def fiscal_year_for_date(date_str: str) -> tuple:
    """Return (fiscal_year, calendar_month)."""
    y, m, _ = map(int, date_str.split("-"))
    return (y + 1 if m >= 4 else y), m


def cal_year_for(fiscal_year: int, month: int) -> int:
    return fiscal_year - 1 if month >= 4 else fiscal_year


# ---------------------------------------------------------------------------
# Seed data — matches Budget vs Actuals.xlsx structure + income
# ---------------------------------------------------------------------------

# (section, name, is_calculated, is_system, sort_order)
LINE_ITEMS_SEED = [
    # ── Income ──────────────────────────────────────────────────────────────
    ("income",   "Commission Income",         0, 1, 10),
    ("income",   "Other Income",              0, 1, 20),
    ("income",   "Total Income",              1, 1, 99),
    # ── Employee Costs ──────────────────────────────────────────────────────
    ("employee", "Compensation",              0, 1, 10),
    ("employee", "Health Insurance",          0, 1, 20),
    ("employee", "Disability Insurance",      0, 1, 25),
    ("employee", "Workers Compensation",      0, 1, 30),
    ("employee", "Employee Benefits",         0, 1, 35),
    ("employee", "Payroll Tax",               0, 1, 80),
    ("employee", "Total Employee Costs",      1, 1, 99),
    # ── Office Costs ────────────────────────────────────────────────────────
    ("office",   "Office lease",              0, 1, 10),
    ("office",   "Equipment",                 0, 1, 20),
    ("office",   "Subscriptions/Software",    0, 1, 30),
    ("office",   "Telephone",                 0, 1, 40),
    ("office",   "Office supplies",           0, 1, 50),
    ("office",   "Security",                  0, 1, 60),
    ("office",   "Postage and Delivery",      0, 1, 65),
    ("office",   "Repairs and Maintenance",   0, 1, 70),
    ("office",   "Depreciation",              0, 1, 75),
    ("office",   "Amortization",             0, 1, 76),
    ("office",   "Miscellaneous expenses",    0, 1, 80),
    ("office",   "Total Office Costs",        1, 1, 99),
    # ── Bank/Legal/Admin ────────────────────────────────────────────────────
    ("admin",    "Bank charges",              0, 1, 10),
    ("admin",    "Taxes",                     0, 1, 15),
    ("admin",    "Insurance expense",         0, 1, 20),
    ("admin",    "Accounting",                0, 1, 30),
    ("admin",    "Legal",                     0, 1, 40),
    ("admin",    "LLC",                       0, 1, 50),
    ("admin",    "Payroll services",          0, 1, 60),
    ("admin",    "Interest Expense",          0, 1, 65),
    ("admin",    "Fees",                      0, 1, 70),
    ("admin",    "Total Admin",               1, 1, 99),
    # ── Conference/Travel ───────────────────────────────────────────────────
    ("travel",   "Registration",              0, 1, 10),
    ("travel",   "Meals and Entertainment",   0, 1, 15),
    ("travel",   "Travel costs",              0, 1, 20),
    ("travel",   "Car Rental",                0, 1, 25),
    ("travel",       "Total Travel",              1, 1, 99),
    # ── Investment ──────────────────────────────────────────────────────────
    ("investment",   "Capital Expenditure",       0, 1, 10),
    ("investment",   "Equipment Purchase",        0, 1, 20),
    ("investment",   "R&D Investment",            0, 1, 30),
    ("investment",   "Other Investment",          0, 1, 40),
    ("investment",   "Total Investment",          1, 1, 99),
    # ── Grand totals ────────────────────────────────────────────────────────
    ("totals",       "Total Expenses",            1, 1, 10),
    ("totals",       "Balance",                   1, 1, 20),
    ("totals",       "Cash Position",             1, 1, 30),
]

# Items added after initial release — used by the migration to patch existing DBs
_MIGRATION_LINE_ITEMS = [
    ("employee", "Health Insurance",        0, 1, 20),
    ("employee", "Disability Insurance",    0, 1, 25),
    ("employee", "Workers Compensation",    0, 1, 30),
    ("employee", "Employee Benefits",       0, 1, 35),
    ("office",   "Postage and Delivery",    0, 1, 65),
    ("office",   "Repairs and Maintenance", 0, 1, 70),
    ("office",   "Depreciation",            0, 1, 75),
    ("office",   "Amortization",           0, 1, 76),
    ("admin",    "Taxes",                   0, 1, 15),
    ("admin",    "Interest Expense",        0, 1, 65),
    ("admin",    "Fees",                    0, 1, 70),
    ("travel",   "Meals and Entertainment", 0, 1, 15),
    ("travel",      "Car Rental",              0, 1, 25),
    ("investment",  "Capital Expenditure",     0, 1, 10),
    ("investment",  "Equipment Purchase",      0, 1, 20),
    ("investment",  "R&D Investment",          0, 1, 30),
    ("investment",  "Other Investment",        0, 1, 40),
    ("investment",  "Total Investment",        1, 1, 99),
]

SECTION_LABELS = {
    "income":     "INCOME",
    "employee":   "EMPLOYEE COSTS",
    "office":     "OFFICE COSTS",
    "admin":      "BANK / LEGAL / ADMIN",
    "travel":     "CONFERENCE / TRAVEL",
    "investment": "INVESTMENT",
    "totals":     "",
}

SECTION_ORDER = ["income", "employee", "office", "admin", "travel", "investment", "totals"]

# Default account → line item mapping
ACCOUNTS_SEED = [
    # Income
    ("Commission Income",           "income",   "Commission Income",        1,  10),
    ("Other Income",                "income",   "Other Income",             1,  20),
    # Employee
    ("Compensation",                "employee", "Compensation",             1,  30),
    ("Health Insurance",            "employee", "Health Insurance",         1,  35),
    ("Disability Insurance",        "employee", "Disability Insurance",     1,  38),
    ("Workers Compensation",        "employee", "Workers Compensation",     1,  40),
    ("Paid Family Leave",           "employee", "Disability Insurance",     1,  42),
    ("Employee Benefits",           "employee", "Employee Benefits",        1,  45),
    ("Payroll Tax",                 "employee", "Payroll Tax",              1,  50),
    # Office
    ("Office Lease / Rent",         "office",   "Office lease",             1,  60),
    ("Equipment",                   "office",   "Equipment",                1,  70),
    ("Subscriptions/Software",      "office",   "Subscriptions/Software",   1,  80),
    ("Computer and Internet",       "office",   "Subscriptions/Software",   1,  85),
    ("Dues and Subscriptions",      "office",   "Subscriptions/Software",   1,  87),
    ("Telephone",                   "office",   "Telephone",                1,  90),
    ("Office Supplies",             "office",   "Office supplies",          1, 100),
    ("Security",                    "office",   "Security",                 1, 110),
    ("Postage and Delivery",        "office",   "Postage and Delivery",     1, 115),
    ("Repairs and Maintenance",     "office",   "Repairs and Maintenance",  1, 118),
    ("Depreciation Expense",        "office",   "Depreciation",             1, 120),
    ("Amortization Expense",        "office",   "Amortization",             1, 122),
    ("Miscellaneous",               "office",   "Miscellaneous expenses",   1, 125),
    # Admin
    ("Bank Charges",                "admin",    "Bank charges",             1, 130),
    ("Taxes",                       "admin",    "Taxes",                    1, 133),
    ("Commercial Liability Ins",    "admin",    "Insurance expense",        1, 135),
    ("Directors & Officers Ins",    "admin",    "Insurance expense",        1, 137),
    ("Business Owners Ins",         "admin",    "Insurance expense",        1, 139),
    ("Insurance (Business)",        "admin",    "Insurance expense",        1, 140),
    ("Accounting & Audit",          "admin",    "Accounting",               1, 150),
    ("Legal Fees",                  "admin",    "Legal",                    1, 160),
    ("Professional Fees",           "admin",    "Legal",                    1, 170),
    ("Consultant Expense",          "admin",    "Legal",                    1, 175),
    ("LLC / State Fees",            "admin",    "LLC",                      1, 180),
    ("Payroll Services",            "admin",    "Payroll services",         1, 190),
    ("Interest Expense",            "admin",    "Interest Expense",         1, 195),
    ("Fees",                        "admin",    "Fees",                     1, 198),
    ("Membership",                  "admin",    "Fees",                     1, 199),
    # Travel
    ("Registration / Events",       "travel",      "Registration",             1, 200),
    ("Conference Expense",          "travel",      "Registration",             1, 202),
    ("Meals and Entertainment",     "travel",      "Meals and Entertainment",  1, 205),
    ("Travel Expense",              "travel",      "Travel costs",             1, 210),
    ("Airfare",                     "travel",      "Travel costs",             1, 212),
    ("Hotel / Lodging",             "travel",      "Travel costs",             1, 214),
    ("Car Rental",                  "travel",      "Car Rental",               1, 220),
    # Investment
    ("Capital Expenditure",         "investment",  "Capital Expenditure",      1, 300),
    ("Equipment Purchase",          "investment",  "Equipment Purchase",       1, 310),
    ("R&D Investment",              "investment",  "R&D Investment",           1, 320),
    ("Other Investment",            "investment",  "Other Investment",         1, 330),
]

PAYMENT_ACCOUNTS_SEED = [
    ("GBInc Bank Account", "bank"),
    ("Petty Cash",         "cash"),
    ("Credit Card",        "credit_card"),
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS line_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                section       TEXT    NOT NULL,
                name          TEXT    NOT NULL,
                is_calculated INTEGER NOT NULL DEFAULT 0,
                is_system     INTEGER NOT NULL DEFAULT 0,
                sort_order    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(section, name)
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                section       TEXT    NOT NULL DEFAULT '',
                line_item_id  INTEGER REFERENCES line_items(id),
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

            -- Expense transactions (type='expense') and income (type='income')
            CREATE TABLE IF NOT EXISTS transactions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                date                TEXT    NOT NULL,
                account_id          INTEGER NOT NULL REFERENCES accounts(id),
                amount              REAL    NOT NULL,
                currency            TEXT    NOT NULL DEFAULT 'USD',
                transaction_type    TEXT    NOT NULL DEFAULT 'expense',
                payment_account_id  INTEGER REFERENCES payment_accounts(id),
                vendor_id           INTEGER REFERENCES vendors(id),
                reference           TEXT    DEFAULT '',
                notes               TEXT    DEFAULT '',
                receipt_filename    TEXT    DEFAULT '',
                image_url           TEXT    DEFAULT '',
                fiscal_year         INTEGER,
                month               INTEGER,
                created_at          TEXT,
                updated_at          TEXT
            );

            -- Budget entries (planned amounts)
            CREATE TABLE IF NOT EXISTS budget (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                line_item_id INTEGER NOT NULL REFERENCES line_items(id),
                fiscal_year  INTEGER NOT NULL,
                month        INTEGER NOT NULL,
                amount       REAL    NOT NULL DEFAULT 0,
                updated_at   TEXT,
                UNIQUE(line_item_id, fiscal_year, month)
            );

            -- Manual actuals additions (for items not entered as transactions)
            CREATE TABLE IF NOT EXISTS actuals_manual (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                line_item_id INTEGER NOT NULL REFERENCES line_items(id),
                fiscal_year  INTEGER NOT NULL,
                month        INTEGER NOT NULL,
                amount       REAL    NOT NULL DEFAULT 0,
                updated_at   TEXT,
                UNIQUE(line_item_id, fiscal_year, month)
            );

            -- Archived fiscal years (read-only flag)
            CREATE TABLE IF NOT EXISTS fy_archive (
                fiscal_year INTEGER PRIMARY KEY,
                archived_at TEXT
            );
        """)
        _seed_line_items(conn)
        _seed_accounts(conn)
        _seed_payment_accounts(conn)
        _run_migrations(conn)


def _seed_line_items(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO line_items (section,name,is_calculated,is_system,sort_order) VALUES (?,?,?,?,?)",
        LINE_ITEMS_SEED,
    )


def _seed_accounts(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
        return
    for name, section, li_name, is_sys, srt in ACCOUNTS_SEED:
        row = conn.execute("SELECT id FROM line_items WHERE name=?", (li_name,)).fetchone()
        li_id = row["id"] if row else None
        conn.execute(
            "INSERT INTO accounts (name,section,line_item_id,is_system,sort_order) VALUES (?,?,?,?,?)",
            (name, section, li_id, is_sys, srt),
        )


def _seed_payment_accounts(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM payment_accounts").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO payment_accounts (name,account_type,is_system) VALUES (?,?,1)",
        PAYMENT_ACCOUNTS_SEED,
    )


def _run_migrations(conn) -> None:
    """Idempotent — safe to run on every startup.
    Inserts any line items / accounts that were added after initial release."""
    fy_cols = {r[1] for r in conn.execute("PRAGMA table_info(fy_archive)").fetchall()}
    if "opening_balance" not in fy_cols:
        conn.execute("ALTER TABLE fy_archive ADD COLUMN opening_balance REAL DEFAULT 0")

    conn.execute(
        "UPDATE line_items SET name='Balance' WHERE name='Net (Income - Expenses)' AND section='totals'"
    )
    conn.execute(
        "INSERT OR IGNORE INTO line_items (section,name,is_calculated,is_system,sort_order) "
        "VALUES ('totals','Cash Position',1,1,30)"
    )

    # 1. Add missing line items (INSERT OR IGNORE respects UNIQUE(section,name))
    conn.executemany(
        "INSERT OR IGNORE INTO line_items "
        "(section,name,is_calculated,is_system,sort_order) VALUES (?,?,?,?,?)",
        _MIGRATION_LINE_ITEMS,
    )
    # 2. Add missing accounts and fix any with NULL line_item_id
    for name, section, li_name, is_sys, srt in ACCOUNTS_SEED:
        row = conn.execute(
            "SELECT id FROM line_items WHERE name=? AND section=?", (li_name, section)
        ).fetchone()
        if not row:
            row = conn.execute("SELECT id FROM line_items WHERE name=?", (li_name,)).fetchone()
        li_id = row["id"] if row else None
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(name,section,line_item_id,is_system,sort_order) VALUES (?,?,?,?,?)",
            (name, section, li_id, is_sys, srt),
        )
        # Fix any existing account that was inserted with NULL line_item_id
        if li_id:
            conn.execute(
                "UPDATE accounts SET line_item_id=? WHERE name=? AND section=? AND line_item_id IS NULL",
                (li_id, name, section),
            )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
    if "image_url" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN image_url TEXT DEFAULT ''")


# ---------------------------------------------------------------------------
# Line item queries
# ---------------------------------------------------------------------------

def list_line_items() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM line_items ORDER BY "
            "CASE section WHEN 'income' THEN 1 WHEN 'employee' THEN 2 "
            "WHEN 'office' THEN 3 WHEN 'admin' THEN 4 WHEN 'travel' THEN 5 "
            "WHEN 'investment' THEN 6 ELSE 7 END, sort_order"
        ).fetchall()]


def add_line_item(section: str, name: str) -> int:
    """Add a user-defined line item (e.g. extra comp line)."""
    with get_db() as conn:
        # Insert before the section total (sort_order 90, total is 99)
        cur = conn.execute(
            "INSERT OR IGNORE INTO line_items (section,name,is_calculated,is_system,sort_order) "
            "VALUES (?,?,0,0,90)",
            (section, name),
        )
        return cur.lastrowid


def delete_line_item(lid: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM line_items WHERE id=? AND is_system=0", (lid,))


# ---------------------------------------------------------------------------
# Budget grid
# ---------------------------------------------------------------------------

def get_budget_grid(fiscal_year: int) -> dict:
    """{(line_item_id, month): amount}"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT line_item_id, month, amount FROM budget WHERE fiscal_year=?",
            (fiscal_year,)
        ).fetchall()
    return {(r["line_item_id"], r["month"]): r["amount"] for r in rows}


def save_budget_grid(fiscal_year: int, values: dict) -> None:
    """{"{lid}_{month}": amount}"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        for key, amount in values.items():
            lid, month = map(int, key.split("_"))
            conn.execute(
                """INSERT INTO budget (line_item_id,fiscal_year,month,amount,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(line_item_id,fiscal_year,month)
                   DO UPDATE SET amount=excluded.amount,updated_at=excluded.updated_at""",
                (lid, fiscal_year, month, amount, now),
            )


# ---------------------------------------------------------------------------
# Actuals: transaction rollup + manual
# ---------------------------------------------------------------------------

def get_transaction_rollup(fiscal_year: int) -> dict:
    """{(line_item_id, month): sum_amount} from transactions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT a.line_item_id, t.month, SUM(t.amount) AS total
               FROM transactions t
               JOIN accounts a ON t.account_id = a.id
               WHERE t.fiscal_year=? AND a.line_item_id IS NOT NULL
               GROUP BY a.line_item_id, t.month""",
            (fiscal_year,)
        ).fetchall()
    return {(r["line_item_id"], r["month"]): r["total"] for r in rows}


def get_actuals_manual(fiscal_year: int) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT line_item_id, month, amount FROM actuals_manual WHERE fiscal_year=?",
            (fiscal_year,)
        ).fetchall()
    return {(r["line_item_id"], r["month"]): r["amount"] for r in rows}


def save_actuals_manual(fiscal_year: int, values: dict) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        for key, amount in values.items():
            lid, month = map(int, key.split("_"))
            conn.execute(
                """INSERT INTO actuals_manual (line_item_id,fiscal_year,month,amount,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(line_item_id,fiscal_year,month)
                   DO UPDATE SET amount=excluded.amount,updated_at=excluded.updated_at""",
                (lid, fiscal_year, month, amount, now),
            )


def compute_grid(raw: dict, items: list[dict], opening_balance: float = 0.0) -> dict:
    """Add calculated rows to a raw {(lid,month): amount} grid.
    Balance = monthly income − expenses. Cash Position = opening + cumulative balance."""
    result = dict(raw)
    by_name = {i["name"]: i["id"] for i in items}

    def sec_sum(section: str, month: int) -> float:
        return sum(
            result.get((i["id"], month), 0)
            for i in items
            if i["section"] == section and not i["is_calculated"]
        )

    cash = opening_balance
    for month in FY_MONTHS:
        ti  = sec_sum("income",     month)
        tec = sec_sum("employee",   month)
        toc = sec_sum("office",     month)
        tad = sec_sum("admin",      month)
        ttr = sec_sum("travel",     month)
        tin = sec_sum("investment", month)
        tex = tec + toc + tad + ttr + tin
        net = ti - tex
        cash = cash + net

        for name, val in [
            ("Total Income",         ti),
            ("Total Employee Costs", tec),
            ("Total Office Costs",   toc),
            ("Total Admin",          tad),
            ("Total Travel",         ttr),
            ("Total Investment",     tin),
            ("Total Expenses",       tex),
            ("Balance",              net),
            ("Cash Position",        cash),
        ]:
            if name in by_name:
                result[(by_name[name], month)] = val

    return result


def get_opening_balance(fiscal_year: int) -> float:
    with get_db() as conn:
        row = conn.execute(
            "SELECT opening_balance FROM fy_archive WHERE fiscal_year=?", (fiscal_year,)
        ).fetchone()
        return float(row["opening_balance"]) if row and row["opening_balance"] else 0.0


def save_opening_balance(fiscal_year: int, amount: float) -> None:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT fiscal_year FROM fy_archive WHERE fiscal_year=?", (fiscal_year,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE fy_archive SET opening_balance=? WHERE fiscal_year=?",
                (amount, fiscal_year),
            )
        else:
            conn.execute(
                "INSERT INTO fy_archive (fiscal_year, opening_balance) VALUES (?, ?)",
                (fiscal_year, amount),
            )


# ---------------------------------------------------------------------------
# Fiscal year helpers
# ---------------------------------------------------------------------------

def get_fiscal_years() -> list[int]:
    from datetime import date
    today = date.today()
    current = today.year + 1 if today.month >= 4 else today.year
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT fiscal_year FROM budget "
            "UNION SELECT DISTINCT fiscal_year FROM transactions"
        ).fetchall()
    return sorted({r[0] for r in rows} | {current}, reverse=True)


def is_archived(fiscal_year: int) -> bool:
    with get_db() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM fy_archive WHERE fiscal_year=?", (fiscal_year,)
        ).fetchone())


def archive_year(fiscal_year: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO fy_archive (fiscal_year,archived_at) VALUES (?,?)",
            (fiscal_year, now),
        )


def unarchive_year(fiscal_year: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM fy_archive WHERE fiscal_year=?", (fiscal_year,))


# ---------------------------------------------------------------------------
# Account / Vendor / Payment account queries
# ---------------------------------------------------------------------------

def list_accounts() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT a.*, l.name AS line_item_name FROM accounts a "
            "LEFT JOIN line_items l ON a.line_item_id = l.id "
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


def save_vendor(name: str, email: str, phone: str, notes: str, vid: int = None) -> int:
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


def save_account(name: str, section: str, line_item_id: int = None, aid: int = None) -> int:
    with get_db() as conn:
        if aid:
            conn.execute(
                "UPDATE accounts SET name=?,section=?,line_item_id=? WHERE id=?",
                (name, section, line_item_id, aid)
            )
            return aid
        mx = conn.execute("SELECT MAX(sort_order) FROM accounts").fetchone()[0] or 0
        cur = conn.execute(
            "INSERT INTO accounts (name,section,line_item_id,is_system,sort_order) VALUES (?,?,?,0,?)",
            (name, section, line_item_id, mx + 10)
        )
        return cur.lastrowid


def delete_account(aid: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM accounts WHERE id=? AND is_system=0", (aid,))


def save_payment_account(name: str, account_type: str, paid: int = None) -> int:
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
        conn.execute(
            "DELETE FROM payment_accounts WHERE id=? AND is_system=0", (paid,)
        )

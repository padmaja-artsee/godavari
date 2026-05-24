"""
Finance module database — fully independent from Leads.
Fiscal year = April–March (Indian FY). FY27 = Apr 2026 – Mar 2027.
All monetary values stored in USD $1000s to match the source template.
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
    # Packaged app → same user data dir as Leads
    data_env = os.environ.get("LEADS_DATA_DIR")
    if data_env:
        return Path(data_env) / "finance.db"
    # Source / dev
    return Path(__file__).resolve().parent.parent.parent / "data" / "finance.db"

DB_PATH = _get_db_path()


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

# Fiscal month order: Apr=1 … Mar=12 within the FY
FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
MONTH_LABELS = {
    4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep",
    10: "Oct", 11: "Nov", 12: "Dec", 1: "Jan", 2: "Feb", 3: "Mar",
}


def calendar_year_for(fiscal_year: int, month: int) -> int:
    """Return the calendar year for a given FY and calendar month.
    FY27 Apr–Dec → 2026;  FY27 Jan–Mar → 2027.
    """
    if month >= 4:
        return fiscal_year - 1
    return fiscal_year


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

PL_LINES = [
    # (name, section, is_calculated, sort_order)
    # INCOME
    ("Revenue",                     "income",        0, 10),
    ("Increase / Decrease in Stock","income",        0, 20),
    ("Other Income",                "income",        0, 30),
    ("Total Income",                "income_total",  1, 40),
    # EXPENSES
    ("Raw Material Cost",           "expense",       0, 50),
    ("Power & Fuel Cost",           "expense",       0, 60),
    ("Stores, Spares & Chemicals",  "expense",       0, 70),
    ("Packing Cost",                "expense",       0, 80),
    ("Repairs & Maintenance",       "expense",       0, 90),
    ("Employee Cost",               "expense",       0, 100),
    ("Selling Expenses",            "expense",       0, 110),
    ("General & Admin Expenses",    "expense",       0, 120),
    ("Total Expenses",              "expense_total", 1, 130),
    # BELOW-LINE
    ("EBITDA",                      "ebitda",        1, 140),
    ("Interest",                    "below_ebitda",  0, 150),
    ("Depreciation",                "below_ebitda",  0, 160),
    ("EBT",                         "ebt",           1, 170),
    ("Extraordinary Items",         "below_ebitda",  0, 180),
    ("Net EBT",                     "net_ebt",       1, 190),
]


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pl_lines (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL UNIQUE,
                section      TEXT    NOT NULL,
                is_calculated INTEGER NOT NULL DEFAULT 0,
                sort_order   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS budget (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                pl_line_id   INTEGER NOT NULL REFERENCES pl_lines(id),
                fiscal_year  INTEGER NOT NULL,
                month        INTEGER NOT NULL,   -- calendar month 1-12
                amount       REAL    NOT NULL DEFAULT 0,
                updated_at   TEXT,
                UNIQUE(pl_line_id, fiscal_year, month)
            );

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
        # Seed P&L lines if empty
        count = conn.execute("SELECT COUNT(*) FROM pl_lines").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO pl_lines (name, section, is_calculated, sort_order) VALUES (?,?,?,?)",
                PL_LINES,
            )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def list_pl_lines() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM pl_lines ORDER BY sort_order"
        ).fetchall()]


def get_grid(table: str, fiscal_year: int) -> dict[tuple, float]:
    """Return {(pl_line_id, month): amount} for the given year."""
    assert table in ("budget", "actuals")
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT pl_line_id, month, amount FROM {table} WHERE fiscal_year = ?",
            (fiscal_year,)
        ).fetchall()
    return {(r["pl_line_id"], r["month"]): r["amount"] for r in rows}


def save_grid(table: str, fiscal_year: int, values: dict[str, float]) -> None:
    """values: {"<pl_line_id>_<month>": amount, ...}"""
    assert table in ("budget", "actuals")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        for key, amount in values.items():
            line_id, month = map(int, key.split("_"))
            conn.execute(
                f"""INSERT INTO {table} (pl_line_id, fiscal_year, month, amount, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(pl_line_id, fiscal_year, month)
                    DO UPDATE SET amount=excluded.amount, updated_at=excluded.updated_at""",
                (line_id, fiscal_year, month, amount, now),
            )


def computed_grid(raw: dict[tuple, float], lines: list[dict]) -> dict[tuple, float]:
    """Add calculated rows (totals, EBITDA, EBT) to a raw grid."""
    result = dict(raw)
    by_name = {l["name"]: l["id"] for l in lines}

    income_lines  = [l["id"] for l in lines if l["section"] == "income"]
    expense_lines = [l["id"] for l in lines if l["section"] == "expense"]

    ti_id   = by_name.get("Total Income")
    te_id   = by_name.get("Total Expenses")
    eb_id   = by_name.get("EBITDA")
    int_id  = by_name.get("Interest")
    dep_id  = by_name.get("Depreciation")
    ebt_id  = by_name.get("EBT")
    ext_id  = by_name.get("Extraordinary Items")
    net_id  = by_name.get("Net EBT")

    for month in FY_MONTHS:
        ti  = sum(result.get((lid, month), 0) for lid in income_lines)
        te  = sum(result.get((lid, month), 0) for lid in expense_lines)
        eb  = ti - te
        interest   = result.get((int_id,  month), 0)
        depreciation = result.get((dep_id, month), 0)
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
    """Return all fiscal years that have any budget or actuals data, plus current."""
    from datetime import date
    today = date.today()
    current_fy = today.year + 1 if today.month >= 4 else today.year
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT fiscal_year FROM budget UNION SELECT DISTINCT fiscal_year FROM actuals"
        ).fetchall()
    years = sorted({r[0] for r in rows} | {current_fy}, reverse=True)
    return years

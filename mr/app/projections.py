"""Sales projections by fiscal year for Management Report.

Fiscal year follows the Finance convention: FY ending year
(e.g. 2027 = Apr 2026 – Mar 2027 = FY 26-27).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import get_data_dir

# Default product lines used when creating a new fiscal-year projection.
DEFAULT_PRODUCTS = [
    "Ethyl Acetate",
    "MPO",
    "Bio Ethyl Acetate",
    "Bio Acetic Acid",
    "EVE",
    "1,3 BG",
    "Crotonaldehyde",
    "n-Butanol",
    "Ethyl Lactate",
    "Triacetin",
]

# FY 2026-27 (Target) from Volume Derivables for Management Report.
FY_26_27_TARGETS = [
    ("Ethyl Acetate", 150, 126482, 3850),
    ("MPO", 1500, 4047367, 121420),
    ("Bio Ethyl Acetate", 200, 400000, 20000),
    ("Bio Acetic Acid", 70, 90100, 7000),
    ("EVE", 20, 80000, 4000),
    ("1,3 BG", 20, 80000, 4000),
    ("Crotonaldehyde", 0, None, 0),
    ("n-Butanol", 0, None, 0),
    ("Ethyl Lactate", 0, None, 0),
    ("Triacetin", 0, None, 0),
]


def projections_db_path() -> Path:
    d = get_data_dir() / "mr"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sales_projections.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(projections_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_projection_years (
                fiscal_year INTEGER PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_projection_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year INTEGER NOT NULL,
                product TEXT NOT NULL,
                qty_mt REAL,
                sales_value REAL,
                income REAL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(fiscal_year, product),
                FOREIGN KEY(fiscal_year) REFERENCES sales_projection_years(fiscal_year)
            )
            """
        )
        conn.commit()


def init_projections() -> None:
    _ensure_schema()
    ensure_fy_26_27_seeded()


def fy_label(fiscal_year: int) -> str:
    """2027 → 'FY 26-27'."""
    start = fiscal_year - 1
    return f"FY {start % 100:02d}-{fiscal_year % 100:02d}"


def fy_title(fiscal_year: int) -> str:
    """2027 → 'Fiscal Year 2026-27 (Target)'."""
    start = fiscal_year - 1
    return f"Fiscal Year {start}-{fiscal_year % 100:02d} (Target)"


def list_projection_years() -> list[int]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT fiscal_year FROM sales_projection_years ORDER BY fiscal_year DESC"
        ).fetchall()
    return [int(r["fiscal_year"]) for r in rows]


def get_projection(fiscal_year: int) -> dict[str, Any] | None:
    _ensure_schema()
    with _connect() as conn:
        year = conn.execute(
            "SELECT * FROM sales_projection_years WHERE fiscal_year = ?",
            (fiscal_year,),
        ).fetchone()
        if not year:
            return None
        lines = conn.execute(
            """
            SELECT * FROM sales_projection_lines
            WHERE fiscal_year = ?
            ORDER BY sort_order, id
            """,
            (fiscal_year,),
        ).fetchall()
    line_dicts = [dict(r) for r in lines]
    totals = {
        "qty_mt": sum((r.get("qty_mt") or 0) for r in line_dicts),
        "sales_value": sum((r.get("sales_value") or 0) for r in line_dicts),
        "income": sum((r.get("income") or 0) for r in line_dicts),
    }
    return {
        "fiscal_year": fiscal_year,
        "label": fy_label(fiscal_year),
        "title": year["title"] or fy_title(fiscal_year),
        "lines": line_dicts,
        "totals": totals,
    }


def save_projection_year(
    fiscal_year: int,
    lines: list[dict[str, Any]],
    *,
    title: str | None = None,
) -> None:
    """Create or replace all projection lines for a fiscal year."""
    _ensure_schema()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sales_projection_years WHERE fiscal_year = ?",
            (fiscal_year,),
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE sales_projection_years SET title = COALESCE(?, title) WHERE fiscal_year = ?",
                (title, fiscal_year),
            )
            conn.execute(
                "DELETE FROM sales_projection_lines WHERE fiscal_year = ?",
                (fiscal_year,),
            )
        else:
            conn.execute(
                """
                INSERT INTO sales_projection_years (fiscal_year, title, created_at)
                VALUES (?, ?, ?)
                """,
                (fiscal_year, title or fy_title(fiscal_year), now),
            )
        for i, line in enumerate(lines):
            product = (line.get("product") or "").strip()
            if not product:
                continue
            conn.execute(
                """
                INSERT INTO sales_projection_lines
                  (fiscal_year, product, qty_mt, sales_value, income, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fiscal_year,
                    product,
                    line.get("qty_mt"),
                    line.get("sales_value"),
                    line.get("income"),
                    line.get("sort_order", i),
                ),
            )
        conn.commit()


def create_blank_projection(fiscal_year: int) -> dict[str, Any]:
    """Add a new fiscal year with default products and zero targets."""
    lines = [
        {
            "product": p,
            "qty_mt": 0,
            "sales_value": None,
            "income": 0,
            "sort_order": i,
        }
        for i, p in enumerate(DEFAULT_PRODUCTS)
    ]
    save_projection_year(fiscal_year, lines, title=fy_title(fiscal_year))
    return get_projection(fiscal_year)  # type: ignore[return-value]


def ensure_fy_26_27_seeded() -> None:
    """Seed FY 2026-27 (ending 2027) targets once if missing."""
    fy = 2027
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sales_projection_years WHERE fiscal_year = ?", (fy,)
        ).fetchone()
        if exists:
            return
    lines = [
        {
            "product": product,
            "qty_mt": qty,
            "sales_value": sales,
            "income": income,
            "sort_order": i,
        }
        for i, (product, qty, sales, income) in enumerate(FY_26_27_TARGETS)
    ]
    save_projection_year(fy, lines, title=fy_title(fy))


def update_projection_lines(fiscal_year: int, posted: list[dict[str, Any]]) -> None:
    """Update existing lines from an edit form (matched by id)."""
    _ensure_schema()
    with _connect() as conn:
        for item in posted:
            row_id = item.get("id")
            if not row_id:
                continue
            conn.execute(
                """
                UPDATE sales_projection_lines
                SET product = ?, qty_mt = ?, sales_value = ?, income = ?
                WHERE id = ? AND fiscal_year = ?
                """,
                (
                    (item.get("product") or "").strip(),
                    item.get("qty_mt"),
                    item.get("sales_value"),
                    item.get("income"),
                    int(row_id),
                    fiscal_year,
                ),
            )
        conn.commit()


def _parse_optional_float(raw: Any):
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "").strip())
    except ValueError:
        return None

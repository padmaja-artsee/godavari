from typing import Optional
"""Expense CRUD and receipt file management."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from finance.app.database import (
    fiscal_year_for_date, get_db, get_receipts_dir,
)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Receipt file helpers
# ---------------------------------------------------------------------------

def save_receipt(file_bytes: bytes, original_name: str) -> str:
    """Save receipt bytes, return the stored filename (not full path)."""
    receipts_dir = get_receipts_dir()
    receipts_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        suffix = ".pdf"
    fname = f"{uuid.uuid4().hex}{suffix}"
    (receipts_dir / fname).write_bytes(file_bytes)
    return fname


def delete_receipt(filename: str) -> None:
    if not filename:
        return
    path = get_receipts_dir() / filename
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def receipt_path(filename: str) -> Path:
    return get_receipts_dir() / filename


# ---------------------------------------------------------------------------
# Expense CRUD
# ---------------------------------------------------------------------------

def list_expenses(
    fiscal_year: "int | None" = None,
    account_id: "int | None" = None,
    vendor_id: "int | None" = None,
    limit: int = 500,
) -> list[dict]:
    clauses = []
    params: list = []
    if fiscal_year:
        clauses.append("e.fiscal_year = ?")
        params.append(fiscal_year)
    if account_id:
        clauses.append("e.account_id = ?")
        params.append(account_id)
    if vendor_id:
        clauses.append("e.vendor_id = ?")
        params.append(vendor_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT e.*,
               a.name  AS account_name,
               a.group_label,
               v.name  AS vendor_name,
               p.name  AS payment_account_name
        FROM expenses e
        JOIN accounts a          ON e.account_id = a.id
        LEFT JOIN vendors v      ON e.vendor_id  = v.id
        LEFT JOIN payment_accounts p ON e.payment_account_id = p.id
        {where}
        ORDER BY e.date DESC, e.id DESC
        LIMIT ?
    """
    params.append(limit)
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_expense(expense_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT e.*,
                      a.name  AS account_name,
                      a.group_label,
                      v.name  AS vendor_name,
                      p.name  AS payment_account_name
               FROM expenses e
               JOIN accounts a          ON e.account_id = a.id
               LEFT JOIN vendors v      ON e.vendor_id  = v.id
               LEFT JOIN payment_accounts p ON e.payment_account_id = p.id
               WHERE e.id = ?""",
            (expense_id,)
        ).fetchone()
    return dict(row) if row else None


def create_expense(
    date: str,
    account_id: int,
    amount: float,
    currency: str = "USD",
    payment_account_id: "int | None" = None,
    vendor_id: "int | None" = None,
    reference: str = "",
    notes: str = "",
    receipt_filename: str = "",
) -> int:
    fy, month = fiscal_year_for_date(date)
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO expenses
               (date, account_id, amount, currency, payment_account_id,
                vendor_id, reference, notes, receipt_filename,
                fiscal_year, month, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (date, account_id, amount, currency, payment_account_id,
             vendor_id, reference, notes, receipt_filename,
             fy, month, now, now)
        )
        return cur.lastrowid


def update_expense(
    expense_id: int,
    date: str,
    account_id: int,
    amount: float,
    currency: str = "USD",
    payment_account_id: "int | None" = None,
    vendor_id: "int | None" = None,
    reference: str = "",
    notes: str = "",
    receipt_filename: "str | None" = None,
) -> None:
    fy, month = fiscal_year_for_date(date)
    now = _now()
    with get_db() as conn:
        if receipt_filename is not None:
            conn.execute(
                """UPDATE expenses SET date=?,account_id=?,amount=?,currency=?,
                   payment_account_id=?,vendor_id=?,reference=?,notes=?,
                   receipt_filename=?,fiscal_year=?,month=?,updated_at=?
                   WHERE id=?""",
                (date, account_id, amount, currency, payment_account_id,
                 vendor_id, reference, notes, receipt_filename,
                 fy, month, now, expense_id)
            )
        else:
            conn.execute(
                """UPDATE expenses SET date=?,account_id=?,amount=?,currency=?,
                   payment_account_id=?,vendor_id=?,reference=?,notes=?,
                   fiscal_year=?,month=?,updated_at=?
                   WHERE id=?""",
                (date, account_id, amount, currency, payment_account_id,
                 vendor_id, reference, notes, fy, month, now, expense_id)
            )


def delete_expense(expense_id: int) -> None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT receipt_filename FROM expenses WHERE id=?", (expense_id,)
        ).fetchone()
        if row and row["receipt_filename"]:
            delete_receipt(row["receipt_filename"])
        conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))

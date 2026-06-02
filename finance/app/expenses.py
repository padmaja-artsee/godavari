"""Transaction CRUD (expenses + income) and receipt file management."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path

from finance.app.database import fiscal_year_for_date, get_db, get_receipts_dir

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_receipt(file_bytes: bytes, original_name: str) -> str:
    rd = get_receipts_dir()
    rd.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        suffix = ".pdf"
    fname = f"{uuid.uuid4().hex}{suffix}"
    (rd / fname).write_bytes(file_bytes)
    return fname


def delete_receipt(filename: str) -> None:
    if not filename:
        return
    try:
        (get_receipts_dir() / filename).unlink(missing_ok=True)
    except Exception:
        pass


def receipt_path(filename: str) -> Path:
    return get_receipts_dir() / filename


def list_transactions(
    fiscal_year: int = None,
    transaction_type: str = None,
    account_id: int = None,
    vendor_id: int = None,
    limit: int = 500,
) -> list[dict]:
    clauses, params = [], []
    if fiscal_year:
        clauses.append("t.fiscal_year=?"); params.append(fiscal_year)
    if transaction_type:
        clauses.append("t.transaction_type=?"); params.append(transaction_type)
    if account_id:
        clauses.append("t.account_id=?"); params.append(account_id)
    if vendor_id:
        clauses.append("t.vendor_id=?"); params.append(vendor_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT t.*, a.name AS account_name, a.section AS account_section,
               v.name AS vendor_name, p.name AS payment_account_name
        FROM transactions t
        JOIN accounts a ON t.account_id=a.id
        LEFT JOIN vendors v ON t.vendor_id=v.id
        LEFT JOIN payment_accounts p ON t.payment_account_id=p.id
        {where}
        ORDER BY t.date DESC, t.id DESC LIMIT ?
    """
    params.append(limit)
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_transaction(tx_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """SELECT t.*, a.name AS account_name, v.name AS vendor_name,
                      p.name AS payment_account_name
               FROM transactions t
               JOIN accounts a ON t.account_id=a.id
               LEFT JOIN vendors v ON t.vendor_id=v.id
               LEFT JOIN payment_accounts p ON t.payment_account_id=p.id
               WHERE t.id=?""", (tx_id,)
        ).fetchone()
    return dict(row) if row else None


def create_transaction(
    date: str, account_id: int, amount: float,
    currency: str = "USD", transaction_type: str = "expense",
    payment_account_id: int = None, vendor_id: int = None,
    reference: str = "", notes: str = "", receipt_filename: str = "",
    image_url: str = "",
) -> int:
    fy, month = fiscal_year_for_date(date)
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO transactions
               (date,account_id,amount,currency,transaction_type,
                payment_account_id,vendor_id,reference,notes,
                receipt_filename,image_url,fiscal_year,month,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (date, account_id, amount, currency, transaction_type,
             payment_account_id, vendor_id, reference, notes,
             receipt_filename, (image_url or "").strip(), fy, month, now, now)
        )
        return cur.lastrowid


def update_transaction(
    tx_id: int, date: str, account_id: int, amount: float,
    currency: str = "USD", transaction_type: str = "expense",
    payment_account_id: int = None, vendor_id: int = None,
    reference: str = "", notes: str = "", receipt_filename: str = None,
    image_url: str = "",
) -> None:
    fy, month = fiscal_year_for_date(date)
    now = _now()
    img = (image_url or "").strip()
    with get_db() as conn:
        if receipt_filename is not None:
            conn.execute(
                """UPDATE transactions SET date=?,account_id=?,amount=?,currency=?,
                   transaction_type=?,payment_account_id=?,vendor_id=?,reference=?,
                   notes=?,receipt_filename=?,image_url=?,fiscal_year=?,month=?,updated_at=?
                   WHERE id=?""",
                (date, account_id, amount, currency, transaction_type,
                 payment_account_id, vendor_id, reference, notes,
                 receipt_filename, img, fy, month, now, tx_id)
            )
        else:
            conn.execute(
                """UPDATE transactions SET date=?,account_id=?,amount=?,currency=?,
                   transaction_type=?,payment_account_id=?,vendor_id=?,reference=?,
                   notes=?,image_url=?,fiscal_year=?,month=?,updated_at=?
                   WHERE id=?""",
                (date, account_id, amount, currency, transaction_type,
                 payment_account_id, vendor_id, reference, notes,
                 img, fy, month, now, tx_id)
            )


def delete_transaction(tx_id: int) -> None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT receipt_filename FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if row and row["receipt_filename"]:
            delete_receipt(row["receipt_filename"])
        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))

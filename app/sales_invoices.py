"""Commercial (Sales) Invoice — standalone module.

To remove this feature entirely:
  1. Delete app/sales_invoices.py, app/si_exports.py
  2. Delete templates/generate/sales_invoices/
  3. Delete static/si_wysiwyg.js, static/si_wysiwyg.css
  4. Remove the SI entry from app/generate.py
  5. Remove the "── Sales Invoice routes ──" block in app/main.py
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from typing import Any

from app.database import get_db, now_iso


# ── helpers ──────────────────────────────────────────────────────────────────

def _float(v, default: float = 0.0) -> float:
    try:
        return float(str(v or "").replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def form_getlist(form: Any, name: str) -> list[str]:
    """Works with both Starlette FormData (getlist) and plain dicts."""
    if hasattr(form, "getlist"):
        return form.getlist(name)
    v = form.get(name, [])
    return v if isinstance(v, list) else [v]


# ── defaults ─────────────────────────────────────────────────────────────────

SI_SCALAR_FIELDS = [
    "document_title", "company_name",
    "invoice_number", "invoice_date",
    # Bill-to
    "bill_to_name", "bill_to_address_1", "bill_to_address_2", "bill_to_address_3",
    "bill_to_vat", "customer_order_no", "customer_material_code",
    # Transaction
    "transaction_description",
    # Delivery
    "delivery_address", "delivery_vat", "delivery_date",
    "iso_tank_number", "cleaning_cert_number",
    # Product section extras
    "brand_name", "incoterms", "delivery_note_number", "batch_numbers",
    # Table units (editable in header)
    "qty_unit", "rate_currency", "rate_unit", "value_currency",
    # Totals & terms
    "amount_in_words", "terms_of_delivery", "payment_terms", "enclosures",
    # Bank
    "bank_name", "bank_account_no", "bank_iban", "bank_bic",
    # Admin
    "status", "prepared_by", "internal_notes",
]

DEFAULT_SI: dict[str, Any] = {
    "document_title":        "COMMERCIAL INVOICE",
    "company_name":          "Godavari Biorefineries Inc",
    "invoice_number":        "",
    "invoice_date":          date.today().isoformat(),
    # Bill-to
    "bill_to_name":          "",
    "bill_to_address_1":     "",
    "bill_to_address_2":     "",
    "bill_to_address_3":     "",
    "bill_to_vat":           "",
    "customer_order_no":     "",
    "customer_material_code": "",
    # Transaction
    "transaction_description": "",
    # Delivery
    "delivery_address":      "",
    "delivery_vat":          "",
    "delivery_date":         "",
    "iso_tank_number":       "",
    "cleaning_cert_number":  "",
    # Product section extras
    "brand_name":            "",
    "incoterms":             "",
    "delivery_note_number":  "",
    "batch_numbers":         "",
    # Table units
    "qty_unit":              "MT",
    "rate_currency":         "Euro",
    "rate_unit":             "MT",
    "value_currency":        "Euro",
    # Totals & terms
    "vat_percent":           0,
    "amount_in_words":       "",
    "terms_of_delivery":     "",
    "payment_terms":         "End of Month 60 days",
    "enclosures":            "a)  Delivery Note\nb)  Batch Certificate",
    # Bank
    "bank_name":             "RABO BANK - HAARLEM",
    "bank_account_no":       "Account no 0311323650",
    "bank_iban":             "NL83RABO0311323650",
    "bank_bic":              "RABONL2U",
    # Admin
    "status":                "Draft",
    "prepared_by":           "",
    "internal_notes":        "",
    # Lines
    "line_items": [
        {
            "product_description": "",
            "quantity":            0.0,
            "rate":                0.0,
            "value":               0.0,
            "remark":              "",
        }
    ],
}


# ── calculations ─────────────────────────────────────────────────────────────

def recalc_si_line(line: dict[str, Any]) -> dict[str, Any]:
    line = dict(line)
    qty  = _float(line.get("quantity"))
    rate = _float(line.get("rate"))
    line["value"] = round(qty * rate, 2) if qty and rate else 0.0
    return line


def calculate_si_totals(
    line_items: list[dict[str, Any]],
    vat_percent: float = 0,
) -> dict[str, Any]:
    lines     = [recalc_si_line(li) for li in line_items]
    net_value = round(sum(_float(l.get("value")) for l in lines), 2)
    vat_amt   = round(net_value * vat_percent / 100, 2)
    total_pay = round(net_value + vat_amt, 2)
    return {
        "line_items": lines,
        "net_value":  net_value,
        "vat_amount": vat_amt,
        "total_to_pay": total_pay,
    }


# ── schema ────────────────────────────────────────────────────────────────────

# Extra columns added after initial creation — migrated automatically
SI_EXTRA_COLS: list[str] = []   # nothing extra yet


def _upgrade_si_extra_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sales_invoices)").fetchall()}
    for col in SI_EXTRA_COLS:
        if col not in cols:
            conn.execute(f"ALTER TABLE sales_invoices ADD COLUMN {col} TEXT")


def upgrade_sales_invoices_schema() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sales_invoices (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_document_id   INTEGER,
                deal_id                 INTEGER,
                customer_id             INTEGER,
                document_title          TEXT,
                company_name            TEXT,
                invoice_number          TEXT,
                invoice_date            TEXT,
                bill_to_name            TEXT,
                bill_to_address_1       TEXT,
                bill_to_address_2       TEXT,
                bill_to_address_3       TEXT,
                bill_to_vat             TEXT,
                customer_order_no       TEXT,
                customer_material_code  TEXT,
                transaction_description TEXT,
                delivery_address        TEXT,
                delivery_vat            TEXT,
                delivery_date           TEXT,
                iso_tank_number         TEXT,
                cleaning_cert_number    TEXT,
                brand_name              TEXT,
                incoterms               TEXT,
                delivery_note_number    TEXT,
                batch_numbers           TEXT,
                qty_unit                TEXT,
                rate_currency           TEXT,
                rate_unit               TEXT,
                value_currency          TEXT,
                vat_percent             REAL DEFAULT 0,
                amount_in_words         TEXT,
                terms_of_delivery       TEXT,
                payment_terms           TEXT,
                enclosures              TEXT,
                bank_name               TEXT,
                bank_account_no         TEXT,
                bank_iban               TEXT,
                bank_bic                TEXT,
                status                  TEXT DEFAULT 'Draft',
                prepared_by             TEXT,
                internal_notes          TEXT,
                created_at              TEXT,
                updated_at              TEXT,
                FOREIGN KEY(generated_document_id) REFERENCES generated_documents(id),
                FOREIGN KEY(deal_id)    REFERENCES deals(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS sales_invoice_line_items (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                sales_invoice_id  INTEGER NOT NULL,
                product_description TEXT,
                quantity          REAL,
                rate              REAL,
                value             REAL,
                remark            TEXT,
                sort_order        INTEGER DEFAULT 0,
                FOREIGN KEY(sales_invoice_id) REFERENCES sales_invoices(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_si_deal ON sales_invoices(deal_id);
            """
        )
        _upgrade_si_extra_columns(conn)


# ── form parsing ──────────────────────────────────────────────────────────────

def parse_si_form(form: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data: dict[str, Any] = {f: (form.get(f) or "").strip() for f in SI_SCALAR_FIELDS}
    data["vat_percent"] = _float(form.get("vat_percent"), 0)
    if not data.get("document_title"):
        data["document_title"] = "COMMERCIAL INVOICE"

    products = form_getlist(form, "product_description")
    text_fields    = ["remark"]
    numeric_fields = ["quantity", "rate"]

    line_items: list[dict[str, Any]] = []
    for i, product in enumerate(products):
        product = product.strip()
        if not product:
            continue
        line: dict[str, Any] = {"product_description": product}
        for tf in text_fields:
            vals = form_getlist(form, tf)
            line[tf] = (vals[i] if i < len(vals) else "").strip()
        for nf in numeric_fields:
            vals = form_getlist(form, nf)
            line[nf] = _float(vals[i] if i < len(vals) else 0)
        line_items.append(recalc_si_line(line))

    return data, line_items


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _load_si_rows(conn, si_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sales_invoices WHERE id = ?", (si_id,)).fetchone()
    if not row:
        return None
    si = dict(row)
    lines = conn.execute(
        "SELECT * FROM sales_invoice_line_items WHERE sales_invoice_id = ? ORDER BY sort_order, id",
        (si_id,),
    ).fetchall()
    si["line_items"] = [dict(l) for l in lines]
    totals = calculate_si_totals(si["line_items"], _float(si.get("vat_percent")))
    si.update(totals)
    return si


def list_sales_invoices() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT si.*, li.product_description AS product, li.value AS line_value
            FROM sales_invoices si
            LEFT JOIN sales_invoice_line_items li
              ON li.sales_invoice_id = si.id AND li.sort_order = 0
            ORDER BY si.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_sales_invoice(si_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        return _load_si_rows(conn, si_id)


def get_sales_invoice_for_export(si_id: int) -> dict[str, Any] | None:
    return get_sales_invoice(si_id)


def _save_si_lines(conn, si_id: int, line_items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM sales_invoice_line_items WHERE sales_invoice_id = ?", (si_id,))
    for sort_order, line in enumerate(line_items):
        conn.execute(
            """
            INSERT INTO sales_invoice_line_items
                (sales_invoice_id, product_description, quantity, rate, value, remark, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                si_id,
                line.get("product_description"), line.get("quantity"),
                line.get("rate"), line.get("value"), line.get("remark"),
                sort_order,
            ),
        )


def create_sales_invoice(
    data: dict[str, Any],
    line_items: list[dict[str, Any]],
    *,
    deal_id: int | None = None,
    customer_id: int | None = None,
) -> int:
    totals     = calculate_si_totals(line_items, _float(data.get("vat_percent")))
    line_items = totals["line_items"]
    now        = now_iso()

    with get_db() as conn:
        doc_cur = conn.execute(
            """
            INSERT INTO generated_documents
                (document_type, document_number, title, status, source_type, source_id, created_at, updated_at)
            VALUES ('sales_invoice', ?, ?, ?, 'manual', NULL, ?, ?)
            """,
            (data.get("invoice_number"), data.get("document_title") or "COMMERCIAL INVOICE",
             data.get("status") or "Draft", now, now),
        )
        gen_id = doc_cur.lastrowid

        cols = ", ".join(SI_SCALAR_FIELDS)
        placeholders = ", ".join("?" for _ in SI_SCALAR_FIELDS)
        vals = [data.get(f, "") for f in SI_SCALAR_FIELDS]

        cur = conn.execute(
            f"""
            INSERT INTO sales_invoices
                ({cols}, generated_document_id, deal_id, customer_id, created_at, updated_at)
            VALUES ({placeholders}, ?, ?, ?, ?, ?)
            """,
            (*vals, gen_id, deal_id, customer_id, now, now),
        )
        si_id = cur.lastrowid
        _save_si_lines(conn, si_id, line_items)
        return si_id


def update_sales_invoice(
    si_id: int, data: dict[str, Any], line_items: list[dict[str, Any]]
) -> None:
    totals     = calculate_si_totals(line_items, _float(data.get("vat_percent")))
    line_items = totals["line_items"]
    now        = now_iso()

    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM sales_invoices WHERE id = ?", (si_id,)
        ).fetchone()
        if not row:
            return

        set_clause = ", ".join(f"{f} = ?" for f in SI_SCALAR_FIELDS)
        vals = [data.get(f, "") for f in SI_SCALAR_FIELDS]
        conn.execute(
            f"UPDATE sales_invoices SET {set_clause}, updated_at = ? WHERE id = ?",
            (*vals, now, si_id),
        )
        _save_si_lines(conn, si_id, line_items)

        gen_id = row["generated_document_id"]
        if gen_id:
            conn.execute(
                """UPDATE generated_documents
                   SET document_number = ?, title = ?, status = ?, updated_at = ?
                   WHERE id = ?""",
                (data.get("invoice_number"), data.get("document_title") or "COMMERCIAL INVOICE",
                 data.get("status") or "Draft", now, gen_id),
            )


def duplicate_sales_invoice(si_id: int) -> int | None:
    si = get_sales_invoice(si_id)
    if not si:
        return None
    copy = deepcopy(si)
    copy["invoice_number"] = (copy.get("invoice_number") or "") + " (copy)"
    copy["status"] = "Draft"
    return create_sales_invoice(
        copy, copy.get("line_items") or [],
        deal_id=si.get("deal_id"), customer_id=si.get("customer_id"),
    )


def delete_sales_invoice(si_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM sales_invoices WHERE id = ?", (si_id,)
        ).fetchone()
        if not row:
            return False
        if row["generated_document_id"]:
            conn.execute(
                "DELETE FROM generated_documents WHERE id = ?", (row["generated_document_id"],)
            )
        return True


# ── deal prefill ──────────────────────────────────────────────────────────────

def _deal_to_si_line(d: dict) -> dict:
    """Build a single SI line item from a deal row dict."""
    price    = _float(d.get("price"))
    qty_raw  = d.get("quantity") or ""
    qty_nums = re.findall(r"\d+\.?\d*", qty_raw.replace(",", ""))
    qty      = float(qty_nums[0]) if qty_nums else 0.0
    line = deepcopy(DEFAULT_SI["line_items"][0])
    line["product_description"] = d.get("product") or ""
    line["quantity"] = qty
    line["rate"]     = price or 0.0
    line["value"]    = round(price * qty, 2) if price and qty else 0.0
    return line


def create_si_from_deals(deal_ids: list[int]) -> dict[str, Any] | None:
    """Prefill a Sales Invoice from one or more deals."""
    if not deal_ids:
        return None
    placeholders = ", ".join("?" for _ in deal_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT d.*, c.name AS company, p.name AS product,
                   p.hs_code AS product_hs_code
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products  p ON p.id = d.product_id
            WHERE d.id IN ({placeholders}) AND d.deleted_at IS NULL
            ORDER BY d.deal_date DESC
            """,
            deal_ids,
        ).fetchall()
    if not rows:
        return None

    si = deepcopy(DEFAULT_SI)
    first = dict(rows[0])

    # Header from first deal
    si["bill_to_name"]        = first.get("company") or ""
    si["customer_order_no"]   = first.get("po_number") or ""
    si["invoice_date"]        = date.today().isoformat()
    si["terms_of_delivery"]   = first.get("incoterms") or ""
    si["incoterms"]           = first.get("incoterms") or ""
    si["payment_terms"]       = first.get("payment_terms") or DEFAULT_SI["payment_terms"]
    si["delivery_note_number"] = first.get("gbl_invoice") or ""
    si["batch_numbers"]       = first.get("container_number") or ""
    si["delivery_address"]    = first.get("destination") or ""

    # Transaction description
    products = list({dict(r).get("product") or "" for r in rows if dict(r).get("product")})
    companies = list({dict(r).get("company") or "" for r in rows if dict(r).get("company")})
    bl = first.get("gbl_invoice") or ""
    si["transaction_description"] = (
        f"Sale of {', '.join(products)} to {', '.join(companies)}"
        + (f" — BL No: {bl}" if bl else "")
    )

    # Quantity unit from first deal
    qu = first.get("quantity_unit") or "MT"
    si["qty_unit"]  = qu
    si["rate_unit"] = qu

    # One line per deal
    si["line_items"] = [_deal_to_si_line(dict(r)) for r in rows]

    totals = calculate_si_totals(si["line_items"])
    si.update(totals)
    return si


def create_si_from_deal(deal_id: int) -> dict[str, Any] | None:
    return create_si_from_deals([deal_id])

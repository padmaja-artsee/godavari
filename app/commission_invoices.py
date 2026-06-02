"""Commission Invoice – storage, validation, and deal prefilling.

Self-contained module: no imports from purchase_orders.py or po_exports.py.
Remove this file + ci_exports.py + templates/generate/commission_invoices/ +
static/ci_wysiwyg.* + the CI route block in main.py to drop the feature entirely.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from typing import Any

from app.database import compute_commission_amount, compute_fob_value, get_db, now_iso
from app.product_labels import deal_document_product


# ── helpers ──────────────────────────────────────────────────────────────────

def _float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def safe_ci_filename(invoice_number: str) -> str:
    text = re.sub(r"[^\w.\- ]", "_", (invoice_number or "CI").strip())
    text = re.sub(r"\s+", "_", text).strip("_")
    return text or "CI"


_ONES = (
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return (_TENS[t] + (" " + _ONES[o] if o else "")).strip()
    h, rem = divmod(n, 100)
    rest = _under_thousand(rem)
    return f"{_ONES[h]} Hundred" + (f" {rest}" if rem else "")


def _int_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts: list[str] = []
    for label, div in (("Million", 1_000_000), ("Thousand", 1_000), ("", 1)):
        if n >= div:
            chunk, n = divmod(n, div)
            w = _under_thousand(chunk)
            parts.append(f"{w} {label}".strip() if label else w)
    return " ".join(parts)


def dollars_in_words(amount: float) -> str:
    """USD amount in words for invoice (e.g. commission total)."""
    v = round(_float(amount), 2)
    dollars = int(v)
    cents = int(round((v - dollars) * 100))
    words = _int_words(dollars) + " Dollar" + ("s" if dollars != 1 else "")
    if cents:
        words += f" and {_int_words(cents)} Cent" + ("s" if cents != 1 else "")
    return words


def form_getlist(form: Any, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(v) for v in form.getlist(key)]
    val = form.get(key)
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]


# ── defaults ─────────────────────────────────────────────────────────────────

DEFAULT_CI: dict[str, Any] = {
    "document_title":        "Commercial Invoice",
    "company_name":          "Godavari Biorefineries Inc",
    "invoice_number":        "",
    "invoice_date":          date.today().isoformat(),
    "notice_date":           "",
    # Bill-to (GBL — static in template, editable)
    "bill_to_name":          "Godavari Biorefineries Ltd",
    "bill_to_address_1":     "Factory: Sakarwadi (Stn. Kanhegaon)",
    "bill_to_address_2":     "Dist. Ahmednagar",
    "bill_to_address_3":     "Maharashtra - 413 708",
    "customer_order_no":     "",
    "contact_person":        "Padmaja Ganapathy",
    "delivery_port":         "",
    # Transaction
    "transaction_description": "",
    # Shipment
    "shipment_date":         "",
    "bl_number":             "",
    "bl_date":               "",
    "port_of_loading":       "",
    "container_numbers":     "",
    # Payment
    "payment_terms":         "PROMPT",
    "enclosures":            "",
    # Bank (US — Chemung Canal, per template)
    "bank_name":             "Chemung Canal Trust Company",
    "bank_account_no":       "204082566",
    "bank_iban":             "",
    "bank_bic":              "CCTRUS31",
    # Editable table units
    "qty_unit":              "MT",
    "fob_currency":          "USD",
    "value_currency":        "USD",
    # Totals
    "vat_percent":           0,
    "amount_in_words":       "",
    # Admin
    "status":                "Draft",
    "prepared_by":           "",
    "internal_notes":        "",
    # Lines
    "line_items": [
        {
            "end_customer":        "",
            "product_description": "",
            "gbl_invoice_number":  "",
            "quantity":            0.0,
            "unit_price":          0.0,
            "cif_price":           0.0,
            "fob_value":           0.0,
            "commission_rate":     3.0,
            "commission_value":    0.0,
            "shipment_date":       "",
        }
    ],
}


# ── calculations ─────────────────────────────────────────────────────────────

def recalc_line(line: dict[str, Any]) -> dict[str, Any]:
    """Recalculate commission from FOB; only derive FOB from qty×price when FOB not set."""
    line = dict(line)
    qty = _float(line.get("quantity"))
    unit_price = _float(line.get("unit_price"))
    cif = _float(line.get("cif_price"))
    fob = _float(line.get("fob_value"))
    if not fob:
        if unit_price and qty:
            fob = round(qty * unit_price, 2)
        elif cif and qty:
            fob = round(qty * cif, 2)
        line["fob_value"] = fob
    rate = _float(line.get("commission_rate"))
    comm = _float(line.get("commission_value"))
    if not comm and fob and rate:
        line["commission_value"] = round(fob * rate / 100, 2)
    return line


def calculate_ci_totals(line_items: list[dict[str, Any]], vat_percent: float = 0) -> dict[str, Any]:
    lines      = [recalc_line(li) for li in line_items]
    total_comm = round(sum(_float(l.get("commission_value")) for l in lines), 2)
    vat_amt    = round(total_comm * vat_percent / 100, 2)
    return {
        "line_items":       lines,
        "total_commission": total_comm,
        "net_value":        total_comm,
        "vat_amount":       vat_amt,
        "total_to_pay":     round(total_comm + vat_amt, 2),
    }


# ── form parsing ─────────────────────────────────────────────────────────────

CI_SCALAR_FIELDS = [
    "document_title", "company_name", "invoice_number", "invoice_date", "notice_date",
    "bill_to_name", "bill_to_address_1", "bill_to_address_2", "bill_to_address_3",
    "customer_order_no", "contact_person", "delivery_port", "transaction_description",
    "shipment_date", "bl_number", "bl_date", "port_of_loading", "container_numbers",
    "payment_terms", "enclosures",
    "bank_name", "bank_account_no", "bank_iban", "bank_bic",
    "amount_in_words", "status", "prepared_by", "internal_notes",
    "qty_unit", "fob_currency", "value_currency",
]

CI_EXTRA_FIELDS = [
    "qty_unit", "fob_currency", "value_currency",
    "contact_person", "delivery_port", "notice_date",
]


def _upgrade_ci_extra_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(commission_invoices)").fetchall()}
    for col in CI_EXTRA_FIELDS:
        if col not in cols:
            conn.execute(f"ALTER TABLE commission_invoices ADD COLUMN {col} TEXT")
    # Migrate line-items table
    li_cols = {r[1] for r in conn.execute("PRAGMA table_info(commission_invoice_line_items)").fetchall()}
    for col, ddl in [
        ("unit_price", "REAL DEFAULT 0"),
        ("end_customer", "TEXT DEFAULT ''"),
        ("cif_price", "REAL DEFAULT 0"),
        ("shipment_date", "TEXT DEFAULT ''"),
    ]:
        if col not in li_cols:
            conn.execute(f"ALTER TABLE commission_invoice_line_items ADD COLUMN {col} {ddl}")


def parse_ci_form(form: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data: dict[str, Any] = {f: (form.get(f) or "").strip() for f in CI_SCALAR_FIELDS}
    data["vat_percent"] = _float(form.get("vat_percent"), 0)
    if not data.get("document_title"):
        data["document_title"] = "COMMISSION INVOICE"
    if not data.get("notice_date"):
        data["notice_date"] = data.get("invoice_date", "")

    products = form_getlist(form, "product_description")
    end_customers = form_getlist(form, "end_customer")
    text_fields    = ["gbl_invoice_number", "shipment_date"]
    numeric_fields = ["quantity", "unit_price", "cif_price", "fob_value", "commission_rate"]

    line_items: list[dict[str, Any]] = []
    for i, product in enumerate(products):
        product = product.strip()
        end_co = (end_customers[i] if i < len(end_customers) else "").strip()
        if not product and not end_co:
            continue
        line: dict[str, Any] = {
            "end_customer": end_co,
            "product_description": product,
        }
        for tf in text_fields:
            vals = form_getlist(form, tf)
            line[tf] = (vals[i] if i < len(vals) else "").strip()
        for nf in numeric_fields:
            vals = form_getlist(form, nf)
            line[nf] = _float(vals[i] if i < len(vals) else 0)
        line_items.append(recalc_line(line))

    return data, line_items


# ── DB schema ────────────────────────────────────────────────────────────────

def upgrade_commission_invoices_schema() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS commission_invoices (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_document_id   INTEGER,
                deal_id                 INTEGER,
                customer_id             INTEGER,
                document_title          TEXT,
                company_name            TEXT,
                invoice_number          TEXT NOT NULL,
                invoice_date            TEXT,
                bill_to_name            TEXT,
                bill_to_address_1       TEXT,
                bill_to_address_2       TEXT,
                bill_to_address_3       TEXT,
                customer_order_no       TEXT,
                transaction_description TEXT,
                shipment_date           TEXT,
                bl_number               TEXT,
                bl_date                 TEXT,
                port_of_loading         TEXT,
                container_numbers       TEXT,
                payment_terms           TEXT,
                enclosures              TEXT,
                bank_name               TEXT,
                bank_account_no         TEXT,
                bank_iban               TEXT,
                bank_bic                TEXT,
                vat_percent             REAL DEFAULT 0,
                amount_in_words         TEXT,
                status                  TEXT DEFAULT 'Draft',
                prepared_by             TEXT,
                internal_notes          TEXT,
                created_at              TEXT,
                updated_at              TEXT,
                FOREIGN KEY(generated_document_id) REFERENCES generated_documents(id),
                FOREIGN KEY(deal_id)   REFERENCES deals(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS commission_invoice_line_items (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                commission_invoice_id INTEGER NOT NULL,
                product_description   TEXT,
                gbl_invoice_number    TEXT,
                quantity              REAL,
                fob_value             REAL,
                commission_rate       REAL,
                commission_value      REAL,
                sort_order            INTEGER DEFAULT 0,
                FOREIGN KEY(commission_invoice_id) REFERENCES commission_invoices(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ci_deal ON commission_invoices(deal_id);
            """
        )
        _upgrade_ci_extra_columns(conn)


# ── CRUD ─────────────────────────────────────────────────────────────────────

def _load_ci_rows(conn, ci_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM commission_invoices WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        return None
    ci = dict(row)
    lines = conn.execute(
        "SELECT * FROM commission_invoice_line_items WHERE commission_invoice_id = ? ORDER BY sort_order, id",
        (ci_id,),
    ).fetchall()
    ci["line_items"] = [dict(l) for l in lines]
    totals = calculate_ci_totals(ci["line_items"], _float(ci.get("vat_percent")))
    ci.update(totals)
    return ci


def list_commission_invoices() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ci.*,
                   li.product_description AS product,
                   li.commission_value    AS line_commission,
                   c.name                AS customer_name
            FROM commission_invoices ci
            LEFT JOIN commission_invoice_line_items li
              ON li.commission_invoice_id = ci.id AND li.sort_order = 0
            LEFT JOIN customers c ON c.id = ci.customer_id
            ORDER BY ci.updated_at DESC, ci.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_commission_invoice(ci_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        return _load_ci_rows(conn, ci_id)


def get_commission_invoice_for_export(ci_id: int) -> dict[str, Any] | None:
    ci = get_commission_invoice(ci_id)
    if not ci:
        return None
    out = deepcopy(ci)
    out.pop("internal_notes", None)
    out.pop("prepared_by", None)
    return out


def _save_ci_lines(conn, ci_id: int, line_items: list[dict[str, Any]]) -> None:
    conn.execute(
        "DELETE FROM commission_invoice_line_items WHERE commission_invoice_id = ?", (ci_id,)
    )
    for sort_order, line in enumerate(line_items):
        conn.execute(
            """
            INSERT INTO commission_invoice_line_items (
                commission_invoice_id, end_customer, product_description, gbl_invoice_number,
                quantity, unit_price, cif_price, fob_value, commission_rate, commission_value,
                shipment_date, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ci_id,
                line.get("end_customer"), line.get("product_description"),
                line.get("gbl_invoice_number"),
                line.get("quantity"), line.get("unit_price"), line.get("cif_price"),
                line.get("fob_value"),
                line.get("commission_rate"), line.get("commission_value"),
                (line.get("shipment_date") or "")[:10],
                sort_order,
            ),
        )


def create_commission_invoice(
    data: dict[str, Any],
    line_items: list[dict[str, Any]],
    *,
    deal_id: int | None = None,
    customer_id: int | None = None,
) -> int:
    totals     = calculate_ci_totals(line_items, _float(data.get("vat_percent")))
    line_items = totals["line_items"]
    now        = now_iso()

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO generated_documents (
                document_type, document_number, title, status,
                source_type, source_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "commission_invoice",
                data.get("invoice_number"),
                data.get("document_title") or "COMMISSION INVOICE",
                data.get("status") or "Draft",
                None, None, now, now,
            ),
        )
        gen_id = int(cur.lastrowid)

        cur = conn.execute(
            f"""
            INSERT INTO commission_invoices (
                {", ".join(CI_SCALAR_FIELDS)}, vat_percent,
                generated_document_id, deal_id, customer_id, created_at, updated_at
            ) VALUES ({", ".join("?" for _ in CI_SCALAR_FIELDS)}, ?, ?, ?, ?, ?, ?)
            """,
            [data.get(f, "") for f in CI_SCALAR_FIELDS]
            + [data.get("vat_percent", 0), gen_id, deal_id, customer_id, now, now],
        )
        ci_id = int(cur.lastrowid)
        _save_ci_lines(conn, ci_id, line_items)
        return ci_id


def update_commission_invoice(
    ci_id: int, data: dict[str, Any], line_items: list[dict[str, Any]]
) -> None:
    totals     = calculate_ci_totals(line_items, _float(data.get("vat_percent")))
    line_items = totals["line_items"]
    now        = now_iso()

    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM commission_invoices WHERE id = ?", (ci_id,)
        ).fetchone()
        if not row:
            raise ValueError("Commission Invoice not found")

        set_clause = ", ".join(f"{f} = ?" for f in CI_SCALAR_FIELDS)
        conn.execute(
            f"UPDATE commission_invoices SET {set_clause}, vat_percent = ?, updated_at = ? WHERE id = ?",
            [data.get(f, "") for f in CI_SCALAR_FIELDS] + [data.get("vat_percent", 0), now, ci_id],
        )
        _save_ci_lines(conn, ci_id, line_items)

        gen_id = row["generated_document_id"]
        if gen_id:
            conn.execute(
                """
                UPDATE generated_documents
                SET document_number = ?, title = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    data.get("invoice_number"),
                    data.get("document_title") or "COMMISSION INVOICE",
                    data.get("status") or "Draft",
                    now, gen_id,
                ),
            )


def update_commission_invoice_dates(
    ci_id: int, invoice_date: str, notice_date: str
) -> bool:
    inv = (invoice_date or "").strip()[:10]
    notice = (notice_date or "").strip()[:10] or inv
    if not inv:
        return False
    now = now_iso()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM commission_invoices WHERE id = ?", (ci_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """
            UPDATE commission_invoices
            SET invoice_date = ?, notice_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (inv, notice, now, ci_id),
        )
    return True


def delete_commission_invoice(ci_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM commission_invoices WHERE id = ?", (ci_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM commission_invoices WHERE id = ?", (ci_id,))
        if row["generated_document_id"]:
            conn.execute(
                "DELETE FROM generated_documents WHERE id = ?", (row["generated_document_id"],)
            )
        return True


def duplicate_commission_invoice(ci_id: int) -> int | None:
    ci = get_commission_invoice(ci_id)
    if not ci:
        return None
    copy = deepcopy(ci)
    copy["invoice_number"] = f"{ci.get('invoice_number', 'CI')}-COPY"
    copy["status"] = "Draft"
    return create_commission_invoice(
        copy,
        copy.get("line_items") or [],
        deal_id=ci.get("deal_id"),
        customer_id=ci.get("customer_id"),
    )


def _deal_fob_value(d: dict) -> float:
    """FOB total from deal commercial fields (not qty × price / Value)."""
    fob = _float(d.get("fob_value"))
    if fob:
        return fob
    commercial = (d.get("commercial_total") or d.get("value") or "").strip()
    if commercial:
        computed = compute_fob_value(
            commercial,
            d.get("insurance_amount") or "",
            d.get("ocean_freight_amount") or "",
        )
        return _float(computed)
    return 0.0


def _deal_to_ci_line(d: dict) -> dict:
    """Build a single CI line item from a deal row dict."""
    price = _float(d.get("price"))
    qty_raw = d.get("quantity") or ""
    qty_nums = re.findall(r"\d+\.?\d*", qty_raw.replace(",", ""))
    qty = float(qty_nums[0]) if qty_nums else 0.0
    line = deepcopy(DEFAULT_CI["line_items"][0])
    line["end_customer"] = d.get("company") or ""
    line["product_description"] = deal_document_product(d)
    line["gbl_invoice_number"] = d.get("gbl_invoice") or ""
    line["quantity"] = qty
    line["unit_price"] = price or 0.0
    line["cif_price"] = price or 0.0
    line["fob_value"] = _deal_fob_value(d)
    line["commission_rate"] = _float(d.get("commission_rate")) or 3.0
    comm = _float(d.get("commission_amount"))
    if comm:
        line["commission_value"] = comm
    else:
        computed = compute_commission_amount(
            str(line["fob_value"]) if line["fob_value"] else "",
            str(line["commission_rate"]),
        )
        line["commission_value"] = _float(computed)
    etd = (d.get("etd_india") or d.get("shipped_date") or d.get("gbl_invoice_date") or "").strip()
    line["shipment_date"] = etd[:10] if etd else ""
    return line


def create_ci_from_deal(deal_id: int) -> dict[str, Any] | None:
    """Prefill a Commission Invoice from a single deal (backwards-compat wrapper)."""
    return create_ci_from_deals([deal_id])


def create_ci_from_deals(deal_ids: list[int]) -> dict[str, Any] | None:
    """Prefill a Commission Invoice from one or more deals.

    Each deal becomes one line item. Header fields are taken from the first deal.
    """
    if not deal_ids:
        return None
    placeholders = ",".join("?" for _ in deal_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT d.*, c.name AS company, p.name AS product,
                   p.trade_name AS catalog_trade_name
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products p  ON p.id = d.product_id
            WHERE d.id IN ({placeholders}) AND d.deleted_at IS NULL
            ORDER BY d.deal_date, d.id
            """,
            deal_ids,
        ).fetchall()
    if not rows:
        return None

    ci = deepcopy(DEFAULT_CI)
    first = dict(rows[0])

    ci["deal_id"]      = first["id"]
    ci["customer_id"]  = first.get("customer_id")
    ci["invoice_date"] = (
        first.get("gbl_invoice_date") or first.get("po_date") or first.get("deal_date")
        or ci["invoice_date"]
    )[:10]
    ci["notice_date"] = ci["invoice_date"]
    # GBInc invoice # is entered on the CI (may span multiple deals); not copied from deal.
    ci["customer_order_no"] = first.get("po_number") or ""
    ci["delivery_port"] = first.get("destination") or ""
    first_etd = (first.get("etd_india") or first.get("shipped_date") or first.get("gbl_invoice_date") or "")[:10]
    ci["shipment_date"] = first_etd
    ci["container_numbers"] = first.get("container_number") or ""
    ci["port_of_loading"] = first.get("etd_india") and "India" or (ci.get("port_of_loading") or "")

    companies = list(dict.fromkeys(dict(r)["company"] for r in rows))
    products = list(
        dict.fromkeys(deal_document_product(dict(r)) for r in rows if deal_document_product(dict(r)))
    )
    ci["transaction_description"] = (
        f"Commission for supply of {', '.join(products)} to {', '.join(companies)}"
    )
    ci["line_items"] = [_deal_to_ci_line(dict(r)) for r in rows]
    totals = calculate_ci_totals(ci["line_items"], 0)
    ci["line_items"] = totals["line_items"]
    ci["amount_in_words"] = dollars_in_words(totals["total_commission"])

    ci["_field_hints"] = {
        "invoice_number": "missing",
        "delivery_port":  "deal" if first.get("destination") else "missing",
        "shipment_date":  "deal" if first.get("etd_india") else "missing",
        "cif_price":      "deal" if _float(first.get("price")) else "missing",
    }
    return ci

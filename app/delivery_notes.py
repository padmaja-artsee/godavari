"""Delivery Note cum Packing List — standalone module.

To remove this feature entirely:
  1. Delete app/delivery_notes.py, app/dn_exports.py
  2. Delete templates/generate/delivery_notes/
  3. Delete static/dn_wysiwyg.js, static/dn_wysiwyg.css
  4. Remove the DN entry from app/generate.py
  5. Remove the "── Delivery Note routes ──" block in app/main.py
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from typing import Any

from app.database import get_db, now_iso


# ── helpers ───────────────────────────────────────────────────────────────────

def _float(v, default: float = 0.0) -> float:
    try:
        return float(str(v or "").replace(",", "").strip())
    except (ValueError, TypeError):
        return default


# ── defaults ──────────────────────────────────────────────────────────────────

DN_SCALAR_FIELDS = [
    "document_title", "company_name",
    # Reference block (top-right)
    "reference_number", "reference_date", "delivery_pick_date",
    "order_number", "zmpn",
    # Bill-to
    "bill_to_name", "bill_to_address", "bill_to_vat",
    "delivery_contact", "transporter_name",
    # Delivery details
    "delivery_date_requested", "delivery_address", "delivery_vat",
    "slot_booking_ref", "delivery_time_slot",
    # Product
    "product_name", "pack_unit", "quantity_unit",
    # Packaging
    "packaging_type", "pack_description",
    # Batch / product details
    "batch_number", "manufacturing_date", "expiry_date",
    # Additional info
    "manufacturer", "made_in", "handling_instruction",
    # Admin
    "status", "prepared_by", "internal_notes",
]

DN_NUMERIC_FIELDS = [
    "number_of_packs", "total_quantity",
    "net_weight_each", "tare_weight_each", "gross_weight_each",
    "pallet_weight_extra", "number_of_pallets", "pallet_weight_actual",
]

DEFAULT_DN: dict[str, Any] = {
    "document_title":         "DELIVERY NOTE CUM PACKING LIST",
    "company_name":           "Godavari Biorefineries Inc",
    # Reference
    "reference_number":       "",
    "reference_date":         date.today().isoformat(),
    "delivery_pick_date":     "",
    "order_number":           "",
    "zmpn":                   "",
    # Bill-to
    "bill_to_name":           "",
    "bill_to_address":        "",
    "bill_to_vat":            "",
    "delivery_contact":       "",
    "transporter_name":       "",
    # Delivery details
    "delivery_date_requested": "",
    "delivery_address":       "",
    "delivery_vat":           "",
    "slot_booking_ref":       "",
    "delivery_time_slot":     "",
    # Product
    "product_name":           "",
    "number_of_packs":        0,
    "pack_unit":              "Drums",
    "total_quantity":         0,
    "quantity_unit":          "Kgs",
    # Packaging
    "packaging_type":         "DRUMS",
    "pack_description":       "Each DRUM",
    "net_weight_each":        0,
    "tare_weight_each":       0,
    "gross_weight_each":      0,
    "pallet_weight_extra":    0,
    # Batch / product details
    "batch_number":           "",
    "manufacturing_date":     "",
    "expiry_date":            "",
    # Additional info
    "number_of_pallets":      0,
    "pallet_weight_actual":   0,
    "manufacturer":           "Godavari Biorefineries Ltd, Mumbai - India",
    "made_in":                "India",
    "handling_instruction":   "Please refer SDS provided",
    # Admin
    "status":                 "Draft",
    "prepared_by":            "",
    "internal_notes":         "",
}


# ── calculations ──────────────────────────────────────────────────────────────

def recalc_dn(dn: dict[str, Any]) -> dict[str, Any]:
    """Derive total_quantity, total weights from per-pack values × num_packs."""
    dn = dict(dn)
    n            = _float(dn.get("number_of_packs"))
    net_each     = _float(dn.get("net_weight_each"))
    tare_each    = _float(dn.get("tare_weight_each"))
    gross_each   = _float(dn.get("gross_weight_each"))
    pallet_extra = _float(dn.get("pallet_weight_extra"))

    dn["total_net_weight"]   = round(n * net_each,   2)
    dn["total_tare_weight"]  = round(n * tare_each,  2)
    dn["total_gross_weight"] = round(n * gross_each + pallet_extra, 2)

    # total_quantity mirrors total_net_weight when set from packs
    if not _float(dn.get("total_quantity")) and dn["total_net_weight"]:
        dn["total_quantity"] = dn["total_net_weight"]

    return dn


# ── schema ────────────────────────────────────────────────────────────────────

def upgrade_delivery_notes_schema() -> None:
    with get_db() as conn:
        cols_str = "\n".join(
            f"    {f} TEXT," for f in DN_SCALAR_FIELDS
        )
        num_str = "\n".join(
            f"    {f} REAL DEFAULT 0," for f in DN_NUMERIC_FIELDS
        )
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS delivery_notes (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_document_id   INTEGER,
                deal_id                 INTEGER,
                customer_id             INTEGER,
{cols_str}
{num_str}
                created_at              TEXT,
                updated_at              TEXT,
                FOREIGN KEY(generated_document_id) REFERENCES generated_documents(id),
                FOREIGN KEY(deal_id)    REFERENCES deals(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );
            CREATE INDEX IF NOT EXISTS idx_dn_deal ON delivery_notes(deal_id);
            """
        )


# ── form parsing ──────────────────────────────────────────────────────────────

def parse_dn_form(form: Any) -> dict[str, Any]:
    dn: dict[str, Any] = {f: (form.get(f) or "").strip() for f in DN_SCALAR_FIELDS}
    for f in DN_NUMERIC_FIELDS:
        dn[f] = _float(form.get(f), 0)
    return recalc_dn(dn)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _row_to_dn(row) -> dict[str, Any]:
    dn = dict(row)
    return recalc_dn(dn)


def list_delivery_notes() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM delivery_notes ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dn(r) for r in rows]


def get_delivery_note(dn_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM delivery_notes WHERE id = ?", (dn_id,)
        ).fetchone()
    return _row_to_dn(row) if row else None


def _insert_dn(conn, dn: dict[str, Any], deal_id, customer_id, gen_id, now) -> int:
    all_fields = DN_SCALAR_FIELDS + DN_NUMERIC_FIELDS
    cols   = ", ".join(all_fields)
    pholds = ", ".join("?" for _ in all_fields)
    vals   = [dn.get(f, "") for f in all_fields]
    cur = conn.execute(
        f"""
        INSERT INTO delivery_notes
            ({cols}, generated_document_id, deal_id, customer_id, created_at, updated_at)
        VALUES ({pholds}, ?, ?, ?, ?, ?)
        """,
        (*vals, gen_id, deal_id, customer_id, now, now),
    )
    return cur.lastrowid


def create_delivery_note(
    dn: dict[str, Any],
    *,
    deal_id: int | None = None,
    customer_id: int | None = None,
) -> int:
    dn = recalc_dn(dn)
    now = now_iso()
    with get_db() as conn:
        doc_cur = conn.execute(
            """
            INSERT INTO generated_documents
                (document_type, document_number, title, status,
                 source_type, source_id, created_at, updated_at)
            VALUES ('delivery_note', ?, ?, ?, 'manual', NULL, ?, ?)
            """,
            (dn.get("reference_number"),
             dn.get("document_title") or "DELIVERY NOTE",
             dn.get("status") or "Draft", now, now),
        )
        gen_id = doc_cur.lastrowid
        return _insert_dn(conn, dn, deal_id, customer_id, gen_id, now)


def update_delivery_note(dn_id: int, dn: dict[str, Any]) -> None:
    dn  = recalc_dn(dn)
    now = now_iso()
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM delivery_notes WHERE id = ?", (dn_id,)
        ).fetchone()
        if not row:
            return
        all_fields = DN_SCALAR_FIELDS + DN_NUMERIC_FIELDS
        set_clause = ", ".join(f"{f} = ?" for f in all_fields)
        vals = [dn.get(f, "") for f in all_fields]
        conn.execute(
            f"UPDATE delivery_notes SET {set_clause}, updated_at = ? WHERE id = ?",
            (*vals, now, dn_id),
        )
        if row["generated_document_id"]:
            conn.execute(
                """UPDATE generated_documents
                   SET document_number = ?, title = ?, status = ?, updated_at = ?
                   WHERE id = ?""",
                (dn.get("reference_number"),
                 dn.get("document_title") or "DELIVERY NOTE",
                 dn.get("status") or "Draft", now,
                 row["generated_document_id"]),
            )


def duplicate_delivery_note(dn_id: int) -> int | None:
    dn = get_delivery_note(dn_id)
    if not dn:
        return None
    copy = deepcopy(dn)
    copy["reference_number"] = (copy.get("reference_number") or "") + " (copy)"
    copy["status"] = "Draft"
    return create_delivery_note(copy, deal_id=dn.get("deal_id"), customer_id=dn.get("customer_id"))


def delete_delivery_note(dn_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM delivery_notes WHERE id = ?", (dn_id,)
        ).fetchone()
        if not row:
            return False
        if row["generated_document_id"]:
            conn.execute(
                "DELETE FROM generated_documents WHERE id = ?", (row["generated_document_id"],)
            )
        conn.execute("DELETE FROM delivery_notes WHERE id = ?", (dn_id,))
        return True


# ── deal prefill ──────────────────────────────────────────────────────────────

def create_dn_from_deal(deal_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT d.*, c.name AS company, p.name AS product,
                   p.hs_code AS product_hs_code
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products  p ON p.id = d.product_id
            WHERE d.id = ? AND d.deleted_at IS NULL
            """,
            (deal_id,),
        ).fetchone()
    if not row:
        return None
    d  = dict(row)
    dn = deepcopy(DEFAULT_DN)
    dn["deal_id"]     = deal_id
    dn["customer_id"] = d.get("customer_id")

    # Reference / order info
    dn["reference_number"]  = d.get("gbl_invoice") or ""
    dn["order_number"]      = d.get("po_number") or ""
    dn["reference_date"]    = date.today().isoformat()

    # Bill-to
    dn["bill_to_name"]      = d.get("company") or ""
    dn["delivery_address"]  = d.get("destination") or ""

    # Product
    dn["product_name"]      = d.get("product") or ""
    dn["batch_number"]      = d.get("container_number") or ""

    # Quantity / weight from deal quantity if available
    qty_raw   = d.get("quantity") or ""
    qty_nums  = re.findall(r"\d+\.?\d*", qty_raw.replace(",", ""))
    qty_total = float(qty_nums[0]) if qty_nums else 0.0
    qty_unit  = (d.get("quantity_unit") or "MT").upper()

    if qty_unit == "MT" and qty_total:
        dn["total_quantity"]  = qty_total * 1000   # convert to kg
        dn["quantity_unit"]   = "Kgs"
    elif qty_total:
        dn["total_quantity"]  = qty_total
        dn["quantity_unit"]   = qty_unit

    # Shipping timing
    if d.get("shipment_timing"):
        dn["delivery_date_requested"] = d["shipment_timing"]

    return recalc_dn(dn)

"""Purchase Order storage, validation, and deal prefilling."""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from typing import Any

from app.database import format_quantity_display, get_db, now_iso


def _float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _parse_qty_number(text: str) -> float:
    nums = re.findall(r"\d+\.?\d*", (text or "").replace(",", ""))
    if not nums:
        return 0.0
    return max(float(n) for n in nums)


DEFAULT_PO: dict[str, Any] = {
    "document_title": "Purchase Order",
    "po_number": "000 ABCD 202627",
    "po_date": date.today().isoformat(),
    "additional_ref": "PO DE 130263",
    "payment_terms": "",
    "port_of_discharge": "Antwerp",
    "incoterm_terms": "CFR Antwerp",
    "shipment_timing": "Prompt",
    "currency": "Euro",
    "company_name": "Godavari Biorefineries B.V.",
    "issuer_name": "GODAVARI BIOREFINERIES LTD",
    "address_line_1": "Somaiya Bhavan, 45-47, MG ROAD",
    "address_line_2": "Fort, MUMBAI - 400 001",
    "phone_1": "+91 22 22048272",
    "phone_2": "+91 22 22047297",
    "contact_person": "Alka Jaiswal",
    "email": "Alka@somaiya.com",
    "consignee_name": "Connect Chemicals GmbH",
    "consignee_address": "Kokkolastrasse 2, 40882 Ratinggen, Germany",
    "consignee_contact": "Torsten Dunkel",
    "consignee_phone": "+492102 2077-17",
    "notify_party": "COMETRANS",
    "notify_contact": "Jean Philippe Bataille",
    "notify_address": "18 Rue Des Forts, F59960 Neuville En Ferrain, France",
    "hs_code": "2905-39",
    "shipping_notes": "",
    "status": "Draft",
    "prepared_by": "",
    "last_updated_by": "",
    "internal_notes": "",
    "credit_note_remark": "",
    "marking_buyer_name": "",
    "marking_product_brand": "Name of product + Brand Name",
    "marking_batch_no": "",
    "marking_gross_weight": "",
    "marking_net_weight": "",
    "marking_tare_weight": "",
    "marking_made_in": "Made in India",
    "marking_batch_on_docs": "Batch number to be shown on all documents",
    "marking_compliance_remark": "Remark: Standard REACH/SVHC compliance mandatory.",
    "marking_loading_remark": "Please correctly load in the container, please send pictures to connect chemicals prior to shipment.",
    "marking_inform_remark": "Prior to shipment - please inform connect chemicals, about any changes in the shipment schedule.",
    "marking_pallets": "Pallets : ISPM 3",
    "documents_required": "\n".join([
        "Copy BL (Express released)",
        "1 Original Signed Commercial invoice + 1 copy",
        "1+1 Original Packing list",
        "COA",
        "Shippers declaration of origin",
        "Original Form A",
        "Fumigation certificate",
    ]),
    "line_items": [
        {
            "product_description": "1,3 Butylene Glycol Naturo BG",
            "quantity_display": "1 FCL",
            "commercial_quantity": 18,
            "commercial_unit": "MT",
            "pricing_quantity": 18000,
            "pricing_unit": "KG",
            "rate": 3.57,
            "rate_unit": "Euro / MT",
            "currency": "Euro",
            "calculated_value": 64260.0,
            "incoterm_delivery_term": "CFR Antwerp",
            "remark": "Urgent shipment",
            "pack_size": 1000,
            "pack_size_unit": "KG",
            "number_of_packs": 18,
            "total_packed_quantity": 18000,
            "total_packed_unit": "KG",
            "batches": [
                {"batch_name": "BATCH A", "batch_number": "", "batch_quantity": 6, "batch_unit": "MT"},
                {"batch_name": "BATCH B", "batch_number": "", "batch_quantity": 6, "batch_unit": "MT"},
                {"batch_name": "BATCH C", "batch_number": "", "batch_quantity": 6, "batch_unit": "MT"},
            ],
        }
    ],
}


def upgrade_purchase_orders_schema() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS generated_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_type TEXT NOT NULL,
                document_number TEXT,
                title TEXT,
                status TEXT DEFAULT 'Draft',
                source_type TEXT,
                source_id INTEGER,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_document_id INTEGER,
                deal_id INTEGER,
                customer_id INTEGER,
                po_number TEXT NOT NULL,
                po_date TEXT,
                additional_ref TEXT,
                payment_terms TEXT,
                port_of_discharge TEXT,
                incoterm_terms TEXT,
                shipment_timing TEXT,
                currency TEXT DEFAULT 'Euro',
                company_name TEXT,
                issuer_name TEXT,
                address_line_1 TEXT,
                address_line_2 TEXT,
                phone_1 TEXT,
                phone_2 TEXT,
                contact_person TEXT,
                email TEXT,
                consignee_name TEXT,
                consignee_address TEXT,
                consignee_contact TEXT,
                consignee_phone TEXT,
                notify_party TEXT,
                notify_contact TEXT,
                notify_address TEXT,
                hs_code TEXT,
                shipping_notes TEXT,
                status TEXT DEFAULT 'Draft',
                prepared_by TEXT,
                last_updated_by TEXT,
                internal_notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(generated_document_id) REFERENCES generated_documents(id),
                FOREIGN KEY(deal_id) REFERENCES deals(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS purchase_order_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL,
                product_description TEXT,
                quantity_display TEXT,
                commercial_quantity REAL,
                commercial_unit TEXT,
                pricing_quantity REAL,
                pricing_unit TEXT,
                rate REAL,
                rate_unit TEXT,
                currency TEXT,
                calculated_value REAL,
                incoterm_delivery_term TEXT,
                remark TEXT,
                pack_size REAL,
                pack_size_unit TEXT,
                number_of_packs REAL,
                total_packed_quantity REAL,
                total_packed_unit TEXT,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS purchase_order_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL,
                line_item_id INTEGER NOT NULL,
                batch_name TEXT,
                batch_number TEXT,
                batch_quantity REAL,
                batch_unit TEXT,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
                FOREIGN KEY(line_item_id) REFERENCES purchase_order_line_items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_gen_docs_type ON generated_documents(document_type);
            CREATE INDEX IF NOT EXISTS idx_po_deal ON purchase_orders(deal_id);
            """
        )
        _upgrade_po_extra_columns(conn)


PO_EXTRA_FIELDS = [
    "credit_note_remark", "marking_buyer_name", "marking_product_brand",
    "marking_batch_no", "marking_gross_weight", "marking_net_weight", "marking_tare_weight",
    "marking_made_in", "marking_batch_on_docs", "marking_compliance_remark",
    "marking_loading_remark", "marking_inform_remark", "marking_pallets", "documents_required",
]


def _upgrade_po_extra_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(purchase_orders)").fetchall()}
    for col in PO_EXTRA_FIELDS:
        if col not in cols:
            conn.execute(f"ALTER TABLE purchase_orders ADD COLUMN {col} TEXT")
    batch_cols = {r[1] for r in conn.execute("PRAGMA table_info(purchase_order_batches)").fetchall()}
    if "batch_number" not in batch_cols:
        conn.execute("ALTER TABLE purchase_order_batches ADD COLUMN batch_number TEXT")


def kg_from_commercial(qty: float, unit: str) -> float | None:
    u = (unit or "").upper()
    if u == "MT":
        return qty * 1000
    if u == "KG":
        return qty
    return None


def recalc_line(line: dict[str, Any]) -> dict[str, Any]:
    line = dict(line)
    pack_size = _float(line.get("pack_size"))
    num_packs = _float(line.get("number_of_packs"))
    rate = _float(line.get("rate"))

    if pack_size and num_packs:
        line["pricing_quantity"] = round(pack_size * num_packs, 4)
        line["total_packed_quantity"] = line["pricing_quantity"]
        line["total_packed_unit"] = line.get("pack_size_unit") or "KG"
        comm_unit = (line.get("commercial_unit") or "MT").upper()
        pack_unit = (line.get("pack_size_unit") or "KG").upper()
        if comm_unit == "MT" and pack_unit == "KG":
            line["commercial_quantity"] = round(line["pricing_quantity"] / 1000, 4)

    pricing_qty = _float(line.get("pricing_quantity"))
    line["calculated_value"] = round(pricing_qty * rate, 2) if pricing_qty and rate else 0.0
    batch_sum = sum(_float(b.get("batch_quantity")) for b in line.get("batches") or [])
    line["_batch_sum"] = batch_sum
    line["_commercial_kg"] = kg_from_commercial(
        _float(line.get("commercial_quantity")), line.get("commercial_unit") or "MT"
    )
    return line


def calculate_po_totals(line_items: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [recalc_line(li) for li in line_items]
    return {
        "line_items": lines,
        "total_value": round(sum(_float(l.get("calculated_value")) for l in lines), 2),
    }


def validation_warnings(data: dict[str, Any], line_items: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    calc = calculate_po_totals(line_items)
    for idx, line in enumerate(calc["line_items"], start=1):
        label = f"Line {idx}"
        commercial = _float(line.get("commercial_quantity"))
        pricing = _float(line.get("pricing_quantity"))
        packed = _float(line.get("total_packed_quantity"))
        batch_sum = _float(line.get("_batch_sum"))
        comm_kg = line.get("_commercial_kg")
        if commercial and batch_sum and abs(commercial - batch_sum) > 0.01:
            warnings.append(f"{label}: batch total ({batch_sum} MT) ≠ commercial quantity ({commercial} MT).")
        if packed and pricing and abs(packed - pricing) > 0.01:
            warnings.append(f"{label}: packed qty ({packed:g} KG) ≠ pricing qty ({pricing:g} KG).")
        if comm_kg is not None and pricing and abs(comm_kg - pricing) > 0.01:
            warnings.append(
                f"{label}: {commercial:g} MT ({comm_kg:g} KG) ≠ pricing qty ({pricing:g} KG)."
            )
    return warnings


def validate_purchase_order(data: dict[str, Any], line_items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not (data.get("po_number") or "").strip():
        errors.append("PO number is required.")
    if not (data.get("po_date") or "").strip():
        errors.append("PO date is required.")
    if not (data.get("currency") or "").strip():
        errors.append("Currency is required.")
    if not line_items:
        errors.append("At least one product line is required.")
    for idx, line in enumerate(line_items, start=1):
        label = f"Line {idx}"
        if not (line.get("product_description") or "").strip():
            errors.append(f"{label}: product description is required.")
        if _float(line.get("commercial_quantity")) <= 0:
            errors.append(f"{label}: commercial quantity must be numeric.")
        if _float(line.get("pack_size")) <= 0 or _float(line.get("number_of_packs")) <= 0:
            errors.append(f"{label}: pack size and number of packs are required.")
        if _float(line.get("rate")) <= 0:
            errors.append(f"{label}: rate must be numeric.")
    return errors


def safe_document_filename(document_number: str) -> str:
    text = re.sub(r"[^\w.\- ]", "_", (document_number or "PO").strip())
    text = re.sub(r"\s+", "_", text).strip("_")
    return text or "PO"


def form_getlist(form: Any, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(v) for v in form.getlist(key)]
    val = form.get(key)
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]


def parse_po_form(form: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scalar = [
        "document_title", "po_number", "po_date", "additional_ref", "payment_terms",
        "port_of_discharge", "incoterm_terms", "shipment_timing", "currency",
        "company_name", "issuer_name", "address_line_1", "address_line_2",
        "phone_1", "phone_2", "contact_person", "email",
        "consignee_name", "consignee_address", "consignee_contact", "consignee_phone",
        "notify_party", "notify_contact", "notify_address", "hs_code", "shipping_notes",
        "status", "prepared_by", "last_updated_by", "internal_notes",
        *PO_EXTRA_FIELDS,
    ]
    data = {f: (form.get(f) or "").strip() for f in scalar}
    if not data.get("document_title"):
        data["document_title"] = "Purchase Order"

    # If individual doc_N fields exist (from the split table UI), reassemble them
    doc_lines = [form.get(f"doc_{i}", "").strip() for i in range(8)]
    if any(doc_lines):
        data["documents_required"] = "\n".join(d for d in doc_lines if d)

    products = form_getlist(form, "product_description")
    text_fields = [
        "quantity_display", "commercial_unit", "pricing_unit",
        "rate_unit_currency", "rate_unit_per",
        "incoterm_delivery_term", "remark", "pack_size_unit",
    ]
    numeric_fields = {"commercial_quantity", "pack_size", "number_of_packs", "rate"}
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
        # Combine split rate-unit fields back into "Euro / MT" style string
        r_cur = line.pop("rate_unit_currency", "").strip() or "Euro"
        r_per = line.pop("rate_unit_per", "").strip() or "MT"
        line["rate_unit"] = f"{r_cur} / {r_per}"
        line["currency"] = data.get("currency") or "Euro"
        batches = []
        bnums = form_getlist(form, f"batch_number_{i}")
        for j, (bname, bqty, bunit) in enumerate(zip(
            form_getlist(form, f"batch_name_{i}"),
            form_getlist(form, f"batch_quantity_{i}"),
            form_getlist(form, f"batch_unit_{i}"),
        )):
            bname = bname.strip()
            if not bname:
                continue
            batches.append({
                "batch_name": bname,
                "batch_number": (bnums[j] if j < len(bnums) else "").strip(),
                "batch_quantity": _float(bqty),
                "batch_unit": (bunit or "MT").strip() or "MT",
            })
        line["batches"] = batches
        line_items.append(recalc_line(line))
    return data, line_items


def _load_po_rows(conn, po_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not row:
        return None
    po = dict(row)
    lines = conn.execute(
        "SELECT * FROM purchase_order_line_items WHERE purchase_order_id = ? ORDER BY sort_order, id",
        (po_id,),
    ).fetchall()
    po["line_items"] = []
    for line in lines:
        ld = dict(line)
        batches = conn.execute(
            "SELECT * FROM purchase_order_batches WHERE line_item_id = ? ORDER BY sort_order, id",
            (ld["id"],),
        ).fetchall()
        ld["batches"] = [dict(b) for b in batches]
        po["line_items"].append(ld)
    po.setdefault("document_title", "PURCHASE ORDER")
    totals = calculate_po_totals(po["line_items"])
    po["line_items"] = totals["line_items"]
    po["total_value"] = totals["total_value"]
    return po


def list_purchase_orders() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT po.*,
                   li.product_description AS product,
                   li.commercial_quantity,
                   li.commercial_unit,
                   li.calculated_value AS total_value,
                   c.name AS customer_name
            FROM purchase_orders po
            LEFT JOIN purchase_order_line_items li
              ON li.purchase_order_id = po.id AND li.sort_order = 0
            LEFT JOIN customers c ON c.id = po.customer_id
            ORDER BY po.updated_at DESC, po.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_purchase_order(po_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        return _load_po_rows(conn, po_id)


def get_purchase_order_for_export(po_id: int) -> dict[str, Any] | None:
    po = get_purchase_order(po_id)
    if not po:
        return None
    out = deepcopy(po)
    out.pop("internal_notes", None)
    out.pop("prepared_by", None)
    out.pop("last_updated_by", None)
    return out


def _save_lines(conn, po_id: int, line_items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM purchase_order_batches WHERE purchase_order_id = ?", (po_id,))
    conn.execute("DELETE FROM purchase_order_line_items WHERE purchase_order_id = ?", (po_id,))
    for sort_order, line in enumerate(line_items):
        cur = conn.execute(
            """
            INSERT INTO purchase_order_line_items (
                purchase_order_id, product_description, quantity_display,
                commercial_quantity, commercial_unit, pricing_quantity, pricing_unit,
                rate, rate_unit, currency, calculated_value, incoterm_delivery_term,
                remark, pack_size, pack_size_unit, number_of_packs,
                total_packed_quantity, total_packed_unit, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po_id, line.get("product_description"), line.get("quantity_display"),
                line.get("commercial_quantity"), line.get("commercial_unit"),
                line.get("pricing_quantity"), line.get("pricing_unit"),
                line.get("rate"), line.get("rate_unit"), line.get("currency"),
                line.get("calculated_value"), line.get("incoterm_delivery_term"),
                line.get("remark"), line.get("pack_size"), line.get("pack_size_unit"),
                line.get("number_of_packs"), line.get("total_packed_quantity"),
                line.get("total_packed_unit"), sort_order,
            ),
        )
        line_id = int(cur.lastrowid)
        for bsort, batch in enumerate(line.get("batches") or []):
            conn.execute(
                """
                INSERT INTO purchase_order_batches (
                    purchase_order_id, line_item_id, batch_name, batch_number,
                    batch_quantity, batch_unit, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    po_id, line_id, batch.get("batch_name"), batch.get("batch_number"),
                    batch.get("batch_quantity"), batch.get("batch_unit"), bsort,
                ),
            )


def create_purchase_order(
    data: dict[str, Any],
    line_items: list[dict[str, Any]],
    *,
    source_type: str | None = None,
    source_id: int | None = None,
    deal_id: int | None = None,
    customer_id: int | None = None,
) -> int:
    calc = calculate_po_totals(line_items)
    line_items = calc["line_items"]
    now = now_iso()
    fields = [
        "po_number", "po_date", "additional_ref", "payment_terms", "port_of_discharge",
        "incoterm_terms", "shipment_timing", "currency", "company_name", "issuer_name",
        "address_line_1", "address_line_2", "phone_1", "phone_2", "contact_person", "email",
        "consignee_name", "consignee_address", "consignee_contact", "consignee_phone",
        "notify_party", "notify_contact", "notify_address", "hs_code", "shipping_notes",
        "status", "prepared_by", "last_updated_by", "internal_notes",
        *PO_EXTRA_FIELDS,
    ]
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO generated_documents (
                document_type, document_number, title, status,
                source_type, source_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "purchase_order", data.get("po_number"), data.get("document_title") or "PURCHASE ORDER",
                data.get("status") or "Draft", source_type, source_id, now, now,
            ),
        )
        gen_id = int(cur.lastrowid)
        vals = [data.get(f) for f in fields] + [gen_id, deal_id, customer_id, now, now]
        cur = conn.execute(
            f"""
            INSERT INTO purchase_orders (
                {", ".join(fields)}, generated_document_id, deal_id, customer_id, created_at, updated_at
            ) VALUES ({", ".join("?" for _ in fields)}, ?, ?, ?, ?, ?)
            """,
            vals,
        )
        po_id = int(cur.lastrowid)
        _save_lines(conn, po_id, line_items)
        conn.execute(
            """
            UPDATE generated_documents SET document_number = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (data.get("po_number"), data.get("status") or "Draft", now, gen_id),
        )
        return po_id


def update_purchase_order(po_id: int, data: dict[str, Any], line_items: list[dict[str, Any]]) -> None:
    calc = calculate_po_totals(line_items)
    line_items = calc["line_items"]
    now = now_iso()
    fields = [
        "po_number", "po_date", "additional_ref", "payment_terms", "port_of_discharge",
        "incoterm_terms", "shipment_timing", "currency", "company_name", "issuer_name",
        "address_line_1", "address_line_2", "phone_1", "phone_2", "contact_person", "email",
        "consignee_name", "consignee_address", "consignee_contact", "consignee_phone",
        "notify_party", "notify_contact", "notify_address", "hs_code", "shipping_notes",
        "status", "prepared_by", "last_updated_by", "internal_notes",
        *PO_EXTRA_FIELDS,
    ]
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM purchase_orders WHERE id = ?", (po_id,)
        ).fetchone()
        if not row:
            raise ValueError("PO not found")
        vals = [data.get(f) for f in fields] + [now, po_id]
        conn.execute(
            f"UPDATE purchase_orders SET {', '.join(f + ' = ?' for f in fields)}, updated_at = ? WHERE id = ?",
            vals,
        )
        _save_lines(conn, po_id, line_items)
        gen_id = row["generated_document_id"]
        if gen_id:
            conn.execute(
                """
                UPDATE generated_documents
                SET document_number = ?, title = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    data.get("po_number"), data.get("document_title") or "PURCHASE ORDER",
                    data.get("status") or "Draft", now, gen_id,
                ),
            )


def delete_purchase_order(po_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT generated_document_id FROM purchase_orders WHERE id = ?", (po_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))
        if row["generated_document_id"]:
            conn.execute(
                "DELETE FROM generated_documents WHERE id = ?",
                (row["generated_document_id"],),
            )
        return True


def duplicate_purchase_order(po_id: int) -> int | None:
    po = get_purchase_order(po_id)
    if not po:
        return None
    copy = deepcopy(po)
    copy["po_number"] = f"{po.get('po_number', 'PO')}-COPY"
    copy["status"] = "Draft"
    return create_purchase_order(
        copy,
        copy.get("line_items") or [],
        source_type="duplicate",
        source_id=po_id,
        deal_id=po.get("deal_id"),
        customer_id=po.get("customer_id"),
    )


def create_purchase_order_from_deal(deal_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT d.*, c.name AS company, p.name AS product,
                   p.hs_code AS product_hs_code
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products p ON p.id = d.product_id
            WHERE d.id = ? AND d.deleted_at IS NULL
            """,
            (deal_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    po = deepcopy(DEFAULT_PO)
    po["deal_id"] = deal_id
    po["customer_id"] = d.get("customer_id")

    # --- header / meta ---
    po["additional_ref"] = d.get("po_number") or po["additional_ref"]
    po["po_date"] = (d.get("po_date") or d.get("deal_date") or po["po_date"])[:10]

    # --- commercial terms from deal ---
    if d.get("incoterms"):
        po["incoterm_terms"] = d["incoterms"]
    if d.get("payment_terms"):
        po["payment_terms"] = d["payment_terms"]
    if d.get("shipment_timing"):
        po["shipment_timing"] = d["shipment_timing"]

    # --- consignee / delivery ---
    po["consignee_name"] = d.get("company") or po["consignee_name"]
    po["port_of_discharge"] = d.get("destination") or po["port_of_discharge"]

    # --- HS code from product catalogue ---
    if d.get("product_hs_code"):
        po["hs_code"] = d["product_hs_code"]

    # --- marking section ---
    po["marking_buyer_name"] = d.get("company") or po["marking_buyer_name"]
    po["marking_product_brand"] = d.get("product") or po["marking_product_brand"]

    # --- shipping notes ---
    notes_parts = []
    if d.get("packing"):
        notes_parts.append(d["packing"])
    if d.get("notes"):
        notes_parts.append(d["notes"])
    if notes_parts:
        po["shipping_notes"] = "\n".join(notes_parts)

    # --- pricing / quantities ---
    qty_raw = d.get("quantity") or ""
    qty_unit = d.get("quantity_unit") or "MT"
    qty_num = _parse_qty_number(qty_raw)
    price = _float(d.get("price"))
    price_unit = d.get("price_unit") or "/MT"
    rate_currency = "Euro"
    rate_per = price_unit.lstrip("/") or "MT"
    rate_unit = f"{rate_currency} / {rate_per}"

    commercial_qty = qty_num
    if qty_unit.upper() == "KG" and qty_num:
        commercial_qty = qty_num / 1000
    pricing_qty = commercial_qty * 1000 if commercial_qty and qty_unit.upper() != "KG" else qty_num

    line = po["line_items"][0]
    line["product_description"] = d.get("product") or line["product_description"]
    line["quantity_display"] = format_quantity_display(qty_raw, qty_unit) or line["quantity_display"]
    line["commercial_quantity"] = commercial_qty or line["commercial_quantity"]
    line["commercial_unit"] = "MT" if qty_unit.upper() != "KG" else "KG"
    line["pricing_quantity"] = pricing_qty or line["pricing_quantity"]
    line["pricing_unit"] = "KG"
    line["rate"] = price or line["rate"]
    line["rate_unit"] = rate_unit if price else line["rate_unit"]
    line["incoterm_delivery_term"] = po["incoterm_terms"]

    calc = calculate_po_totals(po["line_items"])
    po["line_items"] = calc["line_items"]
    po["total_value"] = calc["total_value"]
    return po

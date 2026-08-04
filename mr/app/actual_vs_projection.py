"""Actual vs Projection report — CS register actuals joined to sales projections."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import get_data_dir
from mr.app.cs_input import _month_from_sail_date, _parse_sail_date, list_register_rows
from mr.app.projections import (
    DEFAULT_PRODUCTS,
    fy_label,
    fy_title,
    get_projection,
    list_projection_years,
)

# Fiscal-year month order (Apr → Mar).
FY_MONTH_ORDER = [
    "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
    "OCTOBER", "NOVEMBER", "DECEMBER", "JANUARY", "FEBRUARY", "MARCH",
]

MONTH_SHORT = {
    "APRIL": "Apr", "MAY": "May", "JUNE": "Jun", "JULY": "Jul",
    "AUGUST": "Aug", "SEPTEMBER": "Sep", "OCTOBER": "Oct",
    "NOVEMBER": "Nov", "DECEMBER": "Dec", "JANUARY": "Jan",
    "FEBRUARY": "Feb", "MARCH": "Mar",
}

# Map CS invoice / sheet / product hints → projection product names.
_PRODUCT_ALIASES = {
    "ETHYL ACETATE": "Ethyl Acetate",
    "EA": "Ethyl Acetate",
    "MPO": "MPO",
    "BIO ETHYL ACETATE": "Bio Ethyl Acetate",
    "BIO EA": "Bio Ethyl Acetate",
    "BIOACETICACID": "Bio Acetic Acid",
    "BIO ACETIC ACID": "Bio Acetic Acid",
    "ACETIC ACID": "Bio Acetic Acid",
    "AA": "Bio Acetic Acid",
    "EVE": "EVE",
    "1,3 BG": "1,3 BG",
    "1,3BG": "1,3 BG",
    "13 BG": "1,3 BG",
    "BG": "1,3 BG",
    "CROTONALDEHYDE": "Crotonaldehyde",
    "N-BUTANOL": "n-Butanol",
    "NBUTANOL": "n-Butanol",
    "ETHYL LACTATE": "Ethyl Lactate",
    "TRIACETIN": "Triacetin",
}


def _norm_key(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip().upper())
    return s


def _compact_key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm_key(text))


def product_maps_db_path() -> Path:
    d = get_data_dir() / "mr"
    d.mkdir(parents=True, exist_ok=True)
    return d / "cs_product_maps.db"


def _maps_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(product_maps_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_maps_schema() -> None:
    with _maps_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cs_product_maps (
                alias_key TEXT PRIMARY KEY,
                product TEXT NOT NULL,
                display_label TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )


def list_saved_product_maps() -> dict[str, str]:
    """alias_key (normalized/compact) → projection product name."""
    _ensure_maps_schema()
    with _maps_connect() as conn:
        rows = conn.execute("SELECT alias_key, product FROM cs_product_maps").fetchall()
    return {r["alias_key"]: r["product"] for r in rows}


def save_product_map(alias_key: str, product: str, display_label: str | None = None) -> None:
    key = _compact_key(alias_key) or _norm_key(alias_key)
    product = (product or "").strip()
    if not key or not product:
        return
    _ensure_maps_schema()
    now = datetime.now(timezone.utc).isoformat()
    with _maps_connect() as conn:
        conn.execute(
            """
            INSERT INTO cs_product_maps (alias_key, product, display_label, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alias_key) DO UPDATE SET
              product=excluded.product,
              display_label=excluded.display_label,
              updated_at=excluded.updated_at
            """,
            (key, product, display_label or alias_key, now),
        )


def _cs_candidates(row: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    invoice = row.get("invoice_no") or ""
    m = re.search(r"GBL/([A-Za-z0-9,]+)/", invoice, re.I)
    if m:
        candidates.append(m.group(1))
    hint = row.get("product_hint") or ""
    if hint:
        candidates.append(hint)
        supply = re.search(r"SUPPLY OF\s+(.+)$", hint, re.I)
        if supply:
            candidates.append(supply.group(1))
    sheet = row.get("source_sheet") or ""
    if sheet:
        candidates.append(sheet)
    return candidates


def unmapped_product_label(row: dict[str, Any]) -> str:
    """Human label for an unmapped CS product (hint preferred, else invoice code)."""
    hint = (row.get("product_hint") or "").strip()
    if hint:
        return hint
    invoice = row.get("invoice_no") or ""
    m = re.search(r"GBL/([A-Za-z0-9,]+)/", invoice, re.I)
    if m:
        return m.group(1)
    sheet = (row.get("source_sheet") or "").strip()
    return sheet or "Unknown"


def unmapped_alias_key(row: dict[str, Any]) -> str:
    """Stable key used for grouping + saving product maps."""
    for cand in _cs_candidates(row):
        compact = _compact_key(cand)
        if compact:
            return compact
    return _compact_key(unmapped_product_label(row)) or "UNKNOWN"


def map_cs_product(row: dict[str, Any], saved_maps: dict[str, str] | None = None) -> str | None:
    """Resolve a CS register row to a sales-projection product name."""
    maps = saved_maps if saved_maps is not None else list_saved_product_maps()
    candidates = _cs_candidates(row)
    for cand in candidates:
        key = _norm_key(cand)
        compact = _compact_key(cand)
        if compact in maps:
            return maps[compact]
        if key in maps:
            return maps[key]
        if key in _PRODUCT_ALIASES:
            return _PRODUCT_ALIASES[key]
        for alias, product in _PRODUCT_ALIASES.items():
            if _compact_key(alias) == compact:
                return product
    return None


def _fy_from_invoice(invoice: str) -> int | None:
    """GBL/.../26-27 → 2027."""
    m = re.search(r"/(\d{2})-(\d{2})\s*$", invoice or "")
    if not m:
        return None
    return 2000 + int(m.group(2))


def _row_fiscal_year(row: dict[str, Any]) -> int | None:
    """FY ending year from vessel sail date, else invoice FY suffix."""
    dt = _parse_sail_date(row.get("vessel_sail_date"))
    if dt:
        return dt.year + 1 if dt.month >= 4 else dt.year
    return _fy_from_invoice(row.get("invoice_no") or "")


def _months_through(selected_month: str) -> list[str]:
    selected = selected_month.upper()
    if selected not in FY_MONTH_ORDER:
        return []
    idx = FY_MONTH_ORDER.index(selected)
    return FY_MONTH_ORDER[: idx + 1]


def _empty_bucket() -> dict[str, float]:
    return {"qty_mt": 0.0, "income": 0.0}


def build_actual_vs_projection(
    *,
    fiscal_year: int,
    month: str,
) -> dict[str, Any]:
    """Build the Actual vs Projection sheet for one FY + selected month."""
    month = (month or "APRIL").upper()
    if month not in FY_MONTH_ORDER:
        month = "APRIL"

    projection = get_projection(fiscal_year)
    products = [line["product"] for line in (projection["lines"] if projection else [])]
    if not products:
        products = list(DEFAULT_PRODUCTS)

    saved_maps = list_saved_product_maps()
    ytd_months = set(_months_through(month))
    month_actual: dict[str, dict[str, float]] = {p: _empty_bucket() for p in products}
    ytd_actual: dict[str, dict[str, float]] = {p: _empty_bucket() for p in products}
    unmapped_groups: dict[str, dict[str, Any]] = {}

    for row in list_register_rows():
        sail_month = (row.get("sail_month") or "").upper()
        if not sail_month:
            sail_month = _month_from_sail_date(row.get("vessel_sail_date"))
        row_fy = _row_fiscal_year(row)
        if row_fy != fiscal_year:
            continue
        if sail_month not in FY_MONTH_ORDER:
            continue

        product = map_cs_product(row, saved_maps)
        qty = float(row.get("qty") or 0)
        income = float(row.get("commission") or 0)

        if not product:
            key = unmapped_alias_key(row)
            group = unmapped_groups.get(key)
            if not group:
                label = unmapped_product_label(row)
                codes = set()
                inv = row.get("invoice_no") or ""
                m = re.search(r"GBL/([A-Za-z0-9,]+)/", inv, re.I)
                if m:
                    codes.add(m.group(1).upper())
                sheet = (row.get("source_sheet") or "").strip()
                if sheet:
                    codes.add(sheet.upper())
                group = {
                    "alias_key": key,
                    "label": label,
                    "codes": codes,
                    "line_count": 0,
                    "month_qty": 0.0,
                    "month_income": 0.0,
                    "ytd_qty": 0.0,
                    "ytd_income": 0.0,
                }
                unmapped_groups[key] = group
            else:
                inv = row.get("invoice_no") or ""
                m = re.search(r"GBL/([A-Za-z0-9,]+)/", inv, re.I)
                if m:
                    group["codes"].add(m.group(1).upper())
                sheet = (row.get("source_sheet") or "").strip()
                if sheet:
                    group["codes"].add(sheet.upper())
            group["line_count"] += 1
            if sail_month == month:
                group["month_qty"] += qty
                group["month_income"] += income
            if sail_month in ytd_months:
                group["ytd_qty"] += qty
                group["ytd_income"] += income
            continue

        if product not in month_actual:
            month_actual[product] = _empty_bucket()
            ytd_actual[product] = _empty_bucket()
            if product not in products:
                products.append(product)

        if sail_month == month:
            month_actual[product]["qty_mt"] += qty
            month_actual[product]["income"] += income
        if sail_month in ytd_months:
            ytd_actual[product]["qty_mt"] += qty
            ytd_actual[product]["income"] += income

    # Targets from projections (keep projection product order first)
    targets: dict[str, dict[str, Any]] = {}
    if projection:
        for line in projection["lines"]:
            targets[line["product"]] = {
                "qty_mt": line.get("qty_mt") or 0,
                "sales_value": line.get("sales_value"),
                "income": line.get("income") or 0,
            }

    rows = []
    totals = {
        "month_qty": 0.0,
        "month_income": 0.0,
        "ytd_qty": 0.0,
        "ytd_income": 0.0,
        "target_qty": 0.0,
        "target_sales": 0.0,
        "target_income": 0.0,
    }
    for product in products:
        m = month_actual.get(product, _empty_bucket())
        y = ytd_actual.get(product, _empty_bucket())
        t = targets.get(product, {"qty_mt": 0, "sales_value": None, "income": 0})
        sales = t.get("sales_value")
        row = {
            "product": product,
            "month_qty": m["qty_mt"],
            "month_income": m["income"],
            "ytd_qty": y["qty_mt"],
            "ytd_income": y["income"],
            "target_qty": t.get("qty_mt") or 0,
            "target_sales": sales,
            "target_income": t.get("income") or 0,
        }
        rows.append(row)
        totals["month_qty"] += row["month_qty"]
        totals["month_income"] += row["month_income"]
        totals["ytd_qty"] += row["ytd_qty"]
        totals["ytd_income"] += row["ytd_income"]
        totals["target_qty"] += row["target_qty"]
        totals["target_sales"] += float(sales or 0)
        totals["target_income"] += row["target_income"]

    unmapped_rows = []
    for key, g in sorted(unmapped_groups.items(), key=lambda kv: kv[1]["label"].upper()):
        codes = sorted(c for c in g["codes"] if c and c != _norm_key(g["label"]))
        unmapped_rows.append(
            {
                "alias_key": g["alias_key"],
                "label": g["label"],
                "codes": codes,
                "line_count": g["line_count"],
                "month_qty": g["month_qty"],
                "month_income": g["month_income"],
                "ytd_qty": g["ytd_qty"],
                "ytd_income": g["ytd_income"],
            }
        )

    unmapped_names = []
    for u in unmapped_rows:
        if u["codes"]:
            unmapped_names.append(f"{u['label']} ({', '.join(u['codes'])})")
        else:
            unmapped_names.append(u["label"])

    return {
        "fiscal_year": fiscal_year,
        "fy_label": fy_label(fiscal_year),
        "month": month,
        "month_label": MONTH_SHORT.get(month, month.title()),
        "month_header": f"{MONTH_SHORT.get(month, month.title())} (Actual)",
        "ytd_header": f"{fy_title(fiscal_year).replace(' (Target)', '')} (Actual)",
        "target_header": fy_title(fiscal_year) if projection else f"{fy_label(fiscal_year)} (Target)",
        "rows": rows,
        "totals": totals,
        "unmapped_count": sum(u["line_count"] for u in unmapped_rows),
        "unmapped_names": unmapped_names,
        "unmapped_rows": unmapped_rows,
        "product_choices": list(products),
        "available_months": FY_MONTH_ORDER,
        "available_years": list_projection_years() or [fiscal_year],
    }

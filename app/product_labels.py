"""Product short names for deals and generated documents (PO, CI, SI, DN)."""
from __future__ import annotations

import sqlite3
from typing import Any, Optional


def _clean_label(value: Any) -> str:
    s = ("" if value is None else str(value)).strip()
    if not s or s.lower() == "none":
        return ""
    return s


def document_product_label(
    *,
    full_name: str = "",
    trade_name: str = "",
    product_short_name: str = "",
) -> str:
    """Trade name if present, else full product name; deal may override."""
    override = _clean_label(product_short_name)
    if override:
        return override
    trade = _clean_label(trade_name)
    if trade:
        return trade
    return _clean_label(full_name)


def deal_document_product(deal: dict[str, Any]) -> str:
    return document_product_label(
        full_name=deal.get("product") or "",
        trade_name=deal.get("catalog_trade_name") or deal.get("trade_name") or "",
        product_short_name=deal.get("product_short_name") or "",
    )


def product_row_document_label(row: Optional[dict[str, Any]]) -> str:
    if not row:
        return ""
    return document_product_label(
        full_name=row.get("name") or "",
        trade_name=row.get("trade_name") or "",
        product_short_name="",
    )


def initial_deal_product_short_name(conn: sqlite3.Connection, product_id: int) -> str:
    row = conn.execute(
        "SELECT name, trade_name FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    return product_row_document_label(dict(row) if row else None)

"""Map Leads deal rows → Tracking & Commission Details template cells."""
from __future__ import annotations

import calendar
import re
from datetime import datetime
from typing import Any


def _parse_amount(text: str) -> float:
    if not text:
        return 0.0
    s = str(text).replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0


def _deal_date_key(deal: dict) -> str:
    return (
        (deal.get("shipped_date") or deal.get("gbl_invoice_date") or deal.get("deal_date") or "")[:10]
    )


def _excel_date(val: str) -> datetime | None:
    if not val:
        return None
    s = str(val).strip()[:20]
    candidates = [s, s.title()]
    fmts = (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%b-%d-%Y",
        "%m-%d-%Y",
        "%d.%m.%Y",
        "%d/%m/%Y",
    )
    for cand in candidates:
        for fmt in fmts:
            try:
                return datetime.strptime(cand, fmt)
            except ValueError:
                continue
    return None


def _display_date(val: str) -> datetime | None:
    return _excel_date(val)


def _sail_date_display(deal: dict) -> datetime | None:
    return _display_date(
        deal.get("shipped_date") or deal.get("gbl_invoice_date") or deal.get("deal_date") or ""
    )


def _sail_month_label(deal: dict, month_hint: int = 0) -> str:
    if month_hint and 1 <= month_hint <= 12:
        return calendar.month_name[month_hint].upper()
    key = _deal_date_key(deal)
    if len(key) >= 7:
        try:
            m = int(key[5:7])
            return calendar.month_name[m].upper()
        except ValueError:
            pass
    return ""


def _invoice_number(deal: dict) -> str:
    return (deal.get("gbl_invoice") or "").strip()


def _currency(deal: dict) -> str:
    raw = (deal.get("price") or "") + (deal.get("price_unit") or "")
    return "EUR" if "EUR" in raw.upper() else "USD"


def deal_to_tracking_row(deal: dict, sr_no: int) -> dict[str, Any]:
    qty = _parse_amount(deal.get("quantity") or "")
    return {
        1: sr_no,
        2: (deal.get("company") or "").strip(),
        3: (deal.get("po_number") or "").strip(),
        4: _display_date(deal.get("po_date") or ""),
        5: qty or None,
        6: (deal.get("packing") or "").strip(),
        7: _invoice_number(deal),
        8: _display_date(deal.get("gbl_invoice_date") or ""),
        9: (deal.get("container_number") or "").strip(),
        10: (deal.get("vessel_name") or "").strip(),
        11: _display_date(deal.get("etd_india") or deal.get("shipped_date") or ""),
        12: (deal.get("transit_time") or "").strip(),
        13: (deal.get("destination") or "").strip(),
        14: _display_date(deal.get("eta") or ""),
    }


def deal_to_commission_row(deal: dict, sr_no: int, *, month_hint: int = 0) -> dict[str, Any]:
    qty = _parse_amount(deal.get("quantity") or "")
    rate = _parse_amount(deal.get("price") or "")
    cur = _currency(deal)
    return {
        2: sr_no,
        3: _sail_month_label(deal, month_hint),
        5: _sail_date_display(deal),
        6: (deal.get("company") or "").strip(),
        7: (deal.get("destination") or "").strip(),
        8: qty or None,
        9: cur,
        10: rate or None,
        # 11 K, 14 N, 15 O — formulas in template
        12: _parse_amount(deal.get("ocean_freight_amount") or "") or None,
        13: _parse_amount(deal.get("insurance_amount") or "") or None,
        16: cur,
    }


def period_label_from_filters(
    *,
    month: int = 0,
    fiscal_year: int = 0,
    date_from: str = "",
    date_to: str = "",
) -> str:
    if date_from or date_to:
        a = date_from[:10] if date_from else "…"
        b = date_to[:10] if date_to else "…"
        return f"{a} to {b}"
    if month and fiscal_year:
        cal_yr = fiscal_year - 1 if month >= 4 else fiscal_year
        return f"{calendar.month_name[month]} {cal_yr} (FY{fiscal_year % 100:02d})"
    return ""


def product_label_from_deals(deals: list[dict]) -> str:
    from app.product_labels import deal_document_product

    names = list(
        dict.fromkeys(
            deal_document_product(d) for d in deals if deal_document_product(d)
        )
    )
    if not names:
        return ""
    if len(names) == 1:
        return names[0].upper()
    return ", ".join(n.upper() for n in names[:3])


def company_label_from_deals(deals: list[dict], company_filter: str = "") -> str:
    if company_filter:
        return company_filter
    names = list(dict.fromkeys((d.get("company") or "").strip() for d in deals if d.get("company")))
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        return "Multiple"
    return ""

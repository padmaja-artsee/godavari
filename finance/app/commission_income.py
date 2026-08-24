"""Commission Income helpers from saved Generate commission invoices.

Note: Finance Actuals no longer autopopulates from this module — Commission
Income on Actuals comes from bank statement categorization (and manual adds).
This module remains available for reporting / consolidated CI exports.

Historically (from 2026-07-01), monthly Commission Income could be summed from
saved CIs (invoice_date) and merged into finance actuals → Total Income;
Actuals no longer do that automatically.
"""
from __future__ import annotations

from typing import Any

# Inclusive start — only invoices on/after this date feed finance income.
CI_INCOME_START = "2026-07-01"
COMMISSION_INCOME_NAME = "Commission Income"


def _commission_income_line_item_id(items: list[dict[str, Any]] | None = None) -> int | None:
    from finance.app.database import list_line_items

    rows = items if items is not None else list_line_items()
    for item in rows:
        if item.get("name") == COMMISSION_INCOME_NAME and item.get("section") == "income":
            return int(item["id"])
    return None


def get_commission_invoice_rollup(
    fiscal_year: int,
    items: list[dict[str, Any]] | None = None,
) -> dict[tuple[int, int], float]:
    """Return {(commission_income_lid, calendar_month): sum} for the FY.

    Amounts come from SUM(line.commission_value) on saved commission invoices
    whose invoice_date is on/after CI_INCOME_START and falls in fiscal_year.
    """
    from finance.app.database import fiscal_year_for_date

    lid = _commission_income_line_item_id(items)
    if lid is None:
        return {}

    try:
        from app.database import get_db as leads_get_db
    except ImportError:
        return {}

    totals: dict[tuple[int, int], float] = {}
    try:
        with leads_get_db() as conn:
            # Ensure CI tables exist (no-op if already created).
            try:
                from app.commission_invoices import upgrade_commission_invoices_schema
                upgrade_commission_invoices_schema()
            except Exception:
                pass

            rows = conn.execute(
                """
                SELECT ci.invoice_date AS invoice_date,
                       COALESCE(SUM(li.commission_value), 0) AS total_commission
                FROM commission_invoices ci
                LEFT JOIN commission_invoice_line_items li
                  ON li.commission_invoice_id = ci.id
                WHERE ci.invoice_date IS NOT NULL
                  AND TRIM(ci.invoice_date) != ''
                  AND substr(ci.invoice_date, 1, 10) >= ?
                GROUP BY ci.id, ci.invoice_date
                """,
                (CI_INCOME_START,),
            ).fetchall()
    except Exception:
        return {}

    for row in rows:
        inv = (row["invoice_date"] or "")[:10]
        if len(inv) < 10:
            continue
        try:
            fy, month = fiscal_year_for_date(inv)
        except Exception:
            continue
        if fy != fiscal_year:
            continue
        amt = float(row["total_commission"] or 0)
        if abs(amt) < 1e-9:
            continue
        key = (lid, int(month))
        totals[key] = round(totals.get(key, 0.0) + amt, 2)

    return totals

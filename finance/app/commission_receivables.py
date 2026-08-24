"""Commission Receivables — invoiced (CIs) vs received (bank/actuals).

Source of truth for invoiced amounts: saved Generate Commission Invoices
(commission line totals by invoice_date month).

Received amounts: Finance transactions + actuals_manual posted to the
Commission Income line item (bank CSV imports and manual actuals).
"""
from __future__ import annotations

from typing import Any

from finance.app.database import (
    FY_MONTHS,
    MONTH_LABELS,
    fiscal_year_for_date,
    get_actuals_manual,
    get_transaction_rollup,
    list_line_items,
)

COMMISSION_INCOME_NAME = "Commission Income"


def commission_income_line_id(items: list[dict] | None = None) -> int | None:
    rows = items if items is not None else list_line_items()
    for item in rows:
        if item.get("name") == COMMISSION_INCOME_NAME and item.get("section") == "income":
            return int(item["id"])
    return None


def _ci_invoiced_by_cal_month() -> dict[tuple[int, int], float]:
    """{(cal_year, month): total} from all non-cancelled GBInc CIs."""
    totals: dict[tuple[int, int], float] = {}
    try:
        from app.commission_invoices import upgrade_commission_invoices_schema
        from app.database import get_db as leads_get_db

        upgrade_commission_invoices_schema()
    except Exception:
        return totals

    try:
        with leads_get_db() as conn:
            rows = conn.execute(
                """
                SELECT ci.invoice_date AS invoice_date,
                       COALESCE(SUM(li.commission_value), 0) AS total_commission
                FROM commission_invoices ci
                LEFT JOIN commission_invoice_line_items li
                  ON li.commission_invoice_id = ci.id
                WHERE ci.invoice_date IS NOT NULL
                  AND TRIM(ci.invoice_date) != ''
                  AND LOWER(COALESCE(ci.status, 'Draft')) != 'cancelled'
                  AND COALESCE(ci.variant, 'gbinc') = 'gbinc'
                GROUP BY ci.id, ci.invoice_date
                """
            ).fetchall()
    except Exception:
        return totals

    for row in rows:
        inv = (row["invoice_date"] or "")[:10]
        if len(inv) < 10:
            continue
        try:
            y, m, _ = map(int, inv.split("-"))
        except Exception:
            continue
        if not (1 <= m <= 12):
            continue
        key = (y, m)
        totals[key] = round(totals.get(key, 0.0) + float(row["total_commission"] or 0), 2)
    return totals


def commission_invoiced_by_month(fiscal_year: int) -> dict[int, float]:
    """{calendar_month: total} from saved CIs (invoice_date) in this FY."""
    totals: dict[int, float] = {m: 0.0 for m in FY_MONTHS}
    by_cal = _ci_invoiced_by_cal_month()
    for (y, m), amt in by_cal.items():
        try:
            fy, month = fiscal_year_for_date(f"{y:04d}-{m:02d}-01")
        except Exception:
            continue
        if fy == fiscal_year and month in totals:
            totals[month] = round(totals[month] + amt, 2)
    return totals


def commission_received_by_month(fiscal_year: int) -> dict[int, float]:
    """{calendar_month: total} from bank transactions + manual actuals."""
    totals: dict[int, float] = {m: 0.0 for m in FY_MONTHS}
    lid = commission_income_line_id()
    if lid is None:
        return totals
    rollup = get_transaction_rollup(fiscal_year)
    manual = get_actuals_manual(fiscal_year)
    for m in FY_MONTHS:
        totals[m] = round(
            float(rollup.get((lid, m), 0) or 0) + float(manual.get((lid, m), 0) or 0),
            2,
        )
    return totals


def _received_lookup_for_fys(fiscal_years: set[int]) -> dict[tuple[int, int], float]:
    """{(fy, month): amount} for Commission Income across FYs."""
    lid = commission_income_line_id()
    out: dict[tuple[int, int], float] = {}
    if lid is None:
        return out
    for fy in fiscal_years:
        rollup = get_transaction_rollup(fy)
        manual = get_actuals_manual(fy)
        for m in FY_MONTHS:
            out[(fy, m)] = round(
                float(rollup.get((lid, m), 0) or 0) + float(manual.get((lid, m), 0) or 0),
                2,
            )
    return out


def commission_receivables_rows_for_points(
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build monthly rows for period points (fy / cal_year / month / label)."""
    if not points:
        return []
    invoiced_by_cal = _ci_invoiced_by_cal_month()
    received_by_fy = _received_lookup_for_fys({int(p["fy"]) for p in points})
    rows = []
    for p in points:
        cal_yr = int(p["cal_year"])
        m = int(p["month"])
        fy = int(p["fy"])
        inv = float(invoiced_by_cal.get((cal_yr, m), 0.0))
        rec = float(received_by_fy.get((fy, m), 0.0))
        rows.append({
            "month": m,
            "cal_year": cal_yr,
            "fy": fy,
            "label": p.get("label") or f"{MONTH_LABELS[m]} {cal_yr}",
            "short_label": MONTH_LABELS[m],
            "invoiced": inv,
            "received": rec,
            "outstanding": round(inv - rec, 2),
        })
    return rows


def commission_receivables_rows(
    fiscal_year: int,
    months: list[int],
) -> list[dict[str, Any]]:
    points = [
        {
            "fy": fiscal_year,
            "month": m,
            "cal_year": fiscal_year - 1 if m >= 4 else fiscal_year,
            "label": f"{MONTH_LABELS[m]} {fiscal_year - 1 if m >= 4 else fiscal_year}",
        }
        for m in months
    ]
    return commission_receivables_rows_for_points(points)


def commission_receivables_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    inv = sum(r["invoiced"] for r in rows)
    rec = sum(r["received"] for r in rows)
    return {
        "invoiced": round(inv, 2),
        "received": round(rec, 2),
        "outstanding": round(inv - rec, 2),
    }

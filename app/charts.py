"""Charts data module — self-contained, no cross-imports with other feature modules.

Provides JSON-ready datasets for the /generate/charts page.
All revenue figures are best-effort: deals where price or quantity are
non-numeric (or use non-MT units) are counted but excluded from revenue totals.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.database import get_db


# ── Period helpers ────────────────────────────────────────────────────────────

def chart_period_start(period: str) -> str | None:
    today = date.today()
    if period == "all":
        return None
    if period == "12m":
        return (today - timedelta(days=365)).isoformat()
    if period == "6m":
        return (today - timedelta(days=182)).isoformat()
    if period == "3m":
        return (today - timedelta(days=91)).isoformat()
    if period == "ytd":
        return today.replace(month=1, day=1).isoformat()
    if period == "lastyear":
        return date(today.year - 1, 1, 1).isoformat()
    return (today - timedelta(days=365)).isoformat()   # fallback = 12 months


def chart_period_end(period: str) -> str | None:
    """For 'lastyear' we cap the end date at Dec 31 of last year."""
    if period == "lastyear":
        return date(date.today().year - 1, 12, 31).isoformat()
    return None


# ── Revenue helper ────────────────────────────────────────────────────────────

def _revenue_expr() -> str:
    """SQLite expression: numeric price × numeric quantity, else NULL."""
    return (
        "CASE WHEN TRIM(d.price) GLOB '[0-9]*' "
        "      AND TRIM(d.quantity) GLOB '[0-9]*' "
        "THEN CAST(TRIM(d.price) AS REAL) * CAST(TRIM(d.quantity) AS REAL) "
        "ELSE NULL END"
    )


def _period_where(start: str | None, end: str | None, date_col: str = "d.deal_date") -> tuple[str, list]:
    clauses = ["d.deleted_at IS NULL", "d.archived = 0"]
    params: list[Any] = []
    if start:
        clauses.append(f"{date_col} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{date_col} <= ?")
        params.append(end)
    return " AND ".join(clauses), params


# ── Query functions ───────────────────────────────────────────────────────────

def deals_by_month(period: str = "12m") -> list[dict]:
    """Deal count and best-effort revenue summed by YYYY-MM."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    rev   = _revenue_expr()
    sql   = f"""
        SELECT strftime('%Y-%m', d.deal_date) AS month,
               COUNT(*)                       AS deal_count,
               COALESCE(SUM({rev}), 0)        AS revenue
        FROM deals d
        WHERE {where}
        GROUP BY month
        ORDER BY month
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def deals_by_status(period: str = "12m") -> list[dict]:
    """Deal counts grouped by status for the period (uses deal_date)."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    sql = f"""
        SELECT d.status, COUNT(*) AS deal_count
        FROM deals d
        WHERE {where}
        GROUP BY d.status
        ORDER BY deal_count DESC
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def deals_by_product_month(period: str = "12m") -> list[dict]:
    """Deals per product per month — used for stacked bar."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    sql = f"""
        SELECT strftime('%Y-%m', d.deal_date) AS month,
               p.name                          AS product,
               COUNT(*)                        AS deal_count
        FROM deals d
        JOIN products p ON p.id = d.product_id
        WHERE {where}
        GROUP BY month, p.id
        ORDER BY month, deal_count DESC
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def top_customers(period: str = "12m", limit: int = 10) -> list[dict]:
    """Top N customers by deal count; includes best-effort revenue."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    rev   = _revenue_expr()
    sql   = f"""
        SELECT c.name                         AS customer,
               COUNT(*)                       AS deal_count,
               COALESCE(SUM({rev}), 0)        AS revenue
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        WHERE {where}
        GROUP BY c.id
        ORDER BY deal_count DESC
        LIMIT {limit}
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def top_products(period: str = "12m", limit: int = 10) -> list[dict]:
    """Top N products by deal count + revenue."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    rev   = _revenue_expr()
    sql   = f"""
        SELECT p.name                         AS product,
               COUNT(*)                       AS deal_count,
               COALESCE(SUM({rev}), 0)        AS revenue
        FROM deals d
        JOIN products p ON p.id = d.product_id
        WHERE {where}
        GROUP BY p.id
        ORDER BY deal_count DESC
        LIMIT {limit}
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def shipped_by_month(period: str = "12m") -> list[dict]:
    """Shipped deal count and revenue by closed_date month."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    clauses = ["d.deleted_at IS NULL", "d.status = 'shipped'",
               "d.closed_date IS NOT NULL"]
    params: list[Any] = []
    if start:
        clauses.append("d.closed_date >= ?")
        params.append(start)
    if end:
        clauses.append("d.closed_date <= ?")
        params.append(end)
    where = " AND ".join(clauses)
    rev   = _revenue_expr()
    sql   = f"""
        SELECT strftime('%Y-%m', d.closed_date) AS month,
               COUNT(*)                          AS deal_count,
               COALESCE(SUM({rev}), 0)           AS revenue
        FROM deals d
        WHERE {where}
        GROUP BY month
        ORDER BY month
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def deals_by_status_month(period: str = "12m") -> list[dict]:
    """Per-month counts of open, shipped, and lost deals — for stacked bar."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    clauses = ["d.deleted_at IS NULL", "d.archived = 0",
               "d.status IN ('open','shipped','lost')"]
    params: list[Any] = []
    if start:
        clauses.append("d.deal_date >= ?")
        params.append(start)
    if end:
        clauses.append("d.deal_date <= ?")
        params.append(end)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT strftime('%Y-%m', d.deal_date) AS month,
               d.status,
               COUNT(*) AS deal_count
        FROM deals d
        WHERE {where}
        GROUP BY month, d.status
        ORDER BY month
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def win_rate_by_month(period: str = "12m") -> list[dict]:
    """Per-month win rate: shipped / (shipped + lost), for closed deals."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    clauses = ["d.deleted_at IS NULL", "d.status IN ('shipped','lost')",
               "d.closed_date IS NOT NULL"]
    params: list[Any] = []
    if start:
        clauses.append("d.closed_date >= ?")
        params.append(start)
    if end:
        clauses.append("d.closed_date <= ?")
        params.append(end)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT strftime('%Y-%m', d.closed_date) AS month,
               SUM(CASE WHEN d.status = 'shipped' THEN 1 ELSE 0 END) AS won,
               SUM(CASE WHEN d.status = 'lost'    THEN 1 ELSE 0 END) AS lost,
               COUNT(*) AS total
        FROM deals d
        WHERE {where}
        GROUP BY month
        ORDER BY month
    """
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["win_rate"] = round(r["won"] / r["total"] * 100, 1) if r["total"] else 0
    return rows


def pipeline_funnel(period: str = "12m") -> dict:
    """Counts for funnel: total open + closed + lost, for a funnel chart."""
    start = chart_period_start(period)
    end   = chart_period_end(period)
    where, params = _period_where(start, end)
    sql = f"""
        SELECT d.status, COUNT(*) AS n
        FROM deals d
        WHERE {where}
        GROUP BY d.status
    """
    with get_db() as conn:
        rows = {r["status"]: r["n"] for r in conn.execute(sql, params).fetchall()}
    total  = sum(rows.values())
    open_  = rows.get("open", 0)
    shipped = rows.get("shipped", 0)
    lost   = rows.get("lost", 0)
    return {"total": total, "open": open_, "shipped": shipped, "lost": lost}


def all_chart_data(period: str = "12m") -> dict:
    """Return all datasets in one call for the static page render."""
    return {
        "period":              period,
        "by_month":            deals_by_month(period),
        "by_status":           deals_by_status(period),
        "by_status_month":     deals_by_status_month(period),
        "by_product_month":    deals_by_product_month(period),
        "top_customers":       top_customers(period),
        "top_products":        top_products(period),
        "shipped_by_month":    shipped_by_month(period),
        "win_rate_by_month":   win_rate_by_month(period),
        "pipeline_funnel":     pipeline_funnel(period),
    }

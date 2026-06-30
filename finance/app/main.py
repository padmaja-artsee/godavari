"""Finance FastAPI application — runs standalone on port 8001 or
   mounted at /finance inside the Leads app (Option B single-port).
   Set FINANCE_BASE_PATH=/finance before importing this module when mounting.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

# When mounted as a sub-app, FINANCE_BASE_PATH is set to "/finance".
# All internal redirects and template hrefs are prefixed with this.
FINANCE_BASE = os.environ.get("FINANCE_BASE_PATH", "")

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finance.app.database import (
    FY_MONTHS, MONTH_LABELS, SECTION_LABELS, SECTION_ORDER,
    add_line_item, archive_year, compute_grid, delete_account,
    delete_line_item, delete_payment_account, delete_vendor,
    get_actuals_manual, get_budget_grid, get_fiscal_years,
    get_opening_balance, get_transaction_rollup, init_db, is_archived,
    list_accounts, list_line_items, list_payment_accounts, list_vendors,
    save_account, save_actuals_manual, save_budget_grid,
    save_opening_balance, save_payment_account, save_vendor, unarchive_year,
)
from finance.app.expenses import (
    create_transaction, delete_transaction, get_transaction,
    list_transactions, receipt_path, save_receipt, update_transaction,
)

# When frozen by PyInstaller, __file__ doesn't reliably resolve to
# sys._MEIPASS/finance/app/main.py.  Use LEADS_BUNDLE_BASE (set by
# launcher.py) to find templates/static inside the bundle instead.
_bundle_base = os.environ.get("LEADS_BUNDLE_BASE")
if _bundle_base:
    BASE = Path(_bundle_base) / "finance"
else:
    BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="GBInc Finance")

if (BASE / "static").exists():
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
if (BASE.parent / "static").exists():
    app.mount("/leads-static", StaticFiles(directory=str(BASE.parent / "static")), name="leads_static")

templates = Jinja2Templates(directory=str(BASE / "templates"))
from app.jinja_compat import patch_template_response

patch_template_response(templates)
templates.env.globals["_base"] = FINANCE_BASE


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

SECTION_STYLES = {
    "Total Income":            "subtotal",
    "Total Employee Costs":    "subtotal",
    "Total Office Costs":      "subtotal",
    "Total Admin":             "subtotal",
    "Total Travel":            "subtotal",
    "Total Investment":        "subtotal",
    "Total Expenses":          "highlight",
    "Balance":                 "total",
    "Cash Position":           "cash",
}


def _ctx(request: Request, **kw):
    return {"request": request, "leads_port": 8000, **kw}


def _fmt_date(d: str) -> str:
    try:
        from datetime import date as _d
        dt = _d.fromisoformat(d)
        return dt.strftime("%-d %b %Y")
    except Exception:
        return d


templates.env.filters["fmtdate"] = _fmt_date


def _row_total(item: dict, lid: int, full: dict, by_name: dict) -> float:
    monthly = {m: full.get((lid, m), 0.0) for m in FY_MONTHS}
    if item["name"] == "Balance":
        inc_lid = by_name.get("Total Income")
        exp_lid = by_name.get("Total Expenses")
        inc_tot = sum(full.get((inc_lid, m), 0) for m in FY_MONTHS) if inc_lid else 0
        exp_tot = sum(full.get((exp_lid, m), 0) for m in FY_MONTHS) if exp_lid else 0
        return inc_tot - exp_tot
    if item["name"] == "Cash Position":
        return full.get((lid, 3), 0)  # March = fiscal year-end position
    return sum(monthly.values())


def _build_rows(grid: dict, items: list[dict], opening_balance: float = 0.0) -> list[dict]:
    full = compute_grid(grid, items, opening_balance)
    by_name = {i["name"]: i["id"] for i in items}
    rows = []
    for item in items:
        lid = item["id"]
        monthly = {m: full.get((lid, m), 0.0) for m in FY_MONTHS}
        total = _row_total(item, lid, full, by_name)
        rows.append({
            "item": item, "monthly": monthly, "total": total,
            "style": SECTION_STYLES.get(item["name"], ""),
        })
    return rows


def _combined_actuals(fiscal_year: int, items: list[dict], opening_balance: float = 0.0) -> dict:
    rollup = get_transaction_rollup(fiscal_year)
    manual = get_actuals_manual(fiscal_year)
    combined = {}
    for k in set(list(rollup.keys()) + list(manual.keys())):
        combined[k] = rollup.get(k, 0) + manual.get(k, 0)
    return compute_grid(combined, items, opening_balance)


def _or_none(v: str):
    try:
        return int(v) if v and v.strip() else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, fy: int = Query(0)):
    fys = get_fiscal_years()
    if not fy:
        fy = fys[0]
    items  = list_line_items()
    ob     = get_opening_balance(fy)
    a_grid = _combined_actuals(fy, items, ob)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    by_name = {i["name"]: i["id"] for i in items}

    def _tot(g, name):
        lid = by_name.get(name)
        return sum(g.get((lid, m), 0) for m in FY_MONTHS) if lid else 0

    chart_months   = [MONTH_LABELS[m] for m in FY_MONTHS]
    exp_budget     = [b_grid.get((by_name.get("Total Expenses"), m), 0) for m in FY_MONTHS]
    exp_actual     = [a_grid.get((by_name.get("Total Expenses"), m), 0) for m in FY_MONTHS]
    income_actual  = [a_grid.get((by_name.get("Total Income"),   m), 0) for m in FY_MONTHS]
    cash_lid = by_name.get("Cash Position")
    from datetime import date
    today = date.today()
    fy_start_year = fy - 1
    elapsed = [m for m in FY_MONTHS if (m >= 4 and (fy_start_year, m) <= (today.year, today.month))
               or (m < 4 and (fy, m) <= (today.year, today.month))]
    last_month = elapsed[-1] if elapsed else FY_MONTHS[0]
    current_balance = a_grid.get((cash_lid, last_month), ob) if cash_lid else ob

    recent = list_transactions(fiscal_year=fy, limit=5)

    return templates.TemplateResponse("dashboard.html", _ctx(
        request, fy=fy, fiscal_years=fys, archived=is_archived(fy),
        total_income    = _tot(a_grid, "Total Income"),
        total_expenses  = _tot(a_grid, "Total Expenses"),
        net             = _tot(a_grid, "Balance"),
        current_balance = current_balance,
        budget_expenses = _tot(b_grid, "Total Expenses"),
        chart_months=chart_months, exp_budget=exp_budget,
        exp_actual=exp_actual, income_actual=income_actual,
        recent=recent,
    ))


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@app.get("/budget", response_class=HTMLResponse)
async def budget_page(
    request: Request, fy: int = Query(0),
    saved: int = Query(0), uploaded: int = Query(0),
    upload_error: str = Query(""),
):
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    items = list_line_items()
    ob = get_opening_balance(fy)
    grid  = get_budget_grid(fy)
    rows  = _build_rows(grid, items, ob)
    archived = is_archived(fy)
    # Group rows by section for template
    sections = []
    current_sec = None
    current_rows = []
    for row in rows:
        sec = row["item"]["section"]
        if sec != current_sec:
            if current_sec is not None:
                sections.append({"section": current_sec, "label": SECTION_LABELS.get(current_sec, ""), "rows": current_rows})
            current_sec = sec
            current_rows = []
        current_rows.append(row)
    if current_sec:
        sections.append({"section": current_sec, "label": SECTION_LABELS.get(current_sec, ""), "rows": current_rows})

    return templates.TemplateResponse("budget.html", _ctx(
        request, fy=fy, fiscal_years=fys, archived=archived,
        sections=sections, items=items,
        months=FY_MONTHS, month_labels=MONTH_LABELS,
        saved=saved, uploaded=uploaded, upload_error=upload_error,
        opening_balance=ob,
    ))


@app.post("/budget/opening-balance")
async def save_opening_balance_route(
    fy: int = Form(...),
    opening_balance: str = Form("0"),
    return_to: str = Form("budget"),
):
    try:
        amount = float(opening_balance.replace(",", "") or 0)
    except ValueError:
        amount = 0.0
    save_opening_balance(fy, amount)
    dest = "actuals" if return_to == "actuals" else "budget"
    return RedirectResponse(f"{FINANCE_BASE}/{dest}?fy={fy}&saved=1", status_code=303)


@app.post("/budget")
async def save_budget(request: Request, fy: int = Form(...)):
    form = await request.form()
    values = {}
    for k, v in form.items():
        if k == "fy": continue
        try:
            values[k] = float(v) if v.strip() else 0.0
        except (ValueError, AttributeError):
            values[k] = 0.0
    save_budget_grid(fy, values)
    return RedirectResponse(f"{FINANCE_BASE}/budget?fy={fy}&saved=1", status_code=303)


@app.post("/budget/autosave")
async def autosave_budget(request: Request):
    """Silent auto-save called by JS on every input change — returns JSON, no redirect."""
    form = await request.form()
    fy = int(form.get("fy", 0))
    if not fy:
        return {"ok": False, "error": "missing fy"}
    values = {}
    for k, v in form.items():
        if k == "fy": continue
        try:
            values[k] = float(v) if str(v).strip() else 0.0
        except (ValueError, AttributeError):
            values[k] = 0.0
    save_budget_grid(fy, values)
    return {"ok": True}


@app.get("/budget/template.xlsx")
async def budget_template(fy: int = Query(0)):
    from finance.app.exports import generate_budget_template
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    items = list_line_items()
    content, fname = generate_budget_template(items, fy)
    bundle = os.environ.get("LEADS_BUNDLE_BASE") or getattr(sys, "frozen", False)
    if bundle:
        import subprocess
        dest = Path.home() / "Downloads" / fname
        dest.write_bytes(content)
        try: subprocess.Popen(["open", str(dest)])
        except Exception: pass
        return Response(status_code=204)
    return Response(content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/budget/upload")
async def budget_upload(fy: int = Form(...), file: UploadFile = File(...)):
    from finance.app.exports import parse_budget_upload
    data = await file.read()
    items = list_line_items()
    try:
        values = parse_budget_upload(data, items)
        save_budget_grid(fy, values)
        return RedirectResponse(f"{FINANCE_BASE}/budget?fy={fy}&saved=1&uploaded={len(values)}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"{FINANCE_BASE}/budget?fy={fy}&upload_error={str(exc)[:120]}", status_code=303)


@app.post("/budget/add-line")
async def budget_add_line(fy: int = Form(...), section: str = Form(...), name: str = Form(...)):
    add_line_item(section, name.strip())
    return RedirectResponse(f"{FINANCE_BASE}/budget?fy={fy}", status_code=303)


@app.post("/budget/delete-line")
async def budget_delete_line(fy: int = Form(...), lid: int = Form(...)):
    delete_line_item(lid)
    return RedirectResponse(f"{FINANCE_BASE}/budget?fy={fy}", status_code=303)


# ---------------------------------------------------------------------------
# Actuals (read-only report)
# ---------------------------------------------------------------------------

@app.get("/actuals", response_class=HTMLResponse)
async def actuals_page(request: Request, fy: int = Query(0), saved: int = Query(0)):
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    items   = list_line_items()
    rollup  = get_transaction_rollup(fy)
    manual  = get_actuals_manual(fy)
    combined = {}
    for k in set(list(rollup.keys()) + list(manual.keys())):
        combined[k] = rollup.get(k, 0) + manual.get(k, 0)
    opening_balance = get_opening_balance(fy)
    full = compute_grid(combined, items, opening_balance)
    by_name = {i["name"]: i["id"] for i in items}

    rows = []
    for item in items:
        lid = item["id"]
        monthly_r = {m: rollup.get((lid, m), 0.0)  for m in FY_MONTHS}
        monthly_m = {m: manual.get((lid, m), 0.0)  for m in FY_MONTHS}
        monthly_t = {m: full.get((lid, m), 0.0)    for m in FY_MONTHS}
        rows.append({
            "item": item, "monthly_r": monthly_r,
            "monthly_m": monthly_m, "monthly_t": monthly_t,
            "total": _row_total(item, lid, full, by_name),
            "style": SECTION_STYLES.get(item["name"], ""),
        })

    sections = _group_by_section(rows)
    return templates.TemplateResponse("actuals.html", _ctx(
        request, fy=fy, fiscal_years=fys, archived=is_archived(fy),
        sections=sections, items=items,
        months=FY_MONTHS, month_labels=MONTH_LABELS, saved=saved,
        opening_balance=opening_balance,
    ))


@app.post("/actuals/manual")
async def save_manual(request: Request, fy: int = Form(...)):
    form = await request.form()
    values = {}
    for k, v in form.items():
        if k == "fy": continue
        try:
            values[k] = float(v) if v.strip() else 0.0
        except (ValueError, AttributeError):
            values[k] = 0.0
    save_actuals_manual(fy, values)
    return RedirectResponse(f"{FINANCE_BASE}/actuals?fy={fy}&saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Expense Variances (view-only)
# ---------------------------------------------------------------------------

@app.get("/variances", response_class=HTMLResponse)
async def variances_page(request: Request, fy: int = Query(0)):
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    items  = list_line_items()
    ob     = get_opening_balance(fy)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    a_grid = _combined_actuals(fy, items, ob)
    by_name = {i["name"]: i["id"] for i in items}

    rows = []
    for item in items:
        lid = item["id"]
        monthly = {}
        for m in FY_MONTHS:
            bud = b_grid.get((lid, m), 0.0)
            act = a_grid.get((lid, m), 0.0)
            # For expenses: negative = over budget; for income: positive = above plan
            var = bud - act if item["section"] != "income" else act - bud
            monthly[m] = {"budget": bud, "actual": act, "variance": var}
        b_tot = _row_total(item, lid, b_grid, by_name)
        a_tot = _row_total(item, lid, a_grid, by_name)
        v_tot = b_tot - a_tot if item["section"] != "income" else a_tot - b_tot
        rows.append({
            "item": item, "monthly": monthly,
            "b_total": b_tot, "a_total": a_tot, "v_total": v_tot,
            "style": SECTION_STYLES.get(item["name"], ""),
        })
    sections = _group_by_section(rows)
    return templates.TemplateResponse("variances.html", _ctx(
        request, fy=fy, fiscal_years=fys, archived=is_archived(fy),
        sections=sections, months=FY_MONTHS, month_labels=MONTH_LABELS,
    ))


# ---------------------------------------------------------------------------
# Expenses Analysis (summary)
# ---------------------------------------------------------------------------

@app.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request, fy: int = Query(0)):
    import json

    fys = get_fiscal_years()
    if not fy:
        fy = fys[0]
    items = list_line_items()
    ob = get_opening_balance(fy)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    a_grid = _combined_actuals(fy, items, ob)

    SUMMARY_LINES = [
        ("income",     "Income"),
        ("employee",   "Employee Costs"),
        ("office",     "Office Costs"),
        ("admin",      "Bank/Legal/Admin"),
        ("travel",     "Conference/Travel"),
        ("investment", "Investment"),
    ]
    summary = []
    for sec, label in SUMMARY_LINES:
        sec_items = [i for i in items if i["section"] == sec and not i["is_calculated"]]
        planned = sum(b_grid.get((i["id"], m), 0) for i in sec_items for m in FY_MONTHS)
        actual = sum(a_grid.get((i["id"], m), 0) for i in sec_items for m in FY_MONTHS)
        var = planned - actual if sec != "income" else actual - planned
        var_pct = (var / planned * 100) if planned else None
        summary.append({
            "label": label, "planned": planned, "actual": actual,
            "variance": var, "var_pct": var_pct, "section": sec,
        })

    chart_months = [MONTH_LABELS[m] for m in FY_MONTHS]
    line_data = {}
    for i in items:
        if i["is_calculated"]:
            continue
        line_data[i["id"]] = {
            "name": i["name"],
            "section": i["section"],
            "budget": [b_grid.get((i["id"], m), 0) for m in FY_MONTHS],
            "actual": [a_grid.get((i["id"], m), 0) for m in FY_MONTHS],
        }

    section_totals = {}
    for sec, label in SUMMARY_LINES:
        sec_items = [i for i in items if i["section"] == sec and not i["is_calculated"]]
        section_totals[sec] = {
            "label": label,
            "budget": [sum(b_grid.get((it["id"], m), 0) for it in sec_items) for m in FY_MONTHS],
            "actual": [sum(a_grid.get((it["id"], m), 0) for it in sec_items) for m in FY_MONTHS],
        }

    return templates.TemplateResponse("analysis.html", _ctx(
        request,
        fy=fy,
        fiscal_years=fys,
        summary=summary,
        chart_months=chart_months,
        line_data_json=json.dumps(line_data),
        section_totals_json=json.dumps(section_totals),
        items=[
            {"id": i["id"], "name": i["name"], "section": i["section"]}
            for i in items if not i["is_calculated"]
        ],
    ))


# ---------------------------------------------------------------------------
# Commission report (deals → Excel template)
# ---------------------------------------------------------------------------

def _commission_defaults():
    import datetime
    today = datetime.date.today()
    fys = get_fiscal_years()
    fy = fys[0] if fys else (today.year + 1 if today.month >= 4 else today.year)
    month = today.month if today.month in FY_MONTHS else FY_MONTHS[0]
    return fy, month


@app.get("/commission", response_class=HTMLResponse)
async def commission_page(
    request: Request,
    fy: int = Query(0),
    month: int = Query(0),
    product: str = Query(""),
    company: str = Query(""),
    status: str = Query("all"),
):
    try:
        from app.database import (
            list_commission_companies,
            list_commission_products,
            list_deals_for_commission,
        )
    except ImportError:
        return templates.TemplateResponse("commission.html", _ctx(
            request, page="commission", error="Commission report requires the Leads app.",
            deals=[], products=[], companies=[], fy=0, month=0,
            product="", company="", status="all",
            fiscal_years=get_fiscal_years(), months=FY_MONTHS, month_labels=MONTH_LABELS,
            period_label="", deal_count=0,
        ))

    def_fy, def_month = _commission_defaults()
    if not fy:
        fy = def_fy
    if not month or month not in FY_MONTHS:
        month = def_month

    cal_yr = (fy - 1) if month >= 4 else fy
    period_label = f"{MONTH_LABELS.get(month, '')} {cal_yr}"
    deals = list_deals_for_commission(
        fiscal_year=fy, month=month, product=product, company=company, status=status,
    )
    products = list_commission_products()
    companies = list_commission_companies()

    return templates.TemplateResponse("commission.html", _ctx(
        request, page="commission", error=None,
        deals=deals, products=products, companies=companies,
        fy=fy, month=month, product=product, company=company, status=status,
        fiscal_years=get_fiscal_years(), months=FY_MONTHS, month_labels=MONTH_LABELS,
        period_label=period_label, deal_count=len(deals),
    ))


@app.get("/export/commission.xlsx")
async def export_commission(
    fy: int = Query(0),
    month: int = Query(0),
    product: str = Query(""),
    company: str = Query(""),
    status: str = Query("all"),
):
    from finance.app.commission_exports import export_commission_xlsx
    try:
        from app.database import list_deals_for_commission
    except ImportError as exc:
        return Response(content=str(exc), status_code=503)

    def_fy, def_month = _commission_defaults()
    if not fy:
        fy = def_fy
    if not month or month not in FY_MONTHS:
        month = def_month

    cal_yr = (fy - 1) if month >= 4 else fy
    period_label = f"{MONTH_LABELS.get(month, '')}_{cal_yr}"
    deals = list_deals_for_commission(
        fiscal_year=fy, month=month, product=product, company=company, status=status,
    )
    prod_label = product.strip().upper() if product else "ALL PRODUCTS"
    content, fname = export_commission_xlsx(
        deals,
        product_label=prod_label,
        period_label=period_label,
        month=month,
    )
    return _excel_response(content, fname)


@app.get("/export/commission-invoices-consolidated.xlsx")
async def export_ci_consolidated_finance():
    """All saved Generate commission invoices — consolidated for Commission Income."""
    try:
        from app.ci_consolidated import read_consolidated_commission_workbook
    except ImportError as exc:
        return Response(content=str(exc), status_code=503)
    content, fname = read_consolidated_commission_workbook()
    return _excel_response(content, fname)


# ---------------------------------------------------------------------------
# P&L Report
# ---------------------------------------------------------------------------

@app.get("/report", response_class=HTMLResponse)
async def report_page(
    request: Request,
    fy: int = Query(0),
    month: int = Query(0),
):
    import datetime
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    items  = list_line_items()
    ob     = get_opening_balance(fy)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    a_grid = _combined_actuals(fy, items, ob)
    by_name = {i["name"]: i["id"] for i in items}

    # Default month to current calendar month, clamped to this FY
    if not month:
        month = datetime.date.today().month
    if month not in FY_MONTHS:
        month = FY_MONTHS[0]

    # YTD = April through selected month (in FY order)
    idx = FY_MONTHS.index(month)
    ytd_months = FY_MONTHS[: idx + 1]

    # Calendar year for the selected month label
    cal_yr = (fy - 1) if month >= 4 else fy
    period_label = (
        f"{MONTH_LABELS.get(month, '')} {cal_yr} vs Budget  |  "
        f"YTD Apr {fy - 1} – {MONTH_LABELS.get(month, '')} {cal_yr}"
    )

    def _sum(grid, name, months_list):
        lid = by_name.get(name)
        if not lid: return 0.0
        return sum(grid.get((lid, m), 0.0) for m in months_list)

    EXPENSE_SECTIONS = [
        ("employee",   "Employee Costs",       "Total Employee Costs"),
        ("office",     "Office Costs",         "Total Office Costs"),
        ("admin",      "Bank / Legal / Admin", "Total Admin"),
        ("travel",     "Conference / Travel",  "Total Travel"),
        ("investment", "Investment",           "Total Investment"),
    ]

    def _line(name, m_list, ytd_list):
        return {
            "name":       name,
            "m_actual":   _sum(a_grid, name, m_list),
            "m_budget":   _sum(b_grid, name, m_list),
            "ytd_actual": _sum(a_grid, name, ytd_list),
            "ytd_budget": _sum(b_grid, name, ytd_list),
        }

    income_lines = [
        _line(i["name"], [month], ytd_months)
        for i in items if i["section"] == "income" and not i["is_calculated"]
    ]

    expense_sections = []
    for sec, label, tot_name in EXPENSE_SECTIONS:
        sec_items = [i for i in items if i["section"] == sec and not i["is_calculated"]]
        lines = [
            _line(i["name"], [month], ytd_months)
            for i in sec_items
            if (_sum(a_grid, i["name"], [month]) or _sum(b_grid, i["name"], [month])
                or _sum(a_grid, i["name"], ytd_months) or _sum(b_grid, i["name"], ytd_months))
        ]
        tot = _line(tot_name, [month], ytd_months)
        expense_sections.append({
            "label": label, "section": sec, "lines": lines,
            "m_total_actual":   tot["m_actual"],
            "m_total_budget":   tot["m_budget"],
            "ytd_total_actual": tot["ytd_actual"],
            "ytd_total_budget": tot["ytd_budget"],
        })

    inc_tot  = _line("Total Income",              [month], ytd_months)
    exp_tot  = _line("Total Expenses",            [month], ytd_months)
    net_tot  = _line("Balance", [month], ytd_months)

    return templates.TemplateResponse("report.html", _ctx(
        request, fy=fy, fiscal_years=fys, month=month,
        period_label=period_label, archived=is_archived(fy),
        month_label=MONTH_LABELS.get(month, ""),
        cal_yr=cal_yr,
        fy_start=fy - 1,
        income_lines=income_lines,
        total_income=inc_tot,
        expense_sections=expense_sections,
        total_expenses=exp_tot,
        net=net_tot,
        months=FY_MONTHS,
        month_labels=MONTH_LABELS,
        page="report",
    ))


# ---------------------------------------------------------------------------
# Transactions (expenses + income)
# ---------------------------------------------------------------------------

@app.get("/expenses", response_class=HTMLResponse)
async def expenses_list(
    request: Request, fy: int = Query(0),
    account_id: int = Query(0), vendor_id: int = Query(0),
    tx_type: str = Query("expense"),
):
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    txs   = list_transactions(fiscal_year=fy, transaction_type=tx_type,
                               account_id=account_id or None, vendor_id=vendor_id or None)
    total = sum(t["amount"] for t in txs)
    return templates.TemplateResponse("expenses.html", _ctx(
        request, fy=fy, fiscal_years=fys,
        transactions=txs, total=total, tx_type=tx_type,
        accounts=list_accounts(), vendors=list_vendors(),
        filter_account=account_id, filter_vendor=vendor_id,
    ))


@app.get("/expenses/new", response_class=HTMLResponse)
async def expense_new_form(
    request: Request, fy: int = Query(0),
    account_id: int = Query(0), vendor_id: int = Query(0),
    tx_type: str = Query("expense"),
):
    from datetime import date
    fys = get_fiscal_years()
    if not fy: fy = fys[0]
    return templates.TemplateResponse("expense_form.html", _ctx(
        request, fy=fy, fiscal_years=fys, transaction=None,
        tx_type=tx_type,
        accounts=list_accounts(), vendors=list_vendors(),
        payment_accounts=list_payment_accounts(),
        today=date.today().isoformat(),
        prefill_account=account_id, prefill_vendor=vendor_id,
        page="expenses",
    ))


@app.post("/expenses/new")
async def expense_new_save(
    request: Request,
    fy: int = Form(...), tx_type: str = Form("expense"),
    date: str = Form(...), account_id: int = Form(...),
    amount: float = Form(...), currency: str = Form("USD"),
    payment_account_id: str = Form(""), vendor_id: str = Form(""),
    reference: str = Form(""), notes: str = Form(""),
    image_url: str = Form(""),
    receipt: UploadFile = File(None),
):
    rfname = ""
    if receipt and receipt.filename:
        data = await receipt.read()
        if data: rfname = save_receipt(data, receipt.filename)
    create_transaction(
        date=date, account_id=account_id, amount=amount, currency=currency,
        transaction_type=tx_type,
        payment_account_id=_or_none(payment_account_id),
        vendor_id=_or_none(vendor_id),
        reference=reference, notes=notes, receipt_filename=rfname,
        image_url=image_url,
    )
    return RedirectResponse(f"{FINANCE_BASE}/expenses?fy={fy}&tx_type={tx_type}", status_code=303)


@app.get("/expenses/{tx_id}/edit", response_class=HTMLResponse)
async def expense_edit_form(request: Request, tx_id: int):
    tx = get_transaction(tx_id)
    if not tx: return RedirectResponse(f"{FINANCE_BASE}/expenses", status_code=303)
    fys = get_fiscal_years()
    return templates.TemplateResponse("expense_form.html", _ctx(
        request, fy=tx["fiscal_year"], fiscal_years=fys,
        transaction=tx, tx_type=tx["transaction_type"],
        accounts=list_accounts(), vendors=list_vendors(),
        payment_accounts=list_payment_accounts(),
        today=tx["date"], prefill_account=0, prefill_vendor=0,
        page="expenses",
    ))


@app.post("/expenses/{tx_id}/edit")
async def expense_edit_save(
    tx_id: int,
    fy: int = Form(...), tx_type: str = Form("expense"),
    date: str = Form(...), account_id: int = Form(...),
    amount: float = Form(...), currency: str = Form("USD"),
    payment_account_id: str = Form(""), vendor_id: str = Form(""),
    reference: str = Form(""), notes: str = Form(""),
    image_url: str = Form(""),
    receipt: UploadFile = File(None),
):
    existing = get_transaction(tx_id)
    rfname = None
    if receipt and receipt.filename:
        data = await receipt.read()
        if data:
            if existing and existing.get("receipt_filename"):
                from finance.app.expenses import delete_receipt
                delete_receipt(existing["receipt_filename"])
            rfname = save_receipt(data, receipt.filename)
    update_transaction(
        tx_id=tx_id, date=date, account_id=account_id, amount=amount,
        currency=currency, transaction_type=tx_type,
        payment_account_id=_or_none(payment_account_id),
        vendor_id=_or_none(vendor_id),
        reference=reference, notes=notes, receipt_filename=rfname,
        image_url=image_url,
    )
    return RedirectResponse(f"{FINANCE_BASE}/expenses?fy={fy}&tx_type={tx_type}", status_code=303)


@app.post("/expenses/{tx_id}/delete")
async def expense_delete(tx_id: int, fy: int = Form(0), tx_type: str = Form("expense")):
    delete_transaction(tx_id)
    return RedirectResponse(f"{FINANCE_BASE}/expenses?fy={fy}&tx_type={tx_type}", status_code=303)


@app.get("/expenses/{tx_id}/receipt")
async def expense_receipt(tx_id: int):
    tx = get_transaction(tx_id)
    if not tx or not tx.get("receipt_filename"):
        return Response(status_code=404)
    path = receipt_path(tx["receipt_filename"])
    if not path.exists(): return Response(status_code=404)
    suffix = path.suffix.lower()
    media = {".pdf":"application/pdf",".png":"image/png",
             ".jpg":"image/jpeg",".jpeg":"image/jpeg"}.get(suffix,"application/octet-stream")
    return FileResponse(str(path), media_type=media)


# ---------------------------------------------------------------------------
# FY archive / new year
# ---------------------------------------------------------------------------

@app.post("/fy/archive")
async def fy_archive(fy: int = Form(...)):
    archive_year(fy)
    return RedirectResponse(f"{FINANCE_BASE}/?fy={fy}", status_code=303)


@app.post("/fy/unarchive")
async def fy_unarchive(fy: int = Form(...)):
    unarchive_year(fy)
    return RedirectResponse(f"{FINANCE_BASE}/?fy={fy}", status_code=303)


# ---------------------------------------------------------------------------
# Excel exports — work in both web and desktop app
# ---------------------------------------------------------------------------

def _excel_response(content: bytes, filename: str):
    """Return file download, or save to ~/Downloads in desktop bundle."""
    import sys as _sys
    bundle = os.environ.get("LEADS_BUNDLE_BASE") or getattr(_sys, "frozen", False)
    if bundle:
        import subprocess
        dest = Path.home() / "Downloads" / filename
        dest.write_bytes(content)
        try:
            subprocess.Popen(["open", str(dest)])
        except Exception:
            pass
        return Response(status_code=204)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/report.xlsx")
async def export_report(
    fy: int = Query(0),
    month: int = Query(0),
):
    import datetime
    from finance.app.exports import export_report_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    items  = list_line_items()
    ob     = get_opening_balance(fy)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    a_grid = _combined_actuals(fy, items, ob)
    by_name = {i["name"]: i["id"] for i in items}

    if not month:
        month = datetime.date.today().month
    if month not in FY_MONTHS:
        month = FY_MONTHS[0]

    idx = FY_MONTHS.index(month)
    ytd_months = FY_MONTHS[: idx + 1]
    cal_yr = (fy - 1) if month >= 4 else fy
    period_label = (
        f"{MONTH_LABELS.get(month, '')} {cal_yr} vs Budget  |  "
        f"YTD Apr {fy - 1} – {MONTH_LABELS.get(month, '')} {cal_yr}"
    )

    def _sum(name, months_list):
        lid = by_name.get(name)
        if not lid: return 0.0
        return sum(a_grid.get((lid, m), 0.0) for m in months_list)

    def _bsum(name, months_list):
        lid = by_name.get(name)
        if not lid: return 0.0
        return sum(b_grid.get((lid, m), 0.0) for m in months_list)

    def _line(name):
        return {
            "name":       name,
            "m_actual":   _sum(name,  [month]),
            "m_budget":   _bsum(name, [month]),
            "ytd_actual": _sum(name,  ytd_months),
            "ytd_budget": _bsum(name, ytd_months),
        }

    EXPENSE_SECTIONS = [
        ("employee",   "Employee Costs",       "Total Employee Costs"),
        ("office",     "Office Costs",         "Total Office Costs"),
        ("admin",      "Bank / Legal / Admin", "Total Admin"),
        ("travel",     "Conference / Travel",  "Total Travel"),
        ("investment", "Investment",           "Total Investment"),
    ]
    income_lines = [
        _line(i["name"])
        for i in items if i["section"] == "income" and not i["is_calculated"]
    ]
    expense_sections = []
    for sec, label, tot_name in EXPENSE_SECTIONS:
        sec_items = [i for i in items if i["section"] == sec and not i["is_calculated"]]
        lines = [
            _line(i["name"])
            for i in sec_items
            if (_sum(i["name"], [month]) or _bsum(i["name"], [month])
                or _sum(i["name"], ytd_months) or _bsum(i["name"], ytd_months))
        ]
        tot = _line(tot_name)
        expense_sections.append({
            "label": label, "lines": lines,
            "m_total_actual":   tot["m_actual"],
            "m_total_budget":   tot["m_budget"],
            "ytd_total_actual": tot["ytd_actual"],
            "ytd_total_budget": tot["ytd_budget"],
        })

    inc  = _line("Total Income")
    exp  = _line("Total Expenses")
    net  = _line("Balance")

    content, fname = export_report_xlsx(
        period_label=period_label,
        month_label=MONTH_LABELS.get(month, ""),
        cal_yr=cal_yr,
        fy_start=fy - 1,
        income_lines=income_lines,
        total_income=inc,
        expense_sections=expense_sections,
        total_expenses=exp,
        net=net,
        fiscal_year=fy,
    )
    return _excel_response(content, fname)


@app.get("/export/analysis.xlsx")
async def export_analysis(fy: int = Query(0)):
    from finance.app.exports import export_analysis_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    items  = list_line_items()
    ob     = get_opening_balance(fy)
    b_grid = compute_grid(get_budget_grid(fy), items, ob)
    a_grid = _combined_actuals(fy, items, ob)

    SUMMARY_LINES = [
        ("income",     "Income"),
        ("employee",   "Employee Costs"),
        ("office",     "Office Costs"),
        ("admin",      "Bank/Legal/Admin"),
        ("travel",     "Conference/Travel"),
        ("investment", "Investment"),
    ]
    summary = []
    for sec, label in SUMMARY_LINES:
        sec_items = [i for i in items if i["section"] == sec and not i["is_calculated"]]
        planned = sum(b_grid.get((i["id"], m), 0) for i in sec_items for m in FY_MONTHS)
        actual  = sum(a_grid.get((i["id"], m), 0) for i in sec_items for m in FY_MONTHS)
        var     = planned - actual if sec != "income" else actual - planned
        var_pct = (var / planned * 100) if planned else None
        summary.append({"label": label, "planned": planned, "actual": actual,
                         "variance": var, "var_pct": var_pct})

    by_name = {i["name"]: i["id"] for i in items}
    chart_months  = [MONTH_LABELS[m] for m in FY_MONTHS]
    exp_budget    = [b_grid.get((by_name.get("Total Expenses"), m), 0) for m in FY_MONTHS]
    exp_actual    = [a_grid.get((by_name.get("Total Expenses"), m), 0) for m in FY_MONTHS]
    income_actual = [a_grid.get((by_name.get("Total Income"),   m), 0) for m in FY_MONTHS]

    content, fname = export_analysis_xlsx(summary, chart_months,
                                           exp_budget, exp_actual, income_actual, fy)
    return _excel_response(content, fname)


@app.get("/export/budget.xlsx")
async def export_budget(fy: int = Query(0)):
    from finance.app.exports import export_budget_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    content, fname = export_budget_xlsx(list_line_items(), fy)
    return _excel_response(content, fname)


@app.get("/export/actuals.xlsx")
async def export_actuals(fy: int = Query(0)):
    from finance.app.exports import export_actuals_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    content, fname = export_actuals_xlsx(list_line_items(), fy)
    return _excel_response(content, fname)


@app.get("/export/variances.xlsx")
async def export_variances(fy: int = Query(0)):
    from finance.app.exports import export_variances_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    content, fname = export_variances_xlsx(list_line_items(), fy)
    return _excel_response(content, fname)


@app.get("/export/transactions.xlsx")
async def export_transactions_route(
    fy: int = Query(0), tx_type: str = Query("expense")
):
    from finance.app.exports import export_transactions_xlsx
    fys = get_fiscal_years()
    if not fy: fy = fys[0] if fys else 2027
    txs = list_transactions(fiscal_year=fy, transaction_type=tx_type)
    content, fname = export_transactions_xlsx(txs, fy, tx_type)
    return _excel_response(content, fname)


@app.get("/export/vendors.xlsx")
async def export_vendors_route():
    from finance.app.exports import export_vendors_xlsx
    content, fname = export_vendors_xlsx(list_vendors())
    return _excel_response(content, fname)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@app.get("/vendors", response_class=HTMLResponse)
async def vendors_page(request: Request, saved: int = Query(0)):
    return templates.TemplateResponse("vendors.html", _ctx(
        request, vendors=list_vendors(), saved=saved, page="vendors",
    ))


@app.get("/vendors/new", response_class=HTMLResponse)
async def vendor_new_form(request: Request):
    return templates.TemplateResponse("vendor_form.html", _ctx(request, vendor=None, page="vendor_new"))


@app.post("/vendors/new")
async def vendor_new(name: str = Form(...), email: str = Form(""),
                     phone: str = Form(""), notes: str = Form("")):
    save_vendor(name, email, phone, notes)
    return RedirectResponse(f"{FINANCE_BASE}/vendors?saved=1", status_code=303)


@app.get("/vendors/{vid}/edit", response_class=HTMLResponse)
async def vendor_edit_form(request: Request, vid: int):
    v = next((x for x in list_vendors() if x["id"] == vid), None)
    if not v: return RedirectResponse(f"{FINANCE_BASE}/vendors", status_code=303)
    return templates.TemplateResponse("vendor_form.html", _ctx(request, vendor=v, page="vendor_new"))


@app.post("/vendors/{vid}/edit")
async def vendor_edit(vid: int, name: str = Form(...), email: str = Form(""),
                      phone: str = Form(""), notes: str = Form("")):
    save_vendor(name, email, phone, notes, vid=vid)
    return RedirectResponse(f"{FINANCE_BASE}/vendors?saved=1", status_code=303)


@app.post("/vendors/{vid}/delete")
async def vendor_delete(vid: int):
    delete_vendor(vid)
    return RedirectResponse(f"{FINANCE_BASE}/vendors", status_code=303)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = Query(0)):
    return templates.TemplateResponse("settings.html", _ctx(
        request, accounts=list_accounts(), payment_accounts=list_payment_accounts(),
        line_items=list_line_items(), section_labels=SECTION_LABELS,
        saved=saved, page="settings",
    ))


@app.post("/settings/accounts/new")
async def account_new(name: str = Form(...), section: str = Form(""),
                      line_item_id: str = Form("")):
    save_account(name, section, _or_none(line_item_id))
    return RedirectResponse(f"{FINANCE_BASE}/settings?saved=1", status_code=303)


@app.post("/settings/accounts/{aid}/edit")
async def account_edit(aid: int, name: str = Form(...), section: str = Form(""),
                       line_item_id: str = Form("")):
    save_account(name, section, _or_none(line_item_id), aid=aid)
    return RedirectResponse(f"{FINANCE_BASE}/settings?saved=1", status_code=303)


@app.post("/settings/accounts/{aid}/delete")
async def account_delete(aid: int):
    delete_account(aid)
    return RedirectResponse(f"{FINANCE_BASE}/settings", status_code=303)


@app.post("/settings/payment-accounts/new")
async def payment_account_new(name: str = Form(...), account_type: str = Form("bank")):
    save_payment_account(name, account_type)
    return RedirectResponse(f"{FINANCE_BASE}/settings?saved=1", status_code=303)


@app.post("/settings/payment-accounts/{paid}/delete")
async def payment_account_delete(paid: int):
    delete_payment_account(paid)
    return RedirectResponse(f"{FINANCE_BASE}/settings", status_code=303)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _group_by_section(rows: list[dict]) -> list[dict]:
    sections = []
    cur_sec = None
    cur_rows = []
    for row in rows:
        sec = row["item"]["section"]
        if sec != cur_sec:
            if cur_sec is not None:
                sections.append({"section": cur_sec, "label": SECTION_LABELS.get(cur_sec, ""), "rows": cur_rows})
            cur_sec, cur_rows = sec, []
        cur_rows.append(row)
    if cur_sec:
        sections.append({"section": cur_sec, "label": SECTION_LABELS.get(cur_sec, ""), "rows": cur_rows})
    return sections

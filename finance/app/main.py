from typing import Optional
"""Finance FastAPI application — runs on port 8001."""
import os
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finance.app.database import (
    FY_MONTHS, MONTH_LABELS,
    computed_grid, delete_account, delete_payment_account, delete_vendor,
    get_expense_rollup, get_fiscal_years, get_grid, init_db,
    list_accounts, list_payment_accounts, list_pl_lines, list_vendors,
    save_account, save_grid, save_payment_account, save_vendor,
)
from finance.app.expenses import (
    create_expense, delete_expense, get_expense,
    list_expenses, receipt_path, save_receipt, update_expense,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="GBInc Finance")

_static = BASE / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

_leads_static = BASE.parent / "static"
if _leads_static.exists():
    app.mount("/leads-static", StaticFiles(directory=str(_leads_static)), name="leads_static")

templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.on_event("startup")
def startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SECTION_STYLE = {
    "income_total":  "subtotal",
    "expense_total": "subtotal",
    "ebitda":        "highlight",
    "ebt":           "highlight",
    "net_ebt":       "total",
}


def _ctx(request: Request, **extra):
    return {"request": request, "leads_port": 8000, **extra}


def _build_table(grid: dict, lines: list[dict]) -> list[dict]:
    full = computed_grid(grid, lines)
    rows = []
    for line in lines:
        lid = line["id"]
        monthly = {m: full.get((lid, m), 0.0) for m in FY_MONTHS}
        total = sum(monthly.values())
        rows.append({
            "line": line, "monthly": monthly, "total": total,
            "style": SECTION_STYLE.get(line["section"], ""),
        })
    return rows


def _or_none(v: str) -> Optional[int]:
    try:
        return int(v) if v and v.strip() else None
    except ValueError:
        return None


def _fmt_date(d: str) -> str:
    """Format YYYY-MM-DD to 'd Mon YYYY'."""
    try:
        from datetime import date as _d
        dt = _d.fromisoformat(d)
        return dt.strftime("%-d %b %Y")
    except Exception:
        return d


templates.env.filters["fmtdate"] = _fmt_date


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, fy: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines   = list_pl_lines()
    rollup  = get_expense_rollup(fy)
    manual  = get_grid("actuals", fy)
    # Combined actuals = rollup + manual additions
    combined: dict = {}
    for k in set(list(rollup.keys()) + list(manual.keys())):
        combined[k] = rollup.get(k, 0) + manual.get(k, 0)
    a_grid = computed_grid(combined, lines)
    b_grid = computed_grid(get_grid("budget", fy), lines)

    ebitda_line = next((l for l in lines if l["name"] == "EBITDA"), None)
    ti_line     = next((l for l in lines if l["name"] == "Total Income"),   None)
    te_line     = next((l for l in lines if l["name"] == "Total Expenses"), None)

    chart_months    = [MONTH_LABELS[m] for m in FY_MONTHS]
    ebitda_budget   = [b_grid.get((ebitda_line["id"], m), 0) for m in FY_MONTHS] if ebitda_line else []
    ebitda_actual   = [a_grid.get((ebitda_line["id"], m), 0) for m in FY_MONTHS] if ebitda_line else []
    income_actual   = [a_grid.get((ti_line["id"],  m), 0) for m in FY_MONTHS] if ti_line  else []
    expense_actual  = [a_grid.get((te_line["id"],  m), 0) for m in FY_MONTHS] if te_line  else []

    def fy_total(g, line):
        if not line: return 0
        return sum(g.get((line["id"], m), 0) for m in FY_MONTHS)

    recent = list_expenses(fiscal_year=fy, limit=5)

    return templates.TemplateResponse("dashboard.html", _ctx(
        request,
        fy=fy, fiscal_years=fiscal_years,
        total_income_actual   = fy_total(a_grid, ti_line),
        total_expenses_actual = fy_total(a_grid, te_line),
        ebitda_actual_total   = fy_total(a_grid, ebitda_line),
        ebitda_budget_total   = fy_total(b_grid, ebitda_line),
        chart_months=chart_months,
        ebitda_budget=ebitda_budget, ebitda_actual=ebitda_actual,
        income_actual=income_actual, expense_actual=expense_actual,
        recent_expenses=recent,
    ))


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@app.get("/budget", response_class=HTMLResponse)
async def budget_page(request: Request, fy: int = Query(0), saved: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines = list_pl_lines()
    grid  = get_grid("budget", fy)
    rows  = _build_table(grid, lines)
    return templates.TemplateResponse("budget.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        lines=lines, rows=rows,
        months=FY_MONTHS, month_labels=MONTH_LABELS, saved=saved,
    ))


@app.post("/budget")
async def save_budget(request: Request, fy: int = Form(...)):
    form = await request.form()
    values = {}
    for k, v in form.items():
        if k == "fy":
            continue
        try:
            values[k] = float(v) if v.strip() else 0.0
        except ValueError:
            values[k] = 0.0
    save_grid("budget", fy, values)
    return RedirectResponse(f"/budget?fy={fy}&saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Actuals (hybrid: expense rollup + manual)
# ---------------------------------------------------------------------------

@app.get("/actuals", response_class=HTMLResponse)
async def actuals_page(request: Request, fy: int = Query(0), saved: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines   = list_pl_lines()
    rollup  = get_expense_rollup(fy)
    manual  = get_grid("actuals", fy)

    rows = []
    for line in lines:
        lid = line["id"]
        monthly_rollup = {m: rollup.get((lid, m), 0.0)  for m in FY_MONTHS}
        monthly_manual = {m: manual.get((lid, m), 0.0)  for m in FY_MONTHS}
        monthly_total  = {m: monthly_rollup[m] + monthly_manual[m] for m in FY_MONTHS}
        total = sum(monthly_total.values())
        rows.append({
            "line": line,
            "monthly_rollup": monthly_rollup,
            "monthly_manual": monthly_manual,
            "monthly_total":  monthly_total,
            "total": total,
            "style": SECTION_STYLE.get(line["section"], ""),
        })
    return templates.TemplateResponse("actuals.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        lines=lines, rows=rows,
        months=FY_MONTHS, month_labels=MONTH_LABELS, saved=saved,
    ))


@app.post("/actuals")
async def save_actuals(request: Request, fy: int = Form(...)):
    form = await request.form()
    values = {}
    for k, v in form.items():
        if k == "fy":
            continue
        try:
            values[k] = float(v) if v.strip() else 0.0
        except ValueError:
            values[k] = 0.0
    save_grid("actuals", fy, values)
    return RedirectResponse(f"/actuals?fy={fy}&saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Budget vs Actuals report
# ---------------------------------------------------------------------------

@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, fy: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines   = list_pl_lines()
    rollup  = get_expense_rollup(fy)
    manual  = get_grid("actuals", fy)
    combined: dict = {}
    for k in set(list(rollup.keys()) + list(manual.keys())):
        combined[k] = rollup.get(k, 0) + manual.get(k, 0)
    b_grid = computed_grid(get_grid("budget", fy), lines)
    a_grid = computed_grid(combined, lines)

    rows = []
    for line in lines:
        lid = line["id"]
        monthly = []
        for m in FY_MONTHS:
            bud = b_grid.get((lid, m), 0.0)
            act = a_grid.get((lid, m), 0.0)
            var = act - bud
            var_pct = (var / bud * 100) if bud else None
            monthly.append({"month": m, "budget": bud, "actual": act,
                             "variance": var, "var_pct": var_pct})
        b_total = sum(b_grid.get((lid, m), 0) for m in FY_MONTHS)
        a_total = sum(a_grid.get((lid, m), 0) for m in FY_MONTHS)
        v_total = a_total - b_total
        vp_total = (v_total / b_total * 100) if b_total else None
        rows.append({
            "line": line, "monthly": monthly,
            "b_total": b_total, "a_total": a_total,
            "v_total": v_total, "vp_total": vp_total,
            "style": SECTION_STYLE.get(line["section"], ""),
        })
    return templates.TemplateResponse("report.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        rows=rows, months=FY_MONTHS, month_labels=MONTH_LABELS,
    ))


@app.get("/report/export.xlsx")
async def export_report(fy: int = Query(0)):
    from finance.app.exports import export_pl_xlsx
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0] if fiscal_years else 2027
    lines  = list_pl_lines()
    rollup = get_expense_rollup(fy)
    manual = get_grid("actuals", fy)
    combined: dict = {}
    for k in set(list(rollup.keys()) + list(manual.keys())):
        combined[k] = rollup.get(k, 0) + manual.get(k, 0)
    b_grid = computed_grid(get_grid("budget", fy), lines)
    a_grid = computed_grid(combined, lines)
    content, fname = export_pl_xlsx(lines, b_grid, a_grid, fy)

    bundle_base = os.environ.get("LEADS_BUNDLE_BASE") or getattr(sys, "frozen", False)
    if bundle_base:
        import subprocess
        dest = Path.home() / "Downloads" / fname
        dest.write_bytes(content)
        try:
            subprocess.Popen(["open", str(dest)])
        except Exception:
            pass
        return Response(status_code=204)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# Expenses — list
# ---------------------------------------------------------------------------

@app.get("/expenses", response_class=HTMLResponse)
async def expenses_list(
    request: Request,
    fy: int = Query(0),
    account_id: int = Query(0),
    vendor_id: int = Query(0),
):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    expenses = list_expenses(
        fiscal_year=fy,
        account_id=account_id or None,
        vendor_id=vendor_id or None,
    )
    total = sum(e["amount"] for e in expenses)
    accounts = list_accounts()
    vendors  = list_vendors()
    return templates.TemplateResponse("expenses.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        expenses=expenses, total=total,
        accounts=accounts, vendors=vendors,
        filter_account=account_id, filter_vendor=vendor_id,
    ))


# ---------------------------------------------------------------------------
# Expenses — new / edit
# ---------------------------------------------------------------------------

@app.get("/expenses/new", response_class=HTMLResponse)
async def expense_new_form(
    request: Request,
    fy: int = Query(0),
    account_id: int = Query(0),
    vendor_id: int = Query(0),
):
    from datetime import date
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    accounts         = list_accounts()
    vendors          = list_vendors()
    payment_accounts = list_payment_accounts()
    return templates.TemplateResponse("expense_form.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        expense=None, accounts=accounts, vendors=vendors,
        payment_accounts=payment_accounts,
        today=date.today().isoformat(),
        prefill_account=account_id,
        prefill_vendor=vendor_id,
        page="expenses",
    ))


@app.post("/expenses/new")
async def expense_new_save(
    request: Request,
    fy: int = Form(...),
    date: str = Form(...),
    account_id: int = Form(...),
    amount: float = Form(...),
    currency: str = Form("USD"),
    payment_account_id: str = Form(""),
    vendor_id: str = Form(""),
    reference: str = Form(""),
    notes: str = Form(""),
    receipt: UploadFile = File(None),
):
    receipt_filename = ""
    if receipt and receipt.filename:
        data = await receipt.read()
        if data:
            receipt_filename = save_receipt(data, receipt.filename)

    create_expense(
        date=date,
        account_id=account_id,
        amount=amount,
        currency=currency,
        payment_account_id=_or_none(payment_account_id),
        vendor_id=_or_none(vendor_id),
        reference=reference,
        notes=notes,
        receipt_filename=receipt_filename,
    )
    return RedirectResponse(f"/expenses?fy={fy}", status_code=303)


@app.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
async def expense_edit_form(request: Request, expense_id: int):
    expense = get_expense(expense_id)
    if not expense:
        return RedirectResponse("/expenses", status_code=303)
    fiscal_years     = get_fiscal_years()
    accounts         = list_accounts()
    vendors          = list_vendors()
    payment_accounts = list_payment_accounts()
    return templates.TemplateResponse("expense_form.html", _ctx(
        request, fy=expense["fiscal_year"],
        fiscal_years=fiscal_years,
        expense=expense, accounts=accounts, vendors=vendors,
        payment_accounts=payment_accounts,
        today=expense["date"],
        page="expenses",
    ))


@app.post("/expenses/{expense_id}/edit")
async def expense_edit_save(
    expense_id: int,
    fy: int = Form(...),
    date: str = Form(...),
    account_id: int = Form(...),
    amount: float = Form(...),
    currency: str = Form("USD"),
    payment_account_id: str = Form(""),
    vendor_id: str = Form(""),
    reference: str = Form(""),
    notes: str = Form(""),
    receipt: UploadFile = File(None),
):
    existing = get_expense(expense_id)
    receipt_filename = None
    if receipt and receipt.filename:
        data = await receipt.read()
        if data:
            # Remove old receipt
            if existing and existing.get("receipt_filename"):
                from finance.app.expenses import delete_receipt
                delete_receipt(existing["receipt_filename"])
            receipt_filename = save_receipt(data, receipt.filename)

    update_expense(
        expense_id=expense_id,
        date=date,
        account_id=account_id,
        amount=amount,
        currency=currency,
        payment_account_id=_or_none(payment_account_id),
        vendor_id=_or_none(vendor_id),
        reference=reference,
        notes=notes,
        receipt_filename=receipt_filename,
    )
    return RedirectResponse(f"/expenses?fy={fy}", status_code=303)


@app.post("/expenses/{expense_id}/delete")
async def expense_delete(expense_id: int, fy: int = Form(0)):
    delete_expense(expense_id)
    return RedirectResponse(f"/expenses?fy={fy}", status_code=303)


@app.get("/expenses/{expense_id}/receipt")
async def expense_receipt(expense_id: int):
    expense = get_expense(expense_id)
    if not expense or not expense.get("receipt_filename"):
        return Response(status_code=404)
    path = receipt_path(expense["receipt_filename"])
    if not path.exists():
        return Response(status_code=404)
    suffix = path.suffix.lower()
    media = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return FileResponse(str(path), media_type=media)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@app.get("/vendors", response_class=HTMLResponse)
async def vendors_page(request: Request, saved: int = Query(0)):
    vendors = list_vendors()
    return templates.TemplateResponse("vendors.html", _ctx(
        request, vendors=vendors, saved=saved, page="vendors",
    ))


@app.get("/vendors/new", response_class=HTMLResponse)
async def vendor_new_form(request: Request):
    return templates.TemplateResponse("vendor_form.html", _ctx(
        request, vendor=None, page="vendor_new",
    ))


@app.post("/vendors/new")
async def vendor_new(
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
):
    save_vendor(name, email, phone, notes)
    return RedirectResponse("/vendors?saved=1", status_code=303)


@app.get("/vendors/{vid}/edit", response_class=HTMLResponse)
async def vendor_edit_form(request: Request, vid: int):
    vendors = list_vendors()
    vendor = next((v for v in vendors if v["id"] == vid), None)
    if not vendor:
        return RedirectResponse("/vendors", status_code=303)
    return templates.TemplateResponse("vendor_form.html", _ctx(
        request, vendor=vendor, page="vendor_new",
    ))


@app.post("/vendors/{vid}/edit")
async def vendor_edit(
    vid: int,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
):
    save_vendor(name, email, phone, notes, vid=vid)
    return RedirectResponse("/vendors?saved=1", status_code=303)


@app.post("/vendors/{vid}/delete")
async def vendor_delete(vid: int):
    delete_vendor(vid)
    return RedirectResponse("/vendors", status_code=303)


# ---------------------------------------------------------------------------
# Settings: Chart of Accounts + Payment Accounts
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = Query(0)):
    accounts         = list_accounts()
    payment_accounts = list_payment_accounts()
    pl_lines         = list_pl_lines()
    return templates.TemplateResponse("settings.html", _ctx(
        request,
        accounts=accounts,
        payment_accounts=payment_accounts,
        pl_lines=pl_lines,
        saved=saved,
        page="settings",
    ))


@app.post("/settings/accounts/new")
async def account_new(
    name: str = Form(...),
    group_label: str = Form(""),
    pl_line_id: str = Form(""),
):
    save_account(name, group_label, _or_none(pl_line_id))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/accounts/{aid}/edit")
async def account_edit(
    aid: int,
    name: str = Form(...),
    group_label: str = Form(""),
    pl_line_id: str = Form(""),
):
    save_account(name, group_label, _or_none(pl_line_id), aid=aid)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/accounts/{aid}/delete")
async def account_delete(aid: int):
    delete_account(aid)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/payment-accounts/new")
async def payment_account_new(
    name: str = Form(...),
    account_type: str = Form("bank"),
):
    save_payment_account(name, account_type)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/payment-accounts/{paid}/delete")
async def payment_account_delete(paid: int):
    delete_payment_account(paid)
    return RedirectResponse("/settings", status_code=303)

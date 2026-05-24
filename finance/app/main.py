"""Finance FastAPI application — runs on port 8001."""
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finance.app.database import (
    FY_MONTHS, MONTH_LABELS,
    calendar_year_for, computed_grid, get_fiscal_years,
    get_grid, init_db, list_pl_lines, save_grid,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="GBInc Finance")

_static = BASE / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

# Also serve Leads static files (shared CSS / logo)
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

SECTION_LABELS = {
    "income":        "Income",
    "income_total":  "Total Income",
    "expense":       "Expenses",
    "expense_total": "Total Expenses",
    "ebitda":        "EBITDA",
    "below_ebitda":  "",
    "ebt":           "EBT",
    "net_ebt":       "Net EBT",
}

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
    """Convert a flat grid dict into rows suitable for template rendering."""
    full = computed_grid(grid, lines)
    rows = []
    for line in lines:
        lid = line["id"]
        monthly = {m: full.get((lid, m), 0.0) for m in FY_MONTHS}
        total = sum(monthly.values())
        rows.append({
            "line":    line,
            "monthly": monthly,
            "total":   total,
            "style":   SECTION_STYLE.get(line["section"], ""),
        })
    return rows


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, fy: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines  = list_pl_lines()
    b_grid = computed_grid(get_grid("budget",  fy), lines)
    a_grid = computed_grid(get_grid("actuals", fy), lines)

    # Build chart data — monthly EBITDA budget vs actual
    ebitda_line = next((l for l in lines if l["name"] == "EBITDA"), None)
    chart_months = [MONTH_LABELS[m] for m in FY_MONTHS]
    ebitda_budget  = [b_grid.get((ebitda_line["id"], m), 0) for m in FY_MONTHS] if ebitda_line else []
    ebitda_actual  = [a_grid.get((ebitda_line["id"], m), 0) for m in FY_MONTHS] if ebitda_line else []

    ti_line  = next((l for l in lines if l["name"] == "Total Income"),   None)
    te_line  = next((l for l in lines if l["name"] == "Total Expenses"), None)
    income_actual   = [a_grid.get((ti_line["id"],  m), 0) for m in FY_MONTHS] if ti_line  else []
    expense_actual  = [a_grid.get((te_line["id"],  m), 0) for m in FY_MONTHS] if te_line  else []

    # KPI cards
    def fy_total(grid, line):
        if not line: return 0
        return sum(grid.get((line["id"], m), 0) for m in FY_MONTHS)

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
    ))


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
        months=FY_MONTHS, month_labels=MONTH_LABELS,
        saved=saved,
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


@app.get("/actuals", response_class=HTMLResponse)
async def actuals_page(request: Request, fy: int = Query(0), saved: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines = list_pl_lines()
    grid  = get_grid("actuals", fy)
    rows  = _build_table(grid, lines)
    return templates.TemplateResponse("actuals.html", _ctx(
        request, fy=fy, fiscal_years=fiscal_years,
        lines=lines, rows=rows,
        months=FY_MONTHS, month_labels=MONTH_LABELS,
        saved=saved,
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


@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, fy: int = Query(0)):
    fiscal_years = get_fiscal_years()
    if not fy:
        fy = fiscal_years[0]
    lines  = list_pl_lines()
    b_grid = computed_grid(get_grid("budget",  fy), lines)
    a_grid = computed_grid(get_grid("actuals", fy), lines)

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
    b_grid = computed_grid(get_grid("budget",  fy), lines)
    a_grid = computed_grid(get_grid("actuals", fy), lines)
    content, fname = export_pl_xlsx(lines, b_grid, a_grid, fy)

    # Desktop app: save to Downloads and open
    bundle_base = os.environ.get("LEADS_BUNDLE_BASE") or (
        hasattr(sys, "frozen") and getattr(sys, "frozen", False)
    )
    if bundle_base:
        import subprocess
        from pathlib import Path as _P
        dest = _P.home() / "Downloads" / fname
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

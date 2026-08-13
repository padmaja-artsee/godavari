"""Management Report (MR) FastAPI application — mounted at /mr inside the Leads app.
Set MR_BASE_PATH=/mr before importing this module when mounting.

NOTE: Do not use PEP604 unions (int | None) in FastAPI route signatures — the
desktop bundle runs Python 3.9 and FastAPI cannot evaluate those annotations.
"""
import os
from pathlib import Path
from typing import Optional

MR_BASE = os.environ.get("MR_BASE_PATH", "")

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from urllib.parse import quote
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.jinja_compat import patch_template_response
from mr.app.cs_input import (
    DISPLAY_COLUMNS,
    delete_input_workbook,
    delete_register_row,
    init_register,
    list_input_files,
    list_register_rows,
    merge_rows_into_register,
    parse_gbl_cs_xlsx,
    recompute_sail_months_from_dates,
    register_filter_options,
    register_stats,
    save_cs_upload,
)
from mr.app.actual_vs_projection import build_actual_vs_projection, save_product_map
from mr.app.avp_exports import export_avp_pdf, export_avp_png, export_avp_xlsx
from mr.app.projections import (
    create_blank_projection,
    fy_label,
    get_projection,
    init_projections,
    list_projection_years,
    update_projection_lines,
    _parse_optional_float,
)

_bundle_base = os.environ.get("LEADS_BUNDLE_BASE")
if _bundle_base:
    BASE = Path(_bundle_base) / "mr"
else:
    BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="GBInc Management Report")

if (BASE / "static").exists():
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
if (BASE.parent / "static").exists():
    app.mount("/leads-static", StaticFiles(directory=str(BASE.parent / "static")), name="leads_static")

templates = Jinja2Templates(directory=str(BASE / "templates"))
patch_template_response(templates)
templates.env.globals["_base"] = MR_BASE


def _money(value):
    try:
        if value is None or value == "":
            return "—"
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return value or "—"


def _num(value):
    try:
        if value is None or value == "":
            return "—"
        n = float(value)
        return f"{n:g}" if n == int(n) else f"{n:,.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return value or "—"


templates.env.filters["money"] = _money
templates.env.filters["num"] = _num


def _ctx(request: Request, **kw):
    return {"request": request, **kw}


@app.on_event("startup")
def _startup():
    init_register()
    recompute_sail_months_from_dates()
    init_projections()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = register_stats()
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(request, page="dashboard", stats=stats),
    )


@app.get("/gbl-cs-input", response_class=HTMLResponse)
async def gbl_cs_input(request: Request):
    return templates.TemplateResponse(
        "gbl_cs_input.html",
        _ctx(
            request,
            page="gbl_cs_input",
            preview=None,
            error=None,
            merge=None,
            saved_as=None,
            input_files=list_input_files(),
            notice=request.query_params.get("notice") or None,
        ),
    )


@app.post("/gbl-cs-input", response_class=HTMLResponse)
async def gbl_cs_input_upload(request: Request, file: UploadFile = File(...)):
    error = None
    preview = None
    merge = None
    saved_as = None
    raw_name = file.filename or "upload.xlsx"
    try:
        data = await file.read()
        if not data:
            raise ValueError("Uploaded file is empty.")
        if not raw_name.lower().endswith((".xlsx", ".xlsm")):
            raise ValueError("Please upload an Excel file (.xlsx).")
        preview = parse_gbl_cs_xlsx(data)
        path = save_cs_upload(raw_name, data)
        saved_as = path.name
        merge = merge_rows_into_register(
            preview["rows"],
            source_file=saved_as,
            source_original=raw_name,
        )
    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(
        "gbl_cs_input.html",
        _ctx(
            request,
            page="gbl_cs_input",
            preview=preview,
            error=error,
            merge=merge,
            saved_as=saved_as,
            uploaded_name=raw_name,
            display_columns=DISPLAY_COLUMNS,
            input_files=list_input_files(),
            notice=None,
        ),
    )


@app.post("/gbl-cs-input/delete", response_class=HTMLResponse)
async def gbl_cs_input_delete(request: Request, key: str = Form(...)):
    try:
        result = delete_input_workbook(key)
        notice = (
            f"Removed {result['deleted_rows']} register line(s) "
            f"and {result['deleted_files']} saved file(s)."
        )
        return RedirectResponse(
            url=f"{MR_BASE}/gbl-cs-input?notice={quote(notice)}",
            status_code=303,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "gbl_cs_input.html",
            _ctx(
                request,
                page="gbl_cs_input",
                preview=None,
                error=str(exc),
                merge=None,
                saved_as=None,
                input_files=list_input_files(),
                notice=None,
            ),
            status_code=400,
        )


@app.get("/gbl-cs-register", response_class=HTMLResponse)
async def gbl_cs_register(
    request: Request,
    month: str = Query(""),
    po: str = Query(""),
):
    month = (month or "").strip()
    po = (po or "").strip()
    rows = list_register_rows(month=month or None, po=po or None)
    options = register_filter_options()
    stats = register_stats(month=month or None, po=po or None)
    # Renumber SR.NO for the filtered view (1..n) while keeping original in data-* if needed
    display_rows = []
    for i, row in enumerate(rows, start=1):
        item = dict(row)
        item["display_sr"] = i
        display_rows.append(item)
    return templates.TemplateResponse(
        "gbl_cs_register.html",
        _ctx(
            request,
            page="gbl_cs_register",
            rows=display_rows,
            display_columns=DISPLAY_COLUMNS,
            filter_month=month,
            filter_po=po,
            months=options["months"],
            po_numbers=options["po_numbers"],
            stats=stats,
            filtered_count=len(display_rows),
            notice=request.query_params.get("notice") or None,
        ),
    )


@app.post("/gbl-cs-register/delete", response_class=HTMLResponse)
async def gbl_cs_register_delete(
    request: Request,
    row_id: int = Form(...),
    month: str = Form(""),
    po: str = Form(""),
):
    month = (month or "").strip()
    po = (po or "").strip()
    try:
        ok = delete_register_row(row_id)
        notice = "Line deleted." if ok else "Line was already removed."
    except Exception as exc:
        notice = f"Could not delete line: {exc}"
    qs = []
    if month:
        qs.append(f"month={quote(month)}")
    if po:
        qs.append(f"po={quote(po)}")
    qs.append(f"notice={quote(notice)}")
    return RedirectResponse(
        url=f"{MR_BASE}/gbl-cs-register?{'&'.join(qs)}",
        status_code=303,
    )


@app.get("/sales-projections", response_class=HTMLResponse)
async def sales_projections(request: Request, fy: Optional[int] = Query(None)):
    years = list_projection_years()
    if not years:
        init_projections()
        years = list_projection_years()
    selected = fy if fy in years else (years[0] if years else 2027)
    projection = get_projection(selected)
    return templates.TemplateResponse(
        "sales_projections.html",
        _ctx(
            request,
            page="sales_projections",
            years=years,
            fy=selected,
            projection=projection,
            fy_labels={y: fy_label(y) for y in years},
            notice=request.query_params.get("notice") or None,
            error=None,
            next_fy=(max(years) + 1) if years else 2027,
        ),
    )


@app.post("/sales-projections/new", response_class=HTMLResponse)
async def sales_projections_new(request: Request, fy: int = Form(...)):
    years = list_projection_years()
    if fy in years:
        return RedirectResponse(
            url=f"{MR_BASE}/sales-projections?fy={fy}&notice={quote('That fiscal year already exists.')}",
            status_code=303,
        )
    create_blank_projection(fy)
    return RedirectResponse(
        url=f"{MR_BASE}/sales-projections?fy={fy}&notice={quote(f'Created {fy_label(fy)} projection.')}",
        status_code=303,
    )


@app.post("/sales-projections/save", response_class=HTMLResponse)
async def sales_projections_save(request: Request):
    form = await request.form()
    try:
        fy = int(form.get("fy"))
    except (TypeError, ValueError):
        return RedirectResponse(
            url=f"{MR_BASE}/sales-projections?notice={quote('Invalid fiscal year.')}",
            status_code=303,
        )
    ids = form.getlist("line_id")
    products = form.getlist("product")
    qtys = form.getlist("qty_mt")
    sales = form.getlist("sales_value")
    incomes = form.getlist("income")
    posted = []
    for i, row_id in enumerate(ids):
        posted.append(
            {
                "id": row_id,
                "product": products[i] if i < len(products) else "",
                "qty_mt": _parse_optional_float(qtys[i] if i < len(qtys) else None),
                "sales_value": _parse_optional_float(sales[i] if i < len(sales) else None),
                "income": _parse_optional_float(incomes[i] if i < len(incomes) else None),
            }
        )
    update_projection_lines(fy, posted)
    return RedirectResponse(
        url=f"{MR_BASE}/sales-projections?fy={fy}&notice={quote('Projection saved.')}",
        status_code=303,
    )


@app.get("/actual-vs-projection", response_class=HTMLResponse)
async def actual_vs_projection(
    request: Request,
    fy: Optional[int] = Query(None),
    month: str = Query("APRIL"),
    notice: Optional[str] = Query(None),
):
    years = list_projection_years()
    if not years:
        init_projections()
        years = list_projection_years() or [2027]
    selected_fy = fy if fy in years else years[0]
    report = build_actual_vs_projection(fiscal_year=selected_fy, month=month)
    report["available_years"] = years
    return templates.TemplateResponse(
        "actual_vs_projection.html",
        _ctx(
            request,
            page="actual_vs_projection",
            report=report,
            fy_labels={y: fy_label(y) for y in years},
            notice=notice,
        ),
    )


@app.post("/actual-vs-projection/map-product")
async def actual_vs_projection_map_product(
    fy: int = Form(...),
    month: str = Form("APRIL"),
    alias_key: str = Form(...),
    display_label: str = Form(""),
    product: str = Form(...),
):
    chosen = (product or "").strip()
    if chosen.startswith("__new__:"):
        chosen = chosen.split(":", 1)[1].strip() or display_label.strip()
    if chosen:
        save_product_map(alias_key, chosen, display_label or chosen)
        notice = quote(f"Mapped to “{chosen}”.")
    else:
        notice = quote("No product selected.")
    return RedirectResponse(
        url=f"{MR_BASE}/actual-vs-projection?fy={fy}&month={month}&notice={notice}",
        status_code=303,
    )


@app.get("/actual-vs-projection/export.xlsx")
async def actual_vs_projection_xlsx(
    fy: Optional[int] = Query(None),
    month: str = Query("APRIL"),
):
    years = list_projection_years() or [2027]
    selected_fy = fy if fy in years else years[0]
    report = build_actual_vs_projection(fiscal_year=selected_fy, month=month)
    content, fname = export_avp_xlsx(report)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/actual-vs-projection/export.pdf")
async def actual_vs_projection_pdf(
    fy: Optional[int] = Query(None),
    month: str = Query("APRIL"),
):
    years = list_projection_years() or [2027]
    selected_fy = fy if fy in years else years[0]
    report = build_actual_vs_projection(fiscal_year=selected_fy, month=month)
    content, fname = export_avp_pdf(report)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/actual-vs-projection/export.png")
async def actual_vs_projection_png(
    fy: Optional[int] = Query(None),
    month: str = Query("APRIL"),
):
    years = list_projection_years() or [2027]
    selected_fy = fy if fy in years else years[0]
    report = build_actual_vs_projection(fiscal_year=selected_fy, month=month)
    content, fname = export_avp_png(report)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

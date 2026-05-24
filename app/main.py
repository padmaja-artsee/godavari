from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from typing import List

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import (
    create_deal,
    create_lead,
    customer_detail,
    delete_activity,
    attach_activity_to_deal,
    delete_customer,
    update_activity,
    dashboard_stats,
    get_deal_detail,
    get_lead_by_company,
    init_db,
    list_customers,
    list_active_leads,
    group_active_leads,
    list_shipping_summary,
    list_deals,
    deals_for_activity_edit,
    iso_date_input,
    list_deals_for_company,
    list_products,
    log_update,
    archive_deal,
    bulk_deal_action,
    delete_deal,
    mark_deal_lost,
    mark_deal_shipped,
    unarchive_deal,
    update_deal_fields,
    PRICE_UNITS,
    format_quantity_display,
    list_quantity_unit_options,
    normalize_quantity_unit,
    migrate_to_leads_deals,
    recent_activities,
    search_leads_contacts,
    summary_by_customer,
    summary_by_product,
    update_lead,
    update_company_profile,
    create_contact,
    update_contact,
    delete_contact,
)
from app.exports import (
    SHIPPING_COLUMNS,
    export_filename,
    rollup_columns,
    rollup_sheet_name,
    to_csv_bytes,
    to_xlsx_bytes,
)
from app.deal_files import (
    add_deal_file,
    delete_deal_file,
    get_deal_file,
    list_deal_files,
)
from app.products import (
    add_product_file,
    delete_product,
    delete_product_file,
    fix_legacy_product_names,
    get_product,
    get_product_file,
    import_catalogue,
    list_products_full,
    save_product,
    update_deal_product,
)
from app.generate import GENERATE_DOCUMENTS
from app.po_exports import export_po_pdf, export_po_xlsx
# ── Commission Invoice (self-contained; remove this block to drop the feature) ──
from app.commission_invoices import (
    DEFAULT_CI,
    create_ci_from_deal,
    create_ci_from_deals,
    create_commission_invoice,
    delete_commission_invoice,
    duplicate_commission_invoice,
    get_commission_invoice,
    get_commission_invoice_for_export,
    list_commission_invoices,
    parse_ci_form,
    upgrade_commission_invoices_schema,
)
from app.ci_exports import export_ci_xlsx
# ── Sales (Commercial) Invoice ──────────────────────────────────────────────
from app.sales_invoices import (
    DEFAULT_SI,
    create_sales_invoice,
    create_si_from_deals,
    delete_sales_invoice,
    duplicate_sales_invoice,
    get_sales_invoice,
    get_sales_invoice_for_export,
    list_sales_invoices,
    parse_si_form,
    upgrade_sales_invoices_schema,
)
from app.si_exports import export_si_xlsx
# ── Delivery Note ────────────────────────────────────────────────────────────
from app.delivery_notes import (
    DEFAULT_DN,
    create_delivery_note,
    create_dn_from_deal,
    delete_delivery_note,
    duplicate_delivery_note,
    get_delivery_note,
    list_delivery_notes,
    parse_dn_form,
    upgrade_delivery_notes_schema,
)
from app.dn_exports import export_dn_xlsx
from app.purchase_orders import (
    DEFAULT_PO,
    calculate_po_totals,
    create_purchase_order,
    create_purchase_order_from_deal,
    delete_purchase_order,
    duplicate_purchase_order,
    get_purchase_order,
    get_purchase_order_for_export,
    list_purchase_orders,
    parse_po_form,
    update_purchase_order,
    validate_purchase_order,
    validation_warnings,
)
from app.seed import load_seed

import sys as _sys
import os as _os

# Mount Finance as a sub-app at /finance (Option B single-port architecture).
# Must set env var BEFORE importing finance.app.main so FINANCE_BASE is correct.
_os.environ.setdefault("FINANCE_BASE_PATH", "/finance")

# When frozen by PyInstaller the launcher sets LEADS_BUNDLE_BASE = sys._MEIPASS,
# which is the directory that actually contains templates/, static/, data/.
# Fall back to Path(__file__).parent.parent for source runs.
_bundle_base = _os.environ.get("LEADS_BUNDLE_BASE")
BASE = Path(_bundle_base) if _bundle_base else Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["qty_display"] = format_quantity_display
templates.env.filters["iso_date"] = iso_date_input


def _money_filter(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return value or "—"


def _num_filter(value):
    try:
        n = float(value)
        return f"{n:g}" if n == int(n) else f"{n:,.2f}"
    except (TypeError, ValueError):
        return value or "—"


templates.env.filters["money"] = _money_filter
templates.env.filters["num"] = _num_filter


def _timeline_deal_ids(timeline: dict) -> set[int]:
    ids: set[int] = set()
    for group in timeline.get("deal_groups") or []:
        if group.get("deal_id"):
            ids.add(int(group["deal_id"]))
        for act in group.get("activities") or []:
            if act.get("deal_id"):
                ids.add(int(act["deal_id"]))
    for act in timeline.get("company_level") or []:
        if act.get("deal_id"):
            ids.add(int(act["deal_id"]))
    return ids

app = FastAPI(title="GBInc Leads Dashboard")

_static_dir = BASE / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
else:
    import warnings
    warnings.warn(f"Static directory not found: {_static_dir}")

# Mount the Finance sub-app at /finance (single-port Option B).
try:
    from finance.app.main import app as _finance_app
    app.mount("/finance", _finance_app)
except Exception as _e:
    import warnings
    warnings.warn(f"Finance sub-app could not be mounted: {_e}")


@app.on_event("startup")
def startup() -> None:
    import threading as _threading
    import logging as _logging

    _log = _logging.getLogger("leads.startup")

    try:
        # Enable WAL mode before anything else so concurrent reads never block saves.
        import sqlite3 as _sqlite3
        from app.database import DB_PATH as _DB_PATH
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _wc = _sqlite3.connect(str(_DB_PATH), timeout=30)
        _wc.execute("PRAGMA journal_mode = WAL")
        _wc.commit()
        _wc.close()
    except Exception as exc:
        _log.error("WAL setup failed: %s", exc)

    try:
        # init_db creates tables — must run synchronously before requests arrive.
        init_db()
    except Exception as exc:
        _log.error("init_db failed: %s", exc)

    # Seed loading can be slow (large JSON with hundreds of records).
    # Run it in a background thread so the server accepts requests immediately.
    # The 3-second delay lets the first user interaction complete before any
    # background writes begin, preventing immediate DB lock contention.
    def _seed_in_background():
        import time as _time
        _time.sleep(3)
        try:
            load_seed()
            migrate_to_leads_deals()
            import_catalogue()
            fix_legacy_product_names()
        except Exception as exc:
            _logging.getLogger("leads.startup").warning("Background seed error: %s", exc)

    _threading.Thread(target=_seed_in_background, daemon=True).start()

    try:
        upgrade_commission_invoices_schema()
        upgrade_sales_invoices_schema()
        upgrade_delivery_notes_schema()
    except Exception as exc:
        _log.error("Schema upgrade failed: %s", exc)


def _open_in_system_browser(path: str) -> None:
    """Open a local URL in the system default browser (Safari/Chrome).
    Used for Print because window.print() is blocked in Tauri's WKWebView."""
    import subprocess, sys as _s
    url = f"http://127.0.0.1:8000{path}"
    try:
        if _s.platform == "darwin":
            subprocess.Popen(["open", url])
        elif _s.platform == "win32":
            subprocess.Popen(["start", url], shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        pass


@app.get("/open-print")
async def open_print_in_browser(url: str = Query(...)):
    """Called by the Print button; opens the print page in the system browser."""
    _open_in_system_browser(url)
    return Response(status_code=204)


def _export_to_downloads(content: bytes, fname: str) -> str:
    """
    Save export bytes to ~/Downloads/<fname> and open in the default app.
    Returns the full path so routes can show it in a success message.
    Used because Tauri's WKWebView does not handle Content-Disposition
    attachment downloads the way a regular browser does.
    """
    import subprocess, sys as _sys2
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    dest = downloads / fname
    # Avoid clobbering: append a counter if the file already exists.
    counter = 1
    while dest.exists():
        stem, suffix = dest.stem, dest.suffix
        dest = downloads / f"{stem}_{counter}{suffix}"
        counter += 1
    dest.write_bytes(content)
    # Open the file with the default application (Excel / Numbers on macOS).
    try:
        if _sys2.platform == "darwin":
            subprocess.Popen(["open", str(dest)])
        elif _sys2.platform == "win32":
            import os as _os2; _os2.startfile(str(dest))
        else:
            subprocess.Popen(["xdg-open", str(dest)])
    except Exception:
        pass
    return str(dest)


def ctx(request: Request, **extra):
    return {
        "request": request,
        "price_units": PRICE_UNITS,
        "quantity_units": list_quantity_unit_options(),
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, period: str = Query("all")):
    return templates.TemplateResponse(
        "dashboard.html",
        ctx(
            request,
            page="dashboard",
            period=period,
            stats=dashboard_stats(period),
            recent=recent_activities(20, period),
            by_product=summary_by_product(period)[:8],
            open_deals=list_deals(status="open", period="all")[:5],
        ),
    )


@app.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    q: str = Query(""),
    category: str = Query(""),
    status: str = Query(""),
):
    products = list_products_full(q, category, status)
    categories = sorted({p.get("category") or "" for p in products if p.get("category")})
    return templates.TemplateResponse(
        "products.html",
        ctx(
            request,
            page="products",
            products=products,
            q=q,
            category=category,
            status=status,
            categories=categories,
        ),
    )


PRODUCTS_COLUMNS: list[tuple[str, str]] = [
    ("Product", "name"),
    ("Trade Name", "trade_name"),
    ("CAS Number", "cas_number"),
    ("Category", "category"),
    ("Status", "status"),
    ("Biobased Content", "biobased_content"),
    ("Certifications", "certifications"),
    ("Applications", "applications"),
    ("Synonyms", "synonyms"),
]


@app.get("/products/export.xlsx")
async def products_export_xlsx(
    q: str = Query(""),
    category: str = Query(""),
    status: str = Query(""),
):
    rows = list_products_full(q, category, status)
    fname = export_filename("gbinc-products", status, "xlsx")
    return _download_response(
        to_xlsx_bytes([("Products", rows, PRODUCTS_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/products/new", response_class=HTMLResponse)
async def product_new(request: Request):
    return templates.TemplateResponse(
        "product_edit.html",
        ctx(request, page="products", product=None),
    )


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_edit_page(
    request: Request,
    product_id: int,
    error: str = Query(""),
):
    product = get_product(product_id)
    if not product:
        return RedirectResponse("/products", status_code=303)
    err_msg = ""
    if error == "pdf_only":
        err_msg = "Only PDF files can be attached."
    elif error == "invalid_file":
        err_msg = "Could not save that file."
    elif error == "delete_failed":
        err_msg = "This product could not be deleted (it may be protected)."
    return templates.TemplateResponse(
        "product_edit.html",
        ctx(request, page="products", product=product, error_msg=err_msg),
    )


@app.post("/products/{product_id}/delete")
async def product_delete(product_id: int):
    result = delete_product(product_id)
    if not result.get("ok"):
        return RedirectResponse(f"/products/{product_id}?error=delete_failed", status_code=303)
    return RedirectResponse("/products", status_code=303)


@app.post("/products/{product_id}/upload")
async def product_upload_pdf(
    product_id: int,
    pdf_file: UploadFile = File(...),
):
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        return RedirectResponse(f"/products/{product_id}?error=pdf_only", status_code=303)
    content = await pdf_file.read()
    try:
        add_product_file(product_id, pdf_file.filename, content)
    except ValueError:
        return RedirectResponse(f"/products/{product_id}?error=invalid_file", status_code=303)
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.get("/products/files/{file_id}")
async def product_download_pdf(file_id: int):
    info = get_product_file(file_id)
    if not info:
        return RedirectResponse("/products", status_code=303)
    return FileResponse(
        info["absolute_path"],
        media_type="application/pdf",
        filename=info["filename"],
    )


@app.post("/products/files/{file_id}/delete")
async def product_delete_pdf(file_id: int):
    product_id = delete_product_file(file_id)
    if product_id:
        return RedirectResponse(f"/products/{product_id}", status_code=303)
    return RedirectResponse("/products", status_code=303)


@app.post("/products/save")
async def product_save(
    name: str = Form(...),
    trade_name: str = Form(""),
    cas_number: str = Form(""),
    hs_code: str = Form(""),
    biobased_content: str = Form(""),
    applications: str = Form(""),
    certifications: str = Form(""),
    category: str = Form(""),
    synonyms: str = Form(""),
    notes: str = Form(""),
    status: str = Form("active"),
    product_id: str = Form(""),
):
    pid = int(product_id) if product_id else None
    save_product(
        {
            "name": name,
            "trade_name": trade_name,
            "cas_number": cas_number,
            "hs_code": hs_code,
            "biobased_content": biobased_content,
            "applications": applications,
            "certifications": certifications,
            "category": category,
            "synonyms": synonyms,
            "notes": notes,
            "status": status,
        },
        pid,
    )
    return RedirectResponse("/products", status_code=303)


@app.post("/deals/{deal_id}/product")
async def deal_change_product(
    deal_id: int,
    product_id: int = Form(...),
    next_url: str = Form(""),
):
    update_deal_product(deal_id, product_id)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.post("/deals/{deal_id}/meta")
async def deal_update_meta(
    deal_id: int,
    notes: str = Form(""),
    po_number: str = Form(""),
    quote_ref: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
    next_url: str = Form(""),
):
    update_deal_fields(
        deal_id,
        notes,
        po_number,
        quote_ref,
        quantity,
        quantity_unit,
        quantity_unit_other,
        price,
        price_unit,
        po_date,
        packing,
        gbl_invoice,
        gbl_invoice_date,
        container_number,
        vessel_name,
        etd_india,
        transit_time,
        destination,
        eta,
        incoterms=incoterms,
        payment_terms=payment_terms,
        shipment_timing=shipment_timing,
    )
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.get("/shipping", response_class=HTMLResponse)
async def shipping_summary_page(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    return templates.TemplateResponse(
        "shipping.html",
        ctx(
            request,
            page="shipping",
            rows=list_shipping_summary(company, product, status, q),
            company=company,
            product=product,
            status=status,
            q=q,
        ),
    )


@app.get("/leads", response_class=HTMLResponse)
async def leads_contacts(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    q: str = Query(""),
):
    return templates.TemplateResponse(
        "leads.html",
        ctx(
            request,
            page="leads",
            leads=search_leads_contacts(company, product, q),
            company=company,
            product=product,
            q=q,
        ),
    )


@app.get("/deals", response_class=HTMLResponse)
async def active_leads_page(
    request: Request,
    status: str = Query("all"),
    period: str = Query("month"),
    company: str = Query(""),
    product: str = Query(""),
    po: str = Query(""),
    q: str = Query(""),
    view: str = Query("company"),
):
    view_mode = "product" if view == "product" else "company"
    leads = list_active_leads(status, period, company, product, po, q)
    return templates.TemplateResponse(
        "deals.html",
        ctx(
            request,
            page="deals",
            leads=leads,
            lead_groups=group_active_leads(leads, view_mode),
            status=status,
            period=period,
            company=company,
            product=product,
            po=po,
            q=q,
            view=view_mode,
        ),
    )


@app.get("/api/company-deals")
async def api_company_deals(company: str = Query(...)):
    return JSONResponse(list_deals_for_company(company, active_only=False))


@app.get("/add", response_class=HTMLResponse)
async def add_page(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    deal_id: str = Query(""),
    tab: str = Query("log"),
    return_to: str = Query(""),
):
    company_deals = (
        list_deals_for_company(company, active_only=False) if company else []
    )
    return templates.TemplateResponse(
        "add.html",
        ctx(
            request,
            page="add",
            tab=tab,
            customers=list_customers(),
            products=list_products(),
            preset_company=company,
            preset_product=product,
            preset_deal_id=deal_id,
            return_to=return_to,
            company_deals=company_deals,
            lead=get_lead_by_company(company) if company else None,
        ),
    )


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_page(
    request: Request,
    deal_id: int,
    error: str = Query(""),
):
    detail = get_deal_detail(deal_id)
    if not detail:
        return RedirectResponse("/deals", status_code=303)
    pid = detail["deal"].get("product_id")
    product_record = get_product(pid) if pid else None
    company = detail["deal"]["company"]
    today = datetime.utcnow().date().isoformat()
    err_msg = ""
    if error == "pdf_only":
        err_msg = "Only PDF files can be attached."
    elif error == "invalid_file":
        err_msg = "Could not attach that file."
    return templates.TemplateResponse(
        "deal.html",
        ctx(
            request,
            page="deals",
            detail=detail,
            product_record=product_record,
            deal_files=list_deal_files(deal_id),
            deal_file_error=err_msg,
            all_products=list_products(),
            company_deals=deals_for_activity_edit(
                company,
                {deal_id, *(a.get("deal_id") for a in detail.get("activities", []))},
            ),
            today=today,
        ),
    )


@app.post("/deals/{deal_id}/upload")
async def deal_upload_pdf(
    deal_id: int,
    pdf_file: UploadFile = File(...),
    next_url: str = Form(""),
):
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        dest = next_url or f"/deal/{deal_id}"
        return RedirectResponse(f"{dest}?error=pdf_only", status_code=303)
    content = await pdf_file.read()
    try:
        add_deal_file(deal_id, pdf_file.filename, content)
    except ValueError:
        dest = next_url or f"/deal/{deal_id}"
        return RedirectResponse(f"{dest}?error=invalid_file", status_code=303)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.get("/deals/files/{file_id}")
async def deal_download_pdf(file_id: int):
    info = get_deal_file(file_id)
    if not info:
        return RedirectResponse("/deals", status_code=303)
    return FileResponse(
        info["absolute_path"],
        media_type="application/pdf",
        filename=info["filename"],
    )


@app.post("/deals/files/{file_id}/delete")
async def deal_delete_pdf_route(
    file_id: int,
    next_url: str = Form(""),
):
    deal_id = delete_deal_file(file_id)
    if deal_id:
        return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)
    return RedirectResponse("/deals", status_code=303)


@app.post("/add/contact")
async def post_contact(
    company: str = Form(...),
    contact: str = Form(""),
    email: str = Form(""),
    website: str = Form(""),
    phone: str = Form(""),
    products_interested: str = Form(""),
    notes: str = Form(""),
):
    create_lead(
        {
            "company": company,
            "contact": contact,
            "email": email,
            "website": website,
            "phone": phone,
            "products_interested": products_interested,
            "notes": notes,
        }
    )
    return RedirectResponse(f"/leads?company={quote(company)}", status_code=303)


@app.post("/add/deal")
async def post_deal(
    company: str = Form(...),
    product: str = Form(...),
    deal_date: str = Form(...),
    po_number: str = Form(""),
    quote_ref: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    notes: str = Form(""),
    # Shipping / tracking fields
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
):
    deal_id = create_deal(
        {
            "company": company,
            "product": product,
            "deal_date": deal_date,
            "po_number": po_number,
            "quote_ref": quote_ref,
            "quantity": quantity,
            "quantity_unit": normalize_quantity_unit(
                quantity_unit, quantity_unit_other
            ),
            "price": price,
            "price_unit": price_unit,
            "notes": notes,
        }
    )
    # Save commercial + shipping fields if any were provided
    extra = {
        "po_date": po_date, "packing": packing, "gbl_invoice": gbl_invoice,
        "gbl_invoice_date": gbl_invoice_date, "container_number": container_number,
        "vessel_name": vessel_name, "etd_india": etd_india,
        "transit_time": transit_time, "destination": destination, "eta": eta,
        "incoterms": incoterms, "payment_terms": payment_terms,
        "shipment_timing": shipment_timing,
    }
    if any(v.strip() for v in extra.values()):
        update_deal_fields(
            deal_id,
            po_number=po_number, quote_ref=quote_ref,
            quantity=quantity,
            quantity_unit=normalize_quantity_unit(quantity_unit, quantity_unit_other),
            price=price, price_unit=price_unit, notes=notes,
            **extra,
        )
    return RedirectResponse("/deals", status_code=303)


@app.post("/add/log")
async def post_log(
    request: Request,
    company: str = Form(...),
    link_mode: str = Form("none"),
    deal_id: str = Form(""),
    product: str = Form(""),
    product_new: str = Form(""),
    product_none: str = Form(""),
    deal_date: str = Form(""),
    po_number: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    deal_quantity: str = Form(""),
    deal_quantity_unit: str = Form("MT"),
    deal_quantity_unit_other: str = Form(""),
    deal_price: str = Form(""),
    deal_price_unit: str = Form("/MT"),
    deal_notes: str = Form(""),
    deal_po_number: str = Form(""),
    deal_notes_append: str = Form(""),
    quote_ref: str = Form(""),
    activity_date: str = Form(...),
    channel: str = Form("Email"),
    comment: str = Form(""),
    value: str = Form(""),
    # Shipping fields — only used when link_mode == "new"
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
):
    if link_mode == "new":
        product_val = product_new or product
    elif link_mode == "none":
        product_val = product_none or product
    else:
        product_val = product
    try:
        result = log_update(
            {
                "company": company,
                "link_mode": link_mode,
                "deal_id": int(deal_id) if deal_id and link_mode == "existing" else None,
                "product": product_val,
                "deal_date": deal_date or activity_date,
                "po_number": po_number,
                "quantity": quantity or deal_quantity,
                "quantity_unit": quantity_unit or deal_quantity_unit,
                "quantity_unit_other": quantity_unit_other or deal_quantity_unit_other,
                "price": price or deal_price,
                "price_unit": price_unit if price or quantity else deal_price_unit,
                "deal_notes": deal_notes,
                "deal_po_number": deal_po_number,
                "quote_ref": quote_ref,
                "deal_quantity": deal_quantity,
                "deal_quantity_unit": deal_quantity_unit,
                "deal_quantity_unit_other": deal_quantity_unit_other,
                "deal_price": deal_price,
                "deal_price_unit": deal_price_unit,
                "deal_notes_append": deal_notes_append,
                "activity_date": activity_date,
                "channel": channel,
                "comment": comment,
                "value": value,
            }
        )
    except ValueError as e:
        return RedirectResponse(
            f"/add?tab=log&company={quote(company)}&error={quote(str(e))}",
            status_code=303,
        )
    # Save shipping + commercial fields for new or existing deals when provided
    if result.get("deal_id") and link_mode in ("new", "existing"):
        extra = {
            "po_date": po_date, "packing": packing, "gbl_invoice": gbl_invoice,
            "gbl_invoice_date": gbl_invoice_date, "container_number": container_number,
            "vessel_name": vessel_name, "etd_india": etd_india,
            "transit_time": transit_time, "destination": destination, "eta": eta,
            "incoterms": incoterms, "payment_terms": payment_terms,
            "shipment_timing": shipment_timing,
        }
        if any(v.strip() for v in extra.values()):
            update_deal_fields(result["deal_id"], **extra)
    return_to = request.query_params.get("return_to", "")
    if return_to.startswith("/"):
        return RedirectResponse(return_to, status_code=303)
    if result.get("deal_id"):
        return RedirectResponse(f"/deal/{result['deal_id']}", status_code=303)
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/deals/{deal_id}/ship")
async def ship_deal(deal_id: int, shipped_date: str = Form(""), next_url: str = Form("")):
    mark_deal_shipped(deal_id, shipped_date or None)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/lost")
async def lost_deal(
    deal_id: int,
    closed_date: str = Form(""),
    lost_reason: str = Form(""),
    next_url: str = Form(""),
):
    mark_deal_lost(deal_id, closed_date or None, lost_reason)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/archive")
async def archive_deal_route(deal_id: int, next_url: str = Form("")):
    archive_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/unarchive")
async def unarchive_deal_route(deal_id: int, next_url: str = Form("")):
    unarchive_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=archived", status_code=303)


@app.post("/deals/{deal_id}/delete")
async def delete_deal_route(deal_id: int, next_url: str = Form("")):
    delete_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/bulk")
async def bulk_deals_route(
    action: str = Form(...),
    deal_ids: List[str] = Form(default=[]),
    lost_reason: str = Form(""),
    closed_date: str = Form(""),
    return_status: str = Form("open"),
    return_period: str = Form("all"),
):
    ids = [int(x) for x in deal_ids if x and x.isdigit()]
    if ids:
        bulk_deal_action(ids, action, lost_reason, closed_date or None)
    qs = f"status={return_status}&period={return_period}"
    return RedirectResponse(f"/deals?{qs}", status_code=303)


@app.post("/activities/{activity_id}/edit")
async def edit_activity_route(
    activity_id: int,
    activity_date: str = Form(...),
    channel: str = Form("Note"),
    comment: str = Form(""),
    link_mode: str = Form("none"),
    deal_id: str = Form(""),
    product: str = Form(""),
    product_new: str = Form(""),
    product_none: str = Form(""),
    deal_date: str = Form(""),
    next_url: str = Form(""),
):
    if link_mode == "new":
        product_val = product_new or product
    elif link_mode == "none":
        product_val = product_none or product
    else:
        product_val = product
    try:
        company = update_activity(
            activity_id,
            {
                "activity_date": activity_date,
                "channel": channel,
                "comment": comment,
                "link_mode": link_mode,
                "deal_id": deal_id if link_mode == "existing" else "",
                "product": product_val,
                "deal_date": deal_date or activity_date,
            },
        )
    except ValueError as e:
        base = next_url if next_url.startswith("/") else "/leads"
        sep = "&" if "?" in base else "?"
        code = "pick_deal" if "Pick a deal" in str(e) else quote(str(e))
        return RedirectResponse(f"{base}{sep}error={code}", status_code=303)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if company:
        return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)
    return RedirectResponse("/leads", status_code=303)


@app.post("/activities/{activity_id}/attach")
async def attach_activity_route(
    activity_id: int,
    deal_id: int = Form(...),
    next_url: str = Form(""),
):
    attach_activity_to_deal(activity_id, deal_id)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.post("/activities/{activity_id}/delete")
async def delete_activity_route(
    activity_id: int,
    next_url: str = Form(""),
):
    company = delete_activity(activity_id)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if company:
        return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)
    return RedirectResponse("/leads", status_code=303)


@app.get("/customer", response_class=HTMLResponse)
async def customer_page(
    request: Request,
    name: str = Query(...),
    product: str = Query(""),
    error: str = Query(""),
):
    detail = customer_detail(name, product)
    if not detail:
        return RedirectResponse("/leads", status_code=303)
    err_msg = ""
    if error == "pick_deal":
        err_msg = "Pick a deal to attach this entry to, or switch to Company only."
    elif error:
        err_msg = error.replace("+", " ")
    return templates.TemplateResponse(
        "customer.html",
        ctx(
            request,
            page="leads",
            detail=detail,
            product_filter=product,
            company_deals=deals_for_activity_edit(
                name, _timeline_deal_ids(detail["timeline"])
            ),
            activity_error=err_msg,
            all_products=list_products(),
        ),
    )


@app.post("/customer/{customer_id}/delete")
async def delete_customer_route(customer_id: int):
    name = delete_customer(customer_id)
    if not name:
        return RedirectResponse("/leads?error=company_not_found", status_code=303)
    return RedirectResponse("/leads", status_code=303)


@app.post("/customer/{customer_id}/profile")
async def edit_company_profile_route(
    customer_id: int,
    website: str = Form(""),
    products_interested: str = Form(""),
    notes: str = Form(""),
    company: str = Form(""),
):
    update_company_profile(
        customer_id,
        {
            "website": website,
            "products_interested": products_interested,
            "notes": notes,
        },
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/customer/{customer_id}/contacts")
async def add_contact(
    customer_id: int,
    contact: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    is_primary: str = Form(""),
    company: str = Form(""),
):
    create_contact(
        customer_id,
        {"contact": contact, "email": email, "phone": phone},
        is_primary=bool(is_primary),
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/contacts/{contact_id}/update")
async def edit_contact(
    contact_id: int,
    contact: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    is_primary: str = Form(""),
    company: str = Form(""),
):
    update_contact(
        contact_id,
        {
            "contact": contact,
            "email": email,
            "phone": phone,
            "is_primary": bool(is_primary),
        },
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/contacts/{contact_id}/delete")
async def remove_contact(
    contact_id: int,
    company: str = Form(""),
):
    delete_contact(contact_id)
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


def _download_response(content: bytes, filename: str, media_type: str) -> Response:
    # In the packaged Tauri app WKWebView cannot trigger file downloads, so
    # save to ~/Downloads and open in the default app instead.
    if _os.environ.get("LEADS_BUNDLE_BASE") or getattr(_sys, "frozen", False):
        _export_to_downloads(content, filename)
        return Response(
            content=b"",
            status_code=204,
        )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/summary/export.csv")
async def summary_export_csv(
    period: str = Query("month"),
    group: str = Query("product"),
    sheet: str = Query("rollup"),
):
    if sheet == "shipping":
        rows = list_shipping_summary(status="open")
        cols = SHIPPING_COLUMNS
        fname = export_filename("gbinc-shipping-summary", period, "csv")
    else:
        rows = (
            summary_by_product(period)
            if group == "product"
            else summary_by_customer(period)
        )
        cols = rollup_columns(group)
        fname = export_filename("gbinc-summary", period, "csv", group)
    return _download_response(
        to_csv_bytes(rows, cols),
        fname,
        "text/csv; charset=utf-8",
    )


@app.get("/summary/export.xlsx")
async def summary_export_xlsx(
    period: str = Query("month"),
    group: str = Query("product"),
    sheet: str = Query("all"),
):
    rollup_rows = (
        summary_by_product(period)
        if group == "product"
        else summary_by_customer(period)
    )
    shipping_rows = list_shipping_summary(status="open")
    if sheet == "rollup":
        sheets = [(rollup_sheet_name(group), rollup_rows, rollup_columns(group))]
        fname = export_filename("gbinc-summary", period, "xlsx", group)
    elif sheet == "shipping":
        sheets = [("Shipping", shipping_rows, SHIPPING_COLUMNS)]
        fname = export_filename("gbinc-shipping-summary", period, "xlsx")
    else:
        sheets = [
            (rollup_sheet_name(group), rollup_rows, rollup_columns(group)),
            ("Shipping", shipping_rows, SHIPPING_COLUMNS),
        ]
        fname = export_filename("gbinc-summary-all", period, "xlsx", group)
    return _download_response(
        to_xlsx_bytes(sheets),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/shipping/export.csv")
async def shipping_export_csv(
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    rows = list_shipping_summary(company, product, status, q)
    fname = export_filename("gbinc-shipping", status if status != "all" else "", "csv")
    return _download_response(
        to_csv_bytes(rows, SHIPPING_COLUMNS),
        fname,
        "text/csv; charset=utf-8",
    )


@app.get("/shipping/export.xlsx")
async def shipping_export_xlsx(
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    rows = list_shipping_summary(company, product, status, q)
    fname = export_filename("gbinc-shipping", status if status != "all" else "", "xlsx")
    return _download_response(
        to_xlsx_bytes([("Shipping", rows, SHIPPING_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


LEADS_COLUMNS: list[tuple[str, str]] = [
    ("Company", "company"),
    ("Contact", "contact"),
    ("Email", "email"),
    ("Phone", "phone"),
    ("Website", "website"),
    ("Products Interested", "products_interested"),
    ("Notes", "notes"),
    ("Last Updated", "updated_at"),
]

DEALS_COLUMNS: list[tuple[str, str]] = [
    ("Deal Date", "deal_date"),
    ("Company", "company"),
    ("Product", "product"),
    ("Quantity", "quantity"),
    ("Unit", "quantity_unit"),
    ("Price", "price"),
    ("Price Unit", "price_unit"),
    ("Value", "value"),
    ("Status", "status"),
    ("PO Number", "po_number"),
    ("Quote Ref", "quote_ref"),
    ("Notes", "notes"),
]


@app.get("/leads/export.xlsx")
async def leads_export_xlsx(
    company: str = Query(""),
    product: str = Query(""),
    q: str = Query(""),
):
    rows = search_leads_contacts(company, product, q)
    fname = export_filename("gbinc-leads", "", "xlsx")
    return _download_response(
        to_xlsx_bytes([("Leads", rows, LEADS_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/deals/export.xlsx")
async def deals_export_xlsx(
    status: str = Query("open"),
    period: str = Query("all"),
    company: str = Query(""),
    product: str = Query(""),
    q: str = Query(""),
):
    rows = list_active_leads(status, period, company, product, "", q)
    fname = export_filename("gbinc-active-leads", status, "xlsx")
    return _download_response(
        to_xlsx_bytes([("Active Leads", rows, DEALS_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/summary", response_class=HTMLResponse)
async def summary(
    request: Request,
    period: str = Query("month"),
    group: str = Query("product"),
):
    rows = summary_by_product(period) if group == "product" else summary_by_customer(period)
    shipping_rows = list_shipping_summary(status="open")[:40]
    return templates.TemplateResponse(
        "summary.html",
        ctx(
            request,
            page="summary",
            shipping_rows=shipping_rows,
            period=period,
            group=group,
            rows=rows,
            stats=dashboard_stats(period),
        ),
    )


# --- Generate module ---


@app.get("/generate", response_class=HTMLResponse)
async def generate_index(request: Request):
    return templates.TemplateResponse(
        "generate/index.html",
        ctx(request, page="generate", documents=GENERATE_DOCUMENTS),
    )


@app.get("/generate/charts", response_class=HTMLResponse)
async def charts_page(request: Request, period: str = "12m"):
    import json
    from app.charts import all_chart_data
    data = all_chart_data(period)
    return templates.TemplateResponse(
        "generate/charts.html",
        ctx(request, page="generate", period=period,
            chart_data_json=json.dumps(data)),
    )


@app.get("/generate/purchase-orders", response_class=HTMLResponse)
async def po_list_page(request: Request):
    return templates.TemplateResponse(
        "generate/purchase_orders/po_list.html",
        ctx(request, page="generate", rows=list_purchase_orders()),
    )


@app.get("/api/po-companies")
async def api_po_companies(q: str = Query("")):
    """Companies that have at least one deal, filtered by q."""
    from app.database import get_db
    q = q.strip()
    with get_db() as conn:
        if q:
            rows = conn.execute(
                """SELECT DISTINCT c.name FROM deals d
                   JOIN customers c ON c.id = d.customer_id
                   WHERE d.deleted_at IS NULL AND d.archived = 0
                     AND c.name LIKE ? COLLATE NOCASE
                   ORDER BY c.name LIMIT 50""",
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT c.name FROM deals d
                   JOIN customers c ON c.id = d.customer_id
                   WHERE d.deleted_at IS NULL AND d.archived = 0
                   ORDER BY c.name LIMIT 50""",
            ).fetchall()
    return {"companies": [r[0] for r in rows]}


@app.get("/api/po-deals")
async def api_po_deals(company: str = Query("")):
    """All deals for a given company."""
    company = company.strip()
    if not company:
        return {"deals": []}
    deals = list_deals_for_company(company, active_only=False)
    return {"deals": [
        {
            "id": d["id"],
            "label": f"{(d.get('po_number') or '—')}  ·  {d.get('product') or '—'}  ·  {d.get('quantity','') or ''} {d.get('quantity_unit','') or ''}  [{d.get('status','—')}]",
            "product": d.get("product") or "",
            "po_number": d.get("po_number") or "",
            "quantity": f"{d.get('quantity','')} {d.get('quantity_unit','')}".strip(),
            "date": (d.get("deal_date") or d.get("po_date") or "")[:10],
            "status": d.get("status") or "",
        }
        for d in deals
    ]}


@app.get("/generate/purchase-orders/new", response_class=HTMLResponse)
async def po_new_page(
    request: Request,
    deal_id: int = Query(0),
    pick: int = Query(0),
    q: str = Query(""),
):
    if pick or (not deal_id and request.query_params.get("blank") != "1"):
        return templates.TemplateResponse(
            "generate/purchase_orders/po_pick_deal.html",
            {"request": request},
        )
    if deal_id:
        po = create_purchase_order_from_deal(deal_id)
        if not po:
            return RedirectResponse("/generate/purchase-orders/new", status_code=303)
    else:
        po = dict(DEFAULT_PO)
        calc = calculate_po_totals(po["line_items"])
        po["line_items"] = calc["line_items"]
        po["total_value"] = calc["total_value"]
    return templates.TemplateResponse(
        "generate/purchase_orders/po_editor.html",
        ctx(request, page="generate", po=po, editing=False, errors=[], warnings=[]),
    )


@app.post("/generate/purchase-orders/new")
async def po_new_save(request: Request):
    form = await request.form()
    data, line_items = parse_po_form(form)
    errors = validate_purchase_order(data, line_items)
    warnings = validation_warnings(data, line_items)
    if errors:
        po = {**data, "line_items": line_items, "total_value": calculate_po_totals(line_items)["total_value"]}
        return templates.TemplateResponse(
            "generate/purchase_orders/po_editor.html",
            ctx(request, page="generate", po=po, editing=False, errors=errors, warnings=warnings),
            status_code=400,
        )
    deal_id = int(form.get("deal_id") or 0) or None
    customer_id = int(form.get("customer_id") or 0) or None
    po_id = create_purchase_order(
        data, line_items,
        source_type="deal" if deal_id else None,
        source_id=deal_id,
        deal_id=deal_id,
        customer_id=customer_id,
    )
    q = "saved=1"
    if warnings:
        q += "&warn=" + quote(warnings[0][:120])
    return RedirectResponse(f"/generate/purchase-orders/{po_id}?{q}", status_code=303)


@app.get("/generate/purchase-orders/{po_id}", response_class=HTMLResponse)
async def po_detail_page(request: Request, po_id: int, saved: str = Query(""), warn: str = Query("")):
    po = get_purchase_order(po_id)
    if not po:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    return templates.TemplateResponse(
        "generate/purchase_orders/po_detail.html",
        ctx(
            request, page="generate", po=po,
            warnings=validation_warnings(po, po.get("line_items") or []),
            saved_msg="Saved." if saved else "",
            warn_msg=warn,
        ),
    )


@app.get("/generate/purchase-orders/{po_id}/edit", response_class=HTMLResponse)
async def po_edit_page(request: Request, po_id: int):
    po = get_purchase_order(po_id)
    if not po:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    return templates.TemplateResponse(
        "generate/purchase_orders/po_editor.html",
        ctx(
            request, page="generate", po=po, editing=True,
            errors=[], warnings=validation_warnings(po, po.get("line_items") or []),
        ),
    )


@app.post("/generate/purchase-orders/{po_id}/edit")
async def po_edit_save(request: Request, po_id: int):
    form = await request.form()
    data, line_items = parse_po_form(form)
    errors = validate_purchase_order(data, line_items)
    warnings = validation_warnings(data, line_items)
    if errors:
        po = {**data, "id": po_id, "line_items": line_items}
        po["total_value"] = calculate_po_totals(line_items)["total_value"]
        return templates.TemplateResponse(
            "generate/purchase_orders/po_editor.html",
            ctx(request, page="generate", po=po, editing=True, errors=errors, warnings=warnings),
            status_code=400,
        )
    update_purchase_order(po_id, data, line_items)
    q = "saved=1"
    if warnings:
        q += "&warn=" + quote(warnings[0][:120])
    return RedirectResponse(f"/generate/purchase-orders/{po_id}?{q}", status_code=303)


@app.post("/generate/purchase-orders/{po_id}/delete")
async def po_delete_route(po_id: int):
    delete_purchase_order(po_id)
    return RedirectResponse("/generate/purchase-orders", status_code=303)


@app.post("/generate/purchase-orders/{po_id}/duplicate")
async def po_duplicate_route(po_id: int):
    new_id = duplicate_purchase_order(po_id)
    if not new_id:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    return RedirectResponse(f"/generate/purchase-orders/{new_id}/edit", status_code=303)


@app.get("/generate/purchase-orders/{po_id}/print", response_class=HTMLResponse)
async def po_print_page(request: Request, po_id: int):
    po = get_purchase_order_for_export(po_id)
    if not po:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    return templates.TemplateResponse(
        "generate/purchase_orders/po_print.html",
        ctx(request, page="generate", po=po, hide_nav=True),
    )


@app.get("/generate/purchase-orders/{po_id}/export.xlsx")
async def po_export_xlsx_route(po_id: int):
    po = get_purchase_order_for_export(po_id)
    if not po:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    content, fname = export_po_xlsx(po)
    return _download_response(
        content, fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/generate/purchase-orders/{po_id}/export.pdf")
async def po_export_pdf_route(request: Request, po_id: int):
    po = get_purchase_order_for_export(po_id)
    if not po:
        return RedirectResponse("/generate/purchase-orders", status_code=303)
    html = templates.get_template("generate/purchase_orders/po_pdf.html").render(
        request=request, po=po, generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )
    result = export_po_pdf(po, html)
    if not result:
        return RedirectResponse(
            f"/generate/purchase-orders/{po_id}/print?pdf_fallback=1", status_code=303
        )
    content, fname = result
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ════════════════════════════════════════════════════════════════════════════
# ── Commission Invoice routes ────────────────────────────────────────────────
# Remove this entire block (and the imports above) to drop the CI feature.
# ════════════════════════════════════════════════════════════════════════════

@app.get("/generate/commission-invoices", response_class=HTMLResponse)
async def ci_list_page(request: Request):
    rows = list_commission_invoices()
    return templates.TemplateResponse(
        "generate/commission_invoices/ci_list.html",
        {"request": request, "rows": rows},
    )


@app.get("/generate/commission-invoices/new", response_class=HTMLResponse)
async def ci_new_page(
    request: Request,
    deal_id: int = Query(0),
    deal_ids: str = Query(""),   # comma-separated list, e.g. "3,7,12"
    blank: str = Query(""),
):
    if not deal_id and not deal_ids and blank != "1":
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_pick_deal.html",
            {"request": request},
        )
    from copy import deepcopy
    ids: list[int] = []
    if deal_ids:
        ids = [int(x) for x in deal_ids.split(",") if x.strip().isdigit()]
    elif deal_id:
        ids = [deal_id]
    if ids:
        ci = create_ci_from_deals(ids) or deepcopy(DEFAULT_CI)
    else:
        ci = deepcopy(DEFAULT_CI)
    return templates.TemplateResponse(
        "generate/commission_invoices/ci_editor.html",
        {"request": request, "ci": ci, "editing": False, "errors": []},
    )


@app.post("/generate/commission-invoices/new", response_class=HTMLResponse)
async def ci_new_post(request: Request):
    form = await request.form()
    data, line_items = parse_ci_form(form)
    if not data.get("invoice_number"):
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_editor.html",
            {"request": request, "ci": {**data, "line_items": line_items},
             "editing": False, "errors": ["Invoice number is required."]},
            status_code=422,
        )
    deal_id    = int(form.get("deal_id") or 0) or None
    customer_id = int(form.get("customer_id") or 0) or None
    ci_id = create_commission_invoice(data, line_items, deal_id=deal_id, customer_id=customer_id)
    return RedirectResponse(f"/generate/commission-invoices/{ci_id}?saved=1", status_code=303)


@app.get("/generate/commission-invoices/{ci_id}", response_class=HTMLResponse)
async def ci_detail_page(request: Request, ci_id: int):
    ci = get_commission_invoice(ci_id)
    if not ci:
        return RedirectResponse("/generate/commission-invoices", status_code=303)
    saved_msg = "Saved successfully." if request.query_params.get("saved") else None
    return templates.TemplateResponse(
        "generate/commission_invoices/ci_detail.html",
        {"request": request, "ci": ci, "saved_msg": saved_msg},
    )


@app.get("/generate/commission-invoices/{ci_id}/edit", response_class=HTMLResponse)
async def ci_edit_page(request: Request, ci_id: int):
    ci = get_commission_invoice(ci_id)
    if not ci:
        return RedirectResponse("/generate/commission-invoices", status_code=303)
    return templates.TemplateResponse(
        "generate/commission_invoices/ci_editor.html",
        {"request": request, "ci": ci, "editing": True, "errors": []},
    )


@app.post("/generate/commission-invoices/{ci_id}/edit", response_class=HTMLResponse)
async def ci_edit_post(request: Request, ci_id: int):
    form = await request.form()
    data, line_items = parse_ci_form(form)
    if not data.get("invoice_number"):
        ci = get_commission_invoice(ci_id) or {}
        ci.update(data)
        ci["line_items"] = line_items
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_editor.html",
            {"request": request, "ci": ci, "editing": True,
             "errors": ["Invoice number is required."]},
            status_code=422,
        )
    from app.commission_invoices import update_commission_invoice
    update_commission_invoice(ci_id, data, line_items)
    return RedirectResponse(f"/generate/commission-invoices/{ci_id}?saved=1", status_code=303)


@app.post("/generate/commission-invoices/{ci_id}/duplicate")
async def ci_duplicate(ci_id: int):
    new_id = duplicate_commission_invoice(ci_id)
    if new_id:
        return RedirectResponse(f"/generate/commission-invoices/{new_id}/edit", status_code=303)
    return RedirectResponse("/generate/commission-invoices", status_code=303)


@app.post("/generate/commission-invoices/{ci_id}/delete")
async def ci_delete(ci_id: int):
    delete_commission_invoice(ci_id)
    return RedirectResponse("/generate/commission-invoices", status_code=303)


@app.get("/generate/commission-invoices/{ci_id}/print", response_class=HTMLResponse)
async def ci_print_page(request: Request, ci_id: int):
    ci = get_commission_invoice(ci_id)
    if not ci:
        return RedirectResponse("/generate/commission-invoices", status_code=303)
    return templates.TemplateResponse(
        "generate/commission_invoices/ci_print.html",
        {"request": request, "ci": ci},
    )


@app.get("/generate/commission-invoices/{ci_id}/export.xlsx")
async def ci_export_xlsx_route(ci_id: int):
    ci = get_commission_invoice_for_export(ci_id)
    if not ci:
        return RedirectResponse("/generate/commission-invoices", status_code=303)
    content, fname = export_ci_xlsx(ci)
    return _download_response(
        content, fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Sales (Commercial) Invoice routes ─────────────────────────────────────────
# Remove this entire block (and the SI imports above) to drop the feature.
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/generate/sales-invoices", response_class=HTMLResponse)
async def si_list_page(request: Request):
    rows = list_sales_invoices()
    return templates.TemplateResponse(
        "generate/sales_invoices/si_list.html",
        {"request": request, "rows": rows},
    )


@app.get("/generate/sales-invoices/new", response_class=HTMLResponse)
async def si_new_page(
    request: Request,
    deal_id: int = Query(0),
    deal_ids: str = Query(""),
    blank: str = Query(""),
):
    if not deal_id and not deal_ids and blank != "1":
        return templates.TemplateResponse(
            "generate/sales_invoices/si_pick_deal.html",
            {"request": request},
        )
    from copy import deepcopy
    ids: list[int] = []
    if deal_ids:
        ids = [int(x) for x in deal_ids.split(",") if x.strip().isdigit()]
    elif deal_id:
        ids = [deal_id]
    if ids:
        si = create_si_from_deals(ids) or deepcopy(DEFAULT_SI)
    else:
        si = deepcopy(DEFAULT_SI)
    return templates.TemplateResponse(
        "generate/sales_invoices/si_editor.html",
        {"request": request, "si": si, "editing": False, "errors": []},
    )


@app.post("/generate/sales-invoices/new", response_class=HTMLResponse)
async def si_new_post(request: Request):
    form = await request.form()
    data, line_items = parse_si_form(form)
    if not data.get("invoice_number"):
        return templates.TemplateResponse(
            "generate/sales_invoices/si_editor.html",
            {"request": request, "si": {**data, "line_items": line_items},
             "editing": False, "errors": ["Invoice number is required."]},
            status_code=422,
        )
    deal_id     = int(form.get("deal_id") or 0) or None
    customer_id = int(form.get("customer_id") or 0) or None
    si_id = create_sales_invoice(data, line_items, deal_id=deal_id, customer_id=customer_id)
    return RedirectResponse(f"/generate/sales-invoices/{si_id}?saved=1", status_code=303)


@app.get("/generate/sales-invoices/{si_id}", response_class=HTMLResponse)
async def si_detail_page(request: Request, si_id: int):
    si = get_sales_invoice(si_id)
    if not si:
        return RedirectResponse("/generate/sales-invoices", status_code=303)
    saved_msg = "Saved successfully." if request.query_params.get("saved") else None
    return templates.TemplateResponse(
        "generate/sales_invoices/si_detail.html",
        {"request": request, "si": si, "saved_msg": saved_msg},
    )


@app.get("/generate/sales-invoices/{si_id}/edit", response_class=HTMLResponse)
async def si_edit_page(request: Request, si_id: int):
    si = get_sales_invoice(si_id)
    if not si:
        return RedirectResponse("/generate/sales-invoices", status_code=303)
    return templates.TemplateResponse(
        "generate/sales_invoices/si_editor.html",
        {"request": request, "si": si, "editing": True, "errors": []},
    )


@app.post("/generate/sales-invoices/{si_id}/edit", response_class=HTMLResponse)
async def si_edit_post(request: Request, si_id: int):
    form = await request.form()
    data, line_items = parse_si_form(form)
    if not data.get("invoice_number"):
        si = get_sales_invoice(si_id) or {}
        si.update(data)
        si["line_items"] = line_items
        return templates.TemplateResponse(
            "generate/sales_invoices/si_editor.html",
            {"request": request, "si": si, "editing": True,
             "errors": ["Invoice number is required."]},
            status_code=422,
        )
    from app.sales_invoices import update_sales_invoice
    update_sales_invoice(si_id, data, line_items)
    return RedirectResponse(f"/generate/sales-invoices/{si_id}?saved=1", status_code=303)


@app.post("/generate/sales-invoices/{si_id}/duplicate")
async def si_duplicate(si_id: int):
    new_id = duplicate_sales_invoice(si_id)
    if new_id:
        return RedirectResponse(f"/generate/sales-invoices/{new_id}/edit", status_code=303)
    return RedirectResponse("/generate/sales-invoices", status_code=303)


@app.post("/generate/sales-invoices/{si_id}/delete")
async def si_delete(si_id: int):
    delete_sales_invoice(si_id)
    return RedirectResponse("/generate/sales-invoices", status_code=303)


@app.get("/generate/sales-invoices/{si_id}/print", response_class=HTMLResponse)
async def si_print_page(request: Request, si_id: int):
    si = get_sales_invoice(si_id)
    if not si:
        return RedirectResponse("/generate/sales-invoices", status_code=303)
    return templates.TemplateResponse(
        "generate/sales_invoices/si_print.html",
        {"request": request, "si": si},
    )


@app.get("/generate/sales-invoices/{si_id}/export.xlsx")
async def si_export_xlsx_route(si_id: int):
    si = get_sales_invoice_for_export(si_id)
    if not si:
        return RedirectResponse("/generate/sales-invoices", status_code=303)
    content, fname = export_si_xlsx(si)
    return _download_response(
        content, fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Delivery Note routes ──────────────────────────────────────────────────────
# Remove this entire block (and the DN imports above) to drop the feature.
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/generate/delivery-notes", response_class=HTMLResponse)
async def dn_list_page(request: Request):
    rows = list_delivery_notes()
    return templates.TemplateResponse(
        "generate/delivery_notes/dn_list.html",
        {"request": request, "rows": rows},
    )


@app.get("/generate/delivery-notes/new", response_class=HTMLResponse)
async def dn_new_page(
    request: Request,
    deal_id: int = Query(0),
    blank: str = Query(""),
):
    if not deal_id and blank != "1":
        return templates.TemplateResponse(
            "generate/delivery_notes/dn_pick_deal.html",
            {"request": request},
        )
    from copy import deepcopy
    if deal_id:
        dn = create_dn_from_deal(deal_id) or deepcopy(DEFAULT_DN)
    else:
        dn = deepcopy(DEFAULT_DN)
    return templates.TemplateResponse(
        "generate/delivery_notes/dn_editor.html",
        {"request": request, "dn": dn, "editing": False, "errors": []},
    )


@app.post("/generate/delivery-notes/new", response_class=HTMLResponse)
async def dn_new_post(request: Request):
    form = await request.form()
    dn   = parse_dn_form(form)
    if not dn.get("reference_number"):
        return templates.TemplateResponse(
            "generate/delivery_notes/dn_editor.html",
            {"request": request, "dn": dn, "editing": False,
             "errors": ["Reference number is required."]},
            status_code=422,
        )
    deal_id     = int(form.get("deal_id") or 0) or None
    customer_id = int(form.get("customer_id") or 0) or None
    dn_id = create_delivery_note(dn, deal_id=deal_id, customer_id=customer_id)
    return RedirectResponse(f"/generate/delivery-notes/{dn_id}?saved=1", status_code=303)


@app.get("/generate/delivery-notes/{dn_id}", response_class=HTMLResponse)
async def dn_detail_page(request: Request, dn_id: int):
    dn = get_delivery_note(dn_id)
    if not dn:
        return RedirectResponse("/generate/delivery-notes", status_code=303)
    saved_msg = "Saved successfully." if request.query_params.get("saved") else None
    return templates.TemplateResponse(
        "generate/delivery_notes/dn_detail.html",
        {"request": request, "dn": dn, "saved_msg": saved_msg},
    )


@app.get("/generate/delivery-notes/{dn_id}/edit", response_class=HTMLResponse)
async def dn_edit_page(request: Request, dn_id: int):
    dn = get_delivery_note(dn_id)
    if not dn:
        return RedirectResponse("/generate/delivery-notes", status_code=303)
    return templates.TemplateResponse(
        "generate/delivery_notes/dn_editor.html",
        {"request": request, "dn": dn, "editing": True, "errors": []},
    )


@app.post("/generate/delivery-notes/{dn_id}/edit", response_class=HTMLResponse)
async def dn_edit_post(request: Request, dn_id: int):
    form = await request.form()
    dn   = parse_dn_form(form)
    if not dn.get("reference_number"):
        existing = get_delivery_note(dn_id) or {}
        existing.update(dn)
        return templates.TemplateResponse(
            "generate/delivery_notes/dn_editor.html",
            {"request": request, "dn": existing, "editing": True,
             "errors": ["Reference number is required."]},
            status_code=422,
        )
    from app.delivery_notes import update_delivery_note
    update_delivery_note(dn_id, dn)
    return RedirectResponse(f"/generate/delivery-notes/{dn_id}?saved=1", status_code=303)


@app.post("/generate/delivery-notes/{dn_id}/duplicate")
async def dn_duplicate(dn_id: int):
    new_id = duplicate_delivery_note(dn_id)
    if new_id:
        return RedirectResponse(f"/generate/delivery-notes/{new_id}/edit", status_code=303)
    return RedirectResponse("/generate/delivery-notes", status_code=303)


@app.post("/generate/delivery-notes/{dn_id}/delete")
async def dn_delete(dn_id: int):
    delete_delivery_note(dn_id)
    return RedirectResponse("/generate/delivery-notes", status_code=303)


@app.get("/generate/delivery-notes/{dn_id}/print", response_class=HTMLResponse)
async def dn_print_page(request: Request, dn_id: int):
    dn = get_delivery_note(dn_id)
    if not dn:
        return RedirectResponse("/generate/delivery-notes", status_code=303)
    return templates.TemplateResponse(
        "generate/delivery_notes/dn_print.html",
        {"request": request, "dn": dn},
    )


@app.get("/generate/delivery-notes/{dn_id}/export.xlsx")
async def dn_export_xlsx_route(dn_id: int):
    dn = get_delivery_note(dn_id)
    if not dn:
        return RedirectResponse("/generate/delivery-notes", status_code=303)
    content, fname = export_dn_xlsx(dn)
    return _download_response(
        content, fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

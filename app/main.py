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
from app.seed import load_seed

BASE = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["qty_display"] = format_quantity_display
templates.env.filters["iso_date"] = iso_date_input


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
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.on_event("startup")
def startup() -> None:
    init_db()
    load_seed()
    migrate_to_leads_deals()
    import_catalogue()
    fix_legacy_product_names()


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
):
    create_deal(
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

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from typing import List

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import (
    create_deal,
    create_lead,
    customer_detail,
    delete_activity,
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
    migrate_to_leads_deals,
    recent_activities,
    search_leads_contacts,
    summary_by_customer,
    summary_by_product,
    update_lead,
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
    return {"request": request, "price_units": PRICE_UNITS, **extra}


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
    return JSONResponse(list_deals_for_company(company))


@app.get("/add", response_class=HTMLResponse)
async def add_page(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    deal_id: str = Query(""),
    tab: str = Query("log"),
    return_to: str = Query(""),
):
    company_deals = list_deals_for_company(company) if company else []
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
async def deal_page(request: Request, deal_id: int):
    detail = get_deal_detail(deal_id)
    if not detail:
        return RedirectResponse("/deals", status_code=303)
    pid = detail["deal"].get("product_id")
    product_record = get_product(pid) if pid else None
    company = detail["deal"]["company"]
    today = datetime.utcnow().date().isoformat()
    return templates.TemplateResponse(
        "deal.html",
        ctx(
            request,
            page="deals",
            detail=detail,
            product_record=product_record,
            all_products=list_products(),
            company_deals=list_deals_for_company(company, active_only=False),
            today=today,
        ),
    )


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
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    deal_quantity: str = Form(""),
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
                "price": price or deal_price,
                "price_unit": price_unit if price or quantity else deal_price_unit,
                "deal_notes": deal_notes,
                "deal_po_number": deal_po_number,
                "quote_ref": quote_ref,
                "deal_quantity": deal_quantity,
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
        return RedirectResponse(f"{base}{sep}error={quote(str(e))}", status_code=303)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if company:
        return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)
    return RedirectResponse("/leads", status_code=303)


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
    request: Request, name: str = Query(...), product: str = Query("")
):
    detail = customer_detail(name, product)
    if not detail:
        return RedirectResponse("/leads", status_code=303)
    return templates.TemplateResponse(
        "customer.html",
        ctx(
            request,
            page="leads",
            detail=detail,
            product_filter=product,
            company_deals=list_deals_for_company(name, active_only=False),
            all_products=list_products(),
        ),
    )


@app.post("/customer/{customer_id}/delete")
async def delete_customer_route(customer_id: int):
    name = delete_customer(customer_id)
    if not name:
        return RedirectResponse("/leads?error=company_not_found", status_code=303)
    return RedirectResponse("/leads", status_code=303)


@app.post("/customer/{lead_id}/edit")
async def edit_lead(
    lead_id: int,
    contact: str = Form(""),
    email: str = Form(""),
    website: str = Form(""),
    phone: str = Form(""),
    products_interested: str = Form(""),
    notes: str = Form(""),
    company: str = Form(""),
):
    update_lead(
        lead_id,
        {
            "contact": contact,
            "email": email,
            "website": website,
            "phone": phone,
            "products_interested": products_interested,
            "notes": notes,
        },
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


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

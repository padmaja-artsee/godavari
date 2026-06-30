"""Commission Invoice HTTP routes — registered once per variant (GBInc, GBBV)."""
from __future__ import annotations

import calendar
from typing import Any, Callable, Optional, Union

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ci_consolidated import read_consolidated_commission_workbook
from app.ci_data_template import generate_data_request_template, generate_prefilled_data_request
from app.ci_exports import export_ci_pdf, export_ci_xlsx
from app.commission_invoices import (
    VARIANT_GBBV,
    VARIANT_GBINC,
    create_ci_from_deals,
    create_commission_invoice,
    delete_commission_invoice,
    duplicate_commission_invoice,
    get_commission_invoice,
    get_commission_invoice_for_export,
    get_default_ci,
    get_ci_variant_meta,
    list_commission_invoices,
    parse_ci_form,
    update_commission_invoice,
    update_commission_invoice_dates,
)
from app.database import list_commission_companies, list_commission_products, list_deals_for_commission
from app.ci_data_fill import period_label_from_filters

_CI_FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]


def _ci_commission_defaults() -> tuple[int, int]:
    import datetime

    today = datetime.date.today()
    fy = today.year + 1 if today.month >= 4 else today.year
    month = today.month if today.month in _CI_FY_MONTHS else _CI_FY_MONTHS[0]
    return fy, month


def _ci_fiscal_years() -> list[int]:
    import datetime

    y = datetime.date.today().year
    return [y + 1, y, y - 1]


def _qi(val: Optional[Union[str, int]], default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _ci_export_deals(
    *,
    mode: str,
    fy: int,
    month: int,
    date_from: str,
    date_to: str,
    product: str,
    company: str,
    status: str,
) -> list[dict]:
    monthly = mode != "range"
    return list_deals_for_commission(
        fiscal_year=fy if monthly and month else 0,
        month=month if monthly else 0,
        date_from=date_from.strip() if not monthly else "",
        date_to=date_to.strip() if not monthly else "",
        product=product.strip(),
        company=company.strip(),
        status=status or "open",
    )


def _ci_ctx(
    ctx: Callable[..., dict],
    request: Request,
    variant: str,
    **extra: Any,
) -> dict[str, Any]:
    meta = get_ci_variant_meta(variant)
    return ctx(
        request,
        ci_variant=variant,
        ci_base=meta["url_prefix"],
        ci_title=meta["short_label"],
        ci_list_label=meta["list_label"],
        **extra,
    )


def register_commission_invoice_routes(
    app,
    *,
    templates,
    ctx: Callable[..., dict],
    download_response: Callable,
    authorized_signature_file_uri: Callable[[], str],
    variant: str,
) -> None:
    """Register full CRUD + export routes for one CI variant."""
    meta = get_ci_variant_meta(variant)
    base = meta["url_prefix"]

    @app.get(base, response_class=HTMLResponse)
    async def ci_list_page(
        request: Request,
        fy: str = Query(""),
        month: str = Query(""),
        date_from: str = Query(""),
        date_to: str = Query(""),
        product: str = Query(""),
        company: str = Query(""),
        status: str = Query("open"),
        mode: str = Query("monthly"),
    ):
        rows = list_commission_invoices(variant=variant)
        def_fy, def_month = _ci_commission_defaults()
        fy_i = _qi(fy, def_fy)
        month_i = _qi(month, def_month)
        monthly = mode != "range"
        preview_deals = _ci_export_deals(
            mode=mode,
            fy=fy_i,
            month=month_i,
            date_from=date_from,
            date_to=date_to,
            product=product,
            company=company,
            status=status,
        )
        month_labels = {m: calendar.month_name[m] for m in _CI_FY_MONTHS}
        period_label = period_label_from_filters(
            month=month_i if monthly and month_i else 0,
            fiscal_year=fy_i if monthly else 0,
            date_from="" if monthly else date_from,
            date_to="" if monthly else date_to,
        )
        if monthly and not month_i:
            period_label = f"All months FY{fy_i % 100:02d}" if fy_i else "All dates"
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_list.html",
            _ci_ctx(
                ctx,
                request,
                variant,
                rows=rows,
                fy=fy_i,
                month=month_i,
                date_from=date_from,
                date_to=date_to,
                product=product,
                company=company,
                status=status,
                mode=mode,
                fiscal_years=_ci_fiscal_years(),
                months=_CI_FY_MONTHS,
                month_labels=month_labels,
                products=list_commission_products(),
                companies=list_commission_companies(),
                preview_deals=preview_deals,
                period_label=period_label,
                filters_applied=bool(request.query_params),
            ),
        )

    if variant == VARIANT_GBINC:

        @app.get(f"{base}/prefilled-template.xlsx")
        async def ci_prefilled_template_route(
            fy: str = Query(""),
            month: str = Query(""),
            date_from: str = Query(""),
            date_to: str = Query(""),
            product: str = Query(""),
            company: str = Query(""),
            status: str = Query("open"),
            mode: str = Query("monthly"),
            deal_ids: list[int] = Query([]),
        ):
            def_fy, def_month = _ci_commission_defaults()
            fy_i = _qi(fy, def_fy)
            month_i = _qi(month, def_month)
            monthly = mode != "range"
            all_deals = _ci_export_deals(
                mode=mode,
                fy=fy_i,
                month=month_i,
                date_from=date_from,
                date_to=date_to,
                product=product,
                company=company,
                status=status,
            )
            if deal_ids:
                allowed = {d["id"] for d in all_deals}
                pick = {i for i in deal_ids if i in allowed}
                deals = [d for d in all_deals if d["id"] in pick]
            else:
                deals = all_deals
            if not deals:
                raise HTTPException(status_code=400, detail="No deals selected for export.")
            period_label = period_label_from_filters(
                month=month_i if monthly and month_i else 0,
                fiscal_year=fy_i if monthly else 0,
                date_from="" if monthly else date_from,
                date_to="" if monthly else date_to,
            )
            if monthly and not month_i:
                period_label = f"All months FY{fy_i % 100:02d}" if fy_i else "All dates"
            content, fname = generate_prefilled_data_request(
                deals,
                company=company.strip(),
                period_label=period_label,
                product=product.strip().upper() if product else "",
                month_hint=month_i if monthly else 0,
            )
            return download_response(
                content,
                fname,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        @app.get(f"{base}/data-request-template.xlsx")
        async def ci_data_request_template_route():
            content, fname = generate_data_request_template()
            return download_response(
                content,
                fname,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        @app.get(f"{base}/consolidated.xlsx")
        async def ci_consolidated_export_route():
            content, fname = read_consolidated_commission_workbook()
            return download_response(
                content,
                fname,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    @app.get(f"{base}/new", response_class=HTMLResponse)
    async def ci_new_page(
        request: Request,
        deal_id: int = Query(0),
        deal_ids: str = Query(""),
        blank: str = Query(""),
    ):
        if not deal_id and not deal_ids and blank != "1":
            return templates.TemplateResponse(
                "generate/commission_invoices/ci_pick_deal.html",
                _ci_ctx(ctx, request, variant),
            )
        ids: list[int] = []
        if deal_ids:
            ids = [int(x) for x in deal_ids.split(",") if x.strip().isdigit()]
        elif deal_id:
            ids = [deal_id]
        if ids:
            ci = create_ci_from_deals(ids, variant=variant) or get_default_ci(variant)
        else:
            ci = get_default_ci(variant)
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_editor.html",
            _ci_ctx(ctx, request, variant, ci=ci, editing=False, errors=[]),
        )

    @app.post(f"{base}/new", response_class=HTMLResponse)
    async def ci_new_post(request: Request):
        form = await request.form()
        data, line_items = parse_ci_form(form)
        data["variant"] = variant
        if not data.get("invoice_number"):
            return templates.TemplateResponse(
                "generate/commission_invoices/ci_editor.html",
                _ci_ctx(
                    ctx,
                    request,
                    variant,
                    ci={**data, "line_items": line_items},
                    editing=False,
                    errors=["Invoice number is required."],
                ),
                status_code=422,
            )
        deal_id = int(form.get("deal_id") or 0) or None
        customer_id = int(form.get("customer_id") or 0) or None
        ci_id = create_commission_invoice(
            data,
            line_items,
            deal_id=deal_id,
            customer_id=customer_id,
            variant=variant,
        )
        return RedirectResponse(f"{base}/{ci_id}?saved=1", status_code=303)

    @app.get(f"{base}/{{ci_id}}", response_class=HTMLResponse)
    async def ci_detail_page(request: Request, ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        saved_msg = None
        if request.query_params.get("opened_print"):
            saved_msg = (
                "Opened print view in Safari — choose File → Print → Save as PDF to download."
            )
        elif request.query_params.get("saved"):
            saved_msg = "Saved successfully."
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_detail.html",
            _ci_ctx(ctx, request, variant, ci=ci, saved_msg=saved_msg),
        )

    @app.get(f"{base}/{{ci_id}}/edit", response_class=HTMLResponse)
    async def ci_edit_page(request: Request, ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_editor.html",
            _ci_ctx(ctx, request, variant, ci=ci, editing=True, errors=[]),
        )

    @app.post(f"{base}/{{ci_id}}/edit", response_class=HTMLResponse)
    async def ci_edit_post(request: Request, ci_id: int):
        form = await request.form()
        data, line_items = parse_ci_form(form)
        data["variant"] = variant
        if not data.get("invoice_number"):
            ci = get_commission_invoice(ci_id) or {}
            ci.update(data)
            ci["line_items"] = line_items
            return templates.TemplateResponse(
                "generate/commission_invoices/ci_editor.html",
                _ci_ctx(ctx, request, variant, ci=ci, editing=True, errors=["Invoice number is required."]),
                status_code=422,
            )
        update_commission_invoice(ci_id, data, line_items)
        return RedirectResponse(f"{base}/{ci_id}?saved=1", status_code=303)

    @app.post(f"{base}/{{ci_id}}/duplicate")
    async def ci_duplicate(ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        new_id = duplicate_commission_invoice(ci_id)
        if new_id:
            return RedirectResponse(f"{base}/{new_id}/edit", status_code=303)
        return RedirectResponse(base, status_code=303)

    @app.post(f"{base}/{{ci_id}}/delete")
    async def ci_delete(ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        delete_commission_invoice(ci_id)
        return RedirectResponse(base, status_code=303)

    @app.get(f"{base}/{{ci_id}}/print", response_class=HTMLResponse)
    async def ci_print_page(request: Request, ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_print.html",
            _ci_ctx(ctx, request, variant, ci=ci),
        )

    @app.post(f"{base}/{{ci_id}}/dates")
    async def ci_update_dates(request: Request, ci_id: int):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        form = await request.form()
        if not update_commission_invoice_dates(
            ci_id,
            invoice_date=str(form.get("invoice_date") or ""),
            notice_date=str(form.get("notice_date") or ""),
            line_shipment_dates=[str(v) for v in form.getlist("shipment_date")],
        ):
            return RedirectResponse(base, status_code=303)
        return RedirectResponse(f"{base}/{ci_id}/print?dates=saved", status_code=303)

    @app.get(f"{base}/{{ci_id}}/export.xlsx")
    async def ci_export_xlsx_route(ci_id: int):
        ci = get_commission_invoice_for_export(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        content, fname = export_ci_xlsx(ci)
        return download_response(
            content,
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get(f"{base}/{{ci_id}}/export.pdf")
    async def ci_export_pdf_route(request: Request, ci_id: int):
        ci = get_commission_invoice_for_export(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        html = templates.get_template("generate/commission_invoices/ci_pdf.html").render(
            ci=ci,
            authorized_signature_src=authorized_signature_file_uri(),
        )
        result = export_ci_pdf(ci, html)
        if not result:
            from app.pdf_render import is_packaged_app
            from app.main import _open_in_system_browser

            if is_packaged_app():
                _open_in_system_browser(f"{base}/{ci_id}/print")
                return RedirectResponse(
                    f"{base}/{ci_id}?opened_print=1", status_code=303
                )
            return RedirectResponse(
                f"{base}/{ci_id}/print?pdf_fallback=1", status_code=303
            )
        content, fname = result
        return download_response(content, fname, "application/pdf")


def register_all_commission_invoice_routes(app, **deps) -> None:
    for key in (VARIANT_GBINC, VARIANT_GBBV):
        register_commission_invoice_routes(app, variant=key, **deps)

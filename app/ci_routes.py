"""Commission Invoice HTTP routes — registered once per variant (GBInc, GBBV)."""
from __future__ import annotations

import calendar
from typing import Any, Callable, Optional, Union

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ci_consolidated import read_consolidated_commission_workbook
from app.ci_data_template import generate_data_request_template, generate_prefilled_data_request
from app.ci_excel_import import (
    create_drafts_from_batch,
    parse_commission_details_workbook,
    preview_rows,
    save_import_batch,
)
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
    list_commission_invoice_products,
    list_commission_invoices,
    parse_ci_form,
    set_ci_show_on_summary,
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
        deals_run: str = Query(""),
        sort: str = Query("created"),
        dir: str = Query("desc"),
        list_status: str = Query("all"),
        list_product: str = Query(""),
        list_q: str = Query(""),
        list_from: str = Query(""),
        list_to: str = Query(""),
    ):
        sort_key = sort if sort in (
            "invoice_number", "invoice_date", "bill_to", "product",
            "commission", "status", "created",
        ) else "created"
        sort_dir = "asc" if str(dir).lower() == "asc" else "desc"
        list_st = (list_status or "all").strip() or "all"
        rows = list_commission_invoices(
            variant=variant,
            sort=sort_key,
            direction=sort_dir,
            status="" if list_st.lower() == "all" else list_st,
            product=list_product,
            q=list_q,
            date_from=list_from,
            date_to=list_to,
        )
        ci_products = list_commission_invoice_products(variant=variant)
        def_fy, def_month = _ci_commission_defaults()
        fy_i = _qi(fy, def_fy)
        month_i = _qi(month, def_month)
        monthly = mode != "range"
        deals_preview = deals_run == "1"
        preview_deals = (
            _ci_export_deals(
                mode=mode,
                fy=fy_i,
                month=month_i,
                date_from=date_from,
                date_to=date_to,
                product=product,
                company=company,
                status=status,
            )
            if deals_preview
            else []
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

        import_msg = None
        import_error = None
        qp = request.query_params
        if qp.get("imported"):
            n = qp.get("imported")
            ids = [x for x in (qp.get("ids") or "").split(",") if x.strip()]
            import_msg = f"Created {n} draft commission invoice(s)."
            if ids:
                import_msg += " Open: " + ", ".join(ids[:12])
                if len(ids) > 12:
                    import_msg += "…"
        elif qp.get("import_error") == "none":
            import_error = "Select at least one row to create."
        elif qp.get("import_error") == "expired":
            import_error = "Import session expired — upload the Excel again."
        elif qp.get("bulk_deleted"):
            import_msg = f"Deleted {qp.get('bulk_deleted')} commission invoice(s)."

        from urllib.parse import urlencode

        list_filter_qs = urlencode({
            "list_status": list_st,
            "list_product": list_product or "",
            "list_q": list_q or "",
            "list_from": list_from or "",
            "list_to": list_to or "",
        })

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
                sort=sort_key,
                sort_dir=sort_dir,
                list_status=list_st,
                list_product=list_product,
                list_q=list_q,
                list_from=list_from,
                list_to=list_to,
                list_filter_qs=list_filter_qs,
                ci_products=ci_products,
                fiscal_years=_ci_fiscal_years(),
                months=_CI_FY_MONTHS,
                month_labels=month_labels,
                products=list_commission_products(),
                companies=list_commission_companies(),
                preview_deals=preview_deals,
                period_label=period_label,
                filters_applied=deals_preview,
                import_msg=import_msg,
                import_error=import_error,
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

        @app.post(f"{base}/import-excel", response_class=HTMLResponse)
        async def ci_import_excel_post(request: Request, file: UploadFile = File(...)):
            raw = await file.read()
            if not raw:
                return templates.TemplateResponse(
                    "generate/commission_invoices/ci_list.html",
                    _ci_ctx(
                        ctx,
                        request,
                        variant,
                        rows=list_commission_invoices(variant=variant),
                        fy=_ci_commission_defaults()[0],
                        month=_ci_commission_defaults()[1],
                        date_from="",
                        date_to="",
                        product="",
                        company="",
                        status="open",
                        mode="monthly",
                        fiscal_years=_ci_fiscal_years(),
                        months=_CI_FY_MONTHS,
                        month_labels={m: calendar.month_name[m] for m in _CI_FY_MONTHS},
                        products=list_commission_products(),
                        companies=list_commission_companies(),
                        preview_deals=[],
                        period_label="",
                        filters_applied=False,
                        import_error="Upload a non-empty .xlsx file.",
                    ),
                    status_code=400,
                )
            try:
                drafts = parse_commission_details_workbook(raw, variant=variant)
            except Exception as exc:
                return templates.TemplateResponse(
                    "generate/commission_invoices/ci_import_preview.html",
                    _ci_ctx(
                        ctx,
                        request,
                        variant,
                        import_error=f"Could not read Excel: {exc}",
                        preview=[],
                        token="",
                        filename=file.filename or "",
                    ),
                    status_code=400,
                )
            if not drafts:
                return templates.TemplateResponse(
                    "generate/commission_invoices/ci_import_preview.html",
                    _ci_ctx(
                        ctx,
                        request,
                        variant,
                        import_error="No commission rows found. Use the monthly product-tabbed sheet (Invoice No, Qty, Rate, …).",
                        preview=[],
                        token="",
                        filename=file.filename or "",
                    ),
                    status_code=400,
                )
            token = save_import_batch(drafts)
            return templates.TemplateResponse(
                "generate/commission_invoices/ci_import_preview.html",
                _ci_ctx(
                    ctx,
                    request,
                    variant,
                    import_error=None,
                    preview=preview_rows(drafts),
                    token=token,
                    filename=file.filename or "upload.xlsx",
                ),
            )

        @app.post(f"{base}/import-excel/create")
        async def ci_import_excel_create(request: Request):
            form = await request.form()
            token = str(form.get("token") or "")
            raw_sel = form.getlist("selected") if hasattr(form, "getlist") else []
            indices: list[int] = []
            for v in raw_sel:
                try:
                    indices.append(int(v))
                except (TypeError, ValueError):
                    continue
            if not indices:
                return RedirectResponse(f"{base}?import_error=none", status_code=303)
            ids = create_drafts_from_batch(token, indices, variant=variant)
            if not ids:
                return RedirectResponse(f"{base}?import_error=expired", status_code=303)
            q = ",".join(str(i) for i in ids)
            return RedirectResponse(f"{base}?imported={len(ids)}&ids={q}", status_code=303)

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

    def _parse_ci_ids(form) -> list[int]:
        raw = form.getlist("ids") if hasattr(form, "getlist") else []
        if not raw and form.get("ids"):
            raw = str(form.get("ids")).split(",")
        out: list[int] = []
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out

    def _cis_for_ids(ids: list[int]) -> list[dict]:
        rows = []
        for cid in ids:
            ci = get_commission_invoice(cid)
            if ci and ci.get("variant", VARIANT_GBINC) == variant:
                rows.append(ci)
        return rows

    @app.post(f"{base}/bulk-delete")
    async def ci_bulk_delete(request: Request):
        form = await request.form()
        ids = _parse_ci_ids(form)
        deleted = 0
        for cid in ids:
            ci = get_commission_invoice(cid)
            if ci and ci.get("variant", VARIANT_GBINC) == variant:
                delete_commission_invoice(cid)
                deleted += 1
        return RedirectResponse(f"{base}?bulk_deleted={deleted}", status_code=303)

    @app.get(f"{base}/bulk-print", response_class=HTMLResponse)
    async def ci_bulk_print(request: Request, ids: str = Query("")):
        id_list = []
        for part in ids.split(","):
            part = part.strip()
            if part.isdigit():
                id_list.append(int(part))
        cis = _cis_for_ids(id_list)
        if not cis:
            return RedirectResponse(base, status_code=303)
        return templates.TemplateResponse(
            "generate/commission_invoices/ci_bulk_print.html",
            _ci_ctx(
                ctx,
                request,
                variant,
                cis=cis,
                authorized_signature_src=authorized_signature_file_uri(),
            ),
        )

    @app.get(f"{base}/bulk-export.xlsx")
    async def ci_bulk_export_xlsx(ids: str = Query("")):
        import io
        import zipfile

        id_list = [int(p) for p in ids.split(",") if p.strip().isdigit()]
        cis = []
        for cid in id_list:
            ci = get_commission_invoice_for_export(cid)
            if ci and ci.get("variant", VARIANT_GBINC) == variant:
                cis.append(ci)
        if not cis:
            return RedirectResponse(base, status_code=303)
        if len(cis) == 1:
            content, fname = export_ci_xlsx(cis[0])
            return download_response(
                content,
                fname,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            used: set[str] = set()
            for ci in cis:
                content, fname = export_ci_xlsx(ci)
                name = fname
                n = 1
                while name in used:
                    stem = fname.rsplit(".", 1)[0]
                    name = f"{stem}_{n}.xlsx"
                    n += 1
                used.add(name)
                zf.writestr(name, content)
        return download_response(
            buf.getvalue(),
            f"Commission_Invoices_{len(cis)}.zip",
            "application/zip",
        )

    @app.get(f"{base}/bulk-export.pdf")
    async def ci_bulk_export_pdf(request: Request, ids: str = Query("")):
        import io
        import zipfile

        id_list = [int(p) for p in ids.split(",") if p.strip().isdigit()]
        if not id_list:
            return RedirectResponse(base, status_code=303)
        # Prefer combined print when PDF engine unavailable / multi-select
        files: list[tuple[str, bytes]] = []
        for cid in id_list:
            ci = get_commission_invoice_for_export(cid)
            if not ci or ci.get("variant", VARIANT_GBINC) != variant:
                continue
            html = templates.get_template("generate/commission_invoices/ci_pdf.html").render(
                ci=ci,
                authorized_signature_src=authorized_signature_file_uri(),
            )
            result = export_ci_pdf(ci, html)
            if result:
                content, fname = result
                files.append((fname, content))
        if not files:
            return RedirectResponse(
                f"{base}/bulk-print?ids={','.join(str(i) for i in id_list)}",
                status_code=303,
            )
        if len(files) == 1:
            return download_response(files[0][1], files[0][0], "application/pdf")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            used: set[str] = set()
            for fname, content in files:
                name = fname
                n = 1
                while name in used:
                    stem = fname.rsplit(".", 1)[0]
                    name = f"{stem}_{n}.pdf"
                    n += 1
                used.add(name)
                zf.writestr(name, content)
        return download_response(
            buf.getvalue(),
            f"Commission_Invoices_{len(files)}.zip",
            "application/zip",
        )

    @app.post(f"{base}/{{ci_id}}/summary")
    async def ci_toggle_summary(request: Request, ci_id: int, show: str = Query("1")):
        ci = get_commission_invoice(ci_id)
        if not ci or ci.get("variant", VARIANT_GBINC) != variant:
            return RedirectResponse(base, status_code=303)
        set_ci_show_on_summary(ci_id, show in ("1", "true", "yes", "on"))
        referer = (request.headers.get("referer") or "").strip()
        if referer and base in referer:
            return RedirectResponse(referer, status_code=303)
        return RedirectResponse(f"{base}/{ci_id}", status_code=303)

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

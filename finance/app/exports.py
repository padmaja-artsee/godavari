"""Excel export — matches Budget vs Actuals.xlsx structure."""
from __future__ import annotations
from io import BytesIO

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from finance.app.database import FY_MONTHS, MONTH_LABELS, SECTION_LABELS

_GREEN   = "1C5631"
_GREEN_D = "134023"
_GREEN_L = "D9EAD3"
_GREY    = "F2F2F2"
_WHITE   = "FFFFFF"
_BLACK   = "000000"
_RED_L   = "FCE4E4"
_RED     = "C0392B"
_GREEN_C = "E8F5E9"


def _f(bold=False, size=9, color=_BLACK, name="Calibri"):
    return Font(name=name, size=size, bold=bold, color=color)

def _fill(c):
    return PatternFill("solid", fgColor=c)

def _border():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)

def _al(h="right", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _write_section_header(ws, row, label, ncols):
    ws.merge_cells(f"B{row}:{get_column_letter(ncols)}{row}")
    c = ws.cell(row=row, column=2, value=label)
    c.font = _f(bold=True, size=9, color=_WHITE)
    c.fill = _fill(_GREEN_D)
    c.alignment = _al(h="left")
    ws.row_dimensions[row].height = 14


def generate_budget_template(items: list[dict], fiscal_year: int) -> tuple[bytes, str]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Budget FY{str(fiscal_year)[-2:]}"

    ncols = 15  # B=label, C-N=months, O=Total
    month_col = {m: 3 + i for i, m in enumerate(FY_MONTHS)}

    # Title
    ws.merge_cells(f"B1:{get_column_letter(ncols)}1")
    c = ws["B1"]
    c.value = f"Godavari Biorefineries Inc"
    c.font = _f(bold=True, size=12, color=_WHITE)
    c.fill = _fill(_GREEN)
    c.alignment = _al(h="left")
    ws.row_dimensions[1].height = 22

    ws.merge_cells(f"B2:{get_column_letter(ncols)}2")
    c = ws["B2"]
    c.value = f"PLANNED EXPENSES — FY{fiscal_year} (Apr {fiscal_year-1}–Mar {fiscal_year})"
    c.font = _f(bold=True, size=10, color=_WHITE)
    c.fill = _fill(_GREEN)
    c.alignment = _al(h="left")
    ws.row_dimensions[2].height = 18

    # Column headers
    hdr_row = 4
    ws.cell(row=hdr_row, column=2, value="").fill = _fill(_GREEN)
    for m in FY_MONTHS:
        c = ws.cell(row=hdr_row, column=month_col[m],
                    value=MONTH_LABELS[m].upper())
        c.font = _f(bold=True, size=8, color=_WHITE)
        c.fill = _fill(_GREEN)
        c.alignment = _al(h="center")
        c.border = _border()
    c = ws.cell(row=hdr_row, column=ncols, value="TOTAL")
    c.font = _f(bold=True, size=8, color=_WHITE)
    c.fill = _fill(_GREEN_D)
    c.alignment = _al(h="center")
    c.border = _border()
    ws.row_dimensions[hdr_row].height = 16

    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 30
    for col in range(3, ncols + 1):
        ws.column_dimensions[get_column_letter(col)].width = 10

    # Data rows
    data_row = hdr_row + 1
    prev_sec = None
    for item in items:
        sec = item["section"]
        if sec in ("income", "totals"):
            continue  # template is expense-only (matches original)
        is_calc = item["is_calculated"]
        if sec != prev_sec:
            _write_section_header(ws, data_row, SECTION_LABELS.get(sec, sec).upper(), ncols)
            data_row += 1
            # Sub-header
            ws.cell(row=data_row, column=2, value=SECTION_LABELS.get(sec, sec).upper()).font = _f(bold=True, size=8)
            for m in FY_MONTHS:
                c = ws.cell(row=data_row, column=month_col[m], value=MONTH_LABELS[m].upper())
                c.font = _f(bold=True, size=8)
                c.alignment = _al(h="center")
            ws.cell(row=data_row, column=ncols, value="TOTAL").font = _f(bold=True, size=8)
            data_row += 1
            prev_sec = sec

        row_fill = _fill(_GREEN_L) if is_calc else (_fill(_GREY) if data_row % 2 == 0 else _fill(_WHITE))
        row_font = _f(bold=is_calc)

        c = ws.cell(row=data_row, column=2, value=item["name"])
        c.font = row_font; c.fill = row_fill
        c.alignment = _al(h="left"); c.border = _border()

        for m in FY_MONTHS:
            c = ws.cell(row=data_row, column=month_col[m])
            c.fill = row_fill; c.border = _border()
            if is_calc:
                c.value = "(auto)"; c.font = _f(size=8, color="999999")
            else:
                c.number_format = "#,##0.00"; c.font = row_font
            c.alignment = _al(h="right")

        c = ws.cell(row=data_row, column=ncols)
        c.fill = _fill(_GREEN_L) if is_calc else _fill(_GREY)
        c.font = _f(bold=True)
        if not is_calc: c.value = 0; c.number_format = "#,##0.00"
        c.alignment = _al(h="right"); c.border = _border()
        ws.row_dimensions[data_row].height = 14
        data_row += 1

    # Monthly Total row
    data_row += 1
    ws.merge_cells(f"B{data_row}:{get_column_letter(ncols)}{data_row}")
    pass  # left blank for user totals

    ws.freeze_panes = "C5"
    fname = f"GBInc-Budget-Template-FY{fiscal_year}.xlsx"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), fname


def parse_budget_upload(file_bytes: bytes, items: list[dict]) -> dict:
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active
    name_to_item = {i["name"].strip().lower(): i for i in items if not i["is_calculated"]}
    values: dict = {}

    # Find header row
    header_row = None
    for r in ws.iter_rows():
        vals = [str(c.value or "").strip().lower() for c in r]
        if any(v in ("jan", "january", "apr", "april") for v in vals):
            header_row = r
            break
    if not header_row:
        raise ValueError("Could not find month header row.")

    label_to_month = {v.lower()[:3]: k for k, v in MONTH_LABELS.items()}
    label_to_month.update({v.lower(): k for k, v in MONTH_LABELS.items()})
    # also map full month names
    full = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
    label_to_month.update(full)

    col_to_month = {}
    for cell in header_row:
        lbl = str(cell.value or "").strip().lower()
        if lbl in label_to_month:
            col_to_month[cell.column] = label_to_month[lbl]

    if not col_to_month:
        raise ValueError("No month columns found.")

    for row in ws.iter_rows(min_row=header_row[0].row + 1):
        name = str(row[0].value or "").strip().lower()
        if not name:
            name = str(row[1].value or "").strip().lower() if len(row) > 1 else ""
        item = name_to_item.get(name)
        if not item:
            continue
        lid = item["id"]
        for cell in row:
            month = col_to_month.get(cell.column)
            if month is None:
                continue
            try:
                val = float(cell.value) if cell.value not in (None, "", "(auto)") else 0.0
            except (TypeError, ValueError):
                val = 0.0
            if val:
                values[f"{lid}_{month}"] = val
    return values

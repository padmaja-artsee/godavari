"""Excel export for the Finance P&L — matches GBINC-STL-FY27 template style."""
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from finance.app.database import FY_MONTHS, MONTH_LABELS, calendar_year_for

# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

_GREEN    = "1C5631"
_GREEN_LT = "D9EAD3"
_GREY     = "F2F2F2"
_WHITE    = "FFFFFF"
_BLACK    = "000000"

def _font(bold=False, size=9, color=_BLACK, name="Calibri"):
    return Font(name=name, size=size, bold=bold, color=color)

def _fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def _thin():
    s = Side(style="thin", color=_BLACK)
    return Border(left=s, right=s, top=s, bottom=s)

def _align(h="right", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def export_pl_xlsx(
    lines: list[dict],
    b_grid: dict,
    a_grid: dict,
    fiscal_year: int,
) -> tuple[bytes, str]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"FY{str(fiscal_year)[-2:]}"

    # ── Title row ──────────────────────────────────────────────────────────
    ws.merge_cells("A1:AQ1")
    c = ws["A1"]
    c.value = f"Profit and Loss Statement — GBInc  ($, 1000s)  FY{fiscal_year}"
    c.font  = _font(bold=True, size=11, color=_WHITE)
    c.fill  = _fill(_GREEN)
    c.alignment = _align(h="center")
    ws.row_dimensions[1].height = 22

    # ── Header row ─────────────────────────────────────────────────────────
    # Columns: Particulars | Apr Budget | Apr Actual | Apr Var | … × 12 | Total Budget | Total Actual | Total Var
    headers = ["Particulars"]
    for m in FY_MONTHS:
        lbl = MONTH_LABELS[m]
        headers += [f"{lbl} Budget", f"{lbl} Actual", f"{lbl} Var"]
    headers += ["FY Budget", "FY Actual", "FY Var"]

    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=2, column=col, value=h)
        c.font      = _font(bold=True, size=8, color=_WHITE)
        c.fill      = _fill(_GREEN)
        c.alignment = _align(h="center", wrap=True)
        c.border    = _thin()

    ws.row_dimensions[2].height = 28
    ws.column_dimensions["A"].width = 30
    for col in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 10

    # ── Data rows ──────────────────────────────────────────────────────────
    SECTION_HEADERS = {
        "income":       ("INCOME", _GREEN, _WHITE),
        "expense":      ("EXPENSES", _GREEN, _WHITE),
        "below_ebitda": None,
    }
    prev_section = None

    data_row = 3
    for line in lines:
        sec = line["section"]
        is_calc = line["is_calculated"]
        name    = line["name"]

        # Section header row
        if sec in ("income", "expense") and sec != prev_section:
            ws.merge_cells(f"A{data_row}:{get_column_letter(len(headers))}{data_row}")
            hdr_info = SECTION_HEADERS[sec]
            if hdr_info:
                label, bg, fg = hdr_info
                c = ws.cell(row=data_row, column=1, value=label)
                c.font = _font(bold=True, size=9, color=fg)
                c.fill = _fill(bg)
                ws.row_dimensions[data_row].height = 16
                data_row += 1
        prev_section = sec

        # Determine row style
        if sec in ("income_total", "expense_total"):
            row_fill = _fill(_GREEN_LT)
            row_font = _font(bold=True)
        elif sec in ("ebitda", "ebt", "net_ebt"):
            row_fill = _fill(_GREEN)
            row_font = _font(bold=True, color=_WHITE)
        elif data_row % 2 == 0:
            row_fill = _fill(_GREY)
            row_font = _font()
        else:
            row_fill = _fill(_WHITE)
            row_font = _font()

        lid = line["id"]
        row_data = [name]
        b_total = a_total = 0.0
        for m in FY_MONTHS:
            bud = b_grid.get((lid, m), 0.0)
            act = a_grid.get((lid, m), 0.0)
            var = act - bud
            b_total += bud
            a_total += act
            row_data += [bud or "", act or "", var or ""]
        v_total = a_total - b_total
        row_data += [b_total or "", a_total or "", v_total or ""]

        for col, val in enumerate(row_data, start=1):
            c = ws.cell(row=data_row, column=col, value=val)
            c.font      = row_font
            c.fill      = row_fill
            c.border    = _thin()
            if col == 1:
                indent = 2 if not is_calc and sec not in ("ebitda","ebt","net_ebt") else 0
                c.alignment = _align(h="left")
                c.value = ("  " * indent) + str(val)
            else:
                c.alignment = _align(h="right")
                if isinstance(val, float) and val != 0:
                    c.number_format = "#,##0.00"

        ws.row_dimensions[data_row].height = 15
        data_row += 1

    # Freeze header rows
    ws.freeze_panes = "B3"

    fname = f"GBInc-PL-FY{fiscal_year}.xlsx"
    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), fname

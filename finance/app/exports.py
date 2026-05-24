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


# ---------------------------------------------------------------------------
# Budget template (downloadable blank)
# ---------------------------------------------------------------------------

def generate_budget_template(lines: list[dict], fiscal_year: int) -> tuple[bytes, str]:
    """Generate a blank budget upload template pre-filled with P&L line names."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Budget FY{str(fiscal_year)[-2:]}"

    # Title
    last_col = get_column_letter(14)
    ws.merge_cells(f"A1:{last_col}1")
    c = ws["A1"]
    c.value = (
        f"GBInc Budget Template — FY{fiscal_year} (Apr {fiscal_year-1} – Mar {fiscal_year})\n"
        "Enter amounts in USD. Do NOT change row names or column headers. "
        "Calculated rows (Total Income, EBITDA etc.) are locked — leave blank."
    )
    c.font = _font(bold=True, size=9, color=_WHITE)
    c.fill = _fill(_GREEN)
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 36

    # Column headers
    headers = ["Particulars"] + [MONTH_LABELS[m] for m in FY_MONTHS]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=col, value=h)
        c.font = _font(bold=True, size=9, color=_WHITE)
        c.fill = _fill(_GREEN)
        c.alignment = _align(h="center")
        c.border = _thin()

    ws.column_dimensions["A"].width = 34
    for col in range(2, 14):
        ws.column_dimensions[get_column_letter(col)].width = 11

    # Data rows — only editable (non-calculated) lines
    row = 3
    prev_sec = None
    for line in lines:
        sec = line["section"]
        is_calc = line["is_calculated"]

        # Section header rows
        if sec == "income" and prev_sec != "income":
            ws.merge_cells(f"A{row}:{last_col}{row}")
            c = ws.cell(row=row, column=1, value="INCOME")
            c.font = _font(bold=True, size=9, color=_WHITE)
            c.fill = _fill(_GREEN)
            row += 1
        elif sec == "expense" and prev_sec != "expense":
            ws.merge_cells(f"A{row}:{last_col}{row}")
            c = ws.cell(row=row, column=1, value="EXPENSES")
            c.font = _font(bold=True, size=9, color=_WHITE)
            c.fill = _fill(_GREEN)
            row += 1
        elif sec == "below_ebitda" and prev_sec not in ("below_ebitda", "ebitda"):
            ws.merge_cells(f"A{row}:{last_col}{row}")
            c = ws.cell(row=row, column=1, value="BELOW EBITDA")
            c.font = _font(bold=True, size=9, color=_WHITE)
            c.fill = _fill(_GREEN)
            row += 1
        prev_sec = sec

        if is_calc:
            row_fill = _fill(_GREEN_LT) if sec in ("income_total", "expense_total") else _fill(_GREEN)
            row_font = _font(bold=True, color=_BLACK if sec in ("income_total", "expense_total") else _WHITE)
        elif row % 2 == 0:
            row_fill = _fill(_GREY)
            row_font = _font()
        else:
            row_fill = _fill(_WHITE)
            row_font = _font()

        # Row label
        c = ws.cell(row=row, column=1, value=line["name"])
        c.font = row_font
        c.fill = row_fill
        c.alignment = _align(h="left")
        c.border = _thin()

        # Month columns
        for col_idx, m in enumerate(FY_MONTHS, 2):
            c = ws.cell(row=row, column=col_idx)
            c.fill = row_fill
            c.border = _thin()
            c.alignment = _align(h="right")
            if is_calc:
                c.value = "(auto)"
                c.font = _font(size=8, color="888888")
                c.protection = openpyxl.styles.Protection(locked=True)
            else:
                c.number_format = "#,##0.00"
                c.font = row_font

        row += 1

    ws.freeze_panes = "B3"
    ws.sheet_protection.sheet = False  # keep editable

    fname = f"GBInc-Budget-Template-FY{fiscal_year}.xlsx"
    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), fname


# ---------------------------------------------------------------------------
# Budget upload parser
# ---------------------------------------------------------------------------

def parse_budget_upload(file_bytes: bytes, lines: list[dict]) -> dict[str, float]:
    """
    Parse an uploaded budget Excel file.
    Returns {"{pl_line_id}_{month}": amount} ready for save_grid().
    Matches rows by the 'Particulars' column name (case-insensitive, stripped).
    """
    from io import BytesIO
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    name_to_line = {l["name"].strip().lower(): l for l in lines if not l["is_calculated"]}
    values: dict[str, float] = {}

    # Find header row: look for a row whose first cell contains "Particulars"
    header_row = None
    for r in ws.iter_rows():
        first = str(r[0].value or "").strip().lower()
        if first == "particulars":
            header_row = r
            break

    if not header_row:
        raise ValueError("Could not find 'Particulars' header row in uploaded file.")

    # Map column index → calendar month
    col_to_month: dict[int, int] = {}
    label_to_month = {v.lower(): k for k, v in MONTH_LABELS.items()}
    for cell in header_row[1:]:
        lbl = str(cell.value or "").strip().lower()
        if lbl in label_to_month:
            col_to_month[cell.column] = label_to_month[lbl]

    if not col_to_month:
        raise ValueError("No month columns (Apr–Mar) found in header row.")

    # Parse data rows
    for row in ws.iter_rows(min_row=header_row[0].row + 1):
        name = str(row[0].value or "").strip().lower()
        line = name_to_line.get(name)
        if not line:
            continue
        lid = line["id"]
        for cell in row[1:]:
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

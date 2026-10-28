"""
Non-destructive XLSX Column Appender.
Preserves 100% of existing columns and values in their exact order,
and strictly appends the 9 standardized Local SEO audit columns to the far right.
"""

import io
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from seo_audit.models import SEOReport
from seo_audit.auditor import SEO_XLSX_COLUMNS


def normalize_domain(url: Optional[str]) -> str:
    """Extracts lowercase netloc domain for flexible matching."""
    if not url:
        return ""
    clean = url.strip().lower()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parsed = urlparse(clean)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return clean


def append_seo_columns_to_excel(
    excel_bytes: bytes,
    seo_reports: Dict[str, SEOReport],
) -> bytes:
    """
    Takes an existing Excel spreadsheet binary, preserves all existing columns,
    and appends the 9 Local SEO columns to the right with matching styling.
    
    `seo_reports` keys can be `place_id`, `website_url`, domain, or row indices.
    """
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    ws = wb.active
    ws.views.sheetView[0].showGridLines = True

    # Identify header columns
    header_cells = [ws.cell(row=1, column=col).value for col in range(1, ws.max_column + 1)]
    place_id_col = None
    website_url_col = None

    for col_idx, col_name in enumerate(header_cells, start=1):
        if col_name == "Place ID":
            place_id_col = col_idx
        elif col_name == "Website URL":
            website_url_col = col_idx

    orig_max_col = ws.max_column

    # Professional Style Tokens matching backend/excel_exporter.py
    header_fill = PatternFill(start_color="094CB2", end_color="094CB2", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    even_row_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    odd_row_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    body_font = Font(name="Calibri", size=10, color="1E293B")
    score_font = Font(name="Calibri", size=10, bold=True, color="094CB2")
    
    thin_border_side = Side(border_style="thin", color="E2E8F0")
    cell_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side
    )

    # 1. Write the 9 new Headers
    for i, col_title in enumerate(SEO_XLSX_COLUMNS):
        col_idx = orig_max_col + i + 1
        cell = ws.cell(row=1, column=col_idx, value=col_title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    # 2. Populate rows
    for row_idx in range(2, ws.max_row + 1):
        place_id_val = ws.cell(row=row_idx, column=place_id_col).value if place_id_col else None
        website_val = ws.cell(row=row_idx, column=website_url_col).value if website_url_col else None
        domain_val = normalize_domain(website_val)

        # Lookup report by place_id, url, domain, or row index
        report: Optional[SEOReport] = None
        if place_id_val and str(place_id_val) in seo_reports:
            report = seo_reports[str(place_id_val)]
        elif website_val and str(website_val) in seo_reports:
            report = seo_reports[str(website_val)]
        elif domain_val:
            for k, rep in seo_reports.items():
                if domain_val == normalize_domain(k) or domain_val == normalize_domain(rep.url):
                    report = rep
                    break

        row_fill = even_row_fill if row_idx % 2 == 0 else odd_row_fill

        for i, col_title in enumerate(SEO_XLSX_COLUMNS):
            col_idx = orig_max_col + i + 1
            if report and report.xlsx_row_data:
                cell_value = report.xlsx_row_data.get(col_title, "Not Audited")
            else:
                if not website_val:
                    cell_value = "No Website" if col_title != "SEO Opportunity Score" else "N/A"
                else:
                    cell_value = "Not Audited"

            cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
            cell.fill = row_fill
            cell.font = score_font if col_title == "SEO Opportunity Score" else body_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = cell_border

    # 3. Auto-adjust width for the 9 appended columns
    col_widths = {
        "Website Speed": 20,
        "Mobile Friendly": 16,
        "Title Tag Status": 24,
        "Meta Description Status": 24,
        "H1 Status": 20,
        "Local Keyword Status": 26,
        "Schema Status": 24,
        "NAP Status": 24,
        "SEO Opportunity Score": 22,
    }
    for i, col_title in enumerate(SEO_XLSX_COLUMNS):
        col_letter = get_column_letter(orig_max_col + i + 1)
        ws.column_dimensions[col_letter].width = col_widths.get(col_title, 20)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()

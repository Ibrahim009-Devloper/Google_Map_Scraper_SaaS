"""
Non-destructive XLSX Column Appender for Agency-Grade Local SEO Audits.
Preserves 100% of existing columns and values in their exact order,
and strictly appends the 21 standardized Local SEO audit columns to the far right
with matching professional agency styling.
"""

import io
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.seo_audit.models import SEOReport
from backend.seo_audit.config import SEO_XLSX_COLUMNS


def normalize_domain(url: Optional[str]) -> str:
    """Extracts lowercase netloc domain for flexible matching without www."""
    if not url:
        return ""
    clean = url.strip().lower()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parsed = urlparse(clean)
        netloc = parsed.netloc.replace("www.", "").strip()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        return netloc
    except Exception:
        return clean


def append_seo_columns_to_excel(
    excel_bytes: bytes,
    seo_reports: Dict[str, SEOReport],
) -> bytes:
    """
    Takes an existing Excel spreadsheet binary, preserves all existing columns,
    and appends the 21 Local SEO columns to the right with matching styling.
    
    `seo_reports` keys can be `place_id`, `website_url`, root domain, or row indices.
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
    pitch_font = Font(name="Calibri", size=10, bold=True, color="B91C1C")
    
    thin_border_side = Side(border_style="thin", color="E2E8F0")
    cell_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side
    )

    # 1. Write the 21 new Headers
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
                    if col_title == "SEO Health Score":
                        cell_value = "N/A"
                    elif col_title == "Lead Pitch Priority":
                        cell_value = "Critical Pitch (No Website)"
                    elif col_title == "AI / Dynamic Icebreaker Hook":
                        cell_value = "Business has no website listed on Google Maps."
                    else:
                        cell_value = "No Website"
                else:
                    cell_value = "Not Audited"

            cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
            cell.fill = row_fill
            cell.border = cell_border

            # Specific column styling
            if col_title == "SEO Health Score":
                cell.font = score_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_title == "Lead Pitch Priority":
                cell.font = pitch_font if "Critical" in str(cell_value) else body_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_title in ("Extracted Title Text", "Extracted Primary H1", "AI / Dynamic Icebreaker Hook"):
                cell.font = body_font
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.font = body_font
                cell.alignment = Alignment(horizontal="left" if len(str(cell_value)) > 25 else "center", vertical="center", wrap_text=True)

    # 3. Column widths for all 21 columns
    col_widths = {
        "Final URL & HTTP Status": 28,
        "SSL & HTTPS Redirect Status": 32,
        "Server Response (TTFB)": 24,
        "Indexability (Meta Robots)": 24,
        "Canonical Tag Status": 26,
        "Robots.txt & XML Sitemap": 24,
        "Extracted Title Text": 35,
        "Title Tag Status": 32,
        "Meta Description Status": 32,
        "Extracted Primary H1": 35,
        "H1 Tag Status": 32,
        "Homepage Word Count": 22,
        "Image Alt Text Gap": 24,
        "Local Keyword Status": 30,
        "Schema Status": 32,
        "NAP Status": 32,
        "Google Maps Embed": 24,
        "GBP Category Alignment": 30,
        "SEO Health Score": 18,
        "Lead Pitch Priority": 24,
        "AI / Dynamic Icebreaker Hook": 52,
    }
    for i, col_title in enumerate(SEO_XLSX_COLUMNS):
        col_letter = get_column_letter(orig_max_col + i + 1)
        ws.column_dimensions[col_letter].width = col_widths.get(col_title, 25)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


# Backward-compatible alias
append_seo_audit_columns_to_workbook = append_seo_columns_to_excel

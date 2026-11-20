"""
Non-destructive XLSX Column Appender for Agency-Grade Local SEO Audits.
Preserves 100% of existing columns and values in their exact order,
and appends standardized Local SEO audit columns to the far right
with matching professional agency styling.

Supports both:
1. Standard 21-column Local SEO schema (SEO_XLSX_COLUMNS).
2. Advanced sortable/filterable split schema (SEO_SPLIT_COLUMNS) with
   distinct <Check> Status (enum: Pass, Warning, Critical, Could Not Read, Not Checked)
   and <Check> Details (diagnostic text) columns, plus pure numeric integer SEO Health Score.
"""

import io
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.seo_audit.models import SEOReport
from backend.seo_audit.config import SEO_XLSX_COLUMNS, SEO_SPLIT_COLUMNS


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


def extract_check_status_and_details(val: Any) -> Tuple[str, str]:
    """
    Splits an audit check summary into strict (Status Enum, Diagnostic Details).
    Status Enum is strictly: Pass, Warning, Critical, Could Not Read, Not Checked.
    """
    if val is None or val == "" or val == "N/A":
        return "Not Checked", "No data available"

    val_str = str(val).strip()
    val_low = val_str.lower()

    if "could not read" in val_low or "js-rendered" in val_low:
        return "Could Not Read", val_str
    if "not tested" in val_low or "no website" in val_low or "not audited" in val_low:
        return "Not Checked", val_str

    if ":" in val_str:
        prefix, details = val_str.split(":", 1)
        prefix_clean = prefix.strip().lower()
        details_clean = details.strip()
        if "pass" in prefix_clean:
            return "Pass", details_clean
        elif "warning" in prefix_clean or "moderate" in prefix_clean:
            return "Warning", details_clean
        elif "critical" in prefix_clean or "high" in prefix_clean or "fail" in prefix_clean:
            return "Critical", details_clean

    if val_low in ("pass", "verified"):
        return "Pass", val_str
    if val_low in ("warning", "caution"):
        return "Warning", val_str
    if val_low in ("critical", "fail", "failed"):
        return "Critical", val_str

    if "pass" in val_low:
        return "Pass", val_str
    if "warn" in val_low:
        return "Warning", val_str
    if "fail" in val_low or "critical" in val_low:
        return "Critical", val_str

    return "Not Checked", val_str


# Mapping for split status/details extraction
_RAW_CHECK_MAP = {
    "SSL Status": ("SSL & HTTPS Redirect Status", True),
    "SSL Details": ("SSL & HTTPS Redirect Status", False),
    "TTFB Status": ("Server Response (TTFB)", True),
    "TTFB Details": ("Server Response (TTFB)", False),
    "Indexability Status": ("Indexability (Meta Robots)", True),
    "Indexability Details": ("Indexability (Meta Robots)", False),
    "Canonical Tag Status": ("Canonical Tag Status", True),
    "Canonical Tag Details": ("Canonical Tag Status", False),
    "Robots & Sitemap Status": ("Robots.txt & XML Sitemap", True),
    "Robots & Sitemap Details": ("Robots.txt & XML Sitemap", False),
    "Title Tag Status": ("Title Tag Status", True),
    "Title Tag Details": ("Title Tag Status", False),
    "Meta Description Status": ("Meta Description Status", True),
    "Meta Description Details": ("Meta Description Status", False),
    "H1 Tag Status": ("H1 Tag Status", True),
    "H1 Tag Details": ("H1 Tag Status", False),
    "Word Count Status": ("Homepage Word Count", True),
    "Word Count Details": ("Homepage Word Count", False),
    "Image Alt Status": ("Image Alt Text Gap", True),
    "Image Alt Details": ("Image Alt Text Gap", False),
    "Local Keyword Status": ("Local Keyword Status", True),
    "Local Keyword Details": ("Local Keyword Status", False),
    "Schema Status": ("Schema Status", True),
    "Schema Details": ("Schema Status", False),
    "NAP Status": ("NAP Status", True),
    "NAP Details": ("NAP Status", False),
    "Maps Embed Status": ("Google Maps Embed", True),
    "Maps Embed Details": ("Google Maps Embed", False),
    "GBP Category Status": ("GBP Category Alignment", True),
    "GBP Category Details": ("GBP Category Alignment", False),
    "Marketing & Tracking Status": ("Marketing & Tracking Tags", True),
    "Marketing & Tracking Details": ("Marketing & Tracking Tags", False),
    "Inner Pages Status": ("Inner Pages & Freshness", True),
    "Inner Pages Details": ("Inner Pages & Freshness", False),
}


def append_seo_columns_to_excel(
    excel_bytes: bytes,
    seo_reports: Dict[str, SEOReport],
    split_status_details: bool = False,
) -> bytes:
    """
    Takes an existing Excel spreadsheet binary, preserves all existing columns,
    and appends standardized Local SEO columns to the right with matching styling.
    
    `seo_reports` keys can be `place_id`, `website_url`, root domain, or row indices.
    If `split_status_details` is True, splits key checks into <Check> Status and <Check> Details.
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

    # Target column list
    target_columns = SEO_SPLIT_COLUMNS if split_status_details else SEO_XLSX_COLUMNS

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

    # 1. Write the new Headers
    for i, col_title in enumerate(target_columns):
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

        for i, col_title in enumerate(target_columns):
            col_idx = orig_max_col + i + 1
            raw_val = "Not Audited"
            if report and report.xlsx_row_data:
                if split_status_details and col_title in _RAW_CHECK_MAP:
                    src_key, is_status = _RAW_CHECK_MAP[col_title]
                    src_val = report.xlsx_row_data.get(src_key)
                    if src_val is None:
                        src_val = report.xlsx_row_data.get(col_title, "Not Audited")
                    status_enum, details_txt = extract_check_status_and_details(src_val)
                    raw_val = status_enum if is_status else details_txt
                else:
                    raw_val = report.xlsx_row_data.get(col_title, "Not Audited")
            else:
                if not website_val:
                    if col_title == "SEO Health Score":
                        raw_val = None if split_status_details else "N/A"
                    elif col_title == "Lead Pitch Priority":
                        raw_val = "Critical Pitch (No Website)"
                    elif col_title == "AI / Dynamic Icebreaker Hook":
                        raw_val = "Business has no website listed on Google Maps."
                    elif col_title.endswith("Status"):
                        raw_val = "Not Checked"
                    elif col_title.endswith("Details"):
                        raw_val = "No website listed"
                    else:
                        raw_val = "No Website"
                else:
                    if col_title.endswith("Status"):
                        raw_val = "Not Checked"
                    elif col_title.endswith("Details"):
                        raw_val = "Site not audited"
                    else:
                        raw_val = "Not Audited"

            cell_value = raw_val

            # Format cell
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = row_fill
            cell.border = cell_border

            # Specific column styling & type coercion
            if col_title == "SEO Health Score":
                # Ensure numeric integer storage (0-100) or blank/None
                if isinstance(cell_value, (int, float)):
                    cell.value = int(cell_value)
                    cell.number_format = "0"
                elif isinstance(cell_value, str) and "/100" in cell_value:
                    num_part = cell_value.split("/100")[0].strip()
                    if num_part.isdigit() and split_status_details:
                        cell.value = int(num_part)
                        cell.number_format = "0"
                    else:
                        cell.value = cell_value
                elif isinstance(cell_value, str) and cell_value.isdigit():
                    cell.value = int(cell_value)
                    cell.number_format = "0"
                elif cell_value in ("N/A", "Not Tested", "N/A (JS-Rendered)") and split_status_details:
                    cell.value = None
                else:
                    cell.value = cell_value

                cell.font = score_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_title == "Lead Pitch Priority":
                cell.value = cell_value
                cell.font = pitch_font if "Critical" in str(cell_value) else body_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_title in ("Extracted Title Text", "Extracted Primary H1", "AI / Dynamic Icebreaker Hook") or col_title.endswith("Details"):
                cell.value = cell_value
                cell.font = body_font
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            elif col_title.endswith("Status"):
                cell.value = cell_value
                cell.font = body_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.value = cell_value
                cell.font = body_font
                cell.alignment = Alignment(horizontal="left" if len(str(cell_value or "")) > 25 else "center", vertical="center", wrap_text=True)

    # 3. Column widths
    col_widths = {
        "Final URL & HTTP Status": 28,
        "SSL & HTTPS Redirect Status": 32,
        "SSL Status": 16,
        "SSL Details": 28,
        "Server Response (TTFB)": 24,
        "TTFB Status": 16,
        "TTFB Details": 26,
        "Indexability (Meta Robots)": 24,
        "Indexability Status": 16,
        "Indexability Details": 28,
        "Canonical Tag Status": 20,
        "Canonical Tag Details": 28,
        "Robots.txt & XML Sitemap": 24,
        "Robots & Sitemap Status": 18,
        "Robots & Sitemap Details": 28,
        "Extracted Title Text": 35,
        "Title Tag Status": 18,
        "Title Tag Details": 30,
        "Meta Description Status": 18,
        "Meta Description Details": 30,
        "Extracted Primary H1": 35,
        "H1 Tag Status": 18,
        "H1 Tag Details": 30,
        "Homepage Word Count": 22,
        "Word Count Status": 16,
        "Word Count Details": 24,
        "Image Alt Text Gap": 24,
        "Image Alt Status": 16,
        "Image Alt Details": 24,
        "Local Keyword Status": 18,
        "Local Keyword Details": 30,
        "Schema Status": 18,
        "Schema Details": 30,
        "NAP Status": 18,
        "NAP Details": 30,
        "Google Maps Embed": 24,
        "Maps Embed Status": 16,
        "Maps Embed Details": 24,
        "GBP Category Alignment": 30,
        "GBP Category Status": 18,
        "GBP Category Details": 30,
        "Marketing & Tracking Tags": 28,
        "Marketing & Tracking Status": 18,
        "Marketing & Tracking Details": 30,
        "Inner Pages & Freshness": 28,
        "Inner Pages Status": 18,
        "Inner Pages Details": 30,
        "SEO Health Score": 18,
        "Lead Pitch Priority": 24,
        "AI / Dynamic Icebreaker Hook": 52,
    }
    for i, col_title in enumerate(target_columns):
        col_letter = get_column_letter(orig_max_col + i + 1)
        ws.column_dimensions[col_letter].width = col_widths.get(col_title, 22)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def append_split_seo_columns_to_excel(
    excel_bytes: bytes,
    seo_reports: Dict[str, SEOReport],
) -> bytes:
    """
    Appends the advanced sortable/filterable split Local SEO schema (SEO_SPLIT_COLUMNS)
    featuring dedicated <Check> Status and <Check> Details columns and pure numeric SEO scores.
    """
    return append_seo_columns_to_excel(excel_bytes, seo_reports, split_status_details=True)


# Backward-compatible alias
append_seo_audit_columns_to_workbook = append_seo_columns_to_excel

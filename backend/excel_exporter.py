"""
Executive Excel (.xlsx) Exporter with Professional Table Styling.
Generates publication-ready spreadsheets featuring:
- Alexandria / LeadPulse Royal Navy Header (#094CB2) with bold white text
- Alternating zebra row striping (#FFFFFF / #F8FAFC)
- Subtle borders (#CBD5E1)
- Clickable hyperlinks for websites and Google Maps
- Auto-adjusted column widths and frozen top header row with auto-filters
"""

import io
from typing import List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from agent.schemas import LeadItem


def generate_leads_excel(
    leads: List[LeadItem],
    title: str = "LeadPulse Verified Leads",
    include_enrichment: Optional[bool] = None,
) -> bytes:
    """
    Exports a list of LeadItem objects into a beautifully formatted,
    executive-grade Microsoft Excel (.xlsx) spreadsheet.

    When include_enrichment is False (or when auto-detected that no website
    enrichment was performed), empty enrichment columns (Emails, Facebook,
    Instagram, LinkedIn, WhatsApp, CMS / Tech) are excluded to ensure a clean,
    uncluttered Google Maps spreadsheet without empty columns.
    """
    if include_enrichment is None:
        include_enrichment = (
            any(bool(l.emails) for l in leads) or
            any(bool(l.social_links and (
                l.social_links.facebook or
                l.social_links.instagram or
                l.social_links.linkedin or
                l.social_links.whatsapp
            )) for l in leads) or
            any(bool(l.cms_tech) for l in leads)
        )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Verified Leads"
    ws.views.sheetView[0].showGridLines = True

    # Base Google Maps Columns (always present)
    columns = [
        ("Business Name", lambda l: l.name, 28, "left"),
        ("Category", lambda l: l.category or "", 22, "left"),
        ("Phone Number", lambda l: l.phone or "", 18, "center"),
    ]

    # Only include Emails if website enrichment was performed
    if include_enrichment:
        columns.append(("Emails", lambda l: "; ".join(l.emails) if l.emails else "", 28, "left"))

    columns.extend([
        ("Website Status", lambda l: l.website_status, 16, "center"),
        ("Website URL", lambda l: l.website_url or "", 26, "left"),
        ("Rating", lambda l: l.rating if l.rating is not None else "", 10, "center"),
        ("Reviews Count", lambda l: l.reviews_count, 14, "center"),
        ("Price Range", lambda l: l.price_range or "", 12, "center"),
        ("Unclaimed Business", lambda l: "Yes" if l.is_unclaimed_business else "No", 18, "center"),
        ("Neighborhood", lambda l: l.neighborhood or "", 18, "left"),
        ("Full Address", lambda l: l.address or "", 36, "left"),
    ])

    # Only include Social Links & CMS Tech if website enrichment was performed
    if include_enrichment:
        columns.extend([
            ("Facebook", lambda l: (l.social_links.facebook or "") if l.social_links else "", 22, "left"),
            ("Instagram", lambda l: (l.social_links.instagram or "") if l.social_links else "", 22, "left"),
            ("LinkedIn", lambda l: (l.social_links.linkedin or "") if l.social_links else "", 22, "left"),
            ("WhatsApp", lambda l: (l.social_links.whatsapp or "") if l.social_links else "", 18, "center"),
            ("CMS / Tech", lambda l: l.cms_tech or "", 14, "center"),
        ])

    columns.extend([
        ("Latitude", lambda l: l.lat if l.lat is not None else "", 12, "center"),
        ("Longitude", lambda l: l.lon if l.lon is not None else "", 12, "center"),
        ("Google Maps Link", lambda l: l.google_maps_url or "", 24, "left"),
        ("Place ID", lambda l: l.place_id, 28, "left"),
    ])

    # Professional Style Tokens
    header_fill = PatternFill(start_color="094CB2", end_color="094CB2", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    even_row_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    odd_row_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    body_font = Font(name="Calibri", size=10, color="1E293B")
    link_font = Font(name="Calibri", size=10, color="094CB2", underline="single")
    badge_unclaimed_font = Font(name="Calibri", size=10, color="B45309", bold=True)
    
    thin_border_side = Side(border_style="thin", color="E2E8F0")
    cell_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side
    )

    # 1. Write Header Row
    ws.row_dimensions[1].height = 28
    for col_idx, (col_name, _, _, align) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        cell.border = cell_border

    # 2. Write Data Rows
    for row_idx, lead in enumerate(leads, start=2):
        ws.row_dimensions[row_idx].height = 20
        row_fill = even_row_fill if row_idx % 2 == 0 else odd_row_fill

        for col_idx, (col_name, getter, _, default_align) in enumerate(columns, start=1):
            val = getter(lead)
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = row_fill
            cell.font = body_font
            cell.border = cell_border

            # Alignments
            cell.alignment = Alignment(horizontal=default_align, vertical="center", wrap_text=False)

            # Highlight Unclaimed
            if col_name == "Unclaimed Business" and val == "Yes":
                cell.font = badge_unclaimed_font

            # Clickable Links
            if col_name in ("Website URL", "Google Maps Link") and val and str(val).startswith("http"):
                cell.hyperlink = str(val)
                cell.font = link_font

    # 3. Auto-fit column widths with padding
    for col_idx, (col_name, _, min_w, _) in enumerate(columns, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = len(col_name)
        for row in range(2, min(len(leads) + 2, 50)):  # check first 50 rows for speed
            val_str = str(ws.cell(row=row, column=col_idx).value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(min_w, min(max_len + 4, 45))

    # 4. Enable Auto-Filter & Freeze Panes
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(leads) + 1}"
    ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

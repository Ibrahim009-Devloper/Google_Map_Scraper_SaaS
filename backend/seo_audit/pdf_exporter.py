"""
White-Label Branded PDF Exporter using ReportLab.
Generates pure Python, agency-grade Local SEO Audit PDFs without headless browsers.
"""

import io
import os
import re
import html
from typing import Optional, List, Dict, Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas

from backend.seo_audit.models import (
    AIAuditReport,
    AgencyBranding,
    AuditSectionConfig,
    ActionPlanItem,
    CompetitorComparison,
)


def _safe_xml(text: Any) -> str:
    """Escapes XML entities so ReportLab's paraparser doesn't choke on HTML code snippets."""
    if text is None:
        return ""
    return html.escape(str(text))


def _safe_hex_color(hex_str: Optional[str], default_hex: str) -> colors.HexColor:
    """Safely parses a hex color string into a ReportLab HexColor."""
    if not hex_str:
        return colors.HexColor(default_hex)
    clean = hex_str.strip()
    if not clean.startswith("#"):
        clean = "#" + clean
    if re.match(r"^#[0-9a-fA-F]{6}$", clean):
        try:
            return colors.HexColor(clean)
        except Exception:
            pass
    return colors.HexColor(default_hex)


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that dynamically calculates and renders
    'Page X of Y' along with a professional agency footer.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.agency_name = "Agency"
        self.agency_contact = ""
        self.primary_hex = "#2563EB"

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        page_w, page_h = self._pagesize

        # Footer divider line
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(36, 40, page_w - 36, 40)

        # Footer text
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))

        left_footer = f"Confidential Local SEO Audit  •  Prepared by {self.agency_name}"
        if self.agency_contact:
            left_footer += f"  ({self.agency_contact})"

        self.drawString(36, 26, left_footer)
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(page_w - 36, 26, page_str)

        self.restoreState()


def generate_audit_pdf(
    report: AIAuditReport,
    branding: Optional[AgencyBranding] = None,
) -> bytes:
    """
    Builds a professional white-label PDF audit report from an AIAuditReport object.
    Returns the binary PDF content as bytes.
    """
    if branding is None:
        branding = report.branding or AgencyBranding()

    primary_color = _safe_hex_color(branding.primary_color, "#2563EB")
    accent_color = _safe_hex_color(branding.accent_color, "#10B981")
    dark_slate = colors.HexColor("#0F172A")
    body_text_color = colors.HexColor("#334155")
    muted_color = colors.HexColor("#64748B")
    card_bg = colors.HexColor("#F8FAFC")
    border_color = colors.HexColor("#E2E8F0")

    # Severity Colors
    crit_color = colors.HexColor("#DC2626")
    crit_bg = colors.HexColor("#FEF2F2")
    warn_color = colors.HexColor("#D97706")
    warn_bg = colors.HexColor("#FFFBEB")
    pass_color = colors.HexColor("#16A34A")
    pass_bg = colors.HexColor("#F0FDF4")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    # Custom Typography Styles
    style_agency_title = ParagraphStyle(
        "AgencyTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=primary_color,
    )

    style_agency_tagline = ParagraphStyle(
        "AgencyTagline",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=muted_color,
    )

    style_doc_heading = ParagraphStyle(
        "DocHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=dark_slate,
    )

    style_section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=primary_color,
        spaceBefore=10,
        spaceAfter=4,
    )

    style_body = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=body_text_color,
    )

    style_body_bold = ParagraphStyle(
        "ReportBodyBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=dark_slate,
    )

    style_badge = ParagraphStyle(
        "BadgeText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=1,
    )

    style_table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    style_cell_desc = ParagraphStyle(
        "CellDesc",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=body_text_color,
    )

    story: List[Any] = []
    content_width = 540  # 612 - 72

    # =========================================================================
    # 1. HEADER BANNER: Agency Branding (Logo / Title / Contact)
    # =========================================================================
    agency_contact_parts = []
    if branding.website:
        agency_contact_parts.append(branding.website.replace("https://", "").replace("http://", ""))
    if branding.contact_email:
        agency_contact_parts.append(branding.contact_email)
    if branding.phone:
        agency_contact_parts.append(branding.phone)
    agency_contact_str = "  |  ".join(agency_contact_parts)

    agency_left_content = [
        Paragraph(f"<b>{_safe_xml(branding.agency_name)}</b>", style_agency_title),
        Paragraph(_safe_xml(branding.tagline or "Local SEO & Digital Marketing Solutions"), style_agency_tagline),
    ]
    if agency_contact_str:
        agency_left_content.append(Spacer(1, 2))
        agency_left_content.append(Paragraph(_safe_xml(agency_contact_str), style_agency_tagline))

    agency_right_content = [
        Paragraph("<b>EXECUTIVE REPORT</b>", ParagraphStyle(
            "BadgeTop", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=primary_color, alignment=2
        )),
        Paragraph(f"Audit Date: {_safe_xml(report.audit_date)}", ParagraphStyle(
            "DateTop", parent=styles["Normal"], fontName="Helvetica", fontSize=8, textColor=muted_color, alignment=2
        )),
    ]

    header_table = Table(
        [[agency_left_content, agency_right_content]],
        colWidths=[360, 180]
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceBefore=4, spaceAfter=10))

    # =========================================================================
    # 2. TARGET BUSINESS PROFILE CARD
    # =========================================================================
    story.append(Paragraph("LOCAL SEO & DIGITAL VISIBILITY AUDIT", style_doc_heading))
    story.append(Spacer(1, 6))

    biz_info_left = [
        Paragraph(f"<b>Target Business:</b> {_safe_xml(report.business_name)}", style_body),
        Paragraph(f"<b>Category:</b> {_safe_xml(report.category)}", style_body),
        Paragraph(f"<b>Location:</b> {_safe_xml(report.location)}", style_body),
    ]
    biz_info_right = [
        Paragraph(f"<b>Target Website:</b> {_safe_xml(report.website_url)}", style_body),
        Paragraph(f"<b>Audited URL:</b> {_safe_xml(report.audited_url)}", style_body),
        Paragraph(f"<b>Report Scope:</b> {_safe_xml(', '.join(report.audit_scope[:4]))}", style_body),
    ]

    biz_table = Table(
        [[biz_info_left, biz_info_right]],
        colWidths=[270, 270]
    )
    biz_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), card_bg),
        ("BOX", (0, 0), (-1, -1), 1, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(biz_table)
    story.append(Spacer(1, 10))

    # =========================================================================
    # 3. EXECUTIVE SCORECARD & AUDIT SCOPE
    # =========================================================================
    score_val = report.seo_health_score
    if score_val is not None:
        score_str = f"{score_val}"
        if score_val >= 85:
            score_status_str = "WELL OPTIMIZED"
            score_status_color = pass_color
            score_badge_bg = pass_bg
        elif score_val >= 60:
            score_status_str = "MODERATE OPPORTUNITY"
            score_status_color = warn_color
            score_badge_bg = warn_bg
        else:
            score_status_str = "CRITICAL OPTIMIZATION NEEDED"
            score_status_color = crit_color
            score_badge_bg = crit_bg
    else:
        score_str = "N/A"
        score_status_str = "JS-RENDERED (MANUAL REVIEW)"
        score_status_color = muted_color
        score_badge_bg = card_bg

    score_box_left = [
        Paragraph("SEO HEALTH SCORE", ParagraphStyle(
            "ScoreLbl", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=muted_color
        )),
        Paragraph(f"<b>{score_str}</b> <font size=12 color='#64748B'>/ 100</font>", ParagraphStyle(
            "ScoreBig", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=score_status_color
        )),
        Paragraph(f"<b>{score_status_str}</b>", ParagraphStyle(
            "ScoreStat", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=score_status_color
        )),
    ]

    # Metrics summary stats on the right
    metrics_stats = [
        Paragraph("<b>Audit Findings Summary</b>", style_body_bold),
        Spacer(1, 3),
        Paragraph(f"• <font color='#DC2626'><b>{len(report.critical_issues)} Critical Issues</b></font> requiring prompt remediation", style_body),
        Paragraph(f"• <font color='#D97706'><b>{len(report.warnings)} Warnings</b></font> with moderate ranking impact", style_body),
        Paragraph(f"• <font color='#16A34A'><b>{len(report.passed_checks)} Passed Checks</b></font> satisfying Google guidelines", style_body),
        Paragraph(f"• <b>{len(report.action_plan)} Strategic Roadmap Items</b> in prioritized action plan", style_body),
    ]

    score_table = Table(
        [[score_box_left, metrics_stats]],
        colWidths=[180, 360]
    )
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), score_badge_bg),
        ("BACKGROUND", (1, 0), (1, 0), card_bg),
        ("BOX", (0, 0), (-1, -1), 1, border_color),
        ("LINEBEFORE", (1, 0), (1, 0), 1, border_color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 10))

    # =========================================================================
    # 4. EXECUTIVE SUMMARY
    # =========================================================================
    story.append(Paragraph("Executive Summary", style_section_title))
    exec_summary_text = _safe_xml(report.executive_summary or "Audit analysis completed.")
    exec_table = Table(
        [[Paragraph(exec_summary_text, style_body)]],
        colWidths=[content_width]
    )
    exec_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), card_bg),
        ("BOX", (0, 0), (-1, -1), 0.75, border_color),
        ("LINELEFT", (0, 0), (0, 0), 3.5, primary_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(exec_table)
    story.append(Spacer(1, 10))

    # =========================================================================
    # 5. PRIORITIZED ACTION PLAN ROADMAP
    # =========================================================================
    if report.action_plan:
        story.append(Paragraph("Prioritized Implementation Roadmap", style_section_title))
        story.append(Paragraph(
            "Recommended step-by-step actions prioritized by business impact and technical effort.",
            style_body
        ))
        story.append(Spacer(1, 4))

        action_rows = [[
            Paragraph("Timeframe", style_table_header),
            Paragraph("Priority", style_table_header),
            Paragraph("Category", style_table_header),
            Paragraph("Strategic Action Item & Expected Impact", style_table_header),
        ]]

        for item in report.action_plan[:8]:  # Top 8 actionable items
            p_color = "#DC2626" if item.priority == "Critical" else ("#D97706" if item.priority == "High" else "#2563EB")
            action_desc = f"<b>{_safe_xml(item.title)}</b><br/>{_safe_xml(item.impact)}"
            if item.description and item.description != item.impact:
                action_desc += f"<br/><font color='#64748B'><i>Evidence: {_safe_xml(item.description)}</i></font>"

            action_rows.append([
                Paragraph(f"<b>{_safe_xml(item.timeframe)}</b>", style_cell_desc),
                Paragraph(f"<font color='{p_color}'><b>{_safe_xml(item.priority)}</b></font>", style_cell_desc),
                Paragraph(_safe_xml(item.category), style_cell_desc),
                Paragraph(action_desc, style_cell_desc),
            ])

        action_table = Table(action_rows, colWidths=[95, 55, 85, 305])
        action_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), primary_color),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(action_table)
        story.append(Spacer(1, 10))

    # =========================================================================
    # 6. COMPETITOR GAP COMPARISON (IF INCLUDED)
    # =========================================================================
    if report.competitors and report.competitor_analysis:
        story.append(Paragraph("Local Competitor Gap Analysis", style_section_title))
        story.append(Paragraph(_safe_xml(report.competitor_analysis), style_body))
        story.append(Spacer(1, 4))

        comp_rows = [[
            Paragraph("Business Name", style_table_header),
            Paragraph("Rating", style_table_header),
            Paragraph("Reviews", style_table_header),
            Paragraph("Schema", style_table_header),
            Paragraph("NAP Phone", style_table_header),
            Paragraph("Key Trailing Gap", style_table_header),
        ]]

        # Target business row
        comp_rows.append([
            Paragraph(f"<b>{_safe_xml(report.business_name)} (Target)</b>", style_cell_desc),
            Paragraph(f"{_safe_xml(report.raw_seo_report.issues.get('rating', '') if report.raw_seo_report else '') or '—'}", style_cell_desc),
            Paragraph("Target", style_cell_desc),
            Paragraph("Audited", style_cell_desc),
            Paragraph("Audited", style_cell_desc),
            Paragraph("Baseline Profile", style_cell_desc),
        ])

        for c in report.competitors[:3]:
            schema_badge = "Yes" if c.has_schema else "No"
            nap_badge = "Yes" if c.has_nap else "No"
            gap_text = "; ".join(c.trailing_gaps) if c.trailing_gaps else "Local competitor"

            comp_rows.append([
                Paragraph(_safe_xml(c.business_name), style_cell_desc),
                Paragraph(f"{_safe_xml(c.rating) or '—'}", style_cell_desc),
                Paragraph(f"{_safe_xml(c.reviews_count) or '—'}", style_cell_desc),
                Paragraph(schema_badge, style_cell_desc),
                Paragraph(nap_badge, style_cell_desc),
                Paragraph(_safe_xml(gap_text), style_cell_desc),
            ])

        comp_table = Table(comp_rows, colWidths=[130, 45, 55, 50, 60, 200])
        comp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), primary_color),
            ("BACKGROUND", (0, 1), (-1, 1), card_bg),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 10))

    # =========================================================================
    # 7. CRITICAL ISSUES & WARNINGS DETAILS
    # =========================================================================
    if report.critical_issues or report.warnings:
        story.append(Paragraph("Verified Issues & Plain-English Explanations", style_section_title))

        issue_rows = [[
            Paragraph("Issue & Severity", style_table_header),
            Paragraph("Technical Evidence", style_table_header),
            Paragraph("Business Impact & Remediation", style_table_header),
        ]]

        for issue_str in report.critical_issues:
            parts = issue_str.split(":", 1)
            issue_title = parts[0].strip()
            evidence = parts[1].strip() if len(parts) > 1 else ""
            explanation = next((exp for exp in report.plain_english_explanations if exp.get("check") == issue_title), None)
            if explanation:
                impact_text = f"{_safe_xml(explanation.get('impact', ''))}<br/><b>Fix:</b> {_safe_xml(explanation.get('recommendation', ''))}"
            else:
                impact_text = "Impairs local rankings."

            issue_rows.append([
                Paragraph(f"<font color='#DC2626'><b>[CRITICAL]</b></font><br/><b>{_safe_xml(issue_title)}</b>", style_cell_desc),
                Paragraph(_safe_xml(evidence), style_cell_desc),
                Paragraph(impact_text, style_cell_desc),
            ])

        for warn_str in report.warnings[:6]:  # Limit to 6 warnings
            parts = warn_str.split(":", 1)
            warn_title = parts[0].strip()
            evidence = parts[1].strip() if len(parts) > 1 else ""
            explanation = next((exp for exp in report.plain_english_explanations if exp.get("check") == warn_title), None)
            if explanation:
                impact_text = f"{_safe_xml(explanation.get('impact', ''))}<br/><b>Fix:</b> {_safe_xml(explanation.get('recommendation', ''))}"
            else:
                impact_text = "Reduces ranking efficiency."

            issue_rows.append([
                Paragraph(f"<font color='#D97706'><b>[WARNING]</b></font><br/><b>{_safe_xml(warn_title)}</b>", style_cell_desc),
                Paragraph(_safe_xml(evidence), style_cell_desc),
                Paragraph(impact_text, style_cell_desc),
            ])

        issues_table = Table(issue_rows, colWidths=[120, 200, 220])
        issues_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(issues_table)
        story.append(Spacer(1, 10))

    # =========================================================================
    # 8. PASSED CHECKS SUMMARY
    # =========================================================================
    if report.passed_checks:
        story.append(Paragraph("Passed SEO Signals", style_section_title))
        pass_items = [f"✓  {_safe_xml(p)}" for p in report.passed_checks[:8]]
        pass_text = "<br/>".join(pass_items)
        pass_table = Table([[Paragraph(pass_text, style_body)]], colWidths=[content_width])
        pass_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), pass_bg),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBF7D0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(pass_table)
        story.append(Spacer(1, 10))

    # =========================================================================
    # 9. DATA LIMITATIONS & METHODOLOGY
    # =========================================================================
    if report.data_limitations:
        story.append(Paragraph("Audit Methodology & Data Transparency", style_section_title))
        limit_items = [f"•  {_safe_xml(d)}" for d in report.data_limitations]
        limit_text = (
            "<b>Transparency Notice:</b> To maintain strict reporting integrity, metrics that could not be verified "
            "over HTTP or required unconfigured APIs are listed below rather than assumed:<br/>"
            + "<br/>".join(limit_items)
        )
        limit_table = Table([[Paragraph(limit_text, style_body)]], colWidths=[content_width])
        limit_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), card_bg),
            ("BOX", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(limit_table)
        story.append(Spacer(1, 12))

    # =========================================================================
    # 10. CALL TO ACTION / AGENCY CLOSING
    # =========================================================================
    closing_p = (
        f"<b>Ready to scale your local search dominance?</b><br/>"
        f"Contact <b>{_safe_xml(branding.agency_name)}</b> today to implement this prioritized roadmap and capture more qualified leads in {_safe_xml(report.location)}."
    )
    if agency_contact_str:
        closing_p += f"<br/><b>Reach us:</b> {_safe_xml(agency_contact_str)}"

    closing_table = Table([[Paragraph(closing_p, style_body)]], colWidths=[content_width])
    closing_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 1, primary_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(closing_table)

    # Build PDF with custom NumberedCanvas
    def _canvas_maker(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.agency_name = branding.agency_name
        c.agency_contact = agency_contact_str
        c.primary_hex = branding.primary_color
        return c

    doc.build(story, canvasmaker=_canvas_maker)
    return buffer.getvalue()

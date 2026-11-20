"""
FastAPI Routes for On-Demand Local SEO Audits, Grounded AI Reports,
and White-Label PDF Export Engine.
"""

import io
import re
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from backend.seo_audit.models import (
    AuditInput,
    SEOReport,
    AuditSectionConfig,
    AgencyBranding,
    CompetitorComparison,
    PageSpeedResult,
    AIAuditReport,
    GenerateReportRequest,
    ExportPdfRequest,
)
from backend.seo_audit.auditor import audit_single_business, audit_bulk_businesses
from backend.seo_audit.ai_report import generate_ai_audit_report
from backend.seo_audit.pdf_exporter import generate_audit_pdf

router = APIRouter(prefix="", tags=["SEO Audit"])


class PageSpeedRequest(BaseModel):
    url: str


def _init_branding_table():
    """Ensures agency branding SQLite table exists in local temp store."""
    try:
        from backend.temp_store import get_sync_connection
        with get_sync_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agency_branding (
                    id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    except Exception:
        pass


def _get_saved_branding() -> AgencyBranding:
    """Retrieves saved agency branding profile from SQLite or returns default."""
    _init_branding_table()
    try:
        from backend.temp_store import get_sync_connection
        with get_sync_connection() as conn:
            row = conn.execute("SELECT data_json FROM agency_branding WHERE id = 'default'").fetchone()
            if row and row[0]:
                return AgencyBranding.model_validate_json(row[0])
    except Exception:
        pass
    return AgencyBranding()


def _save_branding(branding: AgencyBranding) -> AgencyBranding:
    """Persists agency branding profile into SQLite."""
    _init_branding_table()
    try:
        from backend.temp_store import get_sync_connection
        with get_sync_connection() as conn:
            conn.execute(
                "INSERT INTO agency_branding (id, data_json, updated_at) VALUES ('default', ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json, updated_at = CURRENT_TIMESTAMP",
                (branding.model_dump_json(),)
            )
            conn.commit()
    except Exception:
        pass
    return branding


@router.post("/seo-audit", response_model=SEOReport, summary="Audit a single business website")
def seo_audit_endpoint(payload: AuditInput) -> SEOReport:
    """Performs an on-demand 11-check Local SEO audit for a single business website."""
    if not payload.url or not payload.url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid website URL is required for SEO audit.",
        )
    report = audit_single_business(payload)

    # If associated with an active scraping job, persist to temp buffer for export
    if payload.job_id and payload.place_id:
        try:
            from backend.temp_store import get_sync_connection
            with get_sync_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT lead_json FROM temp_leads WHERE job_id = ? AND place_id = ?",
                    (payload.job_id, payload.place_id),
                )
                row = cursor.fetchone()
                if row:
                    lead_dict = json.loads(row[0])
                    lead_dict["seo_report"] = report.model_dump()
                    cursor.execute(
                        "UPDATE temp_leads SET lead_json = ? WHERE job_id = ? AND place_id = ?",
                        (json.dumps(lead_dict, ensure_ascii=False), payload.job_id, payload.place_id),
                    )
                    conn.commit()
        except Exception:
            pass

    return report


@router.post("/seo-audit/bulk", response_model=List[SEOReport], summary="Audit multiple business websites in bulk")
def seo_audit_bulk_endpoint(payload: List[AuditInput]) -> List[SEOReport]:
    """Performs concurrent on-demand Local SEO audits for a batch of business websites."""
    if not payload:
        return []
    return audit_bulk_businesses(payload)


@router.post("/seo-audit/generate-report", response_model=AIAuditReport, summary="Generate client-ready Grounded AI Audit Report")
def generate_report_endpoint(payload: GenerateReportRequest) -> AIAuditReport:
    """Generates an evidence-backed, client-ready agency AI audit report with custom section selection."""
    audit_input = payload.audit_input
    if audit_input is None:
        if not payload.url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid website URL or audit_input is required to generate report.",
            )
        audit_input = AuditInput(
            url=payload.url,
            business_name=payload.business_name,
            category=payload.category,
            city=payload.city,
            target_city=payload.target_city,
            phone=payload.phone,
            address=payload.address,
            rating=payload.rating,
            reviews_count=payload.reviews_count,
            job_id=payload.job_id,
            place_id=payload.place_id,
        )

    sections = payload.sections or AuditSectionConfig()
    branding = payload.branding or _get_saved_branding()

    competitors = None
    if sections.competitor_research and audit_input.place_id:
        competitors = get_competitors_endpoint(audit_input.place_id)

    pagespeed = None
    if sections.pagespeed_mobile:
        pagespeed = run_pagespeed_endpoint(PageSpeedRequest(url=audit_input.url))

    return generate_ai_audit_report(
        audit_input=audit_input,
        sections=sections,
        branding=branding,
        competitors=competitors,
        pagespeed=pagespeed,
    )


@router.post("/seo-audit/export-pdf", summary="Export White-Label Agency Branded PDF Report")
def export_pdf_endpoint(payload: ExportPdfRequest):
    """Exports a client-ready, white-label branded PDF report using pure ReportLab."""
    if payload.report_data:
        report = payload.report_data
        branding = payload.branding or report.branding or _get_saved_branding()
    else:
        audit_input = payload.audit_input
        if audit_input is None:
            if not payload.url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A valid website URL, audit_input, or report_data is required for PDF export.",
                )
            audit_input = AuditInput(
                url=payload.url,
                business_name=payload.business_name,
                category=payload.category,
                city=payload.city,
                target_city=payload.target_city,
                phone=payload.phone,
                address=payload.address,
                rating=payload.rating,
                reviews_count=payload.reviews_count,
                job_id=payload.job_id,
                place_id=payload.place_id,
            )

        sections = payload.sections or AuditSectionConfig()
        branding = payload.branding or _get_saved_branding()

        competitors = None
        if sections.competitor_research and audit_input.place_id:
            competitors = get_competitors_endpoint(audit_input.place_id)

        pagespeed = None
        if sections.pagespeed_mobile:
            pagespeed = run_pagespeed_endpoint(PageSpeedRequest(url=audit_input.url))

        report = generate_ai_audit_report(
            audit_input=audit_input,
            sections=sections,
            branding=branding,
            competitors=competitors,
            pagespeed=pagespeed,
        )

    pdf_bytes = generate_audit_pdf(report, branding=branding)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", report.business_name or "Audit_Report").strip("_")
    filename = f"{safe_name}_SEO_Audit.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"",
            "Content-Type": "application/pdf",
        },
    )


@router.get("/seo-audit/competitors/{place_id}", response_model=List[CompetitorComparison], summary="Get Top 3 local competitor comparison")
def get_competitors_endpoint(place_id: str) -> List[CompetitorComparison]:
    """Retrieves structured side-by-side local competitor comparisons for a target business."""
    # Attempt to import and call competitor module if implemented
    try:
        from backend.seo_audit import competitor as comp_module
        if hasattr(comp_module, "get_competitors_for_place_id"):
            res = comp_module.get_competitors_for_place_id(place_id)
            if res:
                return res
        elif hasattr(comp_module, "find_top_competitors"):
            res = comp_module.find_top_competitors(place_id)
            if res:
                return res
    except Exception:
        pass

    # Fallback to scanning local SQLite temp store
    competitors = []
    try:
        from backend.temp_store import get_sync_connection
        with get_sync_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lead_json FROM temp_leads WHERE place_id = ?", (place_id,))
            target_row = cursor.fetchone()
            if target_row:
                target_lead = json.loads(target_row[0])
                target_cat = target_lead.get("category") or ""
                cursor.execute(
                    "SELECT lead_json FROM temp_leads WHERE place_id != ? ORDER BY id DESC LIMIT 10",
                    (place_id,)
                )
                rows = cursor.fetchall()
                for r in rows:
                    lead = json.loads(r[0])
                    if target_cat and lead.get("category") != target_cat and len(competitors) >= 1:
                        continue
                    seo_rep = lead.get("seo_report") or {}
                    issues = seo_rep.get("issues") or {}
                    has_schema = issues.get("schema_markup", {}).get("audit_status") == "Pass"
                    has_nap = issues.get("nap_consistency", {}).get("audit_status") == "Pass"
                    has_tracking = any("tracking" in k for k in issues.keys())

                    competitors.append(CompetitorComparison(
                        business_name=lead.get("name") or "Local Competitor",
                        place_id=lead.get("place_id"),
                        rating=lead.get("rating"),
                        reviews_count=lead.get("reviews_count"),
                        seo_score=seo_rep.get("seo_health_score"),
                        has_schema=has_schema,
                        has_nap=has_nap,
                        has_tracking=has_tracking,
                        trailing_gaps=[f"{lead.get('reviews_count', 0)} Google Reviews"]
                    ))
                    if len(competitors) >= 3:
                        break
    except Exception:
        pass

    return competitors


@router.post("/seo-audit/pagespeed", response_model=PageSpeedResult, summary="Run Google PageSpeed check")
def run_pagespeed_endpoint(payload: PageSpeedRequest) -> PageSpeedResult:
    """Runs on-demand Google PageSpeed Insights check with graceful fallback."""
    if not payload.url or not payload.url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid website URL is required for PageSpeed check.",
        )
    try:
        from backend.seo_audit import pagespeed as ps_module
        if hasattr(ps_module, "check_pagespeed"):
            return ps_module.check_pagespeed(payload.url)
        elif hasattr(ps_module, "get_pagespeed_metrics"):
            return ps_module.get_pagespeed_metrics(payload.url)
    except Exception:
        pass

    return PageSpeedResult(
        mobile_score=None,
        desktop_score=None,
        status="Unavailable",
        details="Google PageSpeed Insights API key not configured or provider unavailable.",
    )


@router.get("/agency/branding", response_model=AgencyBranding, summary="Get Agency Branding profile")
def get_agency_branding_endpoint() -> AgencyBranding:
    """Returns the configured white-label agency branding profile."""
    return _get_saved_branding()


@router.post("/agency/branding", response_model=AgencyBranding, summary="Save Agency Branding profile")
def save_agency_branding_endpoint(branding: AgencyBranding) -> AgencyBranding:
    """Updates and saves the white-label agency branding profile."""
    return _save_branding(branding)

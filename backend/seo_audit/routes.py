"""
FastAPI Routes for On-Demand Local SEO Audits.
Exposes POST /api/seo-audit and POST /api/seo-audit/bulk endpoints.
"""

import json
from typing import List
from fastapi import APIRouter, HTTPException, status

from backend.seo_audit.models import AuditInput, SEOReport
from backend.seo_audit.auditor import audit_single_business, audit_bulk_businesses

router = APIRouter(prefix="", tags=["SEO Audit"])


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
        except Exception:
            pass

    return report


@router.post("/seo-audit/bulk", response_model=List[SEOReport], summary="Audit multiple business websites in bulk")
def seo_audit_bulk_endpoint(payload: List[AuditInput]) -> List[SEOReport]:
    """Performs concurrent on-demand Local SEO audits for a batch of business websites."""
    if not payload:
        return []
    return audit_bulk_businesses(payload)

"""
FastAPI Routes for On-Demand Local SEO Audits.
Exposes POST /api/seo-audit and POST /api/seo-audit/bulk endpoints.
"""

from typing import List
from fastapi import APIRouter, HTTPException, status

from seo_audit.models import AuditInput, SEOReport
from seo_audit.auditor import audit_single_business, audit_bulk_businesses

router = APIRouter(prefix="", tags=["SEO Audit"])


@router.post("/seo-audit", response_model=SEOReport, summary="Audit a single business website")
def seo_audit_endpoint(payload: AuditInput) -> SEOReport:
    """Performs an on-demand 11-check Local SEO audit for a single business website."""
    if not payload.url or not payload.url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid website URL is required for SEO audit.",
        )
    return audit_single_business(payload)


@router.post("/seo-audit/bulk", response_model=List[SEOReport], summary="Audit multiple business websites in bulk")
def seo_audit_bulk_endpoint(payload: List[AuditInput]) -> List[SEOReport]:
    """Performs concurrent on-demand Local SEO audits for a batch of business websites."""
    if not payload:
        return []
    return audit_bulk_businesses(payload)

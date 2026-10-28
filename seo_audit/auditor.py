"""
Main Orchestrator for On-Demand Local SEO Audits.
Handles per-business error isolation, concurrency, logging, and XLSX row formatting.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict

from seo_audit.models import AuditInput, SEOReport, AuditIssue
from seo_audit.fetcher import fetch_page_for_audit, FetchResult
from seo_audit.analyzer import run_all_seo_checks
from seo_audit.scorer import calculate_seo_opportunity_score

logger = logging.getLogger("seo_audit")

# The exact 9 columns appended to XLSX lead spreadsheets
SEO_XLSX_COLUMNS = [
    "Website Speed",
    "Mobile Friendly",
    "Title Tag Status",
    "Meta Description Status",
    "H1 Status",
    "Local Keyword Status",
    "Schema Status",
    "NAP Status",
    "SEO Opportunity Score",
]


def audit_single_business(
    business: AuditInput,
    cached_html: Optional[str] = None,
) -> SEOReport:
    """
    Audits a single business website safely with full exception isolation.
    Reuses cached HTML if available, otherwise performs a lightweight fetch.
    """
    url = (business.url or "").strip()
    if not url:
        return SEOReport(
            url="",
            opportunity_score=None,
            load_time_seconds=None,
            issues={},
            xlsx_row_data={col: "No Website" for col in SEO_XLSX_COLUMNS},
            error_message="Business has no website URL provided.",
        )

    try:
        logger.info("Auditing SEO for business '%s' at %s", business.business_name or "Unknown", url)

        if cached_html:
            fetch_res = FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                elapsed_seconds=0.0,
                html=cached_html,
                headers={},
            )
        else:
            fetch_res = fetch_page_for_audit(url)

        issues = run_all_seo_checks(business, fetch_res)
        score = calculate_seo_opportunity_score(issues)

        # Build standardized 9-column XLSX dictionary
        speed_summary = issues.get("website_speed").xlsx_summary if issues.get("website_speed") else "Unverified"
        mobile_summary = issues.get("mobile_friendly").xlsx_summary if issues.get("mobile_friendly") else "Unverified"
        title_summary = issues.get("title_tag").xlsx_summary if issues.get("title_tag") else "Unverified"
        meta_summary = issues.get("meta_description").xlsx_summary if issues.get("meta_description") else "Unverified"
        h1_summary = issues.get("h1_status").xlsx_summary if issues.get("h1_status") else "Unverified"
        local_kw_summary = issues.get("local_keywords").xlsx_summary if issues.get("local_keywords") else "Unverified"
        schema_summary = issues.get("schema_markup").xlsx_summary if issues.get("schema_markup") else "Unverified"
        nap_summary = issues.get("nap_consistency").xlsx_summary if issues.get("nap_consistency") else "Unverified"
        score_summary = f"{score}/100" if score is not None else "N/A"

        xlsx_row = {
            "Website Speed": speed_summary,
            "Mobile Friendly": mobile_summary,
            "Title Tag Status": title_summary,
            "Meta Description Status": meta_summary,
            "H1 Status": h1_summary,
            "Local Keyword Status": local_kw_summary,
            "Schema Status": schema_summary,
            "NAP Status": nap_summary,
            "SEO Opportunity Score": score_summary,
        }

        return SEOReport(
            url=url,
            opportunity_score=score,
            load_time_seconds=fetch_res.elapsed_seconds,
            issues=issues,
            xlsx_row_data=xlsx_row,
            error_message=fetch_res.error_message,
        )

    except Exception as exc:
        logger.exception("Unexpected error auditing %s: %s", url, exc)
        return SEOReport(
            url=url,
            opportunity_score=None,
            load_time_seconds=None,
            issues={},
            xlsx_row_data={col: "Error" for col in SEO_XLSX_COLUMNS},
            error_message=str(exc),
        )


def audit_bulk_businesses(
    businesses: List[AuditInput],
    max_workers: int = 5,
) -> List[SEOReport]:
    """
    Audits multiple businesses concurrently with thread pooling while
    preserving the exact input order.
    """
    if not businesses:
        return []

    # ThreadPoolExecutor to run audits concurrently
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        reports = list(executor.map(audit_single_business, businesses))

    return reports

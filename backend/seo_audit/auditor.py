"""
Main Orchestrator for On-Demand Local SEO Audits.
Handles per-business error isolation, concurrency, root-domain caching,
logging, and 21-column XLSX row formatting.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict
from urllib.parse import urlparse

from backend.seo_audit.models import AuditInput, SEOReport, AuditIssue
from backend.seo_audit.fetcher import fetch_page_for_audit, FetchResult, check_robots_and_sitemap
from backend.seo_audit.analyzer import run_all_seo_checks
from backend.seo_audit.scorer import calculate_seo_health_and_pitch, calculate_seo_opportunity_score
from backend.seo_audit.icebreaker import generate_icebreaker_hook
from backend.seo_audit.config import SEO_XLSX_COLUMNS

logger = logging.getLogger("seo_audit")

# Thread-safe in-memory cache for root domain audits
_domain_audit_cache: Dict[str, SEOReport] = {}
_cache_lock = threading.Lock()


def clear_domain_cache() -> None:
    """Clears the root domain audit cache (useful for testing or cache resets)."""
    with _cache_lock:
        _domain_audit_cache.clear()


def extract_root_domain(url: Optional[str]) -> str:
    """Extracts lowercase clean hostname/netloc without www for domain deduplication."""
    if not url:
        return ""
    clean = url.strip().lower()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parsed = urlparse(clean)
        domain = parsed.netloc.replace("www.", "").strip()
        # Remove trailing port if any
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain
    except Exception:
        return clean


def build_no_website_report(business: AuditInput) -> SEOReport:
    """Generates an agency-grade audit report for a business with no website."""
    hook = generate_icebreaker_hook(business, {}, has_website=False)
    pitch_priority = "Critical Pitch (No Website)"

    xlsx_row = {col: "No Website" for col in SEO_XLSX_COLUMNS}
    xlsx_row["Final URL & HTTP Status"] = "No Website"
    xlsx_row["SSL & HTTPS Redirect Status"] = "No Website"
    xlsx_row["Server Response (TTFB)"] = "No Website"
    xlsx_row["SEO Health Score"] = "N/A"
    xlsx_row["Lead Pitch Priority"] = pitch_priority
    xlsx_row["AI / Dynamic Icebreaker Hook"] = hook

    # Legacy keys for backward compatibility
    xlsx_row["Website Speed"] = "No Website"
    xlsx_row["Mobile Friendly"] = "No Website"
    xlsx_row["SEO Opportunity Score"] = "N/A"

    return SEOReport(
        url="",
        final_url="",
        http_status_summary="No Website",
        ssl_status="No Website",
        server_response_ttfb="No Website",
        ttfb_seconds=None,
        seo_health_score=None,
        opportunity_score=None,
        lead_pitch_priority=pitch_priority,
        extracted_title="",
        extracted_h1="",
        word_count=0,
        icebreaker_hook=hook,
        load_time_seconds=None,
        issues={},
        xlsx_row_data=xlsx_row,
        error_message="Business has no website URL provided.",
    )


def audit_single_business(
    business: AuditInput,
    cached_html: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    use_cache: bool = True,
) -> SEOReport:
    """
    Audits a single business website safely with full exception isolation.
    Uses root-domain deduplication cache to ensure practitioner listings sharing a domain
    receive identical, non-conflicting metrics instantly.
    """
    url = (business.url or "").strip()
    if not url:
        return build_no_website_report(business)

    root_domain = extract_root_domain(url)

    # 1. Check Root Domain Cache
    if use_cache and root_domain:
        with _cache_lock:
            cached_rep = _domain_audit_cache.get(root_domain)
        if cached_rep:
            logger.info("Reusing cached SEO audit for domain '%s' (Business: %s)", root_domain, business.business_name or "Unknown")
            # Personalize the icebreaker hook for this specific business name/reviews
            custom_hook = generate_icebreaker_hook(
                business,
                cached_rep.issues,
                final_url=cached_rep.final_url,
                extracted_title=cached_rep.extracted_title,
                word_count=cached_rep.word_count,
                has_website=True,
                score=cached_rep.seo_health_score,
                is_js_rendered=cached_rep.is_js_rendered,
            )
            # Create a shallow copy with personalized hook
            new_row_data = dict(cached_rep.xlsx_row_data)
            new_row_data["AI / Dynamic Icebreaker Hook"] = custom_hook
            return cached_rep.model_copy(
                update={
                    "icebreaker_hook": custom_hook,
                    "xlsx_row_data": new_row_data,
                }
            )

    try:
        logger.info("Auditing SEO for business '%s' at %s", business.business_name or "Unknown", url)

        if cached_html is not None:
            if cached_html:
                is_https = url.startswith("https://")
                has_robots, has_sitemap = check_robots_and_sitemap(url, timeout=2.0)
                fetch_res = FetchResult(
                    url=url,
                    final_url=url,
                    status_code=200,
                    initial_status_code=200,
                    elapsed_seconds=elapsed_seconds if elapsed_seconds is not None else 0.05,
                    html=cached_html,
                    headers={},
                    has_robots=has_robots,
                    has_sitemap=has_sitemap,
                )
            else:
                fetch_res = FetchResult(
                    url=url,
                    final_url=url,
                    status_code=None,
                    initial_status_code=None,
                    elapsed_seconds=elapsed_seconds if elapsed_seconds is not None else 0.0,
                    html="",
                    headers={},
                    error_message="Website unreachable or timed out.",
                )
        else:
            fetch_res = fetch_page_for_audit(url)

        check_res = run_all_seo_checks(business, fetch_res)
        issues = check_res["issues"]
        xlsx_row = check_res["xlsx_row"]
        extracted_title = check_res.get("extracted_title", "")
        extracted_h1 = check_res.get("extracted_h1", "")
        word_count = check_res.get("word_count", 0)
        is_https = check_res.get("is_https", False)
        is_js_rendered = bool(check_res.get("is_js_rendered", False))
        audited_page_type = check_res.get("audited_page_type", "homepage")

        # 2. Compute Health Score & Pitch Priority
        health_score, pitch_priority = calculate_seo_health_and_pitch(
            issues=issues,
            has_website=True,
            is_https=is_https,
            business_rating=business.rating,
            reviews_count=business.reviews_count,
            is_js_rendered=is_js_rendered,
        )

        # 3. Generate Personalized Icebreaker Hook
        icebreaker = generate_icebreaker_hook(
            business=business,
            issues=issues,
            final_url=fetch_res.final_url or url,
            extracted_title=extracted_title,
            word_count=word_count,
            has_website=True,
            score=health_score,
            is_js_rendered=is_js_rendered,
        )

        # 4. Fill in the Scoring & Outreach Columns
        if is_js_rendered:
            xlsx_row["SEO Health Score"] = "N/A (JS-Rendered)"
            xlsx_row["SEO Opportunity Score"] = "N/A (JS-Rendered)"
            opp_score = None
        elif health_score is not None:
            xlsx_row["SEO Health Score"] = health_score
            opp_score = 100 - health_score
            xlsx_row["SEO Opportunity Score"] = opp_score
        else:
            default_score_str = "Not Tested" if pitch_priority == "Not Tested" else "N/A"
            xlsx_row["SEO Health Score"] = default_score_str
            xlsx_row["SEO Opportunity Score"] = default_score_str
            opp_score = None

        xlsx_row["Lead Pitch Priority"] = pitch_priority
        xlsx_row["AI / Dynamic Icebreaker Hook"] = icebreaker

        # Populate legacy keys for backward compatibility
        xlsx_row["Website Speed"] = xlsx_row.get("Server Response (TTFB)", "Unverified")
        xlsx_row["Mobile Friendly"] = xlsx_row.get("Mobile Friendly", "Pass: Viewport Meta Tag Present")

        final_url_str = fetch_res.final_url or url
        http_summary = xlsx_row.get("Final URL & HTTP Status", "")
        ssl_summary = xlsx_row.get("SSL & HTTPS Redirect Status", "")
        ttfb_summary = xlsx_row.get("Server Response (TTFB)", "")

        report = SEOReport(
            url=url,
            final_url=final_url_str,
            http_status_summary=http_summary,
            ssl_status=ssl_summary,
            server_response_ttfb=ttfb_summary,
            ttfb_seconds=fetch_res.elapsed_seconds,
            seo_health_score=health_score,
            opportunity_score=opp_score,
            lead_pitch_priority=pitch_priority,
            extracted_title=extracted_title,
            extracted_h1=extracted_h1,
            word_count=word_count,
            icebreaker_hook=icebreaker,
            load_time_seconds=fetch_res.elapsed_seconds,
            is_js_rendered=is_js_rendered,
            audited_page_type=audited_page_type,
            issues=issues,
            xlsx_row_data=xlsx_row,
            error_message=fetch_res.error_message,
        )

        # Store in root domain cache
        if use_cache and root_domain:
            with _cache_lock:
                _domain_audit_cache[root_domain] = report

        return report

    except Exception as exc:
        logger.exception("Unexpected error auditing %s: %s", url, exc)
        err_row = {col: "Not Tested" for col in SEO_XLSX_COLUMNS}
        err_row["SEO Health Score"] = "Not Tested"
        err_row["Lead Pitch Priority"] = "Not Tested"
        err_row["AI / Dynamic Icebreaker Hook"] = f"Could not audit website for {business.business_name or 'lead'}."
        # Legacy
        err_row["Website Speed"] = "Not Tested"
        err_row["Mobile Friendly"] = "Not Tested"
        err_row["SEO Opportunity Score"] = "Not Tested"

        return SEOReport(
            url=url,
            final_url=url,
            http_status_summary="Error",
            ssl_status="Error",
            server_response_ttfb="Error",
            ttfb_seconds=None,
            seo_health_score=None,
            opportunity_score=None,
            lead_pitch_priority="Critical Pitch",
            extracted_title="",
            extracted_h1="",
            word_count=0,
            icebreaker_hook=err_row["AI / Dynamic Icebreaker Hook"],
            load_time_seconds=None,
            issues={},
            xlsx_row_data=err_row,
            error_message=str(exc),
        )


def infer_default_city_from_inputs(businesses: List[AuditInput]) -> Optional[str]:
    """Infers default search city by taking the most frequent city (mode) from non-empty addresses."""
    from collections import Counter
    city_counts = Counter()
    for b in businesses:
        actual = b.get_actual_city()
        if actual:
            city_counts[actual] += 1
        elif b.target_city and b.target_city.strip() and b.target_city.lower() not in ("downtown", "midtown", "uptown"):
            city_counts[b.target_city.strip()] += 1
        elif b.city and b.city.strip() and b.city.lower() not in ("downtown", "midtown", "uptown"):
            city_counts[b.city.strip()] += 1

    if city_counts:
        return city_counts.most_common(1)[0][0]
    return None


def audit_bulk_businesses(
    businesses: List[AuditInput],
    max_workers: int = 10,
) -> List[SEOReport]:
    """
    Audits multiple businesses concurrently with thread pooling while
    preserving the exact input order.
    Automatically infers default_search_city (mode) for Service Area Businesses where Full Address is empty.
    """
    if not businesses:
        return []

    default_city = infer_default_city_from_inputs(businesses)
    if default_city:
        for b in businesses:
            if not b.get_actual_city() and (not b.target_city or not b.target_city.strip()):
                b.target_city = default_city
            if not b.city or not b.city.strip():
                b.city = default_city

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        reports = list(executor.map(audit_single_business, businesses))

    return reports


# Backward-compatible alias
bulk_audit_businesses = audit_bulk_businesses

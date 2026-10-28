"""
Automated Personalized Cold Outreach Hook Engine (Section 5, Fix #7).
Generates an agency-grade, personalized 1-sentence cold email opener
based on 100% verified hard evidence in strict priority order.
"""

from typing import Dict, Any, Optional
from backend.seo_audit.models import AuditInput, AuditIssue


def truncate_preview(text: str, max_len: int = 30) -> str:
    """Helper to clean preview strings without runaway ellipsis."""
    clean = " ".join((text or "").split()).strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


def generate_icebreaker_hook(
    business: AuditInput,
    issues: Dict[str, AuditIssue],
    final_url: str = "",
    extracted_title: str = "",
    word_count: int = 0,
    has_website: bool = True,
) -> str:
    """
    Generates a personalized, 1-sentence cold email opener according to Fix #7 rules:
    - Rating guardrail: only cite strong reputation if rating >= 4.5 and reviews_count >= 10.
    - Never outputs literal 'in your area' inside quotes; uses resolved actual_city.
    - Strict priority order by 100% verified hard evidence.
    """
    biz_name = (business.business_name or "your business").strip()
    category = (business.category or "business").strip()

    # Resolve primary city safely (never evaluate against empty string or output awkward "your area")
    city = business.get_primary_city() if hasattr(business, "get_primary_city") else (business.city or "")
    city_clean = city.strip()
    city_phrase = f"in {city_clean}" if city_clean else "locally"

    # Rating Guardrail: only mention ratings if rating >= 4.5 and reviews_count >= 10
    rating = business.rating
    reviews_count = business.reviews_count or 0
    has_strong_reviews = bool(rating is not None and rating >= 4.5 and reviews_count >= 10)

    # -------------------------------------------------------------------------
    # Priority 0: No Active Website
    # -------------------------------------------------------------------------
    if not has_website or not business.url:
        if has_strong_reviews:
            return (
                f"Noticed {biz_name} has a strong {rating}★ reputation ({reviews_count} reviews) on Google Maps {city_phrase}, "
                f"but no active website, meaning high-intent local searchers cannot view your services or book online."
            )
        return (
            f"Checked out {biz_name} {city_phrase} and noticed you have no active website listed on Google Maps, "
            f"meaning high-intent local searchers cannot view your services or book online."
        )

    # -------------------------------------------------------------------------
    # Priority 1: Critical noindex tag (Blocks Google Indexing)
    # -------------------------------------------------------------------------
    meta_robots = issues.get("meta_robots")
    if meta_robots and meta_robots.audit_status == "Fail" and "noindex" in meta_robots.evidence.lower():
        return (
            f"Urgent: While analyzing {biz_name}'s website, I detected a 'noindex' tag on your homepage "
            f"that explicitly blocks Google from displaying your business in search results."
        )

    # -------------------------------------------------------------------------
    # Priority 2: Unencrypted HTTP / Missing SSL Redirect (Browser Security Warning)
    # -------------------------------------------------------------------------
    ssl_issue = issues.get("ssl_redirect")
    if ssl_issue and ssl_issue.audit_status == "Fail":
        if has_strong_reviews:
            return (
                f"Noticed {biz_name} ranks on Google Maps with a strong {rating}★ reputation ({reviews_count} reviews), "
                f"but your website loads on unencrypted HTTP without an SSL redirect, triggering browser 'Not Secure' warnings for visitors."
            )
        return (
            f"While checking {biz_name}'s website, I noticed your site loads on unencrypted HTTP without an SSL redirect, "
            f"which triggers browser 'Not Secure' warnings for visitors."
        )

    # -------------------------------------------------------------------------
    # Priority 3: Missing H1 Headline or Thin Content (< 300 words)
    # -------------------------------------------------------------------------
    h1_issue = issues.get("h1_status")
    word_issue = issues.get("word_count")
    if h1_issue and h1_issue.audit_status == "Fail":
        return (
            f"While auditing {biz_name}'s website {city_phrase}, I noticed your homepage has no primary <h1> headline tag, "
            f"making it harder for search engines to identify your core services."
        )
    if word_issue and word_issue.audit_status == "Fail" and 0 < word_count < 300:
        return (
            f"Noticed {biz_name}'s homepage contains only {word_count} words, which search engines often flag as "
            f"thin content, hurting your local pack rankings."
        )

    # -------------------------------------------------------------------------
    # Priority 4: Missing LocalBusiness Schema or Missing NAP Address
    # -------------------------------------------------------------------------
    schema_issue = issues.get("schema_markup")
    nap_issue = issues.get("nap_consistency")
    schema_missing = bool(schema_issue and schema_issue.audit_status in ("Fail", "Warning"))
    address_missing = bool(nap_issue and nap_issue.audit_status in ("Fail", "Warning") and "address" in nap_issue.evidence.lower())

    if schema_missing and address_missing:
        return (
            f"While checking {biz_name}'s site code, I noticed both your street address and {category} LocalBusiness "
            f"JSON-LD schema are missing from the homepage, making it harder for Google to verify your local entity."
        )
    if schema_missing and not address_missing:
        return (
            f"While checking {biz_name}'s site code, I noticed your homepage is missing {category} LocalBusiness "
            f"JSON-LD schema markup, which helps Google validate your local service authority."
        )
    if address_missing and not schema_missing:
        return (
            f"While checking {biz_name}'s site, I noticed your full street address isn't displayed in the homepage text "
            f"to match your Google Business Profile, weakening your local NAP consistency signals."
        )

    # -------------------------------------------------------------------------
    # Priority 5: Title / H1 Local Keyword Gap
    # -------------------------------------------------------------------------
    kw_issue = issues.get("local_keywords")
    title_issue = issues.get("title_tag")
    if kw_issue and kw_issue.audit_status in ("Fail", "Warning") and city_clean:
        title_snippet = truncate_preview(extracted_title, max_len=30)
        return (
            f"Saw {biz_name}'s profile {city_phrase}, though your homepage title tag is currently '{title_snippet}' "
            f"and is missing '{category} in {city_clean}', costing you local organic traffic."
        )
    if title_issue and title_issue.audit_status == "Fail" and city_clean:
        title_snippet = truncate_preview(extracted_title, max_len=30)
        return (
            f"Saw {biz_name}'s presence {city_phrase}, though your homepage title tag is currently '{title_snippet}' "
            f"and is missing '{category} in {city_clean}', costing you local organic traffic."
        )

    # -------------------------------------------------------------------------
    # Default: Professional Senior Outreach Opener
    # -------------------------------------------------------------------------
    if has_strong_reviews:
        return (
            f"Noticed {biz_name}'s strong {rating}★ presence {city_phrase} and identified several high-ROI technical optimizations "
            f"to improve your Google Local Pack rankings."
        )
    return (
        f"Audited {biz_name}'s online presence {city_phrase} and identified several high-ROI technical optimizations "
        f"to improve your Google Local Pack rankings."
    )

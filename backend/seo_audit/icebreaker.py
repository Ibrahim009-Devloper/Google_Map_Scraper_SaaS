"""
Automated Personalized Cold Outreach Hook Engine (Section 5, Fix #7).
Generates an agency-grade, personalized 1-sentence cold email opener
based on 100% verified hard evidence in strict priority order.
"""

import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from backend.seo_audit.models import AuditInput, AuditIssue


def clean_business_name_for_copy(name: Optional[str], possessive: bool = False) -> str:
    """
    Cleans business name for cold outreach copy:
    - Strips everything after ':' or '|'.
    - Strips legal suffixes (Inc., LLC, Corp, Co., Ltd, LLP, PLC).
    - Fixes English possessives: if cleaned name ends in 's', use "'" instead of "'s"
      (e.g. "Contractors'" instead of "Contractors's").
    """
    if not name or not name.strip():
        return "your business's" if possessive else "your business"

    cleaned = name.strip()
    # 1. Strip everything after : or |
    cleaned = re.split(r"[:|]", cleaned)[0].strip()

    # 2. Strip legal suffixes from end
    # Note: Strip ", Inc.", ", LLC", ", Corp.", ", Co.", " Inc.", " LLC", " Corp.", " Co." (with dot or comma)
    legal_pattern = r"(?i)(,\s*(inc\.?|llc|l\.l\.c\.?|corp\.?|co\.|ltd\.?|llp\.?|plc\.?)\s*$|\s+(inc\.|llc|l\.l\.c\.|corp\.|co\.|ltd\.|llp|plc)\s*$)"
    while re.search(legal_pattern, cleaned):
        cleaned = re.sub(legal_pattern, "", cleaned).strip()

    if not cleaned:
        cleaned = name.strip()

    if possessive:
        if cleaned.lower().endswith("s"):
            return f"{cleaned}'"
        return f"{cleaned}'s"

    return cleaned


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
    score: Optional[int] = None,
    is_js_rendered: bool = False,
) -> str:
    """
    Generates a personalized, 1-sentence cold email opener based on verified evidence:
    - Clean business name and correct English possessives.
    - Landing page vs homepage normalization.
    - Zero city leaks if GBP address is empty.
    - Strict branching for NAP (phone only, address only, both).
    - High-priority hook for cross-domain canonicals.
    - Healthy site hook if score >= 90 and no high/critical issues.
    """
    biz_clean = clean_business_name_for_copy(business.business_name, possessive=False)
    biz_possessive = clean_business_name_for_copy(business.business_name, possessive=True)
    category = (business.category or "business").strip()

    # Homepage vs Landing Page Normalization (Objective 3)
    parsed_target = urlparse(final_url or business.url or "")
    is_subpage = bool(parsed_target.path and parsed_target.path not in ("", "/"))
    page_label = "landing page" if is_subpage else "homepage"

    # Fix City State Leak: If Full Address is empty, never reuse target_city or hallucinate city (Objective 5)
    has_address = bool(business.address and business.address.strip())
    if not has_address:
        city_clean = ""
        city_phrase = ""
    else:
        city = business.get_primary_city() if hasattr(business, "get_primary_city") else (business.city or "")
        city_clean = city.strip()
        city_phrase = f"in {city_clean}" if city_clean else ""

    city_phrase_spaced = f" {city_phrase}" if city_phrase else ""

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
                f"Noticed {biz_clean} has a strong {rating}★ reputation ({reviews_count} reviews) on Google Maps{city_phrase_spaced}, "
                f"but no active website, meaning high-intent local searchers cannot view your services or book online."
            )
        return (
            f"Checked out {biz_clean}{city_phrase_spaced} and noticed you have no active website listed on Google Maps, "
            f"meaning high-intent local searchers cannot view your services or book online."
        )

    # -------------------------------------------------------------------------
    # Priority 1: Critical noindex tag (Blocks Google Indexing)
    # -------------------------------------------------------------------------
    meta_robots = issues.get("meta_robots")
    if meta_robots and meta_robots.audit_status == "Fail" and "noindex" in meta_robots.evidence.lower():
        return (
            f"Urgent: While analyzing {biz_possessive} website, I detected a 'noindex' tag on your {page_label} "
            f"that explicitly blocks Google from displaying your business in search results."
        )

    # -------------------------------------------------------------------------
    # Priority 1.5: Critical Canonical Points to Different Domain (Objective 4)
    # -------------------------------------------------------------------------
    canon_issue = issues.get("canonical_tag")
    if canon_issue and canon_issue.audit_status == "Fail" and (
        "different domain" in canon_issue.xlsx_summary.lower() or "external domain" in canon_issue.evidence.lower()
    ):
        return (
            f"Urgent: While analyzing {biz_possessive} website, I noticed your canonical tag points to an external domain, "
            f"which redirects your search ranking equity away from your site."
        )

    # -------------------------------------------------------------------------
    # Priority 2: Unencrypted HTTP / Missing SSL Redirect (Browser Security Warning)
    # -------------------------------------------------------------------------
    ssl_issue = issues.get("ssl_redirect")
    if ssl_issue and ssl_issue.audit_status == "Fail":
        if has_strong_reviews:
            return (
                f"Noticed {biz_clean} ranks on Google Maps with a strong {rating}★ reputation ({reviews_count} reviews), "
                f"but your website loads on unencrypted HTTP without an SSL redirect, triggering browser 'Not Secure' warnings for visitors."
            )
        return (
            f"While checking {biz_possessive} website, I noticed your site loads on unencrypted HTTP without an SSL redirect, "
            f"which triggers browser 'Not Secure' warnings for visitors."
        )

    # -------------------------------------------------------------------------
    # JS/SPA Shell Architecture Hook (Objective 1)
    # -------------------------------------------------------------------------
    if is_js_rendered:
        return (
            f"Noticed {biz_clean}'s website uses a client-side JavaScript architecture ({final_url or 'site'}), "
            f"which requires specialized SEO rendering to ensure search engines index all your dynamic content."
        )

    # -------------------------------------------------------------------------
    # Priority 3: Missing H1 Headline or Thin Content (< 300 words)
    # -------------------------------------------------------------------------
    h1_issue = issues.get("h1_status")
    word_issue = issues.get("word_count")
    if h1_issue and h1_issue.audit_status == "Fail":
        return (
            f"While auditing {biz_possessive} website{city_phrase_spaced}, I noticed your {page_label} has no primary <h1> headline tag, "
            f"making it harder for search engines to identify your core services."
        )
    if word_issue and word_issue.audit_status == "Fail" and 0 < word_count < 300:
        return (
            f"Noticed {biz_possessive} {page_label} contains only {word_count} words, which search engines often flag as "
            f"thin content, hurting your local pack rankings."
        )

    # -------------------------------------------------------------------------
    # Priority 4: Missing LocalBusiness Schema or Missing NAP
    # -------------------------------------------------------------------------
    schema_issue = issues.get("schema_markup")
    nap_issue = issues.get("nap_consistency")
    schema_missing = bool(schema_issue and schema_issue.audit_status in ("Fail", "Warning"))

    address_missing = False
    phone_missing = False
    if nap_issue and nap_issue.audit_status in ("Fail", "Warning"):
        ev_all = f"{nap_issue.xlsx_summary} {nap_issue.evidence}".lower()
        if "both" in ev_all or "neither" in ev_all or "phone & street address missing" in ev_all:
            address_missing = True
            phone_missing = True
        else:
            if "address missing" in ev_all or "street address missing" in ev_all:
                address_missing = True
            if "phone missing" in ev_all or "gbp phone missing" in ev_all:
                phone_missing = True
            # Fallback for generic phrasing if neither specific matched
            if not address_missing and not phone_missing:
                if "address" in ev_all and "phone" in ev_all:
                    address_missing = True
                    phone_missing = True
                elif "address" in ev_all:
                    address_missing = True
                elif "phone" in ev_all:
                    phone_missing = True

    if schema_missing and address_missing:
        return (
            f"While checking {biz_possessive} site code, I noticed both your street address and {category} LocalBusiness "
            f"JSON-LD schema are missing from the {page_label}, making it harder for Google to verify your local entity."
        )

    if schema_missing and phone_missing and not address_missing:
        return (
            f"While checking {biz_possessive} site code, I noticed both your contact phone number and {category} LocalBusiness "
            f"JSON-LD schema are missing from the {page_label}, making it harder for Google to verify your local entity."
        )

    if schema_missing and not address_missing and not phone_missing:
        return (
            f"While checking {biz_possessive} site code, I noticed your {page_label} is missing {category} LocalBusiness "
            f"JSON-LD schema markup, which helps Google validate your local service authority."
        )

    # Strict NAP branching when schema is present
    if address_missing and phone_missing:
        return (
            f"While checking {biz_possessive} site, I noticed both your street address and Google Business Profile "
            f"phone number are missing from the {page_label} text, weakening your local NAP verification."
        )
    if phone_missing and not address_missing:
        return (
            f"While checking {biz_possessive} website{city_phrase_spaced}, I noticed your Google Business Profile phone number "
            f"isn't displayed on the {page_label}, making it harder for local searchers to call directly."
        )
    if address_missing and not phone_missing:
        return (
            f"While checking {biz_possessive} site, I noticed your full street address isn't displayed in the {page_label} text "
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
            f"Saw {biz_clean}'s profile{city_phrase_spaced}, though your {page_label} title tag is currently '{title_snippet}' "
            f"and is missing '{category} in {city_clean}', costing you local organic traffic."
        )
    if title_issue and title_issue.audit_status == "Fail" and city_clean:
        title_snippet = truncate_preview(extracted_title, max_len=30)
        return (
            f"Saw {biz_clean}'s presence{city_phrase_spaced}, though your {page_label} title tag is currently '{title_snippet}' "
            f"and is missing '{category} in {city_clean}', costing you local organic traffic."
        )

    # -------------------------------------------------------------------------
    # Healthy Site Guardrail (Objective 4)
    # -------------------------------------------------------------------------
    has_critical_or_high = any(
        issue.priority in ("Critical", "High") or issue.severity in ("Critical", "High")
        for issue in issues.values()
        if issue.audit_status in ("Fail", "Warning")
    )
    if score is not None and score >= 90 and not has_critical_or_high:
        return "Site is well-optimized — skip technical pitch or use a non-SEO angle."

    # -------------------------------------------------------------------------
    # Default: Professional Senior Outreach Opener
    # -------------------------------------------------------------------------
    if has_strong_reviews:
        return (
            f"Noticed {biz_clean}'s strong {rating}★ presence{city_phrase_spaced} and identified several high-ROI technical optimizations "
            f"to improve your Google Local Pack rankings."
        )
    return (
        f"Audited {biz_clean}'s online presence{city_phrase_spaced} and identified several high-ROI technical optimizations "
        f"to improve your Google Local Pack rankings."
    )

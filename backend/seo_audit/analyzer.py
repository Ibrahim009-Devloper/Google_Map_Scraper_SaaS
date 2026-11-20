"""
Senior Technical SEO & Local Pack Check Engines (Section 3 & 4).
Evaluates on-page, crawlability, technical foundation, and Local Pack signals
producing standardized Senior SEO Expert Output: Severity + Technical Evidence + SEO Impact.
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from backend.seo_audit.models import AuditIssue, AuditInput
from backend.seo_audit.fetcher import FetchResult
from backend.seo_audit.config import (
    TTFB_WARNING_SEC,
    TTFB_HIGH_SEC,
    SEO_SLOW_LOAD_THRESHOLD,
    SEO_MODERATE_LOAD_THRESHOLD,
)

GENERIC_TITLES = {"home", "welcome", "untitled", "homepage", "index", "default"}

# Stopwords for category matching (stop matching on generic terms like contractor, company)
GENERIC_CATEGORY_STOPWORDS = {
    "contractor", "contractors", "company", "services", "service",
    "inc", "group", "llc", "corp", "corporation", "ltd", "agency",
    "solutions", "enterprise", "pros", "pro",
}

# Common Schema.org LocalBusiness types and subtypes
LOCAL_BUSINESS_TYPES = {
    "localbusiness", "dentist", "plumber", "roofingcontractor", "electrician",
    "hvacbusiness", "legalservice", "attorney", "notary", "restaurant",
    "foodestablishment", "bakery", "barorpub", "cafeorcoffeeshop", "medicalbusiness",
    "physician", "pharmacy", "hospital", "autorepair", "autodealer", "automotivebusiness",
    "realestateagent", "financialservice", "accountingbusiness", "bankorcreditunion",
    "insuranceagency", "healthandbeautybusiness", "beautysalon", "hairsalon", "dayspa",
    "homeandconstructionbusiness", "generalservice", "professionalservice", "store",
    "grocerystore", "clothingstore", "lodgingbusiness", "hotel", "motel", "childcare",
    "drycleaningorlaundry", "emergencyservice", "employmentagency", "entertainmentbusiness",
    "recyclecenter", "selfstorage", "touristinformationcenter", "travelagency", "veterinarycare",
}


def normalize_phone_digits(phone: Optional[str]) -> str:
    """Extracts only digits from a phone string."""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def clean_words(text: str) -> List[str]:
    """Tokenizes text into lowercased alphanumeric words."""
    return [w.lower() for w in re.findall(r"[A-Za-z0-9]+", text)]


def truncate_preview(text: str, max_len: int = 35) -> str:
    """Normalizes whitespace and appends ellipsis only if string exceeds max_len (Fix #6)."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


def is_js_spa_shell(soup: BeautifulSoup, word_count: int) -> bool:
    """
    Detects client-side rendered (CSR/SPA) shells where static HTML
    lacks server-rendered DOM nodes (e.g. React/Vue/Angular/Next.js).
    Criteria:
    - visible word count < 30
    - AND (mount point #root, #app, #__next, etc. OR noscript JS warning OR empty body with script bundles)
    """
    if not soup or word_count >= 30:
        return False

    # 1. Mount point IDs or elements common to SPA frameworks
    for mount_id in ("root", "app", "__next", "___gatsby", "main-content", "app-root"):
        if soup.find(id=mount_id) is not None or soup.find(mount_id) is not None:
            return True

    # 2. Noscript tags warning about required JavaScript
    for ns in soup.find_all("noscript"):
        ns_text = ns.get_text().lower()
        if any(phrase in ns_text for phrase in (
            "javascript", "enable js", "enable javascript",
            "requires javascript", "need to enable javascript", "turn on javascript"
        )):
            return True

    # 3. Empty or near-empty body combined with script tags
    scripts = soup.find_all("script")
    if word_count < 15 and len(scripts) >= 1:
        for s in scripts:
            src = (s.get("src") or "").lower()
            if any(b in src for b in ("main.", "bundle.", "chunk.", "app.", "index.", "runtime.", "vendor.", "react", "vue", "angular")):
                return True
        if len(scripts) >= 2:
            return True

    return False


# ============================================================================
# A. Crawlability & Technical Foundation
# ============================================================================

def check_final_url_and_status(fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 1: Final URL & HTTP Status Code."""
    code = fetch_res.status_code
    init_code = fetch_res.initial_status_code
    final_url = fetch_res.final_url or fetch_res.url

    if code is None:
        summary = "Failed to Connect"
        return AuditIssue(
            check_name="final_url_status",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=final_url,
            evidence=f"DNS or network failure: {fetch_res.error_message or 'Host unreachable'}",
            recommended_fix="Verify DNS A records and hosting server uptime.",
            xlsx_summary=summary,
        ), summary

    is_https = final_url.startswith("https://")
    proto_str = "HTTPS" if is_https else "HTTP"

    if init_code in (301, 302, 307, 308) and is_https:
        summary = f"{init_code} -> {code} OK (HTTPS)"
        return AuditIssue(
            check_name="final_url_status",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence_url=final_url,
            evidence=f"HTTP redirect followed successfully: {init_code} -> {code} OK ({final_url}).",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if not is_https and code == 200:
        summary = "Warning: HTTP 200 (No SSL Redirect)"
        return AuditIssue(
            check_name="final_url_status",
            audit_status="Warning",
            priority="High",
            severity="High",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Website loads directly on plain HTTP without redirecting to HTTPS ({final_url}).",
            recommended_fix="Enforce 301 redirection from HTTP to HTTPS in server configuration.",
            xlsx_summary=summary,
        ), summary

    if code >= 400:
        summary = f"Error: HTTP {code}"
        return AuditIssue(
            check_name="final_url_status",
            audit_status="Fail",
            priority="Critical",
            severity="Critical",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Web server returned HTTP error status {code} at {final_url}.",
            recommended_fix="Investigate web server routing or restore missing landing page.",
            xlsx_summary=summary,
        ), summary

    summary = f"{code} OK ({proto_str})"
    return AuditIssue(
        check_name="final_url_status",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence_url=final_url,
        evidence=f"Homepage returned clean status {code} OK on {proto_str}.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary


def check_ssl_redirect_status(fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 2: Decoupled SSL & HTTPS Redirect Status (Section 2.2)."""
    final_url = fetch_res.final_url or fetch_res.url
    is_https = final_url.startswith("https://") and not fetch_res.ssl_failed
    init_code = fetch_res.initial_status_code

    if fetch_res.status_code is None:
        summary = "Unreachable Host"
        return AuditIssue(
            check_name="ssl_redirect",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=final_url,
            evidence="Cannot test SSL because web server is unreachable.",
            recommended_fix="Ensure web server is online.",
            xlsx_summary=summary,
        ), summary

    if is_https:
        if init_code in (301, 302, 307, 308) or (fetch_res.url.startswith("http://") and final_url.startswith("https://")):
            summary = "Pass: HTTP Redirects Cleanly to HTTPS"
            evidence = f"HTTP request redirected cleanly to secure HTTPS: {init_code or 301} -> {final_url}."
        else:
            summary = "Pass: Valid SSL & Enforced HTTPS"
            evidence = f"Secure HTTPS connection verified on {final_url}."
        return AuditIssue(
            check_name="ssl_redirect",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence_url=final_url,
            evidence=evidence,
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    # Plain HTTP (200): Probe if HTTPS works with valid SSL
    https_works = bool(getattr(fetch_res, "https_probe_success", None) is True)
    if getattr(fetch_res, "https_probe_success", None) is None and not fetch_res.ssl_failed and fetch_res.status_code == 200:
        try:
            from urllib.parse import urlsplit
            from curl_cffi import requests as c_req
            p = urlsplit(final_url)
            https_target = f"https://{p.netloc}{p.path or '/'}"
            r = c_req.get(https_target, impersonate="chrome124", timeout=3.0, verify=True, allow_redirects=True)
            if r.status_code is not None:
                https_works = True
        except Exception:
            https_works = False

    if https_works:
        summary = "Warning: HTTPS Available but Missing 301 Auto-Redirect"
        return AuditIssue(
            check_name="ssl_redirect",
            audit_status="Warning",
            priority="Medium",
            severity="Medium",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Valid SSL certificate exists on HTTPS, but plain HTTP requests ({final_url}) do not automatically redirect (301) to HTTPS.",
            recommended_fix="Configure a 301 permanent redirect from HTTP to HTTPS in server configuration.",
            xlsx_summary=summary,
        ), summary

    summary = "Critical: Unencrypted HTTP (Missing 301 Redirect to HTTPS)"
    return AuditIssue(
        check_name="ssl_redirect",
        audit_status="Fail",
        priority="Critical",
        severity="Critical",
        confidence="High",
        evidence_url=final_url,
        evidence=f"Website is served over insecure HTTP ({final_url}) and HTTPS connection fails or lacks a valid SSL certificate.",
        recommended_fix="Install a valid SSL certificate and configure a strict 301 redirect to HTTPS.",
        xlsx_summary=summary,
    ), summary


def check_server_response_ttfb(fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 3: Honest Server Response Time (TTFB) in seconds (Section 2.4)."""
    elapsed = fetch_res.elapsed_seconds
    final_url = fetch_res.final_url or fetch_res.url

    if elapsed is None or fetch_res.status_code is None:
        summary = "N/A (Failed)"
        return AuditIssue(
            check_name="server_response_ttfb",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=final_url,
            evidence="Server did not respond within timeout window.",
            recommended_fix="Improve server uptime and network response.",
            xlsx_summary=summary,
        ), summary

    if elapsed <= 1.0:
        summary = f"TTFB: {elapsed}s (Fast Server Response - HTML Only)"
        return AuditIssue(
            check_name="server_response_ttfb",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Excellent server socket latency: {elapsed}s to first HTML byte.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if elapsed <= TTFB_WARNING_SEC:
        summary = f"Pass: TTFB {elapsed}s (Acceptable Server Latency <= {TTFB_WARNING_SEC}s)"
        return AuditIssue(
            check_name="server_response_ttfb",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Acceptable initial response time: {elapsed}s.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if elapsed <= TTFB_HIGH_SEC:
        summary = f"Warning: TTFB {elapsed}s (Moderate Server Delay > {TTFB_WARNING_SEC}s)"
        return AuditIssue(
            check_name="server_response_ttfb",
            audit_status="Warning",
            priority="Medium",
            severity="Medium",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Server took {elapsed}s to respond with initial HTML. Target is < {TTFB_WARNING_SEC}s.",
            recommended_fix="Enable server-side object caching (Redis/OPcache) and utilize a fast CDN (Cloudflare).",
            xlsx_summary=summary,
        ), summary

    summary = f"High Issue: TTFB {elapsed}s (Slow Server Response > {TTFB_HIGH_SEC}s)"
    return AuditIssue(
        check_name="server_response_ttfb",
        audit_status="Fail",
        priority="High",
        severity="High",
        confidence="High",
        evidence_url=final_url,
        evidence=f"Severely lagging TTFB: {elapsed}s (> {TTFB_HIGH_SEC}s). Major crawler and visitor bounce risk.",
        recommended_fix="Upgrade hosting infrastructure, enable page-level edge caching, and optimize backend DB queries.",
        xlsx_summary=summary,
    ), summary


def check_indexability_meta_robots(soup: BeautifulSoup, fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 4: Indexability & Meta Robots tags."""
    final_url = fetch_res.final_url or fetch_res.url
    if not soup:
        summary = "Unverified"
        return AuditIssue(
            check_name="meta_robots",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=final_url,
            evidence="Could not inspect robots meta tag.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    # Check HTTP header x-robots-tag
    noindex_detected = False
    source = ""

    x_robots = fetch_res.headers.get("x-robots-tag", "").lower()
    if "noindex" in x_robots:
        noindex_detected = True
        source = f"HTTP header X-Robots-Tag ('{x_robots}')"

    # Check meta robots tags in HTML
    if not noindex_detected and soup:
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"robots|googlebot", re.I)}):
            content = (meta.get("content") or "").lower()
            if "noindex" in content:
                noindex_detected = True
                source = f'<meta name="{meta.get("name")}" content="{content}">'
                break

    if noindex_detected:
        summary = "Critical: noindex Tag Present"
        return AuditIssue(
            check_name="meta_robots",
            audit_status="Fail",
            priority="Critical",
            severity="Critical",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Found {source}. Google is strictly instructed NOT to index this homepage.",
            recommended_fix="Immediately remove 'noindex' directive from meta tags or web server headers.",
            xlsx_summary=summary,
        ), summary

    summary = "Pass: Indexable"
    return AuditIssue(
        check_name="meta_robots",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence_url=final_url,
        evidence="No restrictive 'noindex' directives detected. Page is open for Google indexing.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary


def check_canonical_tag(soup: BeautifulSoup, fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 5: Canonical Tag Status."""
    final_url = fetch_res.final_url or fetch_res.url
    if not soup:
        summary = "Warning: Missing Canonical"
        return AuditIssue(
            check_name="canonical_tag",
            audit_status="Warning",
            priority="Low",
            severity="Low",
            confidence="Medium",
            evidence_url=final_url,
            evidence="Could not inspect canonical link tag.",
            recommended_fix="Add self-referencing canonical tag.",
            xlsx_summary=summary,
        ), summary

    canonical = soup.find("link", rel=re.compile(r"^canonical$", re.I))
    if not canonical or not canonical.get("href"):
        summary = "Warning: Missing Canonical"
        return AuditIssue(
            check_name="canonical_tag",
            audit_status="Warning",
            priority="Low",
            severity="Low",
            confidence="High",
            evidence_url=final_url,
            evidence="Homepage lacks a <link rel='canonical'> tag. May cause duplicate content dilution.",
            recommended_fix="Add a self-referencing canonical tag (<link rel='canonical' href='...'>) pointing to final HTTPS URL.",
            xlsx_summary=summary,
        ), summary

    from urllib.parse import urljoin
    raw_href = canonical.get("href", "").strip()
    abs_canonical = urljoin(final_url, raw_href)

    final_parsed = urlparse(final_url)
    canon_parsed = urlparse(abs_canonical)

    final_domain = final_parsed.netloc.replace("www.", "").lower().split(":")[0]
    canon_domain = canon_parsed.netloc.replace("www.", "").lower().split(":")[0]

    if canon_domain and final_domain and canon_domain != final_domain:
        summary = f"Critical: Points to Different Domain ({canon_domain})"
        return AuditIssue(
            check_name="canonical_tag",
            audit_status="Fail",
            priority="Critical",
            severity="Critical",
            confidence="High",
            evidence_url=final_url,
            evidence=f"Canonical tag points to external domain '{canon_domain}', depriving this site of ranking equity.",
            recommended_fix=f"Update canonical tag to point to internal homepage ({final_url}).",
            xlsx_summary=summary,
        ), summary

    summary = "Pass: Self-Referencing"
    return AuditIssue(
        check_name="canonical_tag",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence_url=final_url,
        evidence=f"Valid self-referencing canonical tag verified ({abs_canonical}).",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary


def check_robots_and_sitemap(fetch_res: FetchResult) -> Tuple[AuditIssue, str]:
    """Check 6: Robots.txt & XML Sitemap Availability (Fix #3)."""
    final_url = fetch_res.final_url or fetch_res.url
    has_robots = fetch_res.has_robots
    has_sitemap = fetch_res.has_sitemap

    if has_robots and has_sitemap:
        summary = "Pass: robots.txt & XML Sitemap Verified"
        return AuditIssue(
            check_name="robots_sitemap",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence_url=final_url,
            evidence="Both /robots.txt and XML sitemap verified accessible.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if has_robots and not has_sitemap:
        summary = "Warning: robots.txt Present, XML Sitemap Missing"
        return AuditIssue(
            check_name="robots_sitemap",
            audit_status="Warning",
            priority="Medium",
            severity="Medium",
            confidence="Medium",
            evidence_url=final_url,
            evidence="robots.txt is present, but no XML sitemap declaration or valid sitemap endpoint found.",
            recommended_fix="Generate an XML sitemap and declare 'Sitemap: https://yourdomain.com/sitemap.xml' inside robots.txt.",
            xlsx_summary=summary,
        ), summary

    if not has_robots and has_sitemap:
        summary = "Pass: XML Sitemap Verified (No robots.txt)"
        return AuditIssue(
            check_name="robots_sitemap",
            audit_status="Pass",
            priority="Low",
            severity="Low",
            confidence="High",
            evidence_url=final_url,
            evidence="XML sitemap exists, but /robots.txt is missing.",
            recommended_fix="Add a clean robots.txt at web root to manage search bot crawl budgets.",
            xlsx_summary=summary,
        ), summary

    summary = "High Issue: Both robots.txt & XML Sitemap Missing"
    return AuditIssue(
        check_name="robots_sitemap",
        audit_status="Fail",
        priority="High",
        severity="High",
        confidence="High",
        evidence_url=final_url,
        evidence="Neither /robots.txt nor an XML sitemap could be discovered on the website.",
        recommended_fix="Create a robots.txt file and submit an XML sitemap to Google Search Console.",
        xlsx_summary=summary,
    ), summary


# ============================================================================
# B. Raw Evidence Extraction
# ============================================================================

def extract_raw_title_and_status(
    soup: BeautifulSoup,
    city: Optional[str] = None,
    category: Optional[str] = None,
    audited_page_type: str = "homepage",
) -> Tuple[AuditIssue, str, str]:
    """Check 7 & 8: Extracted Title Text and Title Tag Status (Fix #6)."""
    page_name = audited_page_type.capitalize()
    if not soup:
        summary = "Critical On-Page: Missing <title> Tag"
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="Critical",
            severity="Critical",
            evidence=f"No HTML title tag found on {audited_page_type}.",
            recommended_fix=f"Add a descriptive <title> tag on {audited_page_type}.",
            xlsx_summary=summary,
        ), "", summary

    title_el = soup.find("title")
    raw_title = re.sub(r"\s+", " ", title_el.get_text(separator=" ", strip=True)).strip() if title_el else ""

    if not raw_title:
        summary = "Critical On-Page: Missing <title> Tag"
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="Critical",
            severity="Critical",
            evidence=f"<title> tag is missing or completely empty on {audited_page_type}.",
            recommended_fix=f"Add a descriptive title tag: e.g. '{category or 'Services'} in {city or 'City'} | Company Name'.",
            xlsx_summary=summary,
        ), "", summary

    t_len = len(raw_title)
    t_clean = raw_title.lower()
    preview = truncate_preview(raw_title, max_len=35)

    # Title Quality: Flag titles that are raw URLs or generic prefixes as High Issue
    is_raw_url = any(u in t_clean for u in ("www.", ".com", ".net", ".org", "http://", "https://"))
    is_generic = (
        t_clean in GENERIC_TITLES or
        any(t_clean.startswith(prefix) for prefix in ("home -", "home |", "home :", "welcome to", "untitled"))
    )

    if is_raw_url or is_generic:
        reason = "Raw URL in Title" if is_raw_url else "Generic Title"
        summary = f'High Issue: {reason} ("{preview}")'
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence=f"Title tag is unoptimized ({reason}): '{raw_title}'. Missing high-value local search keywords.",
            recommended_fix=f"Replace with a targeted title tag: e.g. '{category or 'Services'} in {city or 'City'} | Company Name'.",
            xlsx_summary=summary,
        ), raw_title, summary

    if t_len < 30:
        summary = f'High Issue: Too Short ({t_len} chars: "{preview}") - Missing Keyword & City'
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence=f"Title tag is under-optimized at only {t_len} chars: '{raw_title}'. Missing high-value local search keywords.",
            recommended_fix=f"Expand title to 30-60 characters including '{category or 'Services'} in {city or 'City'}'.",
            xlsx_summary=summary,
        ), raw_title, summary

    if t_len >= 61:
        summary = f'Warning: {t_len} chars ("{preview}") - SERP Truncation Risk (> 60 chars)'
        return AuditIssue(
            check_name="title_tag",
            audit_status="Warning",
            priority="Medium",
            severity="Medium",
            confidence="High",
            evidence=f"Title is {t_len} characters long and will be truncated in Google desktop & mobile search snippets.",
            recommended_fix="Condense title to 30-60 characters.",
            xlsx_summary=summary,
        ), raw_title, summary

    summary = f'Pass: Optimal ({t_len} chars: "{preview}")'
    return AuditIssue(
        check_name="title_tag",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence=f"Title tag is ideal length ({t_len} chars): '{raw_title}'.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), raw_title, summary


def check_meta_description_status(soup: BeautifulSoup) -> Tuple[AuditIssue, str]:
    """Check 9: Meta Description Status (Target: 120-160 chars)."""
    if not soup:
        summary = "High Issue: Missing <meta name=\"description\"> (Hurts Organic CTR)"
        return AuditIssue(
            check_name="meta_description",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence="Meta description missing.",
            recommended_fix="Add descriptive meta description.",
            xlsx_summary=summary,
        ), summary

    meta_el = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc_content = (meta_el.get("content") or "").strip() if meta_el else ""

    if not desc_content:
        summary = "High Issue: Missing <meta name=\"description\"> (Hurts Organic CTR)"
        return AuditIssue(
            check_name="meta_description",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence="Homepage lacks a meta description tag. Google will display random snippet text in search results.",
            recommended_fix="Add a 120-160 character meta description with a clear call-to-action and local phone number.",
            xlsx_summary=summary,
        ), summary

    d_len = len(desc_content)
    if d_len < 120:
        summary = f"Warning: Too Short ({d_len} chars; Target: 120-160 chars)"
        return AuditIssue(
            check_name="meta_description",
            audit_status="Warning",
            priority="Low",
            severity="Low",
            confidence="High",
            evidence=f"Meta description is only {d_len} characters: '{desc_content}'. Optimal length is 120-160 characters.",
            recommended_fix="Expand description to 120-160 characters highlighting key business benefits.",
            xlsx_summary=summary,
        ), summary

    if d_len > 160:
        summary = f"Minor: {d_len} chars (Truncated in SERP; Optimal: 120-160 chars)"
        return AuditIssue(
            check_name="meta_description",
            audit_status="Warning",
            priority="Low",
            severity="Low",
            confidence="High",
            evidence=f"Meta description is {d_len} characters and exceeds Google's SERP display cutoff (160 characters).",
            recommended_fix="Trim meta description to under 160 characters.",
            xlsx_summary=summary,
        ), summary

    summary = f"Pass: Optimal ({d_len} chars)"
    return AuditIssue(
        check_name="meta_description",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence=f"Well-crafted meta description ({d_len} chars): '{desc_content[:45]}...'.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary
    return AuditIssue(
        check_name="meta_description",
        audit_status="Pass",
        priority="None",
        evidence=f"Well-crafted meta description ({d_len} chars): '{desc_content[:45]}...'.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary


def extract_raw_h1_and_status(soup: BeautifulSoup, fetch_res: Optional[FetchResult] = None) -> Tuple[AuditIssue, str, str]:
    """Check 10 & 11: Extracted Primary H1 and H1 Tag Status with HTML5 Multi-H1 contextual validation."""
    evidence_url = (fetch_res.final_url or fetch_res.url) if fetch_res else None
    if not soup:
        summary = "Critical On-Page: No <h1> Tag Found on Homepage"
        return AuditIssue(
            check_name="h1_status",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence_url=evidence_url,
            evidence="No H1 tag found.",
            recommended_fix="Add an H1 tag.",
            xlsx_summary=summary,
        ), "", summary

    h1_tags = soup.find_all("h1")
    if not h1_tags:
        summary = "Critical On-Page: No <h1> Tag Found on Homepage"
        return AuditIssue(
            check_name="h1_status",
            audit_status="Fail",
            priority="High",
            severity="High",
            confidence="High",
            evidence_url=evidence_url,
            evidence="Homepage completely lacks an <h1> primary headline. Search engines cannot easily identify page topic.",
            recommended_fix="Add exactly one descriptive <h1> headline at the top of the page.",
            xlsx_summary=summary,
        ), "", summary

    primary_h1 = re.sub(r"\s+", " ", h1_tags[0].get_text(separator=" ", strip=True)).strip()
    count = len(h1_tags)

    if count == 2:
        sec_h1 = re.sub(r"\s+", " ", h1_tags[1].get_text(separator=" ", strip=True)).strip()
        if primary_h1.lower() == sec_h1.lower():
            summary = f'Warning: Duplicate Identical H1 Tags ("{primary_h1[:25]}...")'
            return AuditIssue(
                check_name="h1_status",
                audit_status="Warning",
                priority="Low",
                severity="Low",
                confidence="High",
                evidence_url=evidence_url,
                evidence=f"Found 2 identical <h1> tags on homepage: '{primary_h1}'.",
                recommended_fix="Consolidate duplicate H1 tags into a single primary H1.",
                xlsx_summary=summary,
            ), primary_h1, summary
        else:
            summary = f'Pass: Multi-Section Layout (2 H1 tags found: "{primary_h1[:25]}...")'
            return AuditIssue(
                check_name="h1_status",
                audit_status="Pass",
                priority="None",
                severity="None",
                confidence="High",
                evidence_url=evidence_url,
                evidence=f"Acceptable HTML5 layout: 2 distinct H1 headers verified ('{primary_h1[:40]}' & '{sec_h1[:40]}').",
                recommended_fix=None,
                xlsx_summary=summary,
            ), primary_h1, summary

    if count > 2:
        summary = f'Warning: Multiple H1 Tags ({count} Found: "{primary_h1[:25]}...") - Dilutes Hierarchy'
        return AuditIssue(
            check_name="h1_status",
            audit_status="Warning",
            priority="Low",
            severity="Low",
            confidence="High",
            evidence_url=evidence_url,
            evidence=f"Found {count} separate <h1> tags on the homepage. Dilutes document semantic hierarchy.",
            recommended_fix="Keep only one primary <h1> and convert secondary headers into <h2> and <h3> tags.",
            xlsx_summary=summary,
        ), primary_h1, summary

    summary = f'Pass: Single Descriptive H1 Present ("{primary_h1[:35]}")'
    return AuditIssue(
        check_name="h1_status",
        audit_status="Pass",
        priority="None",
        severity="None",
        confidence="High",
        evidence_url=evidence_url,
        evidence=f"Clean semantic structure: Single <h1> verified ('{primary_h1[:50]}').",
        recommended_fix=None,
        xlsx_summary=summary,
    ), primary_h1, summary


def check_homepage_word_count(soup: BeautifulSoup) -> Tuple[AuditIssue, str, int]:
    """Check 12: Homepage Word Count (Thin Content check)."""
    if not soup:
        summary = "Thin Content [High]: 0 words (< 300 words)"
        return AuditIssue(
            check_name="word_count",
            audit_status="Fail",
            priority="High",
            evidence="No text parsed.",
            recommended_fix="Add content.",
            xlsx_summary=summary,
        ), summary, 0

    # Clone and strip non-content elements
    try:
        from bs4 import Tag
        body_copy = soup.find("body") or soup
        # Count words excluding scripts, styles, header, footer, nav
        text_elements = []
        for el in body_copy.find_all(string=True):
            parent = el.parent
            if parent and parent.name in ("script", "style", "nav", "footer", "noscript", "svg"):
                continue
            t = el.strip()
            if t:
                text_elements.append(t)
        full_text = " ".join(text_elements)
        words = clean_words(full_text)
        word_count = len(words)
    except Exception:
        word_count = 0

    if word_count < 300:
        summary = f"Thin Content [High]: {word_count} words (< 300 words)"
        return AuditIssue(
            check_name="word_count",
            audit_status="Fail",
            priority="High",
            evidence=f"Homepage has only {word_count} words of visible content. Google penalizes thin local homepages.",
            recommended_fix="Expand homepage copy to at least 500-800 words describing core services, service areas, and trust signals.",
            xlsx_summary=summary,
        ), summary, word_count

    summary = f"Pass: {word_count} words (Sufficient Content Depth)"
    return AuditIssue(
        check_name="word_count",
        audit_status="Pass",
        priority="None",
        evidence=f"Good content depth: {word_count} visible words on homepage.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary, word_count


def check_image_alt_gap(soup: BeautifulSoup) -> Tuple[AuditIssue, str]:
    """Check 13: Image Alt Text Coverage."""
    if not soup:
        summary = "Pass: No images"
        return AuditIssue(
            check_name="image_alt",
            audit_status="Pass",
            priority="None",
            evidence="No images found.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    imgs = soup.find_all("img")
    total_imgs = len(imgs)
    if total_imgs == 0:
        summary = "Pass: No content images detected"
        return AuditIssue(
            check_name="image_alt",
            audit_status="Pass",
            priority="None",
            evidence="No <img> elements found on the homepage.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    missing_alt = sum(1 for img in imgs if not (img.get("alt") or "").strip())
    if missing_alt > 0:
        pct = round((missing_alt / total_imgs) * 100)
        summary = f"Missing Alt: {missing_alt} of {total_imgs} images ({pct}%)"
        return AuditIssue(
            check_name="image_alt",
            audit_status="Warning" if pct < 50 else "Fail",
            priority="Medium" if pct < 50 else "High",
            evidence=f"{missing_alt} out of {total_imgs} images ({pct}%) lack descriptive alt text attributes.",
            recommended_fix="Add descriptive, keyword-rich alt tags to all informative images.",
            xlsx_summary=summary,
        ), summary

    summary = f"Pass: All {total_imgs} images contain alt attributes"
    return AuditIssue(
        check_name="image_alt",
        audit_status="Pass",
        priority="None",
        evidence=f"All {total_imgs} images on homepage have descriptive alt text.",
        recommended_fix=None,
        xlsx_summary=summary,
    ), summary


# ============================================================================
# C. Local SEO Signals & Category Synonym Matching (Fix #1, #2, #5)
# ============================================================================

CATEGORY_SYNONYMS: Dict[str, List[str]] = {
    "plumber": ["plumber", "plumbing", "rooter", "drain", "pipe", "water heater", "sewer"],
    "plumbing": ["plumber", "plumbing", "rooter", "drain", "pipe", "water heater", "sewer"],
    "hvac contractor": ["hvac", "heating", "cooling", "air conditioning", "ac repair", "heat pump", "furnace"],
    "heating contractor": ["hvac", "heating", "cooling", "air conditioning", "ac repair", "heat pump", "furnace"],
    "air conditioning contractor": ["hvac", "heating", "cooling", "air conditioning", "ac repair", "heat pump", "furnace"],
    "bathroom remodeler": ["bathroom", "bathtub", "shower", "remodel", "renovation", "refinishing", "tub"],
    "dentist": ["dentist", "dental", "dentistry", "orthodont", "teeth", "smile", "implant"],
    "dental clinic": ["dentist", "dental", "dentistry", "orthodont", "teeth", "smile", "implant"],
    "cosmetic dentist": ["dentist", "dental", "dentistry", "orthodont", "teeth", "smile", "implant"],
    "pediatric dentist": ["dentist", "dental", "dentistry", "orthodont", "teeth", "smile", "implant"],
    "roofing contractor": ["roof", "roofing", "roofer", "shingle", "gutter"],
    "electrician": ["electric", "electrical", "electrician", "wiring", "panel"],
}


def stem_word(w: str) -> str:
    """Strips trailing s, er, or, ing if remaining root length >= 4 (Fix #2)."""
    w = w.lower()
    for suffix in ("ing", "ers", "er", "or", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[:-len(suffix)]
    return w


def matches_category_synonyms(category: Optional[str], text: str) -> bool:
    """Matches category against text using synonym lists and root stemming (Fix #2)."""
    if not category or not text:
        return False
    cat_lower = category.strip().lower()
    text_lower = text.lower()

    # 1. Direct synonym dictionary check
    if cat_lower in CATEGORY_SYNONYMS:
        if any(syn in text_lower for syn in CATEGORY_SYNONYMS[cat_lower]):
            return True

    for key, syns in CATEGORY_SYNONYMS.items():
        if key in cat_lower or cat_lower in key:
            if any(syn in text_lower for syn in syns):
                return True

    # 2. General stem and word boundary matching excluding generic stopwords
    words = clean_words(cat_lower)
    core_words = [w for w in words if w not in GENERIC_CATEGORY_STOPWORDS]
    target_words = core_words if core_words else words

    text_words = set(clean_words(text_lower))
    for w in target_words:
        if len(w) < 3:
            continue
        if w in text_words or w in text_lower:
            return True
        stem = stem_word(w)
        if len(stem) >= 4:
            if any(tw.startswith(stem) or stem in tw for tw in text_words) or stem in text_lower:
                return True

    return False


def extract_flattened_schema_types(data: Any) -> List[str]:
    """Recursively flattens all @type values from JSON-LD objects, stripping URL prefixes (Fix #5)."""
    types: List[str] = []
    if isinstance(data, list):
        for item in data:
            types.extend(extract_flattened_schema_types(item))
    elif isinstance(data, dict):
        if "@type" in data:
            raw = data["@type"]
            if isinstance(raw, list):
                for item in raw:
                    types.extend(extract_flattened_schema_types(item))
            elif isinstance(raw, str):
                cleaned = raw.split("/")[-1].split("#")[-1].strip()
                if cleaned:
                    types.append(cleaned)
        # Recurse into nested structures (@graph, mainEntity, itemListElement, etc.)
        for key in ("@graph", "itemListElement", "mainEntity", "hasPart", "subOrganization", "department"):
            if key in data:
                types.extend(extract_flattened_schema_types(data[key]))
    elif isinstance(data, str):
        cleaned = data.split("/")[-1].split("#")[-1].strip()
        if cleaned:
            types.append(cleaned)
    return types


def check_local_keywords(
    soup: BeautifulSoup,
    city: Optional[str] = None,
    category: Optional[str] = None,
    candidate_cities: Optional[List[str]] = None,
    primary_city: Optional[str] = None,
    address: Optional[str] = None,
) -> Tuple[AuditIssue, str]:
    """Check 14: Target City & Category presence in Title / H1 (Fix #1 & Fix #2)."""
    # If address is explicitly provided as empty string, skip check
    if address is not None and not address.strip():
        summary = "Skipped (No GBP Address)"
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence="Full physical street address was not provided in GBP listing; local keyword match check skipped.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary
    valid_candidates = [c.strip().lower() for c in (candidate_cities or []) if c and c.strip()]
    if city and city.strip() and city.strip().lower() not in valid_candidates:
        valid_candidates.append(city.strip().lower())

    resolved_city = primary_city or (valid_candidates[0].title() if valid_candidates else (city.strip() if city else ""))

    if not valid_candidates and not category:
        summary = "Unverified (No City/Category Specified)"
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Unverified",
            priority="None",
            evidence="Neither city nor category were provided in lead profile.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    text_to_search = ""
    if soup:
        title = soup.find("title")
        h1 = soup.find("h1")
        title_txt = title.get_text(separator=" ", strip=True) if title else ""
        h1_txt = h1.get_text(separator=" ", strip=True) if h1 else ""
        text_to_search = re.sub(r"\s+", " ", f"{title_txt} {h1_txt}").lower()

    # Check city: matches if ANY valid candidate city is in text_to_search
    city_found = False
    if valid_candidates:
        city_found = any(c in text_to_search for c in valid_candidates)

    # Check category: matches using synonym and stem matcher
    cat_found = matches_category_synonyms(category, text_to_search)

    cat_display = category or "Category"
    city_display = resolved_city or "Target City"

    if (city_found or not valid_candidates) and cat_found:
        if valid_candidates:
            summary = f'Pass: City ("{city_display}") & Category ("{cat_display}") Found in Title/H1'
            evidence = f"Both '{city_display}' and '{cat_display}' are prominently featured in Title/H1 headers."
        else:
            summary = f'Pass: Category ("{cat_display}") Found in Title/H1'
            evidence = f"Category '{cat_display}' is prominently featured in Title/H1 headers."
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Pass",
            priority="None",
            evidence=evidence,
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if not city_found and valid_candidates and cat_found:
        summary = f'Local Gap: Target City ("{city_display}") Missing from Title & H1'
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Warning",
            priority="High",
            evidence=f"Category '{cat_display}' was found, but target city '{city_display}' is missing from primary headers.",
            recommended_fix=f"Incorporate '{city_display}' into your Title tag and <h1> headline for immediate Local Pack boost.",
            xlsx_summary=summary,
        ), summary

    if city_found and not cat_found:
        summary = f'Local Gap: Target Category ("{cat_display}") Missing from Title & H1'
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Warning",
            priority="High",
            evidence=f"City '{city_display}' was found, but primary business category '{cat_display}' is missing from headers.",
            recommended_fix=f"Include '{cat_display}' in your homepage Title tag and <h1> headline.",
            xlsx_summary=summary,
        ), summary

    if not valid_candidates:
        summary = f'Local Gap: Target Category ("{cat_display}") Missing from Title & H1'
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Warning",
            priority="High",
            evidence=f"Primary category '{cat_display}' does not appear in your Title or H1 tags.",
            recommended_fix=f"Update Title and H1 to include '{cat_display}'.",
            xlsx_summary=summary,
        ), summary

    summary = f'Critical Local Gap: Both City ("{city_display}") & Category Missing from Title & H1'
    return AuditIssue(
        check_name="local_keywords",
        audit_status="Fail",
        priority="High",
        evidence=f"Neither '{city_display}' nor '{cat_display}' appear in your Title or H1 tags.",
        recommended_fix=f"Update Title and H1 to: '{cat_display} in {city_display} | Business Name'.",
        xlsx_summary=summary,
    ), summary


def check_schema_status(soup: BeautifulSoup, category: Optional[str] = None) -> Tuple[AuditIssue, str]:
    """Check 15: Schema.org LocalBusiness JSON-LD markup (Fix #5)."""
    if not soup:
        summary = "High Issue: No Schema Markup Detected on Homepage"
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Fail",
            priority="High",
            evidence="No schema detected.",
            recommended_fix="Implement LocalBusiness schema.",
            xlsx_summary=summary,
        ), summary

    found_types: List[str] = []

    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            content = script.string or script.get_text()
            if not content or not content.strip():
                continue
            data = json.loads(content.strip())
            extracted = extract_flattened_schema_types(data)
            found_types.extend(extracted)
        except Exception:
            continue

    # Deduplicate while preserving order
    seen = set()
    deduped_types = []
    for t in found_types:
        if t not in seen:
            seen.add(t)
            deduped_types.append(t)

    has_local_biz = any(t.lower() in LOCAL_BUSINESS_TYPES or "localbusiness" in t.lower() for t in deduped_types)
    types_str = ", ".join(deduped_types)

    if has_local_biz:
        summary = f"Pass: LocalBusiness JSON-LD Present ({types_str})"
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Pass",
            priority="None",
            evidence=f"Verified LocalBusiness schema markup: {types_str}.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if deduped_types:
        summary = f"Incomplete JSON-LD: Found ({types_str}), Missing LocalBusiness/{category or 'Industry'}"
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Warning",
            priority="High",
            evidence=f"Generic schema detected ({types_str}), but missing specific LocalBusiness markup.",
            recommended_fix=f"Add a Schema.org LocalBusiness / {category or 'ProfessionalService'} JSON-LD snippet with address & phone.",
            xlsx_summary=summary,
        ), summary

    summary = "High Issue: No Schema Markup Detected on Homepage"
    return AuditIssue(
        check_name="schema_markup",
        audit_status="Fail",
        priority="High",
        evidence="Homepage lacks structured JSON-LD data. Google cannot verify business type, NAP, or opening hours.",
        recommended_fix="Generate and embed LocalBusiness JSON-LD schema into the homepage HTML.",
        xlsx_summary=summary,
    ), summary


def check_nap_status(
    soup: BeautifulSoup,
    business_name: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
) -> Tuple[AuditIssue, str]:
    """Check 16: NAP Consistency (Name, Address, Phone on homepage)."""
    clean_phone_digits = normalize_phone_digits(phone)
    if not clean_phone_digits and not address:
        summary = "Unverified (No Phone/Address Provided in Lead)"
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Unverified",
            priority="None",
            evidence="Lead record did not contain GBP phone or address.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    html_text = soup.get_text() if soup else ""
    html_digits = normalize_phone_digits(html_text)

    phone_found = bool(clean_phone_digits and (clean_phone_digits[-7:] in html_digits or clean_phone_digits[-10:] in html_digits))

    # Check address keywords (first 2 words of street address)
    address_found = False
    if address:
        words = clean_words(address)
        if len(words) >= 2:
            lead_street = f"{words[0]} {words[1]}"
            address_found = lead_street in html_text.lower()
        else:
            address_found = words[0] in html_text.lower() if words else False

    if phone_found and address_found:
        summary = "Pass: Full NAP Match (Business Name, Phone, and Address Verified in HTML)"
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Pass",
            priority="None",
            evidence=f"Verified phone ({phone}) and street address match Google Maps listing.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    if phone_found and not address_found:
        summary = "Warning: Phone Found, but Street Address Missing in HTML"
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            priority="High",
            evidence=f"Phone number ({phone}) found on page, but street address ({address}) could not be located in HTML text.",
            recommended_fix="Add full physical street address in footer and contact page matching Google Business Profile.",
            xlsx_summary=summary,
        ), summary

    if not phone_found and address_found:
        summary = "Warning: Address Found, but GBP Phone Missing in HTML"
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            priority="High",
            evidence=f"Street address verified, but Google Business Profile phone ({phone}) is missing from homepage text.",
            recommended_fix="Add clickable tel: phone number matching your Google Business Profile.",
            xlsx_summary=summary,
        ), summary

    summary = "Critical Local Signal: GBP Phone & Street Address Missing in HTML"
    return AuditIssue(
        check_name="nap_consistency",
        audit_status="Fail",
        priority="High",
        evidence=f"Neither Google Maps phone ({phone}) nor address ({address}) were found in homepage HTML.",
        recommended_fix="Place exact Name, Address, and Phone (NAP) matching Google Business Profile in homepage footer.",
        xlsx_summary=summary,
    ), summary


def check_maps_embed(soup: BeautifulSoup) -> Tuple[AuditIssue, str]:
    """Check 17: Google Maps Embed Check."""
    if not soup:
        summary = "Missing Map Embed [Low]"
        return AuditIssue(
            check_name="maps_embed",
            audit_status="Warning",
            priority="Low",
            evidence="No iframe found.",
            recommended_fix="Embed Google Maps iframe.",
            xlsx_summary=summary,
        ), summary

    has_map = False
    for iframe in soup.find_all("iframe", src=True):
        src = (iframe.get("src") or "").lower()
        if "google.com/maps" in src or "maps.google.com" in src:
            has_map = True
            break

    if has_map:
        summary = "Pass: Map Embedded"
        return AuditIssue(
            check_name="maps_embed",
            audit_status="Pass",
            priority="None",
            evidence="Google Maps iframe interactive embed detected on homepage.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    summary = "Missing Map Embed [Low]"
    return AuditIssue(
        check_name="maps_embed",
        audit_status="Warning",
        priority="Low",
        evidence="Homepage lacks an embedded Google Maps iframe pointing to your Google Business Profile.",
        recommended_fix="Embed an official Google Maps iframe on the contact page or footer to reinforce physical geo-relevance.",
        xlsx_summary=summary,
    ), summary


def check_gbp_category_alignment(soup: BeautifulSoup, category: Optional[str] = None, audited_page_type: str = "homepage") -> Tuple[AuditIssue, str]:
    """Check 18: GBP Category Alignment with Title / H1 (Fix #2)."""
    if not category:
        summary = "Unverified (No GBP Category)"
        return AuditIssue(
            check_name="gbp_category_alignment",
            audit_status="Unverified",
            priority="None",
            evidence="GBP category not provided in lead.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    text = ""
    if soup:
        t = soup.find("title")
        h = soup.find("h1")
        t_txt = t.get_text(separator=" ", strip=True) if t else ""
        h_txt = h.get_text(separator=" ", strip=True) if h else ""
        text = re.sub(r"\s+", " ", f"{t_txt} {h_txt}").lower()

    aligned = matches_category_synonyms(category, text)

    if aligned:
        summary = f"Pass: Category '{category}' aligned with Title/H1"
        return AuditIssue(
            check_name="gbp_category_alignment",
            audit_status="Pass",
            priority="None",
            evidence=f"Primary GBP category '{category}' is semantically supported in Title/H1 headlines.",
            recommended_fix=None,
            xlsx_summary=summary,
        ), summary

    summary = f"Warning: Category Keyword Missing ('{category}' missing from Title & H1)"
    return AuditIssue(
        check_name="gbp_category_alignment",
        audit_status="Warning",
        priority="Medium",
        severity="Medium",
        confidence="High",
        evidence=f"Primary Google Business Profile category '{category}' (core niche keyword) does not appear in Title or H1 tags on {audited_page_type}.",
        recommended_fix=f"Align on-page messaging by adding '{category}' directly to your {audited_page_type} title tag and main header.",
        xlsx_summary=summary,
    ), summary


# ============================================================================
# Master Orchestrator for All Checks
# ============================================================================

class CheckRunResult(dict):
    """
    Dual-compatibility container for SEO check outputs.
    Acts as both a dictionary of AuditIssue objects (for legacy tests/callers),
    and exposes structured metadata attributes:
    .issues, .xlsx_row, .extracted_title, .extracted_h1, .word_count, .is_https, .is_js_rendered, .audited_page_type.
    """
    def __init__(
        self,
        issues: Dict[str, AuditIssue],
        xlsx_row: Dict[str, str],
        extracted_title: str,
        extracted_h1: str,
        word_count: int,
        is_https: bool,
        is_js_rendered: bool = False,
        audited_page_type: str = "homepage",
    ):
        super().__init__(issues)
        self.issues = issues
        self.xlsx_row = xlsx_row
        self.extracted_title = extracted_title
        self.extracted_h1 = extracted_h1
        self.word_count = word_count
        self.is_https = is_https
        self.is_js_rendered = is_js_rendered
        self.audited_page_type = audited_page_type

    def __getitem__(self, key):
        if key == "issues":
            return self.issues
        if key == "xlsx_row":
            return self.xlsx_row
        if key == "extracted_title":
            return self.extracted_title
        if key == "extracted_h1":
            return self.extracted_h1
        if key == "word_count":
            return self.word_count
        if key == "is_https":
            return self.is_https
        if key == "is_js_rendered":
            return self.is_js_rendered
        if key == "audited_page_type":
            return self.audited_page_type
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "issues":
            return self.issues
        if key == "xlsx_row":
            return self.xlsx_row
        if key == "extracted_title":
            return self.extracted_title
        if key == "extracted_h1":
            return self.extracted_h1
        if key == "word_count":
            return self.word_count
        if key == "is_https":
            return self.is_https
        if key == "is_js_rendered":
            return self.is_js_rendered
        if key == "audited_page_type":
            return self.audited_page_type
        return super().get(key, default)


def run_all_seo_checks(input_data: AuditInput, fetch_res: FetchResult) -> CheckRunResult:
    """
    Executes all 18 check engines and packages results into:
    - issues: Dict[str, AuditIssue]
    - xlsx_row: Dict[str, str] (covering all technical & local signals)
    - metadata: extracted_title, extracted_h1, word_count, is_https, is_js_rendered, audited_page_type
    """
    issues: Dict[str, AuditIssue] = {}
    xlsx_row: Dict[str, str] = {}

    target_url_str = fetch_res.final_url or fetch_res.url or (input_data.url if input_data else "")
    parsed_u = urlparse(target_url_str)
    is_subpage = bool(parsed_u.path and parsed_u.path not in ("", "/"))
    audited_page_type = "landing page" if is_subpage else "homepage"

    # 1. Technical Foundation
    iss_url, s_url = check_final_url_and_status(fetch_res)
    issues["final_url_status"] = iss_url
    xlsx_row["Final URL & HTTP Status"] = s_url

    iss_ssl, s_ssl = check_ssl_redirect_status(fetch_res)
    issues["ssl_redirect"] = iss_ssl
    xlsx_row["SSL & HTTPS Redirect Status"] = s_ssl

    iss_ttfb, s_ttfb = check_server_response_ttfb(fetch_res)
    issues["server_response_ttfb"] = iss_ttfb
    xlsx_row["Server Response (TTFB)"] = s_ttfb

    # If the website failed to load/connect (status_code is None) or returned server error (>= 400)
    if fetch_res.status_code is None or fetch_res.status_code >= 400:
        is_unreachable = (fetch_res.status_code is None)
        untested_summary = "Not Tested"
        untested_evidence = (
            "Web server could not be reached (connection timeout or DNS error) - check not tested."
            if is_unreachable
            else f"Web server returned HTTP error status {fetch_res.status_code} - on-page content not tested."
        )

        for col_name, chk_key in [
            ("Indexability (Meta Robots)", "meta_robots"),
            ("Canonical Tag Status", "canonical_tag"),
            ("Robots.txt & XML Sitemap", "robots_sitemap"),
            ("Title Tag Status", "title_tag"),
            ("Meta Description Status", "meta_description"),
            ("H1 Tag Status", "h1_status"),
            ("Homepage Word Count", "word_count"),
            ("Image Alt Text Gap", "image_alt"),
            ("Local Keyword Status", "local_keywords"),
            ("Schema Status", "schema_markup"),
            ("NAP Status", "nap_consistency"),
            ("Google Maps Embed", "maps_embed"),
            ("GBP Category Alignment", "gbp_category_alignment"),
        ]:
            issues[chk_key] = AuditIssue(
                check_name=chk_key,
                audit_status="Unverified",
                priority="None",
                severity="None",
                confidence="Unverified",
                evidence_url=fetch_res.final_url or fetch_res.url,
                evidence=untested_evidence,
                recommended_fix=None,
                xlsx_summary=untested_summary,
            )
            xlsx_row[col_name] = untested_summary

        xlsx_row["Extracted Title Text"] = ""
        xlsx_row["Extracted Primary H1"] = ""
        xlsx_row["SEO Health Score"] = "Not Tested"
        xlsx_row["Lead Pitch Priority"] = "Not Tested"

        # Aliases for legacy compatibility
        issues["website_speed"] = iss_ttfb
        issues["canonical_robots"] = issues.get("meta_robots")
        issues["contact_maps_embed"] = issues.get("maps_embed")
        issues["mobile_friendly"] = AuditIssue(
            check_name="mobile_friendly",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=fetch_res.final_url or fetch_res.url,
            evidence=untested_evidence,
            xlsx_summary=untested_summary,
        )
        xlsx_row["Mobile Friendly"] = untested_summary

        return CheckRunResult(
            issues=issues,
            xlsx_row=xlsx_row,
            extracted_title="",
            extracted_h1="",
            word_count=0,
            is_https=False,
            is_js_rendered=False,
            audited_page_type=audited_page_type,
        )

    soup = BeautifulSoup(fetch_res.html, "html.parser")

    # 4. Meta Robots
    iss_robots, s_robots = check_indexability_meta_robots(soup, fetch_res)
    issues["meta_robots"] = iss_robots
    xlsx_row["Indexability (Meta Robots)"] = s_robots

    # 5. Canonical Tag
    iss_canon, s_canon = check_canonical_tag(soup, fetch_res)
    issues["canonical_tag"] = iss_canon
    xlsx_row["Canonical Tag Status"] = s_canon

    # 6. Robots & Sitemap
    iss_sitemap, s_sitemap = check_robots_and_sitemap(fetch_res)
    issues["robots_sitemap"] = iss_sitemap
    xlsx_row["Robots.txt & XML Sitemap"] = s_sitemap

    # 7 & 8. Extracted Title & Title Tag Status
    primary_city = input_data.get_primary_city() if hasattr(input_data, "get_primary_city") else (input_data.city or "")
    candidate_cities = input_data.get_candidate_cities() if hasattr(input_data, "get_candidate_cities") else ([input_data.city] if input_data.city else [])

    iss_title, raw_title, s_title = extract_raw_title_and_status(
        soup, primary_city, input_data.category, audited_page_type=audited_page_type
    )
    issues["title_tag"] = iss_title
    xlsx_row["Extracted Title Text"] = raw_title
    xlsx_row["Title Tag Status"] = s_title

    # 9. Meta Description
    iss_desc, s_desc = check_meta_description_status(soup)
    issues["meta_description"] = iss_desc
    xlsx_row["Meta Description Status"] = s_desc

    # 10 & 11. Extracted Primary H1 & H1 Status
    iss_h1, raw_h1, s_h1 = extract_raw_h1_and_status(soup, fetch_res=fetch_res)
    issues["h1_status"] = iss_h1
    xlsx_row["Extracted Primary H1"] = raw_h1
    xlsx_row["H1 Tag Status"] = s_h1

    # 12. Homepage Word Count
    iss_words, s_words, word_count = check_homepage_word_count(soup)
    issues["word_count"] = iss_words
    xlsx_row["Homepage Word Count"] = s_words

    # 13. Image Alt Gap
    iss_alt, s_alt = check_image_alt_gap(soup)
    issues["image_alt"] = iss_alt
    xlsx_row["Image Alt Text Gap"] = s_alt

    # Detect CSR / SPA shell (Objective 1)
    is_js_rendered = is_js_spa_shell(soup, word_count)

    # 14. Local Keywords (Fix #1 & #2, and City State Leak fix)
    has_full_address = bool(input_data.address and input_data.address.strip())
    if not has_full_address:
        iss_kw = AuditIssue(
            check_name="local_keywords",
            audit_status="Pass",
            priority="None",
            severity="None",
            confidence="High",
            evidence="Skipped: No physical GBP address provided in lead record.",
            recommended_fix=None,
            xlsx_summary="Skipped (No GBP Address)",
        )
        s_kw = "Skipped (No GBP Address)"
    else:
        iss_kw, s_kw = check_local_keywords(
            soup,
            input_data.city,
            input_data.category,
            candidate_cities=candidate_cities,
            primary_city=primary_city,
            address=input_data.address,
        )
    issues["local_keywords"] = iss_kw
    xlsx_row["Local Keyword Status"] = s_kw

    # 15. Schema Status
    iss_schema, s_schema = check_schema_status(soup, input_data.category)
    issues["schema_markup"] = iss_schema
    xlsx_row["Schema Status"] = s_schema

    # 16. NAP Status
    iss_nap, s_nap = check_nap_status(soup, input_data.business_name, input_data.phone, input_data.address)
    issues["nap_consistency"] = iss_nap
    xlsx_row["NAP Status"] = s_nap

    # 17. Maps Embed
    iss_embed, s_embed = check_maps_embed(soup)
    issues["maps_embed"] = iss_embed
    xlsx_row["Google Maps Embed"] = s_embed

    # 18. GBP Category Alignment
    iss_cat, s_cat = check_gbp_category_alignment(soup, input_data.category, audited_page_type=audited_page_type)
    issues["gbp_category_alignment"] = iss_cat
    xlsx_row["GBP Category Alignment"] = s_cat

    # Zero-Browser JS/SPA False-Positive Fix (Objective 1):
    # If client-side rendered shell detected, skip on-page penalties:
    # 0 words, No H1, Missing NAP.
    if is_js_rendered:
        # Override word_count
        iss_words = AuditIssue(
            check_name="word_count",
            audit_status="Unverified",
            priority="None",
            severity="None",
            confidence="Unverified",
            evidence_url=fetch_res.final_url or fetch_res.url,
            evidence="Client-side rendered (SPA/JS) shell detected. Static HTML word count is not indicative of on-page content.",
            recommended_fix=None,
            xlsx_summary="N/A (JS-Rendered Site)",
        )
        s_words = "N/A (JS-Rendered Site)"
        issues["word_count"] = iss_words
        xlsx_row["Homepage Word Count"] = s_words

        # Override H1 if missing
        if iss_h1.audit_status == "Fail":
            iss_h1 = AuditIssue(
                check_name="h1_status",
                audit_status="Unverified",
                priority="None",
                severity="None",
                confidence="Unverified",
                evidence_url=fetch_res.final_url or fetch_res.url,
                evidence="Client-side rendered (SPA/JS) shell detected. Heading structure is rendered dynamically via JavaScript.",
                recommended_fix=None,
                xlsx_summary="N/A (JS-Rendered Site)",
            )
            s_h1 = "N/A (JS-Rendered Site)"
            issues["h1_status"] = iss_h1
            xlsx_row["H1 Tag Status"] = s_h1

        # Override NAP if missing
        if iss_nap.audit_status in ("Fail", "Warning"):
            iss_nap = AuditIssue(
                check_name="nap_consistency",
                audit_status="Unverified",
                priority="None",
                severity="None",
                confidence="Unverified",
                evidence_url=fetch_res.final_url or fetch_res.url,
                evidence="Client-side rendered (SPA/JS) shell detected. Contact details and address are rendered via client-side JavaScript.",
                recommended_fix=None,
                xlsx_summary="N/A (JS-Rendered Site)",
            )
            s_nap = "N/A (JS-Rendered Site)"
            issues["nap_consistency"] = iss_nap
            xlsx_row["NAP Status"] = s_nap

    # Aliases for legacy compatibility
    issues["website_speed"] = iss_ttfb
    issues["canonical_robots"] = issues.get("meta_robots")
    issues["contact_maps_embed"] = issues.get("maps_embed")
    viewport_meta = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    if viewport_meta:
        issues["mobile_friendly"] = AuditIssue(
            check_name="mobile_friendly",
            audit_status="Pass",
            priority="None",
            evidence="Viewport meta tag is declared.",
            xlsx_summary="Pass: Viewport Meta Tag Present",
        )
    else:
        issues["mobile_friendly"] = AuditIssue(
            check_name="mobile_friendly",
            audit_status="Fail",
            priority="High",
            evidence="Missing viewport meta tag.",
            xlsx_summary="Fail: No Viewport Declared",
        )

    is_https = (fetch_res.final_url or fetch_res.url).startswith("https://") and not fetch_res.ssl_failed

    return CheckRunResult(
        issues=issues,
        xlsx_row=xlsx_row,
        extracted_title=raw_title,
        extracted_h1=raw_h1,
        word_count=word_count,
        is_https=is_https,
        is_js_rendered=is_js_rendered,
        audited_page_type=audited_page_type,
    )

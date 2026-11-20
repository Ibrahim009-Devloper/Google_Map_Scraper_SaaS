"""
Unit and integration tests for the 5 SEO Audit Engine Objectives:
1. Zero-Browser JS/SPA False-Positive Fix
2. Accurate SSL & HTTP Redirect Verification
3. Homepage vs Subpage Normalization
4. Icebreaker Logic, Priority & Grammar Overhaul
5. SEO Audit Thresholds, Alignment & City Leak Fixes
"""

import pytest
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from backend.seo_audit.models import AuditInput, AuditIssue, SEOReport
from backend.seo_audit.config import TTFB_WARNING_SEC, TTFB_HIGH_SEC
from backend.seo_audit.fetcher import FetchResult
from backend.seo_audit.analyzer import (
    is_js_spa_shell,
    run_all_seo_checks,
    check_ssl_redirect_status,
    check_server_response_ttfb,
    extract_raw_title_and_status,
    check_meta_description_status,
    matches_category_synonyms,
    check_gbp_category_alignment,
    check_local_keywords,
)
from backend.seo_audit.scorer import calculate_seo_health_and_pitch
from backend.seo_audit.icebreaker import (
    clean_business_name_for_copy,
    generate_icebreaker_hook,
)
from backend.seo_audit.auditor import audit_single_business


# ============================================================================
# Objective 1: Zero-Browser JS/SPA False-Positive Fix
# ============================================================================

def test_obj1_js_spa_shell_detection():
    # 1. React root mount
    react_html = '<html><head><title>Modern React App</title></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
    soup_react = BeautifulSoup(react_html, "html.parser")
    assert is_js_spa_shell(soup_react, word_count=3) is True

    # 2. Next.js mount
    next_html = '<html><head><title>Next.js App</title></head><body><div id="__next"></div><script src="/_next/static/chunk.js"></script></body></html>'
    soup_next = BeautifulSoup(next_html, "html.parser")
    assert is_js_spa_shell(soup_next, word_count=2) is True

    # 3. Noscript warning
    noscript_html = '<html><head><title>App</title></head><body><noscript>You need to enable JavaScript to run this app.</noscript></body></html>'
    soup_ns = BeautifulSoup(noscript_html, "html.parser")
    assert is_js_spa_shell(soup_ns, word_count=9) is True

    # 4. Standard content page with >= 30 words should NOT be flagged as SPA shell
    regular_html = "<html><body><p>" + ("Solid descriptive local business content. " * 15) + "</p></body></html>"
    soup_reg = BeautifulSoup(regular_html, "html.parser")
    assert is_js_spa_shell(soup_reg, word_count=75) is False


def test_obj1_js_spa_score_and_pitch_priority():
    spa_html = '<html><head><title>Acme Dental</title></head><body><div id="root"></div><script src="/main.js"></script><script src="/bundle.js"></script></body></html>'
    fetch_res = FetchResult(
        url="https://acmedental.com",
        final_url="https://acmedental.com/",
        status_code=200,
        html=spa_html,
    )
    inp = AuditInput(
        url="https://acmedental.com",
        business_name="Acme Dental",
        category="Dentist",
        address="123 Main St, Miami, FL 33101",
    )

    check_res = run_all_seo_checks(inp, fetch_res)
    assert check_res.is_js_rendered is True

    # Verify on-page penalties are skipped
    assert check_res.issues["word_count"].audit_status == "Unverified"
    assert "JS-Rendered" in check_res.xlsx_row["Homepage Word Count"]
    assert check_res.issues["h1_status"].audit_status == "Unverified"
    assert "JS-Rendered" in check_res.xlsx_row["H1 Tag Status"]
    assert check_res.issues["nap_consistency"].audit_status == "Unverified"

    # Verify score is None and pitch priority is "Manual Review (JS Site)"
    score, priority = calculate_seo_health_and_pitch(check_res.issues, is_js_rendered=True)
    assert score is None
    assert priority == "Manual Review (JS Site)"

    # Verify auditor report sets proper strings
    rep = audit_single_business(inp, cached_html=spa_html, use_cache=False)
    assert rep.seo_health_score is None
    assert rep.lead_pitch_priority == "Manual Review (JS Site)"
    assert rep.xlsx_row_data["SEO Health Score"] == "N/A (JS-Rendered)"
    assert rep.xlsx_row_data["Lead Pitch Priority"] == "Manual Review (JS Site)"

    # Verify no fake missing H1 or thin content claims in icebreaker
    assert "no primary <h1> headline" not in rep.icebreaker_hook
    assert "thin content" not in rep.icebreaker_hook
    assert "client-side JavaScript architecture" in rep.icebreaker_hook or "specialized SEO rendering" in rep.icebreaker_hook


# ============================================================================
# Objective 2: Accurate SSL & HTTP Redirect Verification
# ============================================================================

def test_obj2_ssl_and_redirect_verification():
    # 1. Clean Pass: HTTP redirected cleanly to HTTPS
    fetch_clean = FetchResult(
        url="http://example.com",
        final_url="https://example.com/",
        initial_status_code=301,
        status_code=200,
    )
    iss_clean, sum_clean = check_ssl_redirect_status(fetch_clean)
    assert iss_clean.audit_status == "Pass"
    assert "HTTP Redirects Cleanly to HTTPS" in sum_clean or "Pass" in sum_clean

    # 2. Warning (Medium): HTTPS works with valid SSL, but HTTP fails to auto-redirect
    fetch_warn = FetchResult(
        url="http://insecure-http.com",
        final_url="http://insecure-http.com/",
        initial_status_code=200,
        status_code=200,
        https_probe_success=True,
    )
    iss_warn, sum_warn = check_ssl_redirect_status(fetch_warn)
    assert iss_warn.audit_status == "Warning"
    assert iss_warn.priority == "Medium"
    assert "HTTPS Available but Missing 301 Auto-Redirect" in sum_warn

    # Verify Warning SSL alone does NOT trigger Critical Pitch
    score_warn, priority_warn = calculate_seo_health_and_pitch(
        {"ssl_redirect": iss_warn},
        has_website=True,
        is_https=False,
    )
    assert priority_warn != "Critical Pitch"

    # 3. Critical: Truly unencrypted HTTP where HTTPS fails / lacks valid SSL
    fetch_crit = FetchResult(
        url="http://truly-insecure.com",
        final_url="http://truly-insecure.com/",
        initial_status_code=200,
        status_code=200,
        https_probe_success=False,
        ssl_failed=True,
    )
    iss_crit, sum_crit = check_ssl_redirect_status(fetch_crit)
    assert iss_crit.audit_status == "Fail"
    assert iss_crit.priority == "Critical"
    assert "Critical: Unencrypted HTTP" in sum_crit


# ============================================================================
# Objective 3: Homepage vs Subpage Normalization
# ============================================================================

def test_obj3_homepage_vs_subpage_normalization():
    # Subpage URL has path
    subpage_url = "https://example.com/locations/downtown-plumber"
    fetch_res = FetchResult(
        url=subpage_url,
        final_url=subpage_url,
        status_code=200,
        html="<html><head><title>Downtown Plumber</title></head><body><p>Welcome to our landing page</p></body></html>",
    )
    inp = AuditInput(url=subpage_url, business_name="Downtown Plumber", category="Plumber")

    check_res = run_all_seo_checks(inp, fetch_res)
    assert check_res.audited_page_type == "landing page"

    # Icebreaker hook should reference landing page, not homepage
    issues = {
        "h1_status": AuditIssue(check_name="h1_status", audit_status="Fail", evidence="No H1", xlsx_summary="No H1"),
    }
    hook = generate_icebreaker_hook(inp, issues, final_url=subpage_url, has_website=True)
    assert "landing page" in hook
    assert "homepage" not in hook


# ============================================================================
# Objective 4: Icebreaker Logic, Priority & Grammar Overhaul
# ============================================================================

def test_obj4_clean_business_name_and_possessives():
    # 1. Strips after ':' or '|'
    assert clean_business_name_for_copy("Acme Roofing: Best Roofers in Town") == "Acme Roofing"
    assert clean_business_name_for_copy("Joe's Plumbing | Licensed & Insured") == "Joe's Plumbing"

    # 2. Strips legal suffixes
    assert clean_business_name_for_copy("Apex Contractors, LLC") == "Apex Contractors"
    assert clean_business_name_for_copy("Smith & Sons, Inc.") == "Smith & Sons"
    assert clean_business_name_for_copy("Quality Builders Co.") == "Quality Builders"

    # 3. English possessives: if ends in 's', uses "'" instead of "'s"
    assert clean_business_name_for_copy("Apex Contractors, LLC", possessive=True) == "Apex Contractors'"
    assert clean_business_name_for_copy("Williams Plumbing", possessive=True) == "Williams Plumbing's"
    assert clean_business_name_for_copy("Dallas Plumbers", possessive=True) == "Dallas Plumbers'"
    assert clean_business_name_for_copy("Acme Roofing", possessive=True) == "Acme Roofing's"


def test_obj4_nap_branching_never_mentions_missing_address_for_phone_only():
    biz = AuditInput(url="https://site.com", business_name="Metro Electric", category="Electrician")

    # Only phone is missing
    issues_phone_only = {
        "nap_consistency": AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            evidence="Street address verified, but Google Business Profile phone is missing from homepage text.",
            xlsx_summary="Warning: Address Found, but GBP Phone Missing in HTML",
        )
    }
    hook_phone = generate_icebreaker_hook(biz, issues_phone_only, has_website=True)
    assert "phone number" in hook_phone
    assert "street address" not in hook_phone

    # Only address is missing
    issues_addr_only = {
        "nap_consistency": AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            evidence="Phone found, but street address missing from HTML",
            xlsx_summary="Warning: Phone Found, but Street Address Missing in HTML",
        )
    }
    hook_addr = generate_icebreaker_hook(biz, issues_addr_only, has_website=True)
    assert "street address" in hook_addr
    assert "phone number" not in hook_addr


def test_obj4_critical_cross_domain_canonical_hook():
    biz = AuditInput(url="https://site.com", business_name="Precision Heating", category="HVAC")
    issues = {
        "canonical_tag": AuditIssue(
            check_name="canonical_tag",
            audit_status="Fail",
            priority="Critical",
            evidence="Canonical tag points to external domain 'otherdomain.com'",
            xlsx_summary="Critical: Points to Different Domain (otherdomain.com)",
        )
    }
    hook = generate_icebreaker_hook(biz, issues, has_website=True)
    assert "canonical tag points to an external domain" in hook


def test_obj4_healthy_site_guardrail():
    biz = AuditInput(url="https://pristine-site.com", business_name="Pristine Dental", category="Dentist")
    issues_healthy = {
        "canonical_tag": AuditIssue(check_name="canonical_tag", audit_status="Pass", evidence="Self-referencing", xlsx_summary="Pass"),
        "meta_description": AuditIssue(check_name="meta_description", audit_status="Pass", evidence="Optimal", xlsx_summary="Pass"),
    }
    hook = generate_icebreaker_hook(biz, issues_healthy, score=94, has_website=True)
    assert hook == "Site is well-optimized — skip technical pitch or use a non-SEO angle."


# ============================================================================
# Objective 5: SEO Audit Thresholds, Alignment & City Leak Fixes
# ============================================================================

def test_obj5_ttfb_thresholds_and_scoring():
    assert TTFB_WARNING_SEC == 2.0
    assert TTFB_HIGH_SEC == 4.0

    # Test TTFB <= 2.0s is Pass
    f_pass = FetchResult(url="https://site.com", status_code=200, elapsed_seconds=1.8)
    _, s_pass = check_server_response_ttfb(f_pass)
    assert "Pass: TTFB 1.8s" in s_pass

    # Test TTFB between 2.0s and 4.0s is Warning
    f_warn = FetchResult(url="https://site.com", status_code=200, elapsed_seconds=2.8)
    _, s_warn = check_server_response_ttfb(f_warn)
    assert "Warning: TTFB 2.8s" in s_warn

    # Test TTFB > 4.0s is High Issue
    f_high = FetchResult(url="https://site.com", status_code=200, elapsed_seconds=4.5)
    iss_high, s_high = check_server_response_ttfb(f_high)
    assert "High Issue: TTFB 4.5s" in s_high

    # Slow TTFB alone NEVER drops site into Critical Pitch
    score, priority = calculate_seo_health_and_pitch(
        {"server_response_ttfb": iss_high},
        has_website=True,
        is_https=True,
    )
    assert priority != "Critical Pitch"


def test_obj5_meta_description_thresholds():
    # < 120 chars: Warning: Too Short
    soup_short = BeautifulSoup('<html><head><meta name="description" content="Short description"></head></html>', "html.parser")
    iss_short, sum_short = check_meta_description_status(soup_short)
    assert iss_short.audit_status == "Warning"
    assert "Too Short" in sum_short

    # 120-160 chars: Pass: Optimal
    optimal_text = "This is a perfectly crafted professional meta description that clearly outlines all business services and call to action details."
    assert 120 <= len(optimal_text) <= 160
    soup_opt = BeautifulSoup(f'<html><head><meta name="description" content="{optimal_text}"></head></html>', "html.parser")
    iss_opt, sum_opt = check_meta_description_status(soup_opt)
    assert iss_opt.audit_status == "Pass"
    assert "Pass: Optimal" in sum_opt

    # > 160 chars: Minor: Truncated
    long_text = "This is an excessively lengthy meta description that easily runs well over one hundred and sixty characters in length which risks Google SERP truncation for searchers."
    assert len(long_text) > 160
    soup_long = BeautifulSoup(f'<html><head><meta name="description" content="{long_text}"></head></html>', "html.parser")
    iss_long, sum_long = check_meta_description_status(soup_long)
    assert iss_long.audit_status == "Warning"
    assert "Minor" in sum_long and "Truncated" in sum_long


def test_obj5_title_quality_raw_url_and_generic():
    # Raw URL in title
    soup_url = BeautifulSoup("<html><head><title>www.apexplumbing.com</title></head></html>", "html.parser")
    iss_url, _, sum_url = extract_raw_title_and_status(soup_url)
    assert iss_url.audit_status == "Fail"
    assert iss_url.priority == "High"
    assert "Raw URL in Title" in sum_url

    # Generic title (Home - ...)
    soup_gen = BeautifulSoup("<html><head><title>Home - Welcome to Our Business</title></head></html>", "html.parser")
    iss_gen, _, sum_gen = extract_raw_title_and_status(soup_gen)
    assert iss_gen.audit_status == "Fail"
    assert iss_gen.priority == "High"
    assert "Generic Title" in sum_gen


def test_obj5_category_stopwords_and_niche_stem_requirement():
    # Stopword matching prevented: "contractor" alone in title should NOT match "Roofing contractor"
    title_unrelated = "Smith General Electrical Contractor"
    assert matches_category_synonyms("Roofing contractor", title_unrelated) is False

    # Core niche stem "roof" matches
    title_roof = "Smith Residential Roofing & Gutter Experts"
    assert matches_category_synonyms("Roofing contractor", title_roof) is True

    # GBP Category alignment check flags missing core category
    soup_unrelated = BeautifulSoup(f"<html><head><title>{title_unrelated}</title></head><body><h1>Electrician</h1></body></html>", "html.parser")
    iss_cat, sum_cat = check_gbp_category_alignment(soup_unrelated, category="Roofing contractor")
    assert iss_cat.audit_status == "Warning"
    assert "Category Keyword Missing" in sum_cat


def test_obj5_neighborhood_vs_metro_city_matching():
    # Flushing address accepts Queens OR New York OR NYC in Title/H1
    inp = AuditInput(
        url="https://site.com",
        address="136-20 38th Ave, Flushing, NY 11354",
        category="Dentist",
    )
    candidates = [c.lower() for c in inp.get_candidate_cities()]
    assert "flushing" in candidates
    assert "queens" in candidates
    assert "new york" in candidates or "nyc" in candidates

    # Title with parent metro matches
    soup_metro = BeautifulSoup("<html><head><title>Best Dentist in Queens NY</title></head><body><h1>Dental Clinic</h1></body></html>", "html.parser")
    iss_kw, sum_kw = check_local_keywords(
        soup_metro,
        category="Dentist",
        candidate_cities=inp.get_candidate_cities(),
        primary_city=inp.get_primary_city(),
        address=inp.address,
    )
    assert iss_kw.audit_status == "Pass"


def test_obj5_city_leak_fix_skipped_when_no_gbp_address():
    # Empty GBP address skips local keyword check
    fetch_res = FetchResult(
        url="https://site.com",
        final_url="https://site.com",
        status_code=200,
        html="<html><head><title>Quality Services</title></head><body><p>Content</p></body></html>",
    )
    inp_no_addr = AuditInput(
        url="https://site.com",
        business_name="National Consultants",
        category="Consultant",
        address="",  # Empty GBP address
        target_city="Boston",  # Search city must NOT leak
    )

    check_res = run_all_seo_checks(inp_no_addr, fetch_res)
    assert check_res.xlsx_row["Local Keyword Status"] == "Skipped (No GBP Address)"
    assert check_res.issues["local_keywords"].xlsx_summary == "Skipped (No GBP Address)"

    # Icebreaker must NOT hallucinate Boston
    hook = generate_icebreaker_hook(inp_no_addr, check_res.issues, has_website=True)
    assert "Boston" not in hook
    assert "in Boston" not in hook

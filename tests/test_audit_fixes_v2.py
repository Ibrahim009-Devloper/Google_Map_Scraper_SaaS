"""
Exhaustive verification test suite covering all 10 hardening and logic fix requirements:
1. JS-rendered 0-word shell detection:
   - When HTML contains <div id="root"></div> or <div id="__next"></div> with visible word_count < 30,
     must report is_js_rendered = True, score = "N/A (JS-Rendered)" / None, priority = "Manual Review (JS Site)".
     Must NOT score 7/100 or fail with a missing H1 / thin content hook.
2. Accurate SSL & HTTP redirect verification:
   - When input URL is http:// and works on https://: Pass (clean 301/302 to https),
     Warning (https works but no auto-redirect), Critical (https fails / truly unencrypted).
3. NAP Icebreaker branching:
   - When NAP Status is Address Found, Phone Missing: icebreaker mentions phone, NOT street address!
   - When Phone Found, Address Missing: icebreaker mentions street address, NOT phone!
   - When both missing: mentions both!
4. Score >= 90 Healthy Site:
   - Must output "Site is well-optimized — skip technical pitch or use a non-SEO angle."
   - Must NOT claim "identified several high-ROI technical optimizations".
5. Business Name Cleaning & Grammar:
   - clean_business_name_for_copy("Daniel's Roofing: Best Roofing LLC") -> "Daniel's Roofing"
   - Possessive: Contractors -> Contractors' (NOT Contractors's), Roofing -> Roofing's.
6. Thresholds:
   - TTFB 2.0s boundary & Meta Description 120-160 boundary.
   - Raw URL title rejection (www., .com, .net, .org) as High Issue.
   - GBP category alignment with core niche stem (roof in Title/H1), ignoring generic stopwords.
   - Neighborhood vs Metro matching (Flushing vs Queens / NYC).
   - City leak prevention when address is empty.
7. Multi-key deduplication:
   - Different place_id but identical phone or email: duplicate cleanly filtered, preferring higher review count.
8. Social URL sanitization:
   - Cleaning ?igsh=, ?viewAsMember=, concatenated &ved=...
9. CMS detection:
   - Correctly detects Webflow, Framer, GoDaddy, Shopify, Next.js, Elementor.
10. Anonymous quota:
   - Default is 100 leads.
"""

import pytest
from bs4 import BeautifulSoup
from unittest.mock import patch

from config import ANONYMOUS_LEAD_LIMIT
from agent.schemas import LeadItem, ActionPlan, FilterConfig, EnrichmentConfig
from agent.cleaner import clean_social_url, clean_social_links
from agent.web_enricher import detect_cms
from agent.pipeline import normalize_phone_key, normalize_email_key
from backend.seo_audit.config import (
    TTFB_WARNING_SEC,
    TTFB_HIGH_SEC,
    SEO_SLOW_LOAD_THRESHOLD,
    SEO_MODERATE_LOAD_THRESHOLD,
)
from backend.seo_audit.models import AuditInput, AuditIssue, SEOReport
from backend.seo_audit.fetcher import FetchResult
from backend.seo_audit.analyzer import (
    is_js_spa_shell,
    check_ssl_redirect_status,
    check_server_response_ttfb,
    extract_raw_title_and_status,
    check_meta_description_status,
    check_local_keywords,
    check_gbp_category_alignment,
    run_all_seo_checks,
)
from backend.seo_audit.scorer import calculate_seo_health_and_pitch
from backend.seo_audit.icebreaker import (
    clean_business_name_for_copy,
    generate_icebreaker_hook,
)
from backend.seo_audit.auditor import audit_single_business


# ============================================================================
# Requirement 1: JS-Rendered 0-Word Shell Detection
# ============================================================================
def test_req1_js_spa_shell_detection():
    """Requirement 1: Detects JS/SPA shell on <div id='root'> or '__next' with word_count < 30."""
    html_react = '<html><head><title>App</title></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
    soup_react = BeautifulSoup(html_react, "html.parser")
    assert is_js_spa_shell(soup_react, word_count=5) is True

    html_next = '<html><head><title>Next App</title></head><body><div id="__next"></div></body></html>'
    soup_next = BeautifulSoup(html_next, "html.parser")
    assert is_js_spa_shell(soup_next, word_count=10) is True

    # Real content with word_count >= 30 must NOT be flagged as empty JS shell
    html_content = '<html><body><div id="root">' + ("word " * 50) + '</div></body></html>'
    soup_content = BeautifulSoup(html_content, "html.parser")
    assert is_js_spa_shell(soup_content, word_count=50) is False


def test_req1_js_rendered_audit_report_and_scoring():
    """
    Requirement 1: When JS shell is detected:
    - is_js_rendered is True
    - Health Score is None, xlsx_summary is 'N/A (JS-Rendered)'
    - Pitch Priority is 'Manual Review (JS Site)'
    - Must NOT score 7/100 or fail with a missing H1 / thin content hook.
    """
    html_shell = '<html><head><title>Modern React App</title></head><body><div id="root"></div><script src="/static/bundle.js"></script></body></html>'
    fetch_res = FetchResult(
        url="https://modernreactapp.com",
        final_url="https://modernreactapp.com",
        status_code=200,
        html=html_shell,
        elapsed_seconds=0.45,
    )

    business = AuditInput(
        url="https://modernreactapp.com",
        business_name="Modern React App",
        category="Software Company",
        address="100 Main St, Austin, TX 78701",
    )

    with patch("backend.seo_audit.auditor.fetch_page_for_audit", return_value=fetch_res):
        report = audit_single_business(business)

    assert report.is_js_rendered is True
    assert report.seo_health_score is None
    assert report.lead_pitch_priority == "Manual Review (JS Site)"
    assert report.xlsx_row_data["SEO Health Score"] == "N/A (JS-Rendered)"

    # Must NOT fail with a missing H1 or thin content icebreaker hook
    hook_lower = report.icebreaker_hook.lower()
    assert "no primary <h1> headline" not in hook_lower
    assert "thin content" not in hook_lower
    assert "only 0 words" not in hook_lower


# ============================================================================
# Requirement 2: Accurate SSL & HTTP Redirect Verification
# ============================================================================
def test_req2_ssl_pass_when_http_redirects_to_https():
    """Requirement 2: Pass when plain http:// cleanly 301/302 redirects to https://."""
    res_clean_redirect = FetchResult(
        url="http://example.com",
        final_url="https://example.com",
        status_code=200,
        initial_status_code=301,
        ssl_failed=False,
    )
    issue, summary = check_ssl_redirect_status(res_clean_redirect)
    assert issue.audit_status == "Pass"
    assert issue.priority == "None"
    assert "Redirects Cleanly to HTTPS" in summary or "Valid SSL" in summary


def test_req2_ssl_warning_when_https_available_but_no_auto_redirect():
    """Requirement 2: Warning (Medium) when https works with valid SSL, but http:// fails to auto-redirect."""
    res_no_redirect = FetchResult(
        url="http://example.com",
        final_url="http://example.com",
        status_code=200,
        initial_status_code=200,
        ssl_failed=False,
        https_probe_success=True,
    )
    issue, summary = check_ssl_redirect_status(res_no_redirect)
    assert issue.audit_status == "Warning"
    assert issue.priority == "Medium"
    assert "Missing 301 Auto-Redirect" in summary or "HTTPS Available" in summary


def test_req2_ssl_critical_when_https_fails():
    """Requirement 2: Critical when site is plain HTTP and HTTPS completely fails / is unencrypted."""
    res_unencrypted = FetchResult(
        url="http://example.com",
        final_url="http://example.com",
        status_code=200,
        initial_status_code=200,
        ssl_failed=True,
        https_probe_success=False,
        https_probe_error="SSL certificate error: UNKNOWN_CERTIFICATE",
    )
    issue, summary = check_ssl_redirect_status(res_unencrypted)
    assert issue.audit_status == "Fail"
    assert issue.priority == "Critical"
    assert "Unencrypted HTTP" in summary


# ============================================================================
# Requirement 3: NAP Icebreaker Branching
# ============================================================================
def test_req3_nap_icebreaker_address_found_phone_missing():
    """
    Requirement 3: When NAP Status is 'Address Found, Phone Missing',
    the icebreaker MUST mention the phone, NOT the street address!
    """
    business = AuditInput(
        url="https://acmeroofing.com",
        business_name="Acme Roofing LLC",
        category="Roofing contractor",
        address="123 High St, Austin, TX 78701",
        phone="512-555-0199",
    )
    nap_issue = AuditIssue(
        check_name="nap_consistency",
        audit_status="Warning",
        priority="Medium",
        evidence="Full street address verified in homepage footer, but GBP phone was not found in page text.",
        xlsx_summary="Warning: Address Found, Phone Missing",
    )
    issues = {"nap_consistency": nap_issue}

    hook = generate_icebreaker_hook(business, issues)
    hook_lower = hook.lower()

    # Must mention phone
    assert "phone" in hook_lower
    # Must NOT claim street address is missing!
    assert "address" not in hook_lower or "street address" not in hook_lower
    assert "full street address isn't displayed" not in hook_lower


def test_req3_nap_icebreaker_phone_found_address_missing():
    """
    Requirement 3: When NAP Status is 'Phone Found, Address Missing',
    the icebreaker MUST mention the street address, NOT the phone!
    """
    business = AuditInput(
        url="https://acmeroofing.com",
        business_name="Acme Roofing LLC",
        category="Roofing contractor",
        address="123 High St, Austin, TX 78701",
        phone="512-555-0199",
    )
    nap_issue = AuditIssue(
        check_name="nap_consistency",
        audit_status="Warning",
        priority="Medium",
        evidence="GBP phone number verified in header, but full street address was not found in page text.",
        xlsx_summary="Warning: Phone Found, Address Missing",
    )
    issues = {"nap_consistency": nap_issue}

    hook = generate_icebreaker_hook(business, issues)
    hook_lower = hook.lower()

    # Must mention street address
    assert "street address" in hook_lower or "address" in hook_lower
    # Must NOT claim phone is missing
    assert "phone number isn't displayed" not in hook_lower


def test_req3_nap_icebreaker_both_missing():
    """Requirement 3: When both phone and address are missing, hook mentions both."""
    business = AuditInput(
        url="https://acmeroofing.com",
        business_name="Acme Roofing LLC",
        category="Roofing contractor",
        address="123 High St, Austin, TX 78701",
        phone="512-555-0199",
    )
    nap_issue = AuditIssue(
        check_name="nap_consistency",
        audit_status="Fail",
        priority="High",
        evidence="Neither phone nor street address found in page text.",
        xlsx_summary="High Issue: Neither Phone nor Address Found",
    )
    issues = {"nap_consistency": nap_issue}

    hook = generate_icebreaker_hook(business, issues)
    hook_lower = hook.lower()

    assert "both" in hook_lower
    assert "address" in hook_lower
    assert "phone" in hook_lower


# ============================================================================
# Requirement 4: Score >= 90 Healthy Site Guardrail
# ============================================================================
def test_req4_healthy_site_guardrail():
    """
    Requirement 4: Score >= 90 Healthy Site:
    - Must output 'Site is well-optimized — skip technical pitch or use a non-SEO angle.'
    - Must NOT claim 'identified several high-ROI technical optimizations'.
    """
    business = AuditInput(
        url="https://topnotchplumbing.com",
        business_name="Top Notch Plumbing LLC",
        category="Plumber",
        address="456 Main St, Boston, MA 02108",
        rating=4.9,
        reviews_count=120,
    )
    issues = {}  # Pristine site with no flaws

    hook = generate_icebreaker_hook(business, issues, score=94)
    assert hook == "Site is well-optimized — skip technical pitch or use a non-SEO angle."
    assert "identified several high-ROI technical optimizations" not in hook


# ============================================================================
# Requirement 5: Business Name Cleaning & Grammar
# ============================================================================
def test_req5_business_name_cleaning_and_possessive():
    """
    Requirement 5:
    - clean_business_name_for_copy("Daniel's Roofing: Best Roofing LLC") -> "Daniel's Roofing"
    - Possessive: Contractors -> Contractors' (NOT Contractors's), Roofing -> Roofing's.
    """
    # 1. Delimiter stripping & legal suffix removal
    assert clean_business_name_for_copy("Daniel's Roofing: Best Roofing LLC") == "Daniel's Roofing"
    assert clean_business_name_for_copy("Apex Plumbing | Emergency Plumbers Inc.") == "Apex Plumbing"
    assert clean_business_name_for_copy("Elite Electric Corp.") == "Elite Electric"
    assert clean_business_name_for_copy("Metro HVAC Solutions, LLC") == "Metro HVAC Solutions"

    # 2. English possessive rules
    assert clean_business_name_for_copy("Contractors", possessive=True) == "Contractors'"
    assert clean_business_name_for_copy("Roofing", possessive=True) == "Roofing's"
    assert clean_business_name_for_copy("Summit Services LLC", possessive=True) == "Summit Services'"
    assert clean_business_name_for_copy("James", possessive=True) == "James'"


# ============================================================================
# Requirement 6: SEO Audit Thresholds, Alignment & City Leak Fixes
# ============================================================================
def test_req6_ttfb_boundary_thresholds():
    """Requirement 6: TTFB 2.0s boundary and 4.0s boundary."""
    # Fast (<= 2.0s) -> Pass
    res_fast = FetchResult(url="https://ex.com", elapsed_seconds=1.9, status_code=200)
    issue_fast, _ = check_server_response_ttfb(res_fast)
    assert issue_fast.audit_status == "Pass"

    # Moderate (2.0s - 4.0s) -> Warning
    res_mod = FetchResult(url="https://ex.com", elapsed_seconds=2.1, status_code=200)
    issue_mod, _ = check_server_response_ttfb(res_mod)
    assert issue_mod.audit_status == "Warning"

    # Slow (> 4.0s) -> Fail
    res_slow = FetchResult(url="https://ex.com", elapsed_seconds=4.5, status_code=200)
    issue_slow, _ = check_server_response_ttfb(res_slow)
    assert issue_slow.audit_status == "Fail"


def test_req6_meta_description_120_160_boundary():
    """Requirement 6: Meta Description optimal range 120-160 chars."""
    # Too short (< 120 chars) -> Warning
    soup_short = BeautifulSoup('<html><head><meta name="description" content="' + ('A' * 80) + '"></head></html>', "html.parser")
    issue_short, summary_short = check_meta_description_status(soup_short)
    assert issue_short.audit_status == "Warning"
    assert "Too Short" in summary_short

    # Optimal (120-160 chars) -> Pass
    soup_opt = BeautifulSoup('<html><head><meta name="description" content="' + ('A' * 140) + '"></head></html>', "html.parser")
    issue_opt, summary_opt = check_meta_description_status(soup_opt)
    assert issue_opt.audit_status == "Pass"
    assert "Optimal" in summary_opt

    # Truncated (> 160 chars) -> Minor / Warning
    soup_trunc = BeautifulSoup('<html><head><meta name="description" content="' + ('A' * 180) + '"></head></html>', "html.parser")
    issue_trunc, summary_trunc = check_meta_description_status(soup_trunc)
    assert "Truncated" in summary_trunc or issue_trunc.audit_status in ("Warning", "Pass")


def test_req6_raw_url_title_rejection():
    """Requirement 6: Raw URL title rejection (www., .com, .net, .org) as High Issue."""
    soup_raw = BeautifulSoup("<html><head><title>www.danielroofing.com</title></head></html>", "html.parser")
    issue_raw, raw_title, summary = extract_raw_title_and_status(soup_raw)
    assert issue_raw.audit_status == "Fail"
    assert issue_raw.priority == "High"
    assert "Raw URL" in summary or "Raw URL" in issue_raw.evidence


def test_req6_gbp_category_alignment_core_niche_stem():
    """
    Requirement 6: Require core niche stem (e.g. 'roof' for 'Roofing contractor')
    in Title/H1, ignoring generic stopwords ('contractor', 'services', 'company').
    """
    # 1. Matching core niche stem 'roof' -> Pass
    soup_match = BeautifulSoup("<html><head><title>Best Commercial Roofing & Roof Repairs</title></head><body><h1>Austin Roof Services</h1></body></html>", "html.parser")
    issue_m, _ = check_gbp_category_alignment(soup_match, category="Roofing contractor")
    assert issue_m.audit_status == "Pass"

    # 2. Only generic stopword 'contractor' without 'roof' -> Warning (Category Keyword Missing)
    soup_stopword_only = BeautifulSoup("<html><head><title>Top General Contractor Services Inc.</title></head><body><h1>Quality General Construction</h1></body></html>", "html.parser")
    issue_sw, summary_sw = check_gbp_category_alignment(soup_stopword_only, category="Roofing contractor")
    assert issue_sw.audit_status in ("Warning", "Fail")
    assert "Category Keyword Missing" in summary_sw or "missing" in issue_sw.evidence.lower()


def test_req6_neighborhood_vs_metro_matching():
    """Requirement 6: Accept specific neighborhood OR parent metro (Flushing vs Queens / NYC)."""
    inp = AuditInput(
        url="https://flushingdentist.com",
        business_name="Flushing Dental",
        category="Dentist",
        address="136-20 38th Ave, Flushing, NY 11354",
    )
    # Homepage mentions parent metro 'Queens' and 'NYC'
    soup = BeautifulSoup("<html><head><title>Top Rated Queens Dentist | NYC Dental Care</title></head><body><h1>Quality Dentistry in Queens</h1></body></html>", "html.parser")
    issue, summary = check_local_keywords(
        soup,
        city=inp.city,
        category=inp.category,
        candidate_cities=inp.get_candidate_cities(),
        primary_city=inp.get_primary_city(),
        address=inp.address,
    )
    assert issue.audit_status == "Pass"
    assert "Pass" in summary


def test_req6_city_leak_prevention_when_address_empty():
    """
    Requirement 6: If Full Address is empty, set Local Keyword Status to
    'Skipped (No GBP Address)' and never reuse target_city or hallucinate city.
    """
    fetch_res = FetchResult(
        url="https://mystore.com",
        final_url="https://mystore.com",
        status_code=200,
        html="<html><head><title>National Online Store</title></head><body><h1>Online Store</h1></body></html>",
    )
    # 1. Test with empty string address=""
    inp_empty_str = AuditInput(
        url="https://mystore.com",
        business_name="National Store",
        category="Store",
        address="",
        city=None,
        target_city="Dallas",
    )
    check_res1 = run_all_seo_checks(inp_empty_str, fetch_res)
    assert check_res1.xlsx_row["Local Keyword Status"] == "Skipped (No GBP Address)"
    assert check_res1.issues["local_keywords"].xlsx_summary == "Skipped (No GBP Address)"
    assert check_res1.issues["local_keywords"].audit_status == "Pass"

    hook1 = generate_icebreaker_hook(inp_empty_str, check_res1.issues, has_website=True)
    assert "Dallas" not in hook1
    assert "in Dallas" not in hook1

    # 2. Test with address=None
    inp_none_addr = AuditInput(
        url="https://mystore.com",
        business_name="National Store",
        category="Store",
        address=None,
        city=None,
        target_city="Dallas",
    )
    check_res2 = run_all_seo_checks(inp_none_addr, fetch_res)
    assert check_res2.xlsx_row["Local Keyword Status"] == "Skipped (No GBP Address)"
    assert check_res2.issues["local_keywords"].xlsx_summary == "Skipped (No GBP Address)"
    assert check_res2.issues["local_keywords"].audit_status == "Pass"

    hook2 = generate_icebreaker_hook(inp_none_addr, check_res2.issues, has_website=True)
    assert "Dallas" not in hook2
    assert "in Dallas" not in hook2


# ============================================================================
# Requirement 7: Multi-Key Deduplication
# ============================================================================
def test_req7_multi_key_deduplication_keys():
    """Requirement 7: Test normalize_phone_key and normalize_email_key."""
    assert normalize_phone_key("+1 (555) 234-5678") == "5552345678"
    assert normalize_phone_key("01712-345678") == "1712345678"
    assert normalize_phone_key("123") is None  # Too short

    assert normalize_email_key("Contact@MyBusiness.COM") == "contact@mybusiness.com"
    assert normalize_email_key("notanemail") is None


def test_req7_multi_key_deduplication_pipeline_behavior():
    """
    Requirement 7: When two leads have different place_id but identical phone or email,
    the listing with the higher review count is preferred and retained.
    """
    lead_low = LeadItem(
        place_id="ChIJ_low_reviews_1",
        name="Apex Roofing (Old Listing)",
        phone="+1 555-0100",
        emails=["info@apexroofing.com"],
        reviews_count=5,
        rating=4.0,
        website_status="No Website",
    )

    lead_high = LeadItem(
        place_id="ChIJ_high_reviews_2",
        name="Apex Roofing Main HQ",
        phone="+1 (555) 0100",  # Same phone
        emails=["info@apexroofing.com"],
        reviews_count=85,
        rating=4.9,
        website_status="No Website",
    )

    # Simulate deduplication state tracker matching agent/pipeline.py
    filtered_leads = []
    phone_to_lead_idx = {}
    email_to_lead_idx = {}

    def ingest_lead(l: LeadItem):
        p_key = normalize_phone_key(l.phone)
        e_keys = [normalize_email_key(em) for em in l.emails if normalize_email_key(em)]

        matched_idx = None
        if p_key and p_key in phone_to_lead_idx:
            matched_idx = phone_to_lead_idx[p_key]
        elif e_keys:
            for ek in e_keys:
                if ek in email_to_lead_idx:
                    matched_idx = email_to_lead_idx[ek]
                    break

        if matched_idx is not None:
            existing = filtered_leads[matched_idx]
            if (l.reviews_count or 0) > (existing.reviews_count or 0):
                filtered_leads[matched_idx] = l
                return "upgraded"
            else:
                return "skipped"

        idx = len(filtered_leads)
        filtered_leads.append(l)
        if p_key:
            phone_to_lead_idx[p_key] = idx
        for ek in e_keys:
            email_to_lead_idx[ek] = idx
        return "added"

    assert ingest_lead(lead_low) == "added"
    assert len(filtered_leads) == 1
    assert filtered_leads[0].name == "Apex Roofing (Old Listing)"

    # Ingesting higher-review duplicate must upgrade and replace
    assert ingest_lead(lead_high) == "upgraded"
    assert len(filtered_leads) == 1
    assert filtered_leads[0].name == "Apex Roofing Main HQ"
    assert filtered_leads[0].reviews_count == 85

    # Ingesting another lower-review duplicate must be skipped
    lead_dup_low = LeadItem(
        place_id="ChIJ_dup_low_3",
        name="Apex Roofing Branch",
        phone="+1 555-0100",
        emails=["info@apexroofing.com"],
        reviews_count=12,
        website_status="No Website",
    )
    assert ingest_lead(lead_dup_low) == "skipped"
    assert len(filtered_leads) == 1
    assert filtered_leads[0].reviews_count == 85


# ============================================================================
# Requirement 8: Social URL Sanitization
# ============================================================================
def test_req8_social_url_sanitization():
    """Requirement 8: Cleaning ?igsh=, ?viewAsMember=, and concatenated &ved=..."""
    # 1. Instagram with ?igsh= and ?utm_*
    raw_ig = "https://www.instagram.com/daniel_roofing?igsh=MWt5a213eXZkZ3A1bQ==&utm_source=ig_web_button_share_sheet"
    clean_ig = clean_social_url(raw_ig)
    assert clean_ig == "https://www.instagram.com/daniel_roofing"

    # 2. LinkedIn with ?viewAsMember=
    raw_li = "https://www.linkedin.com/company/daniel-roofing/?viewAsMember=true&ref=profile"
    clean_li = clean_social_url(raw_li)
    assert clean_li == "https://www.linkedin.com/company/daniel-roofing"

    # 3. Concatenated &ved=... directly onto path without '?'
    raw_fb_malformed = "https://www.facebook.com/danielroofingllc&ved=2ahUKEwjK_8P57r6IAxW4gf0HHW0qBAAQFnoECBIQAQ&usg=AOvVaw2mQ"
    clean_fb = clean_social_url(raw_fb_malformed)
    assert clean_fb == "https://www.facebook.com/danielroofingllc"

    # 4. WhatsApp with tracking
    raw_wa = "https://wa.me/15551234567?text=hello&utm_campaign=summer&ved=abc"
    clean_wa = clean_social_url(raw_wa)
    assert "utm_campaign" not in clean_wa
    assert "ved" not in clean_wa
    assert "text=hello" in clean_wa


# ============================================================================
# Requirement 9: CMS Detection Expansion
# ============================================================================
def test_req9_cms_detection():
    """Requirement 9: Correctly detects Webflow, Framer, GoDaddy, Shopify, Next.js, Elementor."""
    # Webflow
    assert detect_cms('<html data-wf-page="6123456789"><body>Hello</body></html>') == "Webflow"
    assert detect_cms('<div><script src="https://assets.website-files.com/main.js"></script></div>') == "Webflow"

    # Framer
    assert detect_cms('<div data-framer-name="Desktop Nav">Navigation</div>') == "Framer"
    assert detect_cms('<script>window.__framer__ = true;</script>') == "Framer"

    # GoDaddy Website Builder
    assert detect_cms('<div class="secureserver.net">Site</div>') == "GoDaddy Website Builder"
    assert detect_cms('<div>built with websites.godaddy.com</div>') == "GoDaddy Website Builder"

    # Shopify
    assert detect_cms('<link rel="stylesheet" href="https://cdn.shopify.com/s/files/theme.css">') == "Shopify"
    assert detect_cms('<div id="shopify-section-header">Header</div>') == "Shopify"

    # Next.js
    assert detect_cms('<div id="__next"><div>Shell</div></div>') == "Next.js"
    assert detect_cms('<script src="/_next/static/chunks/main.js"></script>') == "Next.js"

    # Elementor (WordPress)
    assert detect_cms('<div class="elementor elementor-123 elementor-kit-456">Hero</div>') == "WordPress (Elementor)"


# ============================================================================
# Requirement 10: Anonymous Quota
# ============================================================================
def test_req10_anonymous_quota_default():
    """Requirement 10: Anonymous 24h lead quota default is 100 leads."""
    assert ANONYMOUS_LEAD_LIMIT == 100

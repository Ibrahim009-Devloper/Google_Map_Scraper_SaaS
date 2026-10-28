"""
Comprehensive test suite for the 8 SEO Scraper & Audit Engine Improvements:
1. Decoupled Lead Priority vs SEO Health Score (No blanket Critical tagging).
2. False Positive Prevention (Multiple H1 HTML5 layout, self-referencing canonicals, sitemaps).
3. Graceful handling of missing/failed/unreachable sites ("Not Tested", score=None, never automatic 0).
4. Evidence validation (HTTPS, redirects, indexability, mobile usability, TTFB).
5. AuditIssue schema validation (Evidence URL, Severity, Confidence, Recommended Fix).
6. Domain deduplication by normalized domain & business category relevancy filtering.
"""

import pytest
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from backend.seo_audit.models import AuditIssue, AuditInput, SEOReport
from backend.seo_audit.scorer import calculate_seo_health_and_pitch
from backend.seo_audit.fetcher import FetchResult
from backend.seo_audit.analyzer import (
    extract_raw_h1_and_status,
    check_canonical_tag,
    check_indexability_meta_robots,
    run_all_seo_checks,
    matches_category_synonyms,
)
from backend.seo_audit.auditor import audit_single_business, extract_root_domain
from agent.schemas import LeadItem, ActionPlan, FilterConfig, EnrichmentConfig
from agent.pipeline import filter_lead, is_lead_category_relevant


def test_1_lead_priority_and_health_score_decoupling():
    """Requirement 1: Do NOT mark every lead as Critical; health score and lead pitch priority are distinct."""
    # A site with moderate flaws (health score 70) without severe indexing blockers
    issues = {
        "title_tag": AuditIssue(
            check_name="title_tag",
            audit_status="Warning",
            priority="Low",
            evidence="Title tag could be improved",
            evidence_url="https://example.com",
            xlsx_summary="Warning: Short Title",
        ),
        "word_count": AuditIssue(
            check_name="word_count",
            audit_status="Warning",
            priority="Low",
            evidence="250 words",
            evidence_url="https://example.com",
            xlsx_summary="Warning: Thin Content",
        ),
    }

    score, priority = calculate_seo_health_and_pitch(issues, has_website=True, is_https=True)
    assert score is not None
    assert score >= 70
    # Should NOT be Critical Pitch!
    assert priority != "Critical Pitch"
    assert priority in ("Moderate", "Low Priority (Healthy Site)", "Low Priority - Well Optimized")

    # Only severe blockers trigger Critical Pitch
    issues_critical = dict(issues)
    issues_critical["meta_robots"] = AuditIssue(
        check_name="meta_robots",
        audit_status="Fail",
        priority="Critical",
        evidence="Found <meta name='robots' content='noindex'>. Page blocked.",
        evidence_url="https://example.com",
        xlsx_summary="Critical: noindex Tag Present",
    )
    score_crit, priority_crit = calculate_seo_health_and_pitch(issues_critical, has_website=True, is_https=True)
    assert priority_crit == "Critical Pitch"


def test_2_multiple_h1_false_positive_prevention():
    """Requirement 2: In modern HTML5, 2 distinct H1 tags (e.g. brand + page heading) should pass."""
    html_2_h1 = """
    <html>
        <body>
            <header><h1>Miami Dental Care</h1></header>
            <main><h1>Top Cosmetic & Family Dentistry in Miami, FL</h1></main>
        </body>
    </html>
    """
    soup = BeautifulSoup(html_2_h1, "html.parser")
    issue, primary_h1, summary = extract_raw_h1_and_status(soup)
    assert issue.audit_status == "Pass"
    assert "Multi-Section Layout" in summary
    assert "Miami Dental Care" in primary_h1


def test_2_canonical_tag_false_positive_prevention():
    """Requirement 2: Canonical tag with trailing slash or normalized www should pass as self-referencing."""
    html = '<html><head><link rel="canonical" href="https://example.com/" /></head></html>'
    soup = BeautifulSoup(html, "html.parser")
    fetch_res = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html=html,
    )
    issue, summary = check_canonical_tag(soup, fetch_res)
    assert issue.audit_status == "Pass"
    assert summary == "Pass: Self-Referencing"

    # Cross-domain canonical should still be flagged as critical
    html_cross = '<html><head><link rel="canonical" href="https://otherdomain.com/" /></head></html>'
    soup_cross = BeautifulSoup(html_cross, "html.parser")
    issue_cross, summary_cross = check_canonical_tag(soup_cross, fetch_res)
    assert issue_cross.audit_status == "Fail"
    assert "Points to Different Domain" in summary_cross


def test_3_missing_or_unreachable_data_handled_as_not_tested():
    """Requirement 3: Never treat missing/failed test data as an SEO failure or assign 0 score automatically; use 'Not Tested'."""
    unreachable_fetch = FetchResult(
        url="https://unreachable-example-site-12345.com",
        final_url="https://unreachable-example-site-12345.com",
        status_code=None,
        html="",
        error_message="Connection timed out after 10 seconds",
    )
    input_data = AuditInput(
        url="https://unreachable-example-site-12345.com",
        business_name="Unreachable Clinic",
        category="Dentist",
    )
    res = run_all_seo_checks(input_data, unreachable_fetch)

    # All DOM checks must be Unverified, not Fail
    for check_name in ("meta_robots", "canonical_tag", "title_tag", "h1_status", "schema_markup"):
        assert res.issues[check_name].audit_status == "Unverified"
        assert res.xlsx_row[res.issues[check_name].check_name.replace("_", " ").title() if False else "Canonical Tag Status" if check_name == "canonical_tag" else "Title Tag Status" if check_name == "title_tag" else "H1 Tag Status" if check_name == "h1_status" else "Schema Status" if check_name == "schema_markup" else "Indexability (Meta Robots)"] == "Not Tested"

    # Full audit report must output "Not Tested", score must be None (never 0)
    report = audit_single_business(input_data, use_cache=False)
    assert report.seo_health_score is None
    assert report.lead_pitch_priority == "Not Tested"
    assert report.xlsx_row_data["SEO Health Score"] == "Not Tested"
    assert report.xlsx_row_data["Lead Pitch Priority"] == "Not Tested"


def test_4_evidence_fields_in_audit_issue():
    """Requirement 5: Add Evidence URL, Severity, Confidence and Recommended Fix to AuditIssue."""
    issue = AuditIssue(
        check_name="ssl_redirect",
        audit_status="Fail",
        severity="High",
        confidence="High",
        evidence_url="http://insecure-site.com",
        evidence="Website is served over plain unencrypted HTTP.",
        recommended_fix="Install SSL certificate and 301 redirect HTTP to HTTPS.",
        xlsx_summary="Critical: Unencrypted HTTP",
    )

    assert issue.evidence_url == "http://insecure-site.com"
    assert issue.severity == "High"
    assert issue.confidence == "High"
    assert issue.priority == "High"  # Auto-synced
    assert issue.recommended_fix is not None


def test_6_domain_deduplication_and_category_filtering():
    """Requirement 6: Deduplicate leads by normalized domain and filter irrelevant business categories."""
    plan = ActionPlan(
        user_prompt="Find dental clinics in Miami",
        keywords=["Dentist", "Dental clinic"],
        sub_locations=[],
        filters=FilterConfig(),
        enrichment=EnrichmentConfig(),
    )

    # 1. Relevant category passes
    dentist_lead = LeadItem(
        place_id="pl_1",
        name="Dr. Smith Cosmetic Dentistry",
        category="Dentist",
        website_status="Has Own Website",
        website_url="https://smithdental.com",
    )
    assert filter_lead(dentist_lead, plan) is True

    # 2. Irrelevant category is rejected
    gas_station_lead = LeadItem(
        place_id="pl_2",
        name="Chevron Gas & Food Mart",
        category="Gas station",
        website_status="Has Own Website",
        website_url="https://chevrongas.com",
    )
    assert filter_lead(gas_station_lead, plan) is False

    # 3. Normalized root domain extraction
    d1 = extract_root_domain("https://www.smithdental.com/contact-us")
    d2 = extract_root_domain("http://smithdental.com/")
    assert d1 == d2 == "smithdental.com"


def test_edge_case_1_robots_and_sitemap_detection(monkeypatch):
    """Edge Case 1: Check robots.txt and sitemap parsing with browser headers & origin handling."""
    from backend.seo_audit.fetcher import check_robots_and_sitemap
    from curl_cffi import requests as curl_requests

    class MockResp:
        def __init__(self, status, text, headers):
            self.status_code = status
            self.text = text
            self.headers = headers

    def mock_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return MockResp(200, "User-agent: *\nDisallow: /wp-admin/\nSitemap: https://wordpress-site.com/sitemap.xml", {"content-type": "text/plain"})
        if url.endswith("/sitemap.xml"):
            return MockResp(200, "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'></urlset>", {"content-type": "application/xml"})
        return MockResp(404, "Not Found", {})

    monkeypatch.setattr(curl_requests, "get", mock_get)

    has_robots, has_sitemap = check_robots_and_sitemap("https://wordpress-site.com/subpage")
    assert has_robots is True
    assert has_sitemap is True


def test_edge_case_2_lead_pitch_priority_thresholds():
    """Edge Case 2: Strict Lead Pitch Priority classification (Stop marking 88/100 and 81/100 as Critical)."""
    # 88/100 on HTTPS without noindex -> Low Priority (Healthy Site)
    score, priority = calculate_seo_health_and_pitch({}, has_website=True, is_https=True)
    # When issues has minimal penalties yielding 88
    issues_88 = {
        "title_tag": AuditIssue(check_name="title_tag", audit_status="Warning", priority="Low", evidence="Minor", xlsx_summary="Minor")
    }
    s88, p88 = calculate_seo_health_and_pitch(issues_88, has_website=True, is_https=True)
    assert s88 >= 85
    assert p88 == "Low Priority (Healthy Site)"

    # 81/100 on HTTPS without noindex -> Moderate
    issues_81 = {
        "title_tag": AuditIssue(check_name="title_tag", audit_status="Fail", priority="High", evidence="Too short", xlsx_summary="Short"),
        "meta_description": AuditIssue(check_name="meta_description", audit_status="Warning", priority="Low", evidence="Short", xlsx_summary="Short")
    }
    s81, p81 = calculate_seo_health_and_pitch(issues_81, has_website=True, is_https=True)
    assert 70 <= s81 < 85
    assert p81 == "Moderate"

    # 65/100 on HTTPS without noindex -> High Value
    issues_65 = {
        "title_tag": AuditIssue(check_name="title_tag", audit_status="Fail", priority="High", evidence="Too short", xlsx_summary="Short"),
        "h1_status": AuditIssue(check_name="h1_status", audit_status="Fail", priority="High", evidence="Missing H1", xlsx_summary="Missing"),
        "schema_markup": AuditIssue(check_name="schema_markup", audit_status="Fail", priority="High", evidence="Missing", xlsx_summary="Missing"),
    }
    s65, p65 = calculate_seo_health_and_pitch(issues_65, has_website=True, is_https=True)
    assert 50 <= s65 < 70
    assert p65 == "High Value"

    # Unencrypted HTTP -> Critical Pitch
    s_http, p_http = calculate_seo_health_and_pitch(issues_88, has_website=True, is_https=False)
    assert p_http == "Critical Pitch"


def test_edge_case_3_decoupled_schema_and_address_icebreaker_hooks():
    """Edge Case 3: Decouple Schema Missing vs. Street Address Missing in AI Icebreaker Hook."""
    from backend.seo_audit.icebreaker import generate_icebreaker_hook

    biz = AuditInput(
        url="https://plumbingsite.com",
        business_name="Apex Plumbing",
        category="Plumber",
        city="Wilmington",
        address="123 Market St, Wilmington, DE 19801",
    )

    # 1. Both Missing
    issues_both = {
        "schema_markup": AuditIssue(check_name="schema_markup", audit_status="Fail", evidence="No schema", xlsx_summary="No Schema"),
        "nap_consistency": AuditIssue(check_name="nap_consistency", audit_status="Fail", evidence="Street address missing in HTML", xlsx_summary="Missing Address"),
    }
    hook_both = generate_icebreaker_hook(biz, issues_both, has_website=True)
    assert "both your street address and Plumber LocalBusiness JSON-LD schema are missing" in hook_both

    # 2. Only Schema Missing (Address Present in HTML)
    issues_only_schema = {
        "schema_markup": AuditIssue(check_name="schema_markup", audit_status="Fail", evidence="No schema", xlsx_summary="No Schema"),
        "nap_consistency": AuditIssue(check_name="nap_consistency", audit_status="Pass", evidence="Full NAP Match", xlsx_summary="Pass"),
    }
    hook_schema = generate_icebreaker_hook(biz, issues_only_schema, has_website=True)
    assert "missing Plumber LocalBusiness JSON-LD schema markup" in hook_schema
    assert "both your street address" not in hook_schema

    # 3. Only Street Address Missing (Valid Schema Present)
    issues_only_addr = {
        "schema_markup": AuditIssue(check_name="schema_markup", audit_status="Pass", evidence="LocalBusiness schema verified", xlsx_summary="Pass"),
        "nap_consistency": AuditIssue(check_name="nap_consistency", audit_status="Fail", evidence="Street address missing from HTML", xlsx_summary="Missing Address"),
    }
    hook_addr = generate_icebreaker_hook(biz, issues_only_addr, has_website=True)
    assert "full street address isn't displayed in the homepage text" in hook_addr
    assert "schema are missing" not in hook_addr


def test_edge_case_4_phone_domain_and_agency_email_filters():
    """Edge Case 4: Reject phone-number domains, invalid TLDs, and 3rd-party web design agency footer emails."""
    from agent.web_enricher import is_valid_email, select_best_single_email, is_third_party_agency_email

    # 1. Reject phone disguised as domain
    assert is_valid_email("inc.directly@302.221.4200.name") is False
    assert is_valid_email("reached@708-633-9614.reach") is False

    # 2. Reject non-email file / dummy extensions
    assert is_valid_email("user@company.local") is False
    assert is_valid_email("user@company.name") is False
    assert is_valid_email("user@company.test") is False
    assert is_valid_email("image@website.png") is False
    assert is_valid_email("bundle@website.js") is False

    # 3. Agency / Third-Party Email Filter
    # contact@sansoxygen.com on pinnacleplumbingde.com -> 3rd-party agency!
    assert is_third_party_agency_email("contact@sansoxygen.com", "https://pinnacleplumbingde.com", business_name="Pinnacle Plumbing") is True

    # Matching domain email allowed
    assert is_third_party_agency_email("service@pinnacleplumbingde.com", "https://pinnacleplumbingde.com", business_name="Pinnacle Plumbing") is False

    # Consumer ISP email allowed
    assert is_third_party_agency_email("pinnacleplumbing@gmail.com", "https://pinnacleplumbingde.com", business_name="Pinnacle Plumbing") is False

    # select_best_single_email chooses authentic company email over agency footer email
    emails = {"contact@sansoxygen.com", "info@pinnacleplumbingde.com"}
    best = select_best_single_email(emails, "https://pinnacleplumbingde.com", business_name="Pinnacle Plumbing")
    assert best == ["info@pinnacleplumbingde.com"]


def test_edge_case_5_html_text_spacing_and_newline_normalization():
    """Edge Case 5: Ensure child tags extract with spaces and newlines are normalized."""
    from backend.seo_audit.analyzer import extract_raw_title_and_status, extract_raw_h1_and_status

    html = """
    <html>
        <head>
            <title>Wilmington's&#160;Trusted&#10;Plumbers\n&amp; Drain Experts</title>
        </head>
        <body>
            <h1><span>Wilmington's Trusted</span>Plumbers&nbsp;&amp;<span>Drain Experts</span></h1>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    _, raw_title, _ = extract_raw_title_and_status(soup, city="Wilmington", category="Plumber")
    _, raw_h1, _ = extract_raw_h1_and_status(soup)

    # Check that words are not glued together
    assert "Trusted Plumbers" in raw_h1 or "Trusted" in raw_h1 and "Plumbers" in raw_h1
    assert "TrustedPlumbers" not in raw_h1
    assert "\n" not in raw_title
    assert "\n" not in raw_h1


def test_edge_case_6_missing_target_city_fallback_for_service_area_businesses():
    """Edge Case 6: Automatically infer default_search_city from batch mode for Service Area Businesses with no address."""
    from backend.seo_audit.auditor import audit_bulk_businesses, infer_default_city_from_inputs

    inputs = [
        AuditInput(url="https://site1.com", business_name="Biz 1", category="Plumber", address="100 Main St, Wilmington, DE 19801"),
        AuditInput(url="https://site2.com", business_name="Biz 2", category="Plumber", address="200 Market St, Wilmington, DE 19801"),
        AuditInput(url="https://site3.com", business_name="Biz 3", category="Plumber", address="300 King St, Wilmington, DE 19801"),
        AuditInput(url="https://site4.com", business_name="Biz 4", category="Plumber", address=""), # Service Area Business without address
    ]

    # Inferred mode city is Wilmington
    default_city = infer_default_city_from_inputs(inputs)
    assert default_city == "Wilmington"

    # In bulk audit, Biz 4 gets assigned Wilmington as target_city
    reports = audit_bulk_businesses(inputs)
    assert inputs[3].target_city == "Wilmington"
    assert inputs[3].get_primary_city() == "Wilmington"



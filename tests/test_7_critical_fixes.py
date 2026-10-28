"""
Comprehensive Verification Suite for the 7 Critical SEO Audit & Scraper Logic Fixes.
"""

import pytest
from bs4 import BeautifulSoup

from backend.seo_audit.models import AuditInput, AuditIssue
from backend.seo_audit.analyzer import (
    truncate_preview,
    extract_flattened_schema_types,
    matches_category_synonyms,
    check_local_keywords,
    check_gbp_category_alignment,
    check_schema_status,
    extract_raw_title_and_status,
    check_robots_and_sitemap as analyzer_check_robots_and_sitemap,
)
from backend.seo_audit.fetcher import FetchResult, check_robots_and_sitemap as fetcher_check_robots_and_sitemap
from backend.seo_audit.icebreaker import generate_icebreaker_hook
from agent.web_enricher import is_valid_email, is_valid_social_url, is_directory_or_franchise_subpage


# ============================================================================
# Fix #1: Target City Extraction & Fallback Logic
# ============================================================================
def test_fix1_city_extraction_and_fallback():
    # 1. Standard US address extraction
    inp1 = AuditInput(
        url="https://example.com",
        address="50 Euston St, Brookline, MA 02446",
        city=None,
        target_city="Boston",
    )
    assert inp1.get_actual_city() == "Brookline"
    assert "brookline" in [c.lower() for c in inp1.get_candidate_cities()]
    assert "boston" in [c.lower() for c in inp1.get_candidate_cities()]
    assert inp1.get_primary_city() == "Brookline"

    # 2. Generic neighborhood label like 'Downtown' overridden by actual city
    inp2 = AuditInput(
        url="https://example.com",
        address="100 State St, Boston, MA 02109",
        city="Downtown",
        target_city="Boston",
    )
    assert inp2.get_actual_city() == "Boston"
    assert inp2.city == "Boston"

    # 3. Local keywords check passes if either actual city OR metro city matches
    soup = BeautifulSoup("<html><head><title>Top Plumber in Boston MA</title></head><body><h1>Best Plumbing</h1></body></html>", "html.parser")
    issue, summary = check_local_keywords(
        soup=soup,
        category="Plumber",
        candidate_cities=inp1.get_candidate_cities(),
        primary_city=inp1.get_primary_city(),
    )
    assert issue.audit_status == "Pass"
    assert 'Pass: City ("Brookline") & Category ("Plumber") Found in Title/H1' in summary

    # 4. Never evaluate against empty string ""
    inp_empty = AuditInput(url="https://example.com", address="", city="", target_city="")
    assert inp_empty.get_candidate_cities() == []
    issue_empty, summary_empty = check_local_keywords(
        soup=soup,
        category="Plumber",
        candidate_cities=inp_empty.get_candidate_cities(),
        primary_city=inp_empty.get_primary_city(),
    )
    assert 'Target City ("")' not in summary_empty


# ============================================================================
# Fix #2: GBP Category & Local Keyword Stemming / Synonym Matching
# ============================================================================
def test_fix2_category_stemming_and_synonyms():
    # Plumber matches Plumbing
    assert matches_category_synonyms("Plumber", "Welcome to ABC Plumbing and Drain Service") is True
    assert matches_category_synonyms("Plumber", "Emergency Rooter and Pipe Repair") is True

    # HVAC Contractor matches Heating and Cooling / Air Conditioning
    assert matches_category_synonyms("HVAC Contractor", "Residential Heating & Air Conditioning Repair") is True

    # Dentist matches Dental Clinic / Dentistry
    assert matches_category_synonyms("Dentist", "Advanced Family Dental & Orthodontics") is True

    # Unlisted category root stem matching
    assert matches_category_synonyms("Landscaper", "Professional Landscaping & Garden Services") is True

    # GBP Category Alignment Check
    soup_plumb = BeautifulSoup("<html><head><title>Boston Plumbing Experts</title></head><body><h1>Local Drain Cleaning</h1></body></html>", "html.parser")
    issue, summary = check_gbp_category_alignment(soup_plumb, category="Plumber")
    assert issue.audit_status == "Pass"
    assert "Pass: Category 'Plumber' aligned with Title/H1" in summary


# ============================================================================
# Fix #3: XML Sitemap & Robots.txt Detection
# ============================================================================
def test_fix3_sitemap_and_robots_detection(monkeypatch):
    # Test output format rules in analyzer
    res_both = FetchResult(url="https://example.com", status_code=200, has_robots=True, has_sitemap=True)
    _, s_both = analyzer_check_robots_and_sitemap(res_both)
    assert s_both == "Pass: robots.txt & XML Sitemap Verified"

    res_only_robots = FetchResult(url="https://example.com", status_code=200, has_robots=True, has_sitemap=False)
    _, s_only_robots = analyzer_check_robots_and_sitemap(res_only_robots)
    assert s_only_robots == "Warning: robots.txt Present, XML Sitemap Missing"

    res_only_sitemap = FetchResult(url="https://example.com", status_code=200, has_robots=False, has_sitemap=True)
    _, s_only_sitemap = analyzer_check_robots_and_sitemap(res_only_sitemap)
    assert s_only_sitemap == "Pass: XML Sitemap Verified (No robots.txt)"

    res_neither = FetchResult(url="https://example.com", status_code=200, has_robots=False, has_sitemap=False)
    _, s_neither = analyzer_check_robots_and_sitemap(res_neither)
    assert s_neither == "High Issue: Both robots.txt & XML Sitemap Missing"

    # Test sequential probe in fetcher
    class MockResp:
        def __init__(self, status, text, headers):
            self.status_code = status
            self.text = text
            self.headers = headers

    def mock_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return MockResp(200, "User-agent: *\nAllow: /", {})
        if url.endswith("/sitemap_index.xml"):
            return MockResp(200, "<?xml version='1.0'?><sitemapindex></sitemapindex>", {"content-type": "text/xml"})
        return MockResp(404, "Not Found", {})

    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests, "get", mock_get)

    has_robots, has_sitemap = fetcher_check_robots_and_sitemap("https://example.com")
    assert has_robots is True
    assert has_sitemap is True


# ============================================================================
# Fix #4: Filter Out Website Builder, Agency & Directory Socials/Emails
# ============================================================================
def test_fix4_blacklists_and_directory_detection():
    # 1. Social URL blacklist
    assert is_valid_social_url("https://facebook.com/WixStudio") is False
    assert is_valid_social_url("https://instagram.com/wix") is False
    assert is_valid_social_url("https://facebook.com/sharer/sharer.php?u=foo") is False
    assert is_valid_social_url("https://instagram.com/p/B1234567") is False
    assert is_valid_social_url("https://facebook.com/myrealplumbingbiz") is True

    # 2. Email domain blacklist
    assert is_valid_email("info@wix.com") is False
    assert is_valid_email("support@ndiscovered.com") is False
    assert is_valid_email("contact@hibu.com") is False
    assert is_valid_email("contact@realplumbingboston.com") is True

    # 3. Directory / Aggregator detection
    assert is_directory_or_franchise_subpage("https://www.rheem.com/find-a-plumber/florida/miami/abc-plumbing") is True
    assert is_directory_or_franchise_subpage("https://www.1800dentist.com/dentists/dr-smith-123") is True
    assert is_directory_or_franchise_subpage("https://www.yelp.com/biz/local-roofing-dallas") is True
    assert is_directory_or_franchise_subpage("https://www.bostoneliteplumbing.com/about-us") is False


# ============================================================================
# Fix #5: Flatten & Deduplicate JSON-LD Schema @type Output
# ============================================================================
def test_fix5_schema_type_flattening_and_formatting():
    raw_data = [
        {"@type": "http://schema.org/SiteNavigationElement"},
        {"@graph": [
            {"@type": ["Plumber", "https://schema.org/LocalBusiness"]},
            {"@type": "FAQPage"},
            {"@type": "Plumber"}  # Duplicate
        ]}
    ]
    types = extract_flattened_schema_types(raw_data)
    # Deduplicate while preserving order
    seen = set()
    deduped = [t for t in types if not (t in seen or seen.add(t))]
    assert deduped == ["SiteNavigationElement", "Plumber", "LocalBusiness", "FAQPage"]

    html = """<html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@graph": [
        {"@type": ["Plumber", "LocalBusiness"]},
        {"@type": "FAQPage"}
      ]
    }
    </script>
    </head><body></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    issue, summary = check_schema_status(soup, category="Plumber")
    assert issue.audit_status == "Pass"
    assert summary == "Pass: LocalBusiness JSON-LD Present (Plumber, LocalBusiness, FAQPage)"
    assert "[" not in summary and "]" not in summary


# ============================================================================
# Fix #6: Consistent Title Tag Length Thresholds & Snippet Formatting
# ============================================================================
def test_fix6_title_length_rules_and_truncation():
    # Helper truncation
    assert truncate_preview("Short Title", max_len=35) == "Short Title"
    assert truncate_preview("This is a very long title exceeding thirty-five characters easily", max_len=35) == "This is a very long title exceeding..."

    # 0 chars (missing)
    soup_empty = BeautifulSoup("<html><head><title></title></head></html>", "html.parser")
    _, _, s0 = extract_raw_title_and_status(soup_empty)
    assert s0 == "Critical On-Page: Missing <title> Tag"

    # 1 - 29 chars
    soup_short = BeautifulSoup("<html><head><title>Gentille Plumbing</title></head></html>", "html.parser")
    _, _, s_short = extract_raw_title_and_status(soup_short)
    assert s_short == 'High Issue: Too Short (17 chars: "Gentille Plumbing") - Missing Keyword & City'
    assert "..." not in s_short

    # 30 - 60 chars (Optimal)
    title_45 = "Gentille Plumbing | 24/7 Plumber Boston MA"
    soup_opt = BeautifulSoup(f"<html><head><title>{title_45}</title></head></html>", "html.parser")
    _, _, s_opt = extract_raw_title_and_status(soup_opt)
    assert s_opt == f'Pass: Optimal ({len(title_45)} chars: "{truncate_preview(title_45, 35)}")'

    # 61+ chars (Warning)
    title_68 = "Gentille Plumbing & Heating Services in Boston MA and Surrounding Metro"
    soup_warn = BeautifulSoup(f"<html><head><title>{title_68}</title></head></html>", "html.parser")
    _, _, s_warn = extract_raw_title_and_status(soup_warn)
    assert s_warn == f'Warning: {len(title_68)} chars ("{truncate_preview(title_68, 35)}") - SERP Truncation Risk (> 60 chars)'


# ============================================================================
# Fix #7: Dynamic Icebreaker Hook Hallucinations & Placeholders
# ============================================================================
def test_fix7_icebreaker_guardrails_and_priorities():
    # Guardrail: Low reviews or NaN rating should not hallucinate 'top stars'
    b_neutral = AuditInput(
        url="https://example.com",
        business_name="Gentille Plumbing",
        rating=None,
        reviews_count=0,
        address="50 Euston St, Brookline, MA 02446",
    )
    issues = {
        "ssl_redirect": AuditIssue(
            check_name="ssl_redirect",
            audit_status="Fail",
            priority="Critical",
            evidence="Insecure HTTP",
            xlsx_summary="Critical: Unencrypted HTTP",
        )
    }
    hook = generate_icebreaker_hook(b_neutral, issues, has_website=True)
    assert "top" not in hook.lower() and "stars" not in hook.lower()
    assert "unencrypted HTTP" in hook
    assert "in your area" not in hook

    # Guardrail: High rating with 15 reviews cites strong reputation
    b_strong = AuditInput(
        url="https://example.com",
        business_name="Gentille Plumbing",
        rating=4.9,
        reviews_count=15,
        address="50 Euston St, Brookline, MA 02446",
    )
    hook_strong = generate_icebreaker_hook(b_strong, issues, has_website=True)
    assert "4.9★ reputation (15 reviews)" in hook_strong
    assert "in your area" not in hook_strong

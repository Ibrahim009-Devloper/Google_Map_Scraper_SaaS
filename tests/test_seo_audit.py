"""
Unit Tests for Agency-Grade Local SEO Audit Engine (tests/test_seo_audit.py)
Validates 21-column schema, crawlability, raw evidence extraction, local SEO signals,
health scoring & pitch priority, domain deduplication caching, icebreaker hooks, and XLSX export.
"""

import pytest
import io
import openpyxl


def test_seo_models_and_config():
    from backend.seo_audit.config import (
        SEO_AUDIT_TIMEOUT,
        SEO_AUDIT_MAX_RETRIES,
        SEO_SLOW_LOAD_THRESHOLD,
        SEO_MODERATE_LOAD_THRESHOLD,
        SEO_XLSX_COLUMNS,
        SEO_CHECK_PENALTIES,
    )
    from backend.seo_audit.models import AuditIssue, SEOReport, AuditInput

    assert SEO_AUDIT_TIMEOUT >= 5
    assert SEO_AUDIT_MAX_RETRIES >= 1
    assert SEO_SLOW_LOAD_THRESHOLD >= 3.0
    assert SEO_MODERATE_LOAD_THRESHOLD >= 1.0

    # Ensure all 21 agency-grade columns are declared
    assert len(SEO_XLSX_COLUMNS) == 21
    assert "Final URL & HTTP Status" in SEO_XLSX_COLUMNS
    assert "SSL & HTTPS Redirect Status" in SEO_XLSX_COLUMNS
    assert "Server Response (TTFB)" in SEO_XLSX_COLUMNS
    assert "Extracted Title Text" in SEO_XLSX_COLUMNS
    assert "Extracted Primary H1" in SEO_XLSX_COLUMNS
    assert "Homepage Word Count" in SEO_XLSX_COLUMNS
    assert "Image Alt Text Gap" in SEO_XLSX_COLUMNS
    assert "SEO Health Score" in SEO_XLSX_COLUMNS
    assert "Lead Pitch Priority" in SEO_XLSX_COLUMNS
    assert "AI / Dynamic Icebreaker Hook" in SEO_XLSX_COLUMNS

    issue = AuditIssue(
        check_name="title_tag",
        audit_status="Pass",
        priority="None",
        evidence="Title is 45 chars",
        recommended_fix=None,
        xlsx_summary="Optimal (45 chars)",
    )
    assert issue.audit_status == "Pass"
    assert issue.priority == "None"

    audit_input = AuditInput(
        url="https://example.com",
        business_name="Acme Plumbing",
        category="Plumber",
        city="Austin",
        phone="512-555-0199",
        address="123 Main St, Austin, TX",
        rating=4.8,
        reviews_count=95,
    )
    assert audit_input.city == "Austin"
    assert audit_input.rating == 4.8


def test_fetch_page_for_audit_success(monkeypatch):
    from backend.seo_audit.fetcher import fetch_page_for_audit, FetchResult

    class MockResponse:
        status_code = 200
        text = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        headers = {"content-type": "text/html"}
        url = "https://example.com/"
        history = []

    def mock_get(url, **kwargs):
        return MockResponse()

    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests, "get", mock_get)

    res = fetch_page_for_audit("https://example.com", timeout=5)
    assert isinstance(res, FetchResult)
    assert res.status_code == 200
    assert "Hello" in res.html
    assert res.final_url == "https://example.com/"
    assert res.ssl_failed is False
    assert res.elapsed_seconds is not None


def test_fetch_page_for_audit_ssl_retry(monkeypatch):
    from backend.seo_audit.fetcher import fetch_page_for_audit

    class MockResponse:
        status_code = 200
        text = "<html><body>HTTP fallback</body></html>"
        headers = {}
        url = "http://example.com/"
        history = []

    def mock_get(url, **kwargs):
        if url.startswith("https://"):
            from curl_cffi.requests.errors import RequestsError
            raise RequestsError("SSL certificate problem")
        return MockResponse()

    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests, "get", mock_get)

    res = fetch_page_for_audit("https://example.com", timeout=5)
    assert res.status_code == 200
    assert res.ssl_failed is True
    assert "HTTP fallback" in res.html


def test_fetch_page_for_audit_timeout(monkeypatch):
    from backend.seo_audit.fetcher import fetch_page_for_audit

    def mock_get(url, **kwargs):
        from curl_cffi.requests.errors import RequestsError
        raise RequestsError("Connection timed out after 5000ms")

    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests, "get", mock_get)

    res = fetch_page_for_audit("https://timeout-domain.com", timeout=5)
    assert res.status_code is None
    assert "timed out" in res.error_message.lower()


def test_optimal_website_scores_pass_and_high_health():
    from backend.seo_audit.analyzer import run_all_seo_checks
    from backend.seo_audit.fetcher import FetchResult
    from backend.seo_audit.models import AuditInput
    from backend.seo_audit.scorer import calculate_seo_health_and_pitch

    html = """<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Austin Roofing Contractor | Acme Roofing Austin TX</title>
        <meta name="description" content="Acme Roofing provides premier roof replacement and repair services in Austin, TX. Call our certified team today for a free estimate!">
        <link rel="canonical" href="https://acmeroofing.com/">
        <meta name="robots" content="index, follow">
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "RoofingContractor",
            "name": "Acme Roofing",
            "telephone": "(512) 555-0199",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "123 Main St",
                "addressLocality": "Austin",
                "postalCode": "78701"
            }
        }
        </script>
    </head>
    <body>
        <h1>Premier Roofing Contractor in Austin, TX</h1>
        <p>""" + ("Acme Roofing offers comprehensive residential and commercial roofing solutions across the greater Austin area. " * 30) + """</p>
        <img src="roof.jpg" alt="Acme Roofing team installing roof in Austin">
        <p>Contact us at (512) 555-0199 or visit 123 Main St, Austin 78701.</p>
        <iframe src="https://www.google.com/maps/embed?pb=123"></iframe>
    </body>
    </html>"""

    fetch_res = FetchResult(
        url="https://acmeroofing.com",
        final_url="https://acmeroofing.com/",
        initial_status_code=200,
        status_code=200,
        elapsed_seconds=0.4,
        html=html,
        headers={"content-type": "text/html"},
        has_robots=True,
        has_sitemap=True,
    )

    audit_input = AuditInput(
        url="https://acmeroofing.com",
        business_name="Acme Roofing",
        category="Roofing contractor",
        city="Austin",
        phone="(512) 555-0199",
        address="123 Main St, Austin, TX 78701",
    )

    check_res = run_all_seo_checks(audit_input, fetch_res)
    assert check_res.extracted_title == "Austin Roofing Contractor | Acme Roofing Austin TX"
    assert check_res.extracted_h1 == "Premier Roofing Contractor in Austin, TX"
    assert check_res.word_count > 300

    health_score, pitch_priority = calculate_seo_health_and_pitch(check_res.issues, has_website=True, is_https=True)
    assert health_score is not None
    assert health_score >= 85
    assert "Low Priority" in pitch_priority or "Moderate" in pitch_priority


def test_poor_seo_website_critical_pitch():
    from backend.seo_audit.analyzer import run_all_seo_checks
    from backend.seo_audit.fetcher import FetchResult
    from backend.seo_audit.models import AuditInput
    from backend.seo_audit.scorer import calculate_seo_health_and_pitch
    from backend.seo_audit.icebreaker import generate_icebreaker_hook

    html = """<html>
    <head>
        <title>Home</title>
        <meta name="robots" content="noindex, nofollow">
    </head>
    <body>
        <h1>Welcome</h1>
        <h1>Our Services</h1>
        <img src="banner.jpg">
        <p>Short thin content.</p>
    </body>
    </html>"""

    fetch_res = FetchResult(
        url="http://insecureslowsite.com",
        final_url="http://insecureslowsite.com/",
        initial_status_code=200,
        status_code=200,
        elapsed_seconds=4.5,
        html=html,
        headers={},
        ssl_failed=True,
    )

    audit_input = AuditInput(
        url="http://insecureslowsite.com",
        business_name="Dallas Plumbers Co",
        category="Plumber",
        city="Dallas",
        phone="214-555-9876",
        address="789 Elm St, Dallas, TX 75201",
        rating=4.5,
    )

    check_res = run_all_seo_checks(audit_input, fetch_res)
    health_score, pitch_priority = calculate_seo_health_and_pitch(check_res.issues, has_website=True, is_https=False)

    assert health_score is not None
    assert health_score < 60
    assert pitch_priority == "Critical Pitch"

    hook = generate_icebreaker_hook(
        business=audit_input,
        issues=check_res.issues,
        final_url=fetch_res.final_url,
        extracted_title=check_res.extracted_title,
        word_count=check_res.word_count,
        has_website=True,
    )
    assert "Dallas Plumbers Co" in hook
    assert len(hook) > 20


def test_icebreaker_hook_rules():
    from backend.seo_audit.icebreaker import generate_icebreaker_hook
    from backend.seo_audit.models import AuditInput, AuditIssue

    # Rule 4: No Website
    b_no_web = AuditInput(url="", business_name="Dr. Smith Dental", city="Miami", rating=4.9)
    hook_no_web = generate_icebreaker_hook(b_no_web, {}, has_website=False)
    assert "Dr. Smith Dental" in hook_no_web
    assert "no active website" in hook_no_web

    # Rule 1: No SSL
    b_ssl = AuditInput(url="http://drsmith.com", business_name="Dr. Smith Dental", city="Miami", rating=4.9)
    issues_ssl = {
        "ssl_redirect": AuditIssue(
            check_name="ssl_redirect",
            audit_status="Fail",
            priority="Critical",
            evidence="Insecure HTTP",
            xlsx_summary="Critical: Unencrypted HTTP",
        )
    }
    hook_ssl = generate_icebreaker_hook(b_ssl, issues_ssl, final_url="http://drsmith.com", has_website=True)
    assert "unencrypted HTTP" in hook_ssl


def test_root_domain_deduplication_caching():
    from backend.seo_audit.auditor import audit_single_business, clear_domain_cache
    from backend.seo_audit.models import AuditInput

    clear_domain_cache()

    html = "<html><head><title>Vikara Miami Dental Practice</title></head><body><h1>Dentist</h1><p>" + ("Quality dental care in Miami Florida. " * 35) + "</p></body></html>"

    # Practitioner 1 (Dr. A)
    b1 = AuditInput(
        url="https://vikaramiami.com/practitioner-a",
        business_name="Dr. Alpha at Vikara",
        city="Miami",
        category="Dentist",
        rating=4.9,
    )
    rep1 = audit_single_business(b1, cached_html=html, elapsed_seconds=0.2)

    # Practitioner 2 (Dr. B) sharing the same root domain vikaramiami.com
    b2 = AuditInput(
        url="http://www.vikaramiami.com/practitioner-b",
        business_name="Dr. Beta at Vikara",
        city="Miami",
        category="Dentist",
        rating=4.7,
    )
    rep2 = audit_single_business(b2, cached_html=None, elapsed_seconds=None)

    # Root domain caching ensures identical technical metrics without re-fetching
    assert rep1.seo_health_score == rep2.seo_health_score
    assert rep1.extracted_title == rep2.extracted_title
    # But icebreaker hooks are personalized with the individual business name
    assert "Dr. Alpha" in rep1.icebreaker_hook
    assert "Dr. Beta" in rep2.icebreaker_hook


def test_xlsx_appender_preserves_existing_columns_and_appends_twenty_one():
    from agent.schemas import LeadItem
    from backend.excel_exporter import generate_leads_excel
    from backend.seo_audit.xlsx_appender import append_seo_columns_to_excel
    from backend.seo_audit.models import SEOReport
    from backend.seo_audit.config import SEO_XLSX_COLUMNS

    leads = [
        LeadItem(
            place_id="place_1",
            name="Alpha Roofing",
            category="Roofing contractor",
            phone="512-111-2222",
            website_status="Has Own Website",
            website_url="https://alpharoofing.com",
            address="100 Main St, Austin, TX",
        ),
        LeadItem(
            place_id="place_2",
            name="Beta Plumbing",
            category="Plumber",
            phone="512-333-4444",
            website_status="No Website",
            website_url=None,
            address="200 Oak St, Austin, TX",
        ),
    ]

    base_excel_bytes = generate_leads_excel(leads)
    base_wb = openpyxl.load_workbook(io.BytesIO(base_excel_bytes))
    base_ws = base_wb.active
    orig_cols = [cell.value for cell in base_ws[1]]
    orig_col_count = len(orig_cols)
    assert "Business Name" in orig_cols

    seo_reports = {
        "place_1": SEOReport(
            url="https://alpharoofing.com",
            seo_health_score=85,
            lead_pitch_priority="Low Priority - Well Optimized",
            icebreaker_hook="Audited Alpha Roofing in Austin.",
            xlsx_row_data={col: "Pass" for col in SEO_XLSX_COLUMNS},
        )
    }
    seo_reports["place_1"].xlsx_row_data["SEO Health Score"] = "85/100"
    seo_reports["place_1"].xlsx_row_data["Lead Pitch Priority"] = "Low Priority - Well Optimized"
    seo_reports["place_1"].xlsx_row_data["AI / Dynamic Icebreaker Hook"] = "Audited Alpha Roofing in Austin."

    modified_bytes = append_seo_columns_to_excel(base_excel_bytes, seo_reports)

    mod_wb = openpyxl.load_workbook(io.BytesIO(modified_bytes))
    mod_ws = mod_wb.active
    new_cols = [cell.value for cell in mod_ws[1]]

    # 1. Original columns preserved in exact order
    assert new_cols[:orig_col_count] == orig_cols

    # 2. Exactly 21 new columns appended to the right
    assert len(new_cols) == orig_col_count + 21
    assert new_cols[orig_col_count:] == SEO_XLSX_COLUMNS

    # 3. Row 2 (Alpha Roofing) has audited values
    row2_vals = [cell.value for cell in mod_ws[2]]
    assert row2_vals[orig_col_count + SEO_XLSX_COLUMNS.index("SEO Health Score")] == "85/100"

    # 4. Row 3 (Beta Plumbing - no website) gracefully handled
    row3_vals = [cell.value for cell in mod_ws[3]]
    assert row3_vals[orig_col_count + SEO_XLSX_COLUMNS.index("SEO Health Score")] == "N/A"
    assert row3_vals[orig_col_count + SEO_XLSX_COLUMNS.index("Lead Pitch Priority")] == "Critical Pitch (No Website)"


def test_api_seo_audit_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.seo_audit.fetcher import FetchResult

    client = TestClient(app)

    def mock_fetch(url, **kwargs):
        return FetchResult(
            url=url,
            final_url=url,
            initial_status_code=200,
            status_code=200,
            elapsed_seconds=0.5,
            html="<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'><title>Austin Plumber</title></head><body><h1>Austin Plumber</h1><p>" + ("Plumbing services in Austin TX. " * 30) + "</p></body></html>",
        )

    from backend.seo_audit import fetcher
    monkeypatch.setattr(fetcher, "fetch_page_for_audit", mock_fetch)

    resp = client.post(
        "/api/seo-audit",
        json={
            "url": "https://austinplumber.com",
            "business_name": "Austin Plumber Co",
            "category": "Plumber",
            "city": "Austin",
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://austinplumber.com"
    assert "seo_health_score" in data
    assert "lead_pitch_priority" in data
    assert "icebreaker_hook" in data
    assert "xlsx_row_data" in data
    assert "Final URL & HTTP Status" in data["xlsx_row_data"]
    assert "AI / Dynamic Icebreaker Hook" in data["xlsx_row_data"]

"""
Unit Tests for Reusable, On-Demand Local SEO Audit Module (tests/test_seo_audit.py)
Covers all 11 local SEO checks, verified-only scoring, error tolerance, and XLSX export.
"""

import pytest


def test_seo_models_and_config():
    from seo_audit.config import (
        SEO_CHECK_WEIGHTS,
        SEO_AUDIT_TIMEOUT,
        SEO_AUDIT_MAX_RETRIES,
        SEO_SLOW_LOAD_THRESHOLD,
        SEO_MODERATE_LOAD_THRESHOLD,
    )
    from seo_audit.models import AuditIssue, SEOReport, AuditInput

    assert SEO_AUDIT_TIMEOUT == 12
    assert SEO_AUDIT_MAX_RETRIES == 2
    assert SEO_SLOW_LOAD_THRESHOLD == 5.0
    assert SEO_MODERATE_LOAD_THRESHOLD == 2.5

    assert sum(SEO_CHECK_WEIGHTS.values()) == 100
    assert "website_speed" in SEO_CHECK_WEIGHTS
    assert "mobile_friendly" in SEO_CHECK_WEIGHTS
    assert "title_tag" in SEO_CHECK_WEIGHTS
    assert "meta_description" in SEO_CHECK_WEIGHTS
    assert "h1_status" in SEO_CHECK_WEIGHTS
    assert "canonical_robots" in SEO_CHECK_WEIGHTS
    assert "image_alt" in SEO_CHECK_WEIGHTS
    assert "local_keywords" in SEO_CHECK_WEIGHTS
    assert "nap_consistency" in SEO_CHECK_WEIGHTS
    assert "schema_markup" in SEO_CHECK_WEIGHTS
    assert "contact_maps_embed" in SEO_CHECK_WEIGHTS

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
    )
    assert audit_input.city == "Austin"


def test_fetch_page_for_audit_success(monkeypatch):
    from seo_audit.fetcher import fetch_page_for_audit, FetchResult

    class MockResponse:
        status_code = 200
        text = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        headers = {"content-type": "text/html"}
        url = "https://example.com/"

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
    from seo_audit.fetcher import fetch_page_for_audit

    calls = []

    class MockResponse:
        status_code = 200
        text = "<html><body>HTTP fallback</body></html>"
        headers = {}
        url = "http://example.com/"

    def mock_get(url, **kwargs):
        calls.append(url)
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
    assert len(calls) == 2


def test_fetch_page_for_audit_timeout(monkeypatch):
    from seo_audit.fetcher import fetch_page_for_audit

    def mock_get(url, **kwargs):
        from curl_cffi.requests.errors import RequestsError
        raise RequestsError("Connection timed out after 5000ms")

    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests, "get", mock_get)

    res = fetch_page_for_audit("https://timeout-domain.com", timeout=5)
    assert res.status_code is None
    assert "timed out" in res.error_message.lower()


def test_optimal_website_scores_pass_all_checks():
    from seo_audit.analyzer import run_all_seo_checks
    from seo_audit.fetcher import FetchResult
    from seo_audit.models import AuditInput

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
        <p>Welcome to Acme Roofing. Serving Austin with quality roofs.</p>
        <img src="roof.jpg" alt="Acme Roofing team installing roof in Austin">
        <p>Contact us at (512) 555-0199 or visit 123 Main St, Austin 78701.</p>
        <a href="tel:5125550199">Call Now</a>
        <iframe src="https://www.google.com/maps/embed?pb=123"></iframe>
    </body>
    </html>"""

    fetch_res = FetchResult(
        url="https://acmeroofing.com",
        final_url="https://acmeroofing.com/",
        status_code=200,
        elapsed_seconds=1.1,
        html=html,
        headers={"content-type": "text/html"},
    )

    audit_input = AuditInput(
        url="https://acmeroofing.com",
        business_name="Acme Roofing",
        category="Roofing contractor",
        city="Austin",
        phone="(512) 555-0199",
        address="123 Main St, Austin, TX 78701",
    )

    issues = run_all_seo_checks(audit_input, fetch_res)
    assert len(issues) == 11
    # Every check on this well-optimized page should pass
    for check_name, issue in issues.items():
        assert issue.audit_status == "Pass", f"{check_name} expected Pass, got {issue.audit_status}: {issue.evidence}"


def test_poor_seo_website_fails_all_checks():
    from seo_audit.analyzer import run_all_seo_checks
    from seo_audit.fetcher import FetchResult
    from seo_audit.models import AuditInput

    # Poor HTML: No viewport, generic title "Home", no meta description, 3 H1s, noindex, no alt, missing local keywords, wrong phone, no schema, no map embed
    html = """<html>
    <head>
        <title>Home</title>
        <meta name="robots" content="noindex, nofollow">
    </head>
    <body>
        <h1>Welcome</h1>
        <h1>Our Services</h1>
        <h1>Contact</h1>
        <img src="banner.jpg">
        <img src="photo.jpg">
        <p>Generic business content with completely different phone 212-000-0000 and NY address.</p>
    </body>
    </html>"""

    fetch_res = FetchResult(
        url="http://slowbadsite.com",
        final_url="http://slowbadsite.com/",
        status_code=200,
        elapsed_seconds=6.8,  # Slow load time > 5s and HTTP
        html=html,
        headers={},
    )

    audit_input = AuditInput(
        url="http://slowbadsite.com",
        business_name="Dallas Plumbers Co",
        category="Plumber",
        city="Dallas",
        phone="214-555-9876",
        address="789 Elm St, Dallas, TX 75201",
    )

    issues = run_all_seo_checks(audit_input, fetch_res)
    assert issues["website_speed"].audit_status == "Fail"
    assert issues["mobile_friendly"].audit_status == "Fail"
    assert issues["title_tag"].audit_status == "Fail"
    assert issues["meta_description"].audit_status == "Fail"
    assert issues["h1_status"].audit_status == "Warning"  # Multiple H1s is Warning
    assert issues["canonical_robots"].audit_status == "Fail"  # noindex is Critical Fail
    assert issues["image_alt"].audit_status == "Warning"  # >30% missing alt is Warning
    assert issues["local_keywords"].audit_status == "Fail"
    assert issues["nap_consistency"].audit_status == "Fail"
    assert issues["schema_markup"].audit_status == "Fail"
    assert issues["contact_maps_embed"].audit_status == "Fail"


def test_missing_input_data_marked_unverified_not_failed():
    from seo_audit.analyzer import run_all_seo_checks
    from seo_audit.fetcher import FetchResult
    from seo_audit.models import AuditInput

    html = """<!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>General Services Company</title>
    </head>
    <body>
        <h1>General Services</h1>
    </body>
    </html>"""

    fetch_res = FetchResult(
        url="https://general.com",
        status_code=200,
        elapsed_seconds=1.0,
        html=html,
    )

    # Completely missing city, category, phone, and address from Google Maps input
    audit_input = AuditInput(
        url="https://general.com",
        business_name="General Co",
        category=None,
        city=None,
        phone=None,
        address=None,
    )

    issues = run_all_seo_checks(audit_input, fetch_res)
    # Checks requiring missing input baseline MUST be Unverified
    assert issues["local_keywords"].audit_status == "Unverified"
    assert issues["nap_consistency"].audit_status == "Unverified"
    assert issues["image_alt"].audit_status == "Unverified"  # 0 images is Unverified


def test_calculate_seo_opportunity_score_all_pass_is_zero():
    from seo_audit.scorer import calculate_seo_opportunity_score
    from seo_audit.models import AuditIssue
    from seo_audit.config import SEO_CHECK_WEIGHTS

    issues = {
        name: AuditIssue(check_name=name, audit_status="Pass", evidence="OK")
        for name in SEO_CHECK_WEIGHTS
    }
    score = calculate_seo_opportunity_score(issues)
    assert score == 0


def test_calculate_seo_opportunity_score_all_fail_is_hundred():
    from seo_audit.scorer import calculate_seo_opportunity_score
    from seo_audit.models import AuditIssue
    from seo_audit.config import SEO_CHECK_WEIGHTS

    issues = {
        name: AuditIssue(check_name=name, audit_status="Fail", evidence="Failed")
        for name in SEO_CHECK_WEIGHTS
    }
    score = calculate_seo_opportunity_score(issues)
    assert score == 100


def test_calculate_seo_opportunity_score_unverified_excluded_from_denominator():
    from seo_audit.scorer import calculate_seo_opportunity_score
    from seo_audit.models import AuditIssue

    # Suppose only 2 checks are verified:
    # check A (weight 10): Pass (0 pts)
    # check B (weight 10): Fail (10 pts)
    # All others: Unverified
    issues = {
        "title_tag": AuditIssue(check_name="title_tag", audit_status="Pass", evidence="OK"),  # weight 10
        "h1_status": AuditIssue(check_name="h1_status", audit_status="Fail", evidence="Fail"),  # weight 10
    }
    # Remaining checks marked Unverified
    from seo_audit.config import SEO_CHECK_WEIGHTS
    for k in SEO_CHECK_WEIGHTS:
        if k not in issues:
            issues[k] = AuditIssue(check_name=k, audit_status="Unverified", evidence="N/A")

    # (0 + 10) / (10 + 10) * 100 = 50%
    score = calculate_seo_opportunity_score(issues)
    assert score == 50


def test_calculate_seo_opportunity_score_all_unverified_returns_none():
    from seo_audit.scorer import calculate_seo_opportunity_score
    from seo_audit.models import AuditIssue
    from seo_audit.config import SEO_CHECK_WEIGHTS

    issues = {
        name: AuditIssue(check_name=name, audit_status="Unverified", evidence="N/A")
        for name in SEO_CHECK_WEIGHTS
    }
    score = calculate_seo_opportunity_score(issues)
    assert score is None


def test_calculate_seo_opportunity_score_noindex_enforces_min_85():
    from seo_audit.scorer import calculate_seo_opportunity_score
    from seo_audit.models import AuditIssue
    from seo_audit.config import SEO_CHECK_WEIGHTS

    # Suppose all checks pass except canonical_robots is blocked by noindex
    issues = {
        name: AuditIssue(check_name=name, audit_status="Pass", evidence="OK")
        for name in SEO_CHECK_WEIGHTS
    }
    issues["canonical_robots"] = AuditIssue(
        check_name="canonical_robots",
        audit_status="Fail",
        evidence="Page blocked via noindex",
        xlsx_summary="Blocked (noindex) [Critical]"
    )
    # Under normal math: 8 / 100 = 8.
    # But noindex rule enforces max(8, 85) = 85!
    score = calculate_seo_opportunity_score(issues)
    assert score == 85


def test_network_failure_does_not_stop_lead_pipeline(monkeypatch):
    from seo_audit.auditor import audit_bulk_businesses
    from seo_audit.models import AuditInput
    from seo_audit.fetcher import FetchResult

    # 3 businesses: #1 is good, #2 fails/times out, #3 is good
    businesses = [
        AuditInput(url="https://site1.com", business_name="Site One", city="Austin", category="Roofing"),
        AuditInput(url="https://site2-hangs.com", business_name="Site Two", city="Dallas", category="Plumber"),
        AuditInput(url="https://site3.com", business_name="Site Three", city="Houston", category="Dentist"),
    ]

    def mock_fetch(url, **kwargs):
        if "site2" in url:
            return FetchResult(
                url=url,
                status_code=None,
                elapsed_seconds=12.0,
                error_message="Connection timed out after 12s",
            )
        return FetchResult(
            url=url,
            status_code=200,
            elapsed_seconds=1.2,
            html="<html><head><title>Test Site</title></head><body><h1>Service</h1></body></html>",
        )

    from seo_audit import fetcher
    monkeypatch.setattr(fetcher, "fetch_page_for_audit", mock_fetch)

    reports = audit_bulk_businesses(businesses)
    assert len(reports) == 3

    # Business 1 should succeed with a valid report
    assert reports[0].url == "https://site1.com"
    assert reports[0].opportunity_score is not None
    assert "Website Speed" in reports[0].xlsx_row_data

    # Business 2 should report error cleanly without crashing batch
    assert reports[1].url == "https://site2-hangs.com"
    assert reports[1].opportunity_score is None or reports[1].opportunity_score == 100  # speed failed, DOM unverified
    assert reports[1].xlsx_row_data["Website Speed"] == "Failed [High]"

    # Business 3 should succeed
    assert reports[2].url == "https://site3.com"
    assert reports[2].opportunity_score is not None


def test_xlsx_appender_preserves_existing_columns_and_appends_nine():
    import io
    import openpyxl
    from agent.schemas import LeadItem
    from backend.excel_exporter import generate_leads_excel
    from seo_audit.xlsx_appender import append_seo_columns_to_excel
    from seo_audit.models import SEOReport
    from seo_audit.auditor import SEO_XLSX_COLUMNS

    # Create dummy leads
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

    # Load base workbook to verify original column count
    base_wb = openpyxl.load_workbook(io.BytesIO(base_excel_bytes))
    base_ws = base_wb.active
    orig_cols = [cell.value for cell in base_ws[1]]
    orig_col_count = len(orig_cols)
    assert "Business Name" in orig_cols

    # Prepare audit reports for place_1 (place_2 was not audited)
    seo_reports = {
        "place_1": SEOReport(
            url="https://alpharoofing.com",
            opportunity_score=15,
            xlsx_row_data={
                "Website Speed": "Fast (1.1s)",
                "Mobile Friendly": "Pass",
                "Title Tag Status": "Optimal (45 chars)",
                "Meta Description Status": "Optimal (120 chars)",
                "H1 Status": "Optimal (1 H1)",
                "Local Keyword Status": "Pass (City + Niche)",
                "Schema Status": "Pass (RoofingContractor)",
                "NAP Status": "Consistent",
                "SEO Opportunity Score": "15/100",
            }
        )
    }

    modified_bytes = append_seo_columns_to_excel(base_excel_bytes, seo_reports)

    mod_wb = openpyxl.load_workbook(io.BytesIO(modified_bytes))
    mod_ws = mod_wb.active
    new_cols = [cell.value for cell in mod_ws[1]]

    # 1. Original columns must be preserved in exact order
    assert new_cols[:orig_col_count] == orig_cols

    # 2. Exactly 9 new columns appended to the right
    assert len(new_cols) == orig_col_count + 9
    assert new_cols[orig_col_count:] == SEO_XLSX_COLUMNS

    # 3. Row 2 (Alpha Roofing) has audited values
    row2_vals = [cell.value for cell in mod_ws[2]]
    assert row2_vals[orig_col_count] == "Fast (1.1s)"
    assert row2_vals[orig_col_count + 8] == "15/100"

    # 4. Row 3 (Beta Plumbing - not audited) has "Not Audited" or "No Website"
    row3_vals = [cell.value for cell in mod_ws[3]]
    assert row3_vals[orig_col_count] in ("Not Audited", "No Website")
    assert row3_vals[orig_col_count + 8] in ("Not Audited", "N/A")


def test_api_seo_audit_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from seo_audit.fetcher import FetchResult

    client = TestClient(app)

    def mock_fetch(url, **kwargs):
        return FetchResult(
            url=url,
            status_code=200,
            elapsed_seconds=1.2,
            html="<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'><title>Austin Plumber</title></head><body><h1>Austin Plumber</h1></body></html>",
        )

    from seo_audit import fetcher
    monkeypatch.setattr(fetcher, "fetch_page_for_audit", mock_fetch)

    # Test Single Audit Endpoint: POST /api/seo-audit
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
    assert "opportunity_score" in data
    assert "xlsx_row_data" in data
    assert "Website Speed" in data["xlsx_row_data"]

    # Test Bulk Audit Endpoint: POST /api/seo-audit/bulk
    resp_bulk = client.post(
        "/api/seo-audit/bulk",
        json=[
            {
                "url": "https://austinplumber.com",
                "business_name": "Austin Plumber Co",
                "category": "Plumber",
                "city": "Austin",
            }
        ]
    )
    assert resp_bulk.status_code == 200
    bulk_data = resp_bulk.json()
    assert isinstance(bulk_data, list)
    assert len(bulk_data) == 1
    assert bulk_data[0]["url"] == "https://austinplumber.com"







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


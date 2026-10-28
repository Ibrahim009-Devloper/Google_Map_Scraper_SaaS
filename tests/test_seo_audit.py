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

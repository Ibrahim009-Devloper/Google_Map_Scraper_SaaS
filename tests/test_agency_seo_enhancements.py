"""
Unit and integration tests for Agency SEO Enhancements & Excel Schema Upgrades (GEMINI2.md Phase 2).
Covers:
1. Google PageSpeed Insights Client (backend/seo_audit/pagespeed.py)
2. Competitor Research & Local Gap Analysis Engine (backend/seo_audit/competitor.py)
3. Ads & Tracking Detection + Inner Pages in analyzer.py
4. Excel Schema Sortability, Hygiene & Split Column Exporter (backend/excel_exporter.py & xlsx_appender.py)
5. Email Classification & Honest DNS MX Verification (agent/web_enricher.py)
"""

import io
import openpyxl
import pytest
from bs4 import BeautifulSoup

from agent.schemas import LeadItem, SocialLinks
from backend.excel_exporter import generate_leads_excel
from backend.seo_audit.models import AuditInput, SEOReport
from backend.seo_audit.config import SEO_XLSX_COLUMNS, SEO_SPLIT_COLUMNS
from backend.seo_audit.pagespeed import (
    fetch_pagespeed_strategy,
    audit_pagespeed,
    PageSpeedAuditReport,
    PageSpeedStrategyResult,
)
from backend.seo_audit.competitor import (
    discover_top_competitors,
    build_competitor_gap_analysis,
    CompetitorSnapshot,
    CompetitorGapAnalysis,
)
from backend.seo_audit.analyzer import (
    check_ads_and_tracking,
    check_inner_pages_and_freshness,
)
from backend.seo_audit.xlsx_appender import (
    append_seo_columns_to_excel,
    append_split_seo_columns_to_excel,
    extract_check_status_and_details,
)
from agent.web_enricher import (
    classify_email_type,
    verify_email_mx,
    FREE_PROVIDER_DOMAINS,
)


# ============================================================================
# 1. PageSpeed Insights Client Tests
# ============================================================================

def test_pagespeed_unavailable_when_unconfigured_or_unreachable():
    """Verifies that pagespeed client returns clean structure with 'Unavailable' status without crashing."""
    rep = audit_pagespeed("https://nonexistent-site-test-12345.org", api_key="", timeout=1.0)
    assert isinstance(rep, PageSpeedAuditReport)
    assert rep.status in ("Unavailable", "Not Checked")
    assert rep.mobile.status in ("Unavailable", "Not Checked")
    assert rep.desktop.status in ("Unavailable", "Not Checked")
    assert rep.mobile.core_web_vitals.lcp == "Unavailable"


def test_pagespeed_mock_successful_response(monkeypatch):
    """Verifies extraction of scores, Core Web Vitals, mobile viewport, and screenshot data."""
    mock_payload = {
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.88}},
            "audits": {
                "largest-contentful-paint": {"displayValue": "1.9 s"},
                "cumulative-layout-shift": {"displayValue": "0.02"},
                "first-contentful-paint": {"displayValue": "1.1 s"},
                "interaction-to-next-paint": {"displayValue": "95 ms"},
                "viewport": {"score": 1},
                "final-screenshot": {"details": {"data": "data:image/jpeg;base64,mockthumb"}},
            },
        }
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return mock_payload

    from curl_cffi import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockResponse())

    res = fetch_pagespeed_strategy("https://myroofingbiz.com", strategy="mobile", api_key="test_key")
    assert res.status == "Warning"  # 88/100 -> Warning (<90)
    assert res.performance_score == 88
    assert res.core_web_vitals.lcp == "1.9 s"
    assert res.core_web_vitals.cls == "0.02"
    assert res.core_web_vitals.inp == "95 ms"
    assert res.is_mobile_friendly is True
    assert res.screenshot_data_url == "data:image/jpeg;base64,mockthumb"


# ============================================================================
# 2. Competitor Research & Gap Analysis Engine Tests
# ============================================================================

def test_competitor_discovery_and_gap_analysis():
    """Verifies top-3 competitor ranking, review deficit, rating gap, and trailing gap list."""
    target = {
        "place_id": "target_1",
        "name": "Acme Plumbing",
        "category": "Plumber",
        "rating": 4.1,
        "reviews_count": 15,
        "seo_health_score": 62,
        "has_schema": False,
        "has_tracking": False,
        "neighborhood": "Austin, TX",
    }

    candidate_pool = [
        {
            "place_id": "comp_1",
            "name": "Reliable Plumbing Pros",
            "category": "Plumber",
            "rating": 4.9,
            "reviews_count": 250,
            "seo_health_score": 88,
            "has_schema": True,
            "has_tracking": True,
        },
        {
            "place_id": "comp_2",
            "name": "Austin Master Plumber",
            "category": "Plumber",
            "rating": 4.7,
            "reviews_count": 180,
            "seo_health_score": 75,
            "has_schema": True,
            "has_tracking": False,
        },
        {
            "place_id": "target_1",  # Self - should be excluded
            "name": "Acme Plumbing",
            "category": "Plumber",
            "reviews_count": 15,
        },
        {
            "place_id": "unrelated",  # Different category
            "name": "Austin Bakery",
            "category": "Bakery",
            "reviews_count": 500,
        },
    ]

    analysis = build_competitor_gap_analysis(target, candidate_pool)
    assert analysis.status == "Completed"
    assert len(analysis.competitors) == 2
    assert analysis.competitors[0].name == "Reliable Plumbing Pros"

    # Check trailing gaps
    assert len(analysis.trailing_gaps) >= 3
    assert any("Review Volume Gap" in g for g in analysis.trailing_gaps)
    assert any("Star Rating Gap" in g for g in analysis.trailing_gaps)
    assert any("Schema Advantage" in g for g in analysis.trailing_gaps)


def test_competitor_gap_analysis_empty_pool():
    """Verifies graceful handling when candidate pool is empty or no competitors exist."""
    target = {"name": "Solo Electrician", "category": "Electrician"}
    analysis = build_competitor_gap_analysis(target, [])
    assert analysis.status == "Insufficient Competitor Data"
    assert len(analysis.competitors) == 0
    assert len(analysis.trailing_gaps) == 0


# ============================================================================
# 3. Ads & Tracking Detection + Inner Pages in analyzer.py
# ============================================================================

def test_ads_and_tracking_detection():
    """Verifies detection of GA4, GTM, Google Ads, Meta Pixel, Clarity, and Hotjar."""
    html_with_tags = """
    <html>
      <head>
        <script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC1234567"></script>
        <script>
          gtag('config', 'G-ABC1234567');
          gtag('config', 'AW-987654321');
        </script>
        <script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
        new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
        j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
        'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
        })(window,document,'script','dataLayer','GTM-XYZ789');</script>
        <script>!function(f,b,e,v,n,t,s){fbq('init', '123456789012345');}(window, document);</script>
        <script type="text/javascript">
          (function(c,l,a,r,i,t,y){c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
          t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/claritykey123";
          y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
          })(window, document, "clarity", "script", "claritykey123");
        </script>
      </head>
      <body><h1>My Plumbing Company</h1></body>
    </html>
    """
    soup = BeautifulSoup(html_with_tags, "html.parser")
    issue, summary = check_ads_and_tracking(soup, html_with_tags)
    assert issue.audit_status == "Pass"
    assert "Pass: Active" in summary
    assert "Google Analytics 4" in issue.evidence
    assert "GTM-XYZ789" in issue.evidence
    assert "Google Ads" in issue.evidence
    assert "Meta Pixel" in issue.evidence
    assert "Microsoft Clarity" in issue.evidence


def test_ads_and_tracking_missing():
    """Verifies warning when no marketing tags exist on the homepage."""
    bare_html = "<html><body><h1>Local Bakery</h1><p>Welcome to our site!</p></body></html>"
    soup = BeautifulSoup(bare_html, "html.parser")
    issue, summary = check_ads_and_tracking(soup, bare_html)
    assert issue.audit_status == "Warning"
    assert "No Marketing / Tracking Tags Found" in summary
    assert issue.priority == "Medium"


def test_inner_pages_and_freshness():
    """Verifies detection of service pages, location pages, and blog in navigation."""
    nav_html = """
    <html>
      <body>
        <nav>
          <a href="/services/emergency-plumbing">Emergency Plumbing</a>
          <a href="/service-areas/dallas-tx">Dallas Area</a>
          <a href="/blog/how-to-fix-leak">DIY Leak Tips</a>
        </nav>
      </body>
    </html>
    """
    soup = BeautifulSoup(nav_html, "html.parser")
    issue, summary = check_inner_pages_and_freshness(soup)
    assert issue.audit_status == "Pass"
    assert "Services" in summary
    assert "Locations" in summary
    assert "Blog" in summary


# ============================================================================
# 4. Excel Schema Sortability, Hygiene & Split Columns Tests
# ============================================================================

def test_excel_exporter_hygiene_and_shared_contact():
    """
    Verifies:
    1. Permanently blank 'Price Range' column is REMOVED.
    2. 'Shared Contact Flag' is added and marks shared phone/email.
    3. 'Email Type' and 'Email Verification Status' columns are present when enrichment is enabled.
    """
    leads = [
        LeadItem(
            place_id="lead_1",
            name="First Business",
            phone="214-555-0100",
            website_status="Has Own Website",
            website_url="https://firstbiz.com",
            emails=["info@firstbiz.com"],
        ),
        LeadItem(
            place_id="lead_2",
            name="Second Business",
            phone="214-555-0100",  # Shared phone with lead_1
            website_status="Has Own Website",
            website_url="https://secondbiz.com",
            emails=["contact@gmail.com"],
        ),
        LeadItem(
            place_id="lead_3",
            name="Third Business",
            phone="512-555-9999",  # Unique phone
            website_status="No Website",
            emails=[],
        ),
    ]

    excel_bytes = generate_leads_excel(leads, include_enrichment=True)
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    ws = wb.active

    headers = [cell.value for cell in ws[1]]

    # 1. Price Range must be absent
    assert "Price Range" not in headers, "Price Range column must be removed from export"

    # 2. Shared Contact Flag must be present
    assert "Shared Contact Flag" in headers
    assert "Email Type" in headers
    assert "Email Verification Status" in headers

    flag_idx = headers.index("Shared Contact Flag") + 1
    row2_flag = ws.cell(row=2, column=flag_idx).value
    row3_flag = ws.cell(row=3, column=flag_idx).value
    row4_flag = ws.cell(row=4, column=flag_idx).value

    assert row2_flag == "Yes — Shared Email/Phone"
    assert row3_flag == "Yes — Shared Email/Phone"
    assert row4_flag == "No"

    # 3. Email Type classifications
    type_idx = headers.index("Email Type") + 1
    assert ws.cell(row=2, column=type_idx).value == "Business Domain"
    assert ws.cell(row=3, column=type_idx).value == "Free Provider"


def test_split_status_details_extraction_and_numeric_score():
    """
    Verifies that extract_check_status_and_details cleanly separates
    Status enum from diagnostic text, and append_split_seo_columns_to_excel
    produces a sortable table with pure numeric SEO Health Score.
    """
    status, details = extract_check_status_and_details("Pass: robots.txt & XML Sitemap Verified")
    assert status == "Pass"
    assert details == "robots.txt & XML Sitemap Verified"

    status, details = extract_check_status_and_details("Warning: robots.txt Present, XML Sitemap Missing")
    assert status == "Warning"
    assert details == "robots.txt Present, XML Sitemap Missing"

    status, details = extract_check_status_and_details("High Issue: Both robots.txt & XML Sitemap Missing")
    assert status == "Critical"
    assert details == "Both robots.txt & XML Sitemap Missing"

    status, details = extract_check_status_and_details("Could Not Read (JS-Rendered)")
    assert status == "Could Not Read"

    # Test appending split columns
    base_leads = [
        LeadItem(
            place_id="place_roof_99",
            name="Roofing Pros",
            website_status="Has Own Website",
            website_url="https://roofingpros.com",
        )
    ]
    base_xlsx = generate_leads_excel(base_leads)

    rep = SEOReport(
        url="https://roofingpros.com",
        seo_health_score=84,
        lead_pitch_priority="Low Priority",
        xlsx_row_data={
            "SEO Health Score": 84,  # Pure integer!
            "Lead Pitch Priority": "Low Priority",
            "SSL & HTTPS Redirect Status": "Pass: Strict 301 Redirect to HTTPS",
            "Server Response (TTFB)": "Pass: Fast TTFB (0.42s)",
            "Schema Status": "Warning: Schema Missing required postalCode",
        }
    )

    split_bytes = append_split_seo_columns_to_excel(base_xlsx, {"place_roof_99": rep})
    mod_wb = openpyxl.load_workbook(io.BytesIO(split_bytes))
    mod_ws = mod_wb.active

    headers = [cell.value for cell in mod_ws[1]]
    assert "SSL Status" in headers
    assert "SSL Details" in headers
    assert "TTFB Status" in headers
    assert "TTFB Details" in headers
    assert "Schema Status" in headers
    assert "Schema Details" in headers

    # Verify pure numeric SEO Health Score
    score_idx = headers.index("SEO Health Score") + 1
    cell_score = mod_ws.cell(row=2, column=score_idx).value
    assert isinstance(cell_score, int)
    assert cell_score == 84


# ============================================================================
# 5. Email Classification & Honest DNS MX Verification Tests
# ============================================================================

def test_email_classification_and_verification():
    """Verifies Business Domain vs Free Provider and DNS MX verification."""
    # Free provider classification
    assert classify_email_type("contact@gmail.com") == "Free Provider"
    assert classify_email_type("sales@yahoo.com") == "Free Provider"
    assert classify_email_type("info@outlook.com") == "Free Provider"
    assert classify_email_type("user@yahoo.co.uk") == "Free Provider"

    # Business domain classification
    assert classify_email_type("info@austinplumbingmasters.com") == "Business Domain"

    # Honest MX Verification
    # Known free provider with guaranteed MX
    assert verify_email_mx("contact@gmail.com") == "Valid (Syntax + MX)"

    # Invalid syntax or junk username
    assert verify_email_mx("invalid..syntax@@gmail.com") == "Invalid"
    assert verify_email_mx("notanemail") == "Invalid"

    # Non-existent domain
    assert verify_email_mx("info@nonexistent-domain-xyz-99881122.org") == "Invalid"

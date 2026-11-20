"""
Comprehensive Unit & Integration Test Suite for Agency-Grade Local SEO Platform (GEMINI2.md).

Covers:
1. Google PageSpeed Insights HTTP Client & Fallbacks (backend/seo_audit/pagespeed.py)
2. Competitor Research & Local Gap Analysis Engine (backend/seo_audit/competitor.py)
3. Marketing / Analytics Tracking Tags Detection (backend/seo_audit/analyzer.py)
4. Inner Pages & Content Freshness Scanner (backend/seo_audit/analyzer.py)
5. Excel Schema Verification: Price Range removed, Pure Numeric Scores, Split Status+Details, Shared Contacts
6. Grounded AI Audit Report Generator with Section Filtering (backend/seo_audit/ai_report.py)
7. White-Label Branded PDF Exporter using ReportLab (backend/seo_audit/pdf_exporter.py)
8. FastAPI Endpoints in backend/seo_audit/routes.py (via TestClient)
"""

import io
import json
import pytest
import openpyxl
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from agent.schemas import LeadItem, SocialLinks
from backend.main import app
from backend.excel_exporter import generate_leads_excel
from backend.seo_audit.models import (
    AuditInput,
    SEOReport,
    AuditSectionConfig,
    AgencyBranding,
    CompetitorComparison,
    PageSpeedResult,
    ActionPlanItem,
    AIAuditReport,
    GenerateReportRequest,
    ExportPdfRequest,
)
from backend.seo_audit.pagespeed import (
    fetch_pagespeed_strategy,
    audit_pagespeed,
    check_pagespeed,
    PageSpeedAuditReport,
    PageSpeedStrategyResult,
)
from backend.seo_audit.competitor import (
    discover_top_competitors,
    build_competitor_gap_analysis,
    get_competitors_for_place_id,
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
from backend.seo_audit.ai_report import generate_ai_audit_report
from backend.seo_audit.pdf_exporter import generate_audit_pdf


# ============================================================================
# 1. PageSpeed Insights HTTP Client & Fallback Tests
# ============================================================================

def test_pagespeed_client_fallback_on_unconfigured_api_key():
    """Verifies that an unconfigured or empty API key gracefully returns Unavailable without crashing."""
    report = audit_pagespeed("https://example-unreachable-biz-123.com", api_key="", timeout=0.5)
    assert isinstance(report, PageSpeedAuditReport)
    assert report.status in ("Unavailable", "Not Checked")
    assert report.mobile.status in ("Unavailable", "Not Checked")
    assert report.desktop.status in ("Unavailable", "Not Checked")
    assert report.mobile.core_web_vitals.lcp == "Unavailable"
    assert report.mobile.core_web_vitals.cls == "Unavailable"


def test_pagespeed_client_invalid_url():
    """Verifies that invalid or empty URLs are handled with clean error messages."""
    res = fetch_pagespeed_strategy("", strategy="mobile")
    assert res.status == "Unavailable"
    assert "Invalid" in res.diagnostics or "URL" in res.diagnostics


def test_pagespeed_client_mock_successful_response(monkeypatch):
    """Verifies parsing of score, Core Web Vitals, mobile viewport, and screenshot data."""
    mock_payload = {
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.94}},
            "audits": {
                "largest-contentful-paint": {"displayValue": "1.4 s"},
                "cumulative-layout-shift": {"displayValue": "0.01"},
                "first-contentful-paint": {"displayValue": "0.9 s"},
                "interaction-to-next-paint": {"displayValue": "60 ms"},
                "viewport": {"score": 1},
                "final-screenshot": {"details": {"data": "data:image/jpeg;base64,mockthumbdata"}},
            },
        }
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return mock_payload

    from curl_cffi import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockResponse())

    res = fetch_pagespeed_strategy("https://fast-austin-roofing.com", strategy="mobile", api_key="valid_key")
    assert res.status == "Pass"
    assert res.performance_score == 94
    assert res.core_web_vitals.lcp == "1.4 s"
    assert res.core_web_vitals.cls == "0.01"
    assert res.core_web_vitals.inp == "60 ms"
    assert res.core_web_vitals.fcp == "0.9 s"
    assert res.is_mobile_friendly is True
    assert res.screenshot_data_url == "data:image/jpeg;base64,mockthumbdata"

    # Also test check_pagespeed bridge
    bridge_res = check_pagespeed("https://fast-austin-roofing.com", api_key="valid_key")
    assert isinstance(bridge_res, PageSpeedResult)
    assert bridge_res.mobile_score == 94
    assert bridge_res.lcp_seconds == 1.4
    assert bridge_res.cls_value == 0.01
    assert bridge_res.mobile_friendly_status == "Pass"


def test_pagespeed_client_handles_429_rate_limit(monkeypatch):
    """Verifies that HTTP 429 rate limit returns structured Unavailable status."""
    class MockRateLimitResponse:
        status_code = 429
        def json(self):
            return {"error": {"message": "Rate limit exceeded"}}

    from curl_cffi import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockRateLimitResponse())

    res = fetch_pagespeed_strategy("https://busy-site.com", strategy="mobile", api_key="key")
    assert res.status == "Unavailable"
    assert "rate limit" in res.diagnostics.lower()


# ============================================================================
# 2. Competitor Research & Local Gap Analysis Engine Tests
# ============================================================================

def test_competitor_discovery_ranking_and_self_exclusion():
    """Verifies that discover_top_competitors ranks by reviews/ratings and excludes self."""
    target = {
        "place_id": "target_place_id",
        "name": "Austin Premier Roofing",
        "category": "Roofing contractor",
        "rating": 4.2,
        "reviews_count": 25,
        "seo_health_score": 60,
    }

    pool = [
        # Self listing
        {"place_id": "target_place_id", "name": "Austin Premier Roofing", "category": "Roofing contractor", "reviews_count": 25},
        # Direct competitors with high reviews
        {"place_id": "comp_1", "name": "Apex Roofing Austin", "category": "Roofing contractor", "rating": 4.9, "reviews_count": 310, "seo_health_score": 85, "has_schema": True, "has_tracking": True},
        {"place_id": "comp_2", "name": "Texas Shield Roofs", "category": "Roofing contractor", "rating": 4.8, "reviews_count": 195, "seo_health_score": 78, "has_schema": True, "has_tracking": False},
        {"place_id": "comp_3", "name": "Capital City Roofers", "category": "Roofing contractor", "rating": 4.7, "reviews_count": 120, "seo_health_score": 72, "has_schema": False, "has_tracking": True},
        {"place_id": "comp_4", "name": "Austin Small Roofer", "category": "Roofing contractor", "rating": 4.0, "reviews_count": 10, "seo_health_score": 50},
        # Different category
        {"place_id": "comp_diff", "name": "Austin Flower Shop", "category": "Florist", "rating": 5.0, "reviews_count": 500},
    ]

    competitors = discover_top_competitors(target, pool, limit=3)
    assert len(competitors) == 3
    # Verify ranked in descending order of reviews
    assert competitors[0].name == "Apex Roofing Austin"
    assert competitors[0].reviews_count == 310
    assert competitors[1].name == "Texas Shield Roofs"
    assert competitors[2].name == "Capital City Roofers"
    # Verify self is not in competitors
    assert all(c.place_id != "target_place_id" for c in competitors)


def test_competitor_gap_analysis_calculations():
    """Verifies metrics comparison, trailing gaps, and structured summary."""
    target = {
        "place_id": "target_1",
        "name": "Lone Star Dental",
        "category": "Dentist",
        "rating": 4.0,
        "reviews_count": 18,
        "seo_health_score": 55,
        "has_schema": False,
        "has_tracking": False,
        "neighborhood": "Austin, TX",
    }

    pool = [
        {
            "place_id": "comp_lead",
            "name": "Austin Elite Smiles",
            "category": "Dentist",
            "rating": 4.9,
            "reviews_count": 220,
            "seo_health_score": 85,
            "has_schema": True,
            "has_tracking": True,
        }
    ]

    analysis = build_competitor_gap_analysis(target, pool)
    assert analysis.status == "Completed"
    assert len(analysis.competitors) == 1
    # Check that trailing gaps identified review deficit, rating gap, schema, and tracking
    gap_texts = " ".join(analysis.trailing_gaps)
    assert "Review Volume Gap" in gap_texts
    assert "Star Rating Gap" in gap_texts
    assert "Schema Advantage" in gap_texts
    assert "Marketing Analytics" in gap_texts


def test_competitor_gap_analysis_empty_pool():
    """Verifies that an empty competitor pool gracefully returns Insufficient Competitor Data."""
    target = {"name": "Solo Business", "category": "Rare Niche"}
    analysis = build_competitor_gap_analysis(target, candidate_pool=[])
    assert analysis.status == "Insufficient Competitor Data"
    assert len(analysis.competitors) == 0
    assert len(analysis.trailing_gaps) == 0


# ============================================================================
# 3. Tracking & Analytics Tags Detection Tests
# ============================================================================

def test_tracking_tags_detection_with_all_tags():
    """Verifies detection of GA4, GTM, Google Ads, Meta Pixel, Clarity, and Hotjar."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <!-- Google Tag Manager -->
        <script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
        new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
        j=d.createElement(s),dl=l!='dataLayer'?'&l='+dl:'';j.async=true;j.src=
        'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
        })(window,document,'script','dataLayer','GTM-XYZ1234');</script>
        <!-- Google Analytics 4 & Ads -->
        <script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC98765"></script>
        <script>
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-ABC98765');
            gtag('config', 'AW-1122334455');
        </script>
        <!-- Meta Pixel Code -->
        <script>
            !function(f,b,e,v,n,t,s)
            {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
            n.callMethod.apply(n,arguments):n.queue.push(arguments)};
            if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
            n.queue=[];t=b.createElement(e);t.async=!0;
            t.src=v;s=b.getElementsByTagName(e)[0];
            s.parentNode.insertBefore(t,s)}(window, document,'script',
            'https://connect.facebook.net/en_US/fbevents.js');
            fbq('init', '987654321012345');
            fbq('track', 'PageView');
        </script>
        <!-- Microsoft Clarity -->
        <script type="text/javascript">
            (function(c,l,a,r,i,t,y){
                c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
                t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
                y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
            })(window, document, "clarity", "script", "clarityid123");
        </script>
    </head>
    <body>
        <h1>Welcome</h1>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    issue, summary = check_ads_and_tracking(soup, html)
    assert issue.audit_status == "Pass"
    assert "Pass: Active" in summary
    assert "Google Analytics 4" in issue.evidence
    assert "GTM-XYZ1234" in issue.evidence
    assert "Meta Pixel" in issue.evidence
    assert "Google Ads" in issue.evidence
    assert "Microsoft Clarity" in issue.evidence


def test_tracking_tags_detection_missing_tags():
    """Verifies that a site with zero tracking tags is flagged as Warning with clear fix recommendation."""
    html = "<html><head><title>No Tracking</title></head><body><p>Clean site</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    issue, summary = check_ads_and_tracking(soup, html)
    assert issue.audit_status == "Warning"
    assert "No Marketing / Tracking Tags Found" in summary
    assert issue.priority == "Medium"


# ============================================================================
# 4. Inner Pages & Content Freshness Scanner Tests
# ============================================================================

def test_inner_pages_scanner_detects_service_location_and_blog():
    """Verifies that navigation links for services, service areas/locations, and blogs are identified."""
    html = """
    <html>
    <body>
        <nav>
            <a href="/about-us">About Us</a>
            <a href="/services">Our Services</a>
            <a href="/services/roof-repair">Roof Repair Service</a>
            <a href="/locations/austin-tx">Austin Service Area</a>
            <a href="/service-areas/round-rock">Round Rock Location</a>
            <a href="/blog">Latest Articles</a>
            <a href="/contact">Contact Us</a>
        </nav>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    issue, summary = check_inner_pages_and_freshness(soup)
    assert issue.audit_status == "Pass"
    assert "Services" in summary
    assert "Locations" in summary
    assert "Blog" in summary


def test_inner_pages_scanner_minimal_single_page():
    """Verifies that a single-page site with no sub-navigation returns a Warning."""
    html = "<html><body><nav><a href='#contact'>Contact</a></nav></body></html>"
    soup = BeautifulSoup(html, "lxml")
    issue, summary = check_inner_pages_and_freshness(soup)
    assert issue.audit_status == "Warning"
    assert "No Dedicated Service" in summary or "service" in issue.evidence.lower()


# ============================================================================
# 5. Excel Export Refinements Tests
# ============================================================================

def test_excel_export_price_range_removed_and_shared_contact_flag():
    """
    Verifies:
    1. 'Price Range' is completely absent from headers.
    2. 'Shared Contact Flag' column is present and properly flags shared phone/email.
    3. 'Email Type' and 'Email Verification Status' columns are present.
    """
    leads = [
        LeadItem(
            name="Business Alpha",
            category="Electrician",
            phone="512-555-0100",
            emails=["contact@alphagroup.com"],
            website_url="https://alphagroup.com",
            website_status="Has Own Website",
            rating=4.5,
            reviews_count=30,
            place_id="alpha_1",
            address="100 Main St, Austin, TX",
        ),
        LeadItem(
            name="Business Beta (Same Owner)",
            category="Electrician",
            phone="512-555-0100",  # Same phone
            emails=["info@betaelectric.com"],
            website_url="https://betaelectric.com",
            website_status="Has Own Website",
            rating=4.2,
            reviews_count=12,
            place_id="beta_2",
            address="102 Main St, Austin, TX",
        ),
        LeadItem(
            name="Business Gamma",
            category="Electrician",
            phone="512-555-0999",  # Unique phone
            emails=["info@gammapower.com"],
            website_url="https://gammapower.com",
            website_status="Has Own Website",
            rating=4.8,
            reviews_count=50,
            place_id="gamma_3",
            address="200 Oak St, Austin, TX",
        ),
    ]

    xlsx_bytes = generate_leads_excel(leads)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb.active

    headers = [cell.value for cell in ws[1]]
    # 1. Price Range must be removed
    assert "Price Range" not in headers

    # 2. Shared Contact Flag must exist
    assert "Shared Contact Flag" in headers
    shared_flag_col = headers.index("Shared Contact Flag") + 1

    # Row 2 (Alpha) and Row 3 (Beta) share phone -> "Yes — Shared Email/Phone"
    assert ws.cell(row=2, column=shared_flag_col).value == "Yes — Shared Email/Phone"
    assert ws.cell(row=3, column=shared_flag_col).value == "Yes — Shared Email/Phone"
    # Row 4 (Gamma) has unique contact -> "No"
    assert ws.cell(row=4, column=shared_flag_col).value == "No"

    # 3. Email Type & Verification Status exist
    assert "Email Type" in headers
    assert "Email Verification Status" in headers


def test_excel_export_numeric_score_and_split_columns():
    """
    Verifies:
    1. In split schema mode, SEO Health Score is a pure numeric integer (e.g. 78, not '78/100').
    2. Split <Check> Status (enum) and <Check> Details columns are created and populated.
    """
    leads = [
        LeadItem(
            name="Test Biz",
            category="HVAC",
            phone="512-555-1111",
            website_url="https://testhvac.com",
            website_status="Has Own Website",
            place_id="hvac_1",
        )
    ]
    base_xlsx = generate_leads_excel(leads)

    mock_report = SEOReport(
        url="https://testhvac.com",
        seo_health_score=82,
        lead_pitch_priority="Low Priority - Well Optimized",
        xlsx_row_data={
            "SEO Health Score": 82,
            "Lead Pitch Priority": "Low Priority - Well Optimized",
            "SSL & HTTPS Redirect Status": "Pass: Valid SSL and clean 301 HTTPS redirect",
            "Title Tag Status": "Pass: Optimal length (56 chars) and includes primary category",
            "Schema Status": "Critical: Missing LocalBusiness schema markup",
        }
    )

    enriched_xlsx = append_split_seo_columns_to_excel(base_xlsx, {"hvac_1": mock_report})
    wb = openpyxl.load_workbook(io.BytesIO(enriched_xlsx))
    ws = wb.active

    headers = [cell.value for cell in ws[1]]
    # Check that split columns exist
    assert "SSL Status" in headers
    assert "SSL Details" in headers
    assert "Schema Status" in headers
    assert "Schema Details" in headers

    score_col = headers.index("SEO Health Score") + 1
    score_val = ws.cell(row=2, column=score_col).value
    # Must be pure integer 82, not '82/100'
    assert isinstance(score_val, int)
    assert score_val == 82

    ssl_status_col = headers.index("SSL Status") + 1
    ssl_details_col = headers.index("SSL Details") + 1
    assert ws.cell(row=2, column=ssl_status_col).value == "Pass"
    assert "Valid SSL" in str(ws.cell(row=2, column=ssl_details_col).value)

    schema_status_col = headers.index("Schema Status") + 1
    assert ws.cell(row=2, column=schema_status_col).value == "Critical"


# ============================================================================
# 6. Grounded AI Audit Report Generator Tests
# ============================================================================

def test_ai_report_generator_contains_all_8_sections():
    """Verifies that generate_ai_audit_report builds all 8 required sections."""
    from backend.seo_audit.models import AuditIssue
    audit_input = AuditInput(
        url="https://austinpremierroofs.com",
        business_name="Austin Premier Roofs",
        category="Roofing contractor",
        city="Austin",
        phone="512-555-8888",
        rating=4.4,
        reviews_count=45,
    )
    mock_seo = SEOReport(
        url="https://austinpremierroofs.com",
        seo_health_score=72,
        issues={
            "ssl_security": AuditIssue(
                check_name="SSL & HTTPS Redirect Status",
                audit_status="Fail",
                priority="Critical",
                evidence="HTTP does not redirect to HTTPS",
                recommended_fix="Implement 301 permanent redirect rule.",
            ),
            "h1_tag": AuditIssue(
                check_name="H1 Tag Status",
                audit_status="Warning",
                priority="High",
                evidence="H1 tag missing category keyword",
                recommended_fix="Align H1 headline with primary category.",
            ),
        }
    )
    branding = AgencyBranding(agency_name="Apex SEO Studio")
    sections = AuditSectionConfig()

    report = generate_ai_audit_report(
        audit_input=audit_input,
        seo_report=mock_seo,
        sections=sections,
        branding=branding,
    )

    assert isinstance(report, AIAuditReport)
    # 1. Business Overview
    assert report.business_name == "Austin Premier Roofs"
    assert report.website_url == "https://austinpremierroofs.com"
    # 2. Overall Score & Scope
    assert len(report.audit_scope) >= 3
    # 3. Executive Summary
    assert len(report.executive_summary) > 50
    # 4. Categorized Findings
    assert isinstance(report.critical_issues, list)
    assert isinstance(report.warnings, list)
    assert isinstance(report.passed_checks, list)
    # 5. Plain English Explanations
    assert isinstance(report.plain_english_explanations, list)
    # 6. Prioritized Action Plan
    assert len(report.action_plan) >= 1
    # Check roadmap timeframes
    timeframes = [item.timeframe for item in report.action_plan]
    assert any("Quick Win" in tf for tf in timeframes)
    # 7. Competitor Gap or Analysis
    assert report.competitor_analysis is not None
    # 8. Data Limitations
    assert isinstance(report.data_limitations, list)


def test_ai_report_generator_respects_section_filtering():
    """Verifies that disabling sections excludes them from the audit scope and output."""
    audit_input = AuditInput(
        url="https://sampleplumbing.com",
        business_name="Sample Plumbing",
        category="Plumber",
        city="Dallas",
    )
    # Disable competitor research and pagespeed
    sections = AuditSectionConfig(
        competitor_research=False,
        pagespeed_mobile=False,
    )

    report = generate_ai_audit_report(
        audit_input=audit_input,
        sections=sections,
    )

    assert "Competitor Research" not in report.audit_scope
    assert "PageSpeed & Mobile Experience" not in report.audit_scope
    assert report.pagespeed_data is None
    assert len(report.competitors) == 0


def test_ai_report_generator_never_fabricates_when_data_missing():
    """Verifies that missing or unreadable metrics are explicitly noted under data limitations."""
    audit_input = AuditInput(
        url="https://empty-unknown-site-999.org",
        business_name="Unknown Entity",
    )
    sections = AuditSectionConfig()

    report = generate_ai_audit_report(
        audit_input=audit_input,
        sections=sections,
    )

    # Must contain data limitations acknowledging unconfigured or unreadable components
    assert len(report.data_limitations) >= 1
    limitations_str = " ".join(report.data_limitations)
    assert any(term in limitations_str for term in ("PageSpeed", "Competitor", "Could Not Read", "Unavailable", "Not Checked"))


# ============================================================================
# 7. White-Label Branded PDF Exporter Tests
# ============================================================================

def test_pdf_exporter_generates_valid_pdf_bytes():
    """Verifies that generate_audit_pdf returns non-empty valid PDF bytes starting with %PDF-."""
    audit_input = AuditInput(
        url="https://austinqualityroofs.com",
        business_name="Austin Quality Roofs",
        category="Roofing contractor",
        city="Austin",
        phone="512-555-7777",
    )
    branding = AgencyBranding(
        agency_name="Pinnacle Growth Agency",
        primary_color="#1E3A8A",
        accent_color="#10B981",
        contact_email="team@pinnaclegrowth.com",
        website="https://pinnaclegrowth.com",
    )
    report = generate_ai_audit_report(audit_input=audit_input, branding=branding)

    pdf_bytes = generate_audit_pdf(report, branding=branding)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 2000
    # Must start with %PDF- magic header
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_exporter_custom_branding_and_competitor_sections():
    """Verifies PDF generation with competitors, custom brand colors, and action plan roadmap."""
    report = AIAuditReport(
        business_name="Elite HVAC Services",
        category="HVAC contractor",
        website_url="https://elitehvac.com",
        audited_url="https://elitehvac.com",
        location="Austin, TX",
        audit_date="2026-11-20",
        seo_health_score=76,
        audit_scope=["Website Technical SEO", "On-Page & Local SEO", "Competitor Research"],
        executive_summary="Elite HVAC Services has a solid digital foundation with critical local SEO opportunities.",
        critical_issues=["Missing LocalBusiness Schema markup", "Canonical tag points to external staging domain"],
        warnings=["H1 tag missing primary category keyword", "Meta description truncated"],
        passed_checks=["Valid SSL Certificate with clean 301 HTTPS redirect", "Fast TTFB server response"],
        plain_english_explanations=[
            {
                "check": "Schema Markup",
                "meaning": "Lacks structured data helping search engines identify business hours and address.",
                "impact": "Misses out on Google Rich Snippets in local search results.",
                "recommendation": "Deploy JSON-LD LocalBusiness schema.",
            }
        ],
        action_plan=[
            ActionPlanItem(
                title="Implement LocalBusiness Schema Markup",
                timeframe="Quick Win (1-7 Days)",
                priority="Critical",
                category="Technical SEO",
                description="Inject JSON-LD schema into homepage head.",
            ),
            ActionPlanItem(
                title="Optimize H1 & Title Tags with Core Keywords",
                timeframe="Medium-Term (2-4 Weeks)",
                priority="High",
                category="On-Page SEO",
                description="Align primary headlines with 'HVAC contractor in Austin'.",
            ),
        ],
        competitors=[
            CompetitorComparison(
                business_name="Austin Air Masters",
                rating=4.9,
                reviews_count=210,
                seo_score=88,
                has_schema=True,
                has_tracking=True,
                trailing_gaps=["210 Google Reviews vs 25 Target", "LocalBusiness Schema Active"],
            )
        ],
        data_limitations=["Google PageSpeed Insights: Unavailable (API Key unconfigured)"],
    )

    branding = AgencyBranding(
        agency_name="Apex Media Agency",
        primary_color="#094CB2",
        accent_color="#059669",
    )

    pdf_bytes = generate_audit_pdf(report, branding=branding)
    assert len(pdf_bytes) > 3000
    assert pdf_bytes.startswith(b"%PDF-")


# ============================================================================
# 8. FastAPI Endpoints in backend/seo_audit/routes.py Tests
# ============================================================================

@pytest.fixture
def client():
    """Provides FastAPI TestClient instance."""
    return TestClient(app)


def test_api_generate_report_endpoint(client):
    """Tests POST /api/seo-audit/generate-report."""
    payload = {
        "audit_input": {
            "url": "https://austinmasterplumber.com",
            "business_name": "Austin Master Plumber",
            "category": "Plumber",
            "city": "Austin",
            "phone": "512-555-4321",
        },
        "sections": {
            "website_technical_seo": True,
            "onpage_local_seo": True,
            "competitor_research": False,
            "pagespeed_mobile": False,
        },
        "branding": {
            "agency_name": "Test Agency Pro",
            "primary_color": "#2563EB",
        }
    }
    resp = client.post("/api/seo-audit/generate-report", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["business_name"] == "Austin Master Plumber"
    assert "Website Technical SEO" in data["audit_scope"]
    assert "executive_summary" in data
    assert isinstance(data["action_plan"], list)


def test_api_export_pdf_endpoint(client):
    """Tests POST /api/seo-audit/export-pdf."""
    payload = {
        "audit_input": {
            "url": "https://austinelectric.com",
            "business_name": "Austin Electric Pros",
            "category": "Electrician",
            "city": "Austin",
        },
        "branding": {
            "agency_name": "Digital Surge",
        }
    }
    resp = client.post("/api/seo-audit/export-pdf", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    assert len(resp.content) > 1000


def test_api_pagespeed_endpoint(client):
    """Tests POST /api/seo-audit/pagespeed."""
    resp = client.post("/api/seo-audit/pagespeed", json={"url": "https://example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("Pass", "Warning", "Critical", "Unavailable", "Not Checked")


def test_api_agency_branding_get_and_post(client):
    """Tests GET and POST /api/agency/branding."""
    # 1. Get current branding
    get_resp = client.get("/api/agency/branding")
    assert get_resp.status_code == 200
    orig_branding = get_resp.json()
    assert "agency_name" in orig_branding

    # 2. Update branding
    updated_payload = {
        "agency_name": "Custom Agency X",
        "tagline": "Custom Tagline Here",
        "primary_color": "#FF5733",
        "accent_color": "#33FF57",
        "contact_email": "hello@customagencyx.com",
        "website": "https://customagencyx.com",
    }
    post_resp = client.post("/api/agency/branding", json=updated_payload)
    assert post_resp.status_code == 200
    saved = post_resp.json()
    assert saved["agency_name"] == "Custom Agency X"
    assert saved["primary_color"] == "#FF5733"

    # 3. Verify retrieved branding reflects update
    verify_resp = client.get("/api/agency/branding")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["agency_name"] == "Custom Agency X"


def test_api_competitors_endpoint(client):
    """Tests GET /api/seo-audit/competitors/{place_id}."""
    resp = client.get("/api/seo-audit/competitors/non_existent_place_id_123")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

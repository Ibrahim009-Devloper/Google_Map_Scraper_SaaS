"""
Tests for Integrated Single-Fetch Website Scraping & Local SEO Audit Engine.
Verifies simultaneous email extraction, SEO audit on cached HTML, fault isolation,
SQLite buffer persistence, and non-destructive XLSX/CSV exports.
"""

import io
import json
import openpyxl
import pytest

from agent.schemas import LeadItem, SocialLinks
from agent.web_enricher import enrich_single_lead, enrich_leads_concurrently
from agent.pipeline import export_leads_to_csv
from backend.seo_audit.models import SEOReport
from backend.seo_audit.xlsx_appender import append_seo_columns_to_excel, SEO_XLSX_COLUMNS
from backend.temp_store import (
    init_db_sync,
    save_temp_leads_batch_sync,
    get_temp_leads_sync,
    create_job_sync,
)


MOCK_HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Elite Dallas Roofing | Reliable Roof Repair</title>
    <meta name="description" content="Dallas premier commercial and residential roof repair and replacement. Call 214-555-0199 for free inspection.">
    <link rel="canonical" href="https://elitedallasroofing.com/">
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "RoofingContractor",
      "name": "Elite Roofing Dallas",
      "telephone": "+1-214-555-0199",
      "address": {
        "@type": "PostalAddress",
        "addressLocality": "Dallas",
        "addressRegion": "TX"
      }
    }
    </script>
</head>
<body>
    <header>
        <a href="https://facebook.com/elitedallasroofing">Facebook</a>
        <a href="https://instagram.com/elitedallasroofing">Instagram</a>
        <span>Contact: info@elitedallasroofing.com</span>
        <span>Phone: (214) 555-0199</span>
    </header>
    <main>
        <h1>Dallas Premier Roofing Experts</h1>
        <p>Serving Dallas with top quality metal and shingle roofing.</p>
        <img src="/roof.jpg" alt="Commercial roof installation in Dallas TX">
    </main>
</body>
</html>"""


def test_in_flight_enrichment_with_seo(monkeypatch):
    """
    Verifies that enrich_single_lead extracts emails, socials, CMS,
    AND runs the 11-point Local SEO audit in a single pass on the cached HTML.
    """
    from agent import web_enricher

    # Mock fetch_html to return sample rich HTML without network calls
    monkeypatch.setattr(web_enricher, "fetch_html", lambda url, timeout=3.5: MOCK_HOMEPAGE_HTML)

    lead = LeadItem(
        place_id="ChIJ_test_roofing_101",
        name="Elite Roofing Dallas",
        category="Roofing Contractor",
        phone="+1 214-555-0199",
        website_status="Has Own Website",
        website_url="https://elitedallasroofing.com",
        neighborhood="Dallas",
        address="123 Main St, Dallas, TX 75201",
    )

    enriched = enrich_single_lead(
        lead=lead,
        country_code="us",
        extract_email_opt=True,
        extract_social_opt=True,
        detect_cms_opt=True,
        audit_seo_opt=True,
    )

    # 1. Contact info extracted
    assert "info@elitedallasroofing.com" in enriched.emails
    assert enriched.social_links.facebook == "https://facebook.com/elitedallasroofing"
    assert enriched.social_links.instagram == "https://instagram.com/elitedallasroofing"

    # 2. In-flight SEO report generated
    assert enriched.seo_report is not None
    assert isinstance(enriched.seo_report, dict)
    assert "opportunity_score" in enriched.seo_report
    assert enriched.seo_report["opportunity_score"] is not None
    assert "issues" in enriched.seo_report
    assert "xlsx_row_data" in enriched.seo_report

    # 3. Check specific verified signals
    issues = enriched.seo_report["issues"]
    assert issues["mobile_friendly"]["audit_status"] == "Pass"
    assert issues["title_tag"]["audit_status"] == "Pass"
    assert issues["schema_markup"]["audit_status"] == "Pass"


def test_in_flight_enrichment_seo_off(monkeypatch):
    """
    Verifies that when audit_seo_opt=False, contact info is extracted
    and seo_report remains None (Tier 2 behavior).
    """
    from agent import web_enricher
    monkeypatch.setattr(web_enricher, "fetch_html", lambda url, timeout=3.5: MOCK_HOMEPAGE_HTML)

    lead = LeadItem(
        place_id="ChIJ_test_roofing_102",
        name="Elite Roofing Dallas",
        website_status="Has Own Website",
        website_url="https://elitedallasroofing.com",
    )

    enriched = enrich_single_lead(
        lead=lead,
        country_code="us",
        extract_email_opt=True,
        audit_seo_opt=False,
    )

    assert "info@elitedallasroofing.com" in enriched.emails
    assert enriched.seo_report is None


def test_in_flight_enrichment_unreachable_site(monkeypatch):
    """
    Verifies fault tolerance: when a website fails to load,
    the SEO report captures the load failure rather than leaving the lead un-audited.
    """
    from agent import web_enricher
    # Simulate timeout or DNS failure returning None
    monkeypatch.setattr(web_enricher, "fetch_html", lambda url, timeout=3.5: None)

    lead = LeadItem(
        place_id="ChIJ_test_dead_site_103",
        name="Dead Site LLC",
        website_status="Has Own Website",
        website_url="https://broken-down-domain-xyz.com",
    )

    enriched = enrich_single_lead(
        lead=lead,
        country_code="us",
        audit_seo_opt=True,
    )

    # Lead survives without exception
    assert "broken-down-domain-xyz.com" in enriched.website_url
    # SEO report reflects the load failure
    assert enriched.seo_report is not None


def test_lead_storage_with_seo_report(tmp_path, monkeypatch):
    """
    Verifies that LeadItem with embedded seo_report serializes, saves into
    SQLite buffer, and deserializes flawlessly.
    """
    # Point temp DB to test directory
    test_db = tmp_path / "test_temp_cache.db"
    import backend.temp_store as ts
    monkeypatch.setattr(ts, "TEMP_DB_PATH", test_db)

    init_db_sync()

    job_id = "job_test_seo_persist"
    create_job_sync(job_id=job_id, session_owner="test_user", is_authenticated=False, prompt="Test Prompt", target_leads=10)

    sample_seo_dict = {
        "url": "https://example.com",
        "opportunity_score": 75,
        "load_time_seconds": 1.2,
        "issues": {},
        "xlsx_row_data": {col: "Test Val" for col in SEO_XLSX_COLUMNS},
        "error_message": None,
    }

    lead = LeadItem(
        place_id="ChIJ_persist_123",
        name="Persist Biz",
        website_status="Has Own Website",
        website_url="https://example.com",
        seo_report=sample_seo_dict,
    )

    saved = save_temp_leads_batch_sync(job_id, [lead])
    assert saved == 1

    loaded_leads = get_temp_leads_sync(job_id)
    assert len(loaded_leads) == 1
    loaded = loaded_leads[0]
    assert loaded.place_id == "ChIJ_persist_123"
    assert loaded.seo_report is not None
    assert loaded.seo_report["opportunity_score"] == 75
    assert loaded.seo_report["xlsx_row_data"]["Final URL & HTTP Status"] == "Test Val"


def test_xlsx_and_csv_export_with_seo(tmp_path):
    """
    Verifies that CSV export adds the seo_health_score, pitch priority, and outreach hook,
    and XLSX export non-destructively appends all 21 styled agency-grade SEO columns.
    """
    seo_rep = SEOReport(
        url="https://example.com",
        seo_health_score=82,
        lead_pitch_priority="Low Priority - Well Optimized",
        icebreaker_hook="Audited Export Roofing in Dallas.",
        load_time_seconds=1.1,
        issues={},
        xlsx_row_data={col: "Pass" for col in SEO_XLSX_COLUMNS},
    )
    seo_rep.xlsx_row_data["SEO Health Score"] = "82/100"
    seo_rep.xlsx_row_data["Lead Pitch Priority"] = "Low Priority - Well Optimized"
    seo_rep.xlsx_row_data["AI / Dynamic Icebreaker Hook"] = "Audited Export Roofing in Dallas."

    lead = LeadItem(
        place_id="ChIJ_export_1",
        name="Export Roofing",
        category="Contractor",
        phone="555-1234",
        website_status="Has Own Website",
        website_url="https://example.com",
        seo_report=seo_rep.model_dump(),
    )

    # 1. Test CSV export
    csv_file = str(tmp_path / "test_leads.csv")
    export_leads_to_csv([lead], csv_file)

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        content = f.read()
    assert "seo_health_score" in content
    assert "lead_pitch_priority" in content
    assert "icebreaker_hook" in content
    assert "82/100" in content

    # 2. Test XLSX export
    # Create base Excel binary
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Place ID", "Name", "Website URL"])
    ws.append(["ChIJ_export_1", "Export Roofing", "https://example.com"])
    base_buf = io.BytesIO()
    wb.save(base_buf)

    seo_dict = {"ChIJ_export_1": seo_rep}
    appended_bytes = append_seo_columns_to_excel(base_buf.getvalue(), seo_dict)

    res_wb = openpyxl.load_workbook(io.BytesIO(appended_bytes))
    res_ws = res_wb.active

    headers = [res_ws.cell(1, col).value for col in range(1, res_ws.max_column + 1)]
    for col_name in SEO_XLSX_COLUMNS:
        assert col_name in headers

    # Verify score row
    row2 = [res_ws.cell(2, col).value for col in range(1, res_ws.max_column + 1)]
    assert "82/100" in row2
    assert "Low Priority - Well Optimized" in row2
    assert "Audited Export Roofing in Dallas." in row2

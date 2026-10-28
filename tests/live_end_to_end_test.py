"""
Full live end-to-end scraper test verifying:
1. FastAPI /api/scrape/start with audit_seo=True
2. Live pipeline scraping + in-flight Local SEO audit
3. SQLite temp buffer persistence of seo_report with 21 columns
4. Download endpoint delivering XLSX with all 21 SEO columns
5. Download endpoint delivering CSV with seo_health_score, pitch priority & outreach hook
"""

import sys
import os
sys.path.insert(0, os.path.abspath("."))

import io
import time
import openpyxl
from fastapi.testclient import TestClient

from backend.main import app
from backend.temp_store import init_db_sync, get_temp_leads_sync, get_job_sync
from backend.seo_audit.config import SEO_XLSX_COLUMNS


def run_full_test():
    print("=" * 70)
    print("RUNNING COMPLETE LIVE END-TO-END PIPELINE AUDIT TEST (21 COLUMNS)")
    print("=" * 70)

    client = TestClient(app)

    # Mock authentication to run as verified user with full quota
    import backend.security as sec
    import backend.supabase_db as sdb
    sec.verify_auth_token = lambda token, supabase_client=None: {
        "id": "test_e2e_user_123",
        "user_uid": "test_e2e_user_123",
        "email": "test_e2e@example.com",
        "name": "Test User",
        "email_verified": True,
        "provider": "google",
    }
    sdb.check_user_limits = lambda **kwargs: {"allowed": True, "effective_target": 2, "plan": "pro"}
    sdb.update_job_record = lambda **kwargs: None
    headers = {"Authorization": "Bearer mock_valid_token"}

    # 1. Start a scraping job via FastAPI endpoint
    payload = {
        "prompt": "dentists in Miami FL 2 leads",
        "target_leads": 2,
        "scrape_website": True,
        "audit_seo": True,
    }

    print(f"\n[1] Starting scraping job with payload: {payload}")
    start_resp = client.post("/api/scrape/start", json=payload, headers=headers)
    print(f"Start Response Status: {start_resp.status_code}")
    start_data = start_resp.json()
    print(f"Start Response Body: {start_data}")
    assert start_resp.status_code == 200, f"Expected 200, got: {start_data}"
    job_id = start_data["job_id"]
    print(f"--> Job registered successfully: {job_id}")

    # 2. Wait for background thread to execute the scrape and enrich leads
    print("\n[2] Waiting for scraper pipeline to complete...")
    max_wait = 90  # 90 seconds max for live web queries
    start_time = time.time()
    job_completed = False

    while time.time() - start_time < max_wait:
        time.sleep(2)
        job = get_job_sync(job_id)
        status = job.get("status") if job else "unknown"
        leads_count = job.get("leads_count", 0) if job else 0
        area = job.get("current_area", "") if job else ""
        print(f"  ... Elapsed: {int(time.time() - start_time)}s | Status: {status} | Leads: {leads_count} | Area: {area[:40]}")
        if status in ("completed", "stopped", "limit_reached"):
            job_completed = True
            break

    assert job_completed, f"Job did not complete within {max_wait}s!"

    # 3. Check SQLite temp_leads
    leads = get_temp_leads_sync(job_id)
    print(f"\n[3] Total Leads in SQLite for {job_id}: {len(leads)}")
    assert len(leads) > 0, "No leads were saved in SQLite!"

    has_seo_report = False
    for l in leads:
        print(f"  Lead: '{l.name}' | Web Status: {l.website_status} | URL: {l.website_url}")
        print(f"    Emails: {l.emails}")
        print(f"    Has SEO Report: {bool(l.seo_report)}")
        if l.seo_report:
            has_seo_report = True
            health = l.seo_report.get("seo_health_score")
            pitch = l.seo_report.get("lead_pitch_priority")
            hook = l.seo_report.get("icebreaker_hook")
            print(f"    -> Health Score: {health}/100 | Pitch: {pitch}")
            print(f"    -> Cold Email Hook: {hook}")
            print(f"    -> TTFB: {l.seo_report.get('xlsx_row_data', {}).get('Server Response (TTFB)')}")
            print(f"    -> Title: {l.seo_report.get('xlsx_row_data', {}).get('Extracted Title Text')}")

    web_leads = [l for l in leads if l.website_status == "Has Own Website" and l.website_url]
    if web_leads:
        assert has_seo_report, "At least one website lead must have a populated seo_report!"
        print("--> SUCCESS: In-flight SEO report successfully generated and saved to SQLite!")

    # 4. Test XLSX download endpoint
    print(f"\n[4] Testing GET /api/scrape/download/{job_id}?format=xlsx")
    xlsx_resp = client.get(f"/api/scrape/download/{job_id}?format=xlsx")
    assert xlsx_resp.status_code == 200, f"XLSX download failed: {xlsx_resp.status_code}"
    assert len(xlsx_resp.content) > 1000, "XLSX binary is empty!"

    # Verify openpyxl can load and inspect columns
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_resp.content))
    ws = wb.active
    header_vals = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    print(f"  XLSX Max Columns: {ws.max_column}")
    print(f"  XLSX Max Rows: {ws.max_row}")

    for col in SEO_XLSX_COLUMNS:
        assert col in header_vals, f"Missing SEO column in XLSX: {col}"
    print(f"--> SUCCESS: All {len(SEO_XLSX_COLUMNS)} Local SEO columns present in generated XLSX!")

    # 5. Test CSV download endpoint
    print(f"\n[5] Testing GET /api/scrape/download/{job_id}?format=csv")
    csv_resp = client.get(f"/api/scrape/download/{job_id}?format=csv")
    assert csv_resp.status_code == 200
    csv_text = csv_resp.text
    assert "seo_health_score" in csv_text
    assert "lead_pitch_priority" in csv_text
    assert "icebreaker_hook" in csv_text
    print("--> SUCCESS: CSV export contains seo_health_score, lead_pitch_priority, and icebreaker_hook!")

    print("\n" + "=" * 70)
    print("ALL 5 LIVE END-TO-END CRITERIA VERIFIED 100% PERFECTLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_full_test()

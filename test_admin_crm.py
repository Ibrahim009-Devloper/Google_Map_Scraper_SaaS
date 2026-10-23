"""
Automated Test Suite for Admin CRM, User Search Auditing,
Runtime Duration Tracking & Scraper Diagnostics.
"""

import time
import json
from fastapi.testclient import TestClient

from backend.main import app
from backend.temp_store import (
    init_db_sync,
    create_job_sync,
    update_job_sync,
    add_job_log_sync,
    get_job_logs_sync,
    get_all_recent_jobs_sync,
    save_temp_leads_batch_sync,
)
from backend import supabase_db
from agent.schemas import LeadItem, SocialLinks


client = TestClient(app)


def test_admin_crm_suite():
    print("=" * 60)
    print("Starting Admin CRM & Scraper Diagnostic Tests...")
    print("=" * 60)

    # 1. Initialize SQLite Database Tables
    init_db_sync()

    # Create dummy admin token mock or override require_admin_user
    # Let's inspect security.require_admin_user:
    from backend import security
    original_require_admin = security.require_admin_user
    security.require_admin_user = lambda auth, supabase_client=None: {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "admin@example.com",
        "role": "admin"
    }

    try:
        # 2. Test Mock Jobs (One Successful, One Failed with Error, One Running)
        job_success_id = f"job_test_success_{int(time.time())}"
        create_job_sync(
            job_id=job_success_id,
            session_owner="usr_alpha_123",
            is_authenticated=True,
            prompt="Dentists in Banani Dhaka with verified email",
            scrape_website=True,
            user_email="client.alex@gmail.com",
            target_leads=50,
        )
        add_job_log_sync(job_success_id, "AI Geo-Planner selected Banani, Dhaka zone.", "PLAN")
        add_job_log_sync(job_success_id, "Harvested 20 leads from page 1.", "INFO")
        add_job_log_sync(job_success_id, "Deep scraped 15 websites and verified 8 emails.", "SUCCESS")
        
        # Save dummy leads for inspection
        dummy_lead = LeadItem(
            place_id="ChIJ_test_place_01",
            name="Banani Dental Clinic",
            category="Dental clinic",
            phone="+8801700000001",
            website_status="Has Own Website",
            website_url="https://bananidental.com",
            emails=["info@bananidental.com"],
            social_links=SocialLinks(facebook="https://facebook.com/bananidental"),
            rating=4.9,
            reviews_count=45,
            address="Road 11, Banani, Dhaka",
        )
        save_temp_leads_batch_sync(job_success_id, [dummy_lead])

        # Complete success job with 45.2s duration
        update_job_sync(
            job_id=job_success_id,
            status="completed",
            leads_count=50,
            duration_seconds=45.2,
            current_area="Done",
        )

        # Job 2: Failed Job with explicit error
        job_fail_id = f"job_test_fail_{int(time.time())}"
        create_job_sync(
            job_id=job_fail_id,
            session_owner="anon_ip_192_168_1_50",
            is_authenticated=False,
            prompt="Restaurants in Gulshan 2 with foodpanda",
            scrape_website=False,
            user_email="Guest (192.168.1.50)",
            target_leads=100,
        )
        add_job_log_sync(job_fail_id, "Starting search for 'Restaurants in Gulshan 2'", "PLAN")
        add_job_log_sync(job_fail_id, "HTTP 429 Connection refused by target", "ERROR")
        add_job_log_sync(job_fail_id, "Traceback (most recent call last):\nTimeoutError: Connection timed out", "ERROR")

        update_job_sync(
            job_id=job_fail_id,
            status="failed",
            error_message="Connection timed out after 3 retries",
            duration_seconds=12.5,
            current_area="Error: Connection timed out",
        )

        print("--> Test 1: Testing GET /api/admin/crm/metrics...")
        resp_metrics = client.get("/api/admin/crm/metrics", headers={"Authorization": "Bearer mock_token"})
        assert resp_metrics.status_code == 200, f"Expected 200, got {resp_metrics.status_code}"
        metrics = resp_metrics.json()
        assert "total_searches" in metrics
        assert "failed_searches" in metrics
        assert "avg_duration_seconds" in metrics
        assert metrics["total_searches"] >= 2
        assert metrics["failed_searches"] >= 1
        print(f"    [PASS] CRM Metrics operational: {metrics}")

        print("\n--> Test 2: Testing GET /api/admin/jobs (All, Filters, and Search)...")
        resp_jobs = client.get("/api/admin/jobs", headers={"Authorization": "Bearer mock_token"})
        assert resp_jobs.status_code == 200
        jobs_data = resp_jobs.json()["jobs"]
        assert len(jobs_data) >= 2
        
        # Verify columns & fields
        found_success = next((j for j in jobs_data if j["job_id"] == job_success_id), None)
        assert found_success is not None
        assert found_success["user_email"] == "client.alex@gmail.com"
        assert found_success["duration_seconds"] == 45.2
        assert found_success["status"] == "completed"
        assert found_success["has_error"] is False
        print("    [PASS] Successful job verified with exact runtime duration (45.2s).")

        found_fail = next((j for j in jobs_data if j["job_id"] == job_fail_id), None)
        assert found_fail is not None
        assert found_fail["has_error"] is True
        assert "Connection timed out" in found_fail["error_message"]
        assert found_fail["duration_seconds"] == 12.5
        print("    [PASS] Failed job verified with error note and duration (12.5s).")

        # Test search filter
        resp_search = client.get("/api/admin/jobs?search=alex@gmail.com", headers={"Authorization": "Bearer mock_token"})
        assert resp_search.status_code == 200
        search_results = resp_search.json()["jobs"]
        assert any(j["job_id"] == job_success_id for j in search_results)
        print("    [PASS] Search by user email operational.")

        # Test errors_only filter
        resp_errors = client.get("/api/admin/jobs?errors_only=true", headers={"Authorization": "Bearer mock_token"})
        assert resp_errors.status_code == 200
        err_results = resp_errors.json()["jobs"]
        assert any(j["job_id"] == job_fail_id for j in err_results)
        assert not any(j["job_id"] == job_success_id for j in err_results)
        print("    [PASS] errors_only filter strictly returns errored searches.")

        print("\n--> Test 3: Testing GET /api/admin/jobs/{job_id}/logs (Log Inspector)...")
        resp_logs = client.get(f"/api/admin/jobs/{job_fail_id}/logs", headers={"Authorization": "Bearer mock_token"})
        assert resp_logs.status_code == 200
        logs_payload = resp_logs.json()
        assert logs_payload["job_id"] == job_fail_id
        assert logs_payload["count"] >= 3
        log_levels = [l["level"] for l in logs_payload["logs"]]
        assert "ERROR" in log_levels
        assert "Traceback" in logs_payload["raw_text"]
        print(f"    [PASS] Retrieved {logs_payload['count']} log lines with error stack traces.")

        print("\n--> Test 4: Testing GET /api/admin/jobs/{job_id}/leads (Leads Inspector)...")
        resp_leads = client.get(f"/api/admin/jobs/{job_success_id}/leads", headers={"Authorization": "Bearer mock_token"})
        assert resp_leads.status_code == 200
        leads_payload = resp_leads.json()
        assert leads_payload["job_id"] == job_success_id
        assert leads_payload["count"] >= 1
        assert leads_payload["leads"][0]["name"] == "Banani Dental Clinic"
        assert leads_payload["leads"][0]["emails"] == ["info@bananidental.com"]
        print("    [PASS] Harvested leads inspection verified with business and emails.")

        print("\n" + "=" * 60)
        print("ALL ADMIN CRM & DEBUGGING TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 60)

    finally:
        security.require_admin_user = original_require_admin


if __name__ == "__main__":
    test_admin_crm_suite()

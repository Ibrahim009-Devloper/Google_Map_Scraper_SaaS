"""
End-to-End Verification Suite for Admin CRM:
1. Zero Mock/Fake Data
2. Unauthenticated / Guest Search Tracking (Prompt, Timestamp, Duration, IP)
3. Blocked Search Attempt Audit
4. Guest vs Registered Filtering & Metrics
"""
import time
from fastapi.testclient import TestClient

from backend.main import app
from backend.temp_store import (
    get_sync_connection,
    clean_mock_jobs_sync,
    create_job_sync,
    update_job_sync,
)
from backend import security, supabase_db

client = TestClient(app)

def test_full_e2e_crm_and_guest_tracking():
    print("=" * 60)
    print("STARTING E2E VERIFICATION SUITE...")
    print("=" * 60)

    # 1. Verify Clean Mock Data
    purged = clean_mock_jobs_sync()
    with get_sync_connection() as conn:
        mock_rows = conn.execute("SELECT * FROM active_jobs WHERE job_id LIKE 'job_test_%' OR user_email = 'client.alex@gmail.com'").fetchall()
        assert len(mock_rows) == 0, f"Found mock rows: {mock_rows}"
    print("[PASS] Verified: Zero mock/fake records in active_jobs.")

    # 2. Test Guest Search with Duration and IP
    guest_job_id = f"job_guest_real_{int(time.time())}"
    create_job_sync(
        job_id=guest_job_id,
        session_owner="anon_ip_203_0_113_195",
        is_authenticated=False,
        user_email="Guest (203.0.113.195)",
        prompt="Dentists and Orthodontists in Dhanmondi",
        scrape_website=False,
        target_leads=20,
    )
    # Simulate scraper run for 18.4 seconds
    update_job_sync(
        job_id=guest_job_id,
        status="completed",
        leads_count=20,
        duration_seconds=18.4,
        current_area="Done",
    )

    # 3. Test Blocked Guest Attempt (quota exceeded)
    with get_sync_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO anonymous_quotas (identifier, total_leads_scraped, jobs_count) VALUES ('anon_ip_198_51_100_99', 100, 1)")
        conn.commit()

    blocked_resp = client.post(
        "/api/scrape/start",
        headers={"x-forwarded-for": "198.51.100.99"},
        json={"prompt": "Marketing Agencies in Uttara", "target_leads": 50}
    )
    assert blocked_resp.status_code == 403
    assert blocked_resp.json()["detail"]["status"] == "limit_reached_login_required"

    # Verify blocked attempt is recorded in SQLite
    with get_sync_connection() as conn:
        blocked_row = conn.execute("SELECT * FROM active_jobs WHERE prompt = 'Marketing Agencies in Uttara'").fetchone()
        assert blocked_row is not None
        assert blocked_row["is_authenticated"] == 0
        assert blocked_row["status"] == "blocked_limit"
        assert "198.51.100.99" in blocked_row["user_email"]
        assert blocked_row["duration_seconds"] > 0
    print("[PASS] Verified: Blocked guest attempt recorded with prompt, IP, and duration.")

    # 4. Test Admin CRM API with mock admin auth
    orig_require_admin = security.require_admin_user
    security.require_admin_user = lambda auth, supabase_client=None: {
        "id": "dd34441f-bdee-4ac5-9610-3745a2be31a1",
        "email": "ibrahim009.developer@gmail.com",
        "role": "admin"
    }

    try:
        # A. Test CRM Metrics
        resp_metrics = client.get("/api/admin/crm/metrics", headers={"Authorization": "Bearer mock_token"})
        assert resp_metrics.status_code == 200
        m = resp_metrics.json()
        assert "guest_searches" in m
        assert "user_searches" in m
        assert m["guest_searches"] >= 2
        print(f"[PASS] CRM Metrics: Total={m['total_searches']}, Guest={m['guest_searches']}, Registered={m['user_searches']}, AvgDuration={m['avg_duration_seconds']}s")

        # B. Test GET /api/admin/jobs?user_type=guest
        resp_guests = client.get("/api/admin/jobs?user_type=guest", headers={"Authorization": "Bearer mock_token"})
        assert resp_guests.status_code == 200
        guests_data = resp_guests.json()["jobs"]
        assert len(guests_data) >= 2
        assert all(not j["is_authenticated"] or j["user_role"] == "guest" for j in guests_data)
        
        found_guest_job = next((j for j in guests_data if j["job_id"] == guest_job_id), None)
        assert found_guest_job is not None
        assert found_guest_job["prompt"] == "Dentists and Orthodontists in Dhanmondi"
        assert found_guest_job["duration_seconds"] == 18.4
        assert found_guest_job["user_email"] == "Guest (203.0.113.195)"
        assert found_guest_job["created_at"] is not None
        print(f"[PASS] Found Guest Search in CRM: Prompt='{found_guest_job['prompt']}', Duration={found_guest_job['duration_seconds']}s, Time={found_guest_job['created_at']}")

        # C. Test GET /api/admin/jobs?user_type=user
        resp_users = client.get("/api/admin/jobs?user_type=user", headers={"Authorization": "Bearer mock_token"})
        assert resp_users.status_code == 200
        users_data = resp_users.json()["jobs"]
        assert all(j["is_authenticated"] and j["user_role"] != "guest" for j in users_data)
        print(f"[PASS] Registered Users Filter returned {len(users_data)} authenticated jobs.")

        # D. Clean up test rows
        with get_sync_connection() as conn:
            conn.execute("DELETE FROM active_jobs WHERE job_id = ? OR prompt = 'Marketing Agencies in Uttara'", (guest_job_id,))
            conn.execute("DELETE FROM anonymous_quotas WHERE identifier = 'anon_ip_198_51_100_99'")
            conn.commit()

        print("\n" + "=" * 60)
        print("ALL E2E VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
        print("=" * 60)

    finally:
        security.require_admin_user = orig_require_admin

if __name__ == "__main__":
    test_full_e2e_crm_and_guest_tracking()

"""
Tests for Guest (unauthenticated) search tracking & attempt logging.
"""
from fastapi.testclient import TestClient
from backend.main import app
from backend.temp_store import get_sync_connection

client = TestClient(app)

def test_guest_search_blocked_attempt_is_logged():
    # Force guest quota to be exceeded for testclient IP
    with get_sync_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO anonymous_quotas (identifier, total_leads_scraped, jobs_count) VALUES ('anon_ip_testclient', 100, 1)")
        conn.commit()

    resp = client.post("/api/scrape/start", json={
        "prompt": "Guest Target Query Testing Dhaka",
        "target_leads": 20
    })

    assert resp.status_code == 403
    assert resp.json()["detail"]["status"] == "limit_reached_login_required"

    # Verify that even though 403 was raised, the guest's attempt was captured in active_jobs!
    with get_sync_connection() as conn:
        row = conn.execute("SELECT * FROM active_jobs WHERE prompt = 'Guest Target Query Testing Dhaka'").fetchone()
        assert row is not None
        assert row["is_authenticated"] == 0
        assert row["status"] == "blocked_limit"
        assert "Guest" in row["user_email"]

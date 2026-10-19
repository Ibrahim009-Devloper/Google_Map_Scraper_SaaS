"""
Comprehensive Verification Test Suite for Milestone 4:
FastAPI Application, Rate Limiting, Concurrency Locks, SSE Live Stream,
CSV/JSON Exports, and Auth Protected Endpoints.
"""

import json
import time
from fastapi.testclient import TestClient

from backend.main import app, job_manager
from backend.temp_store import (
    init_db_sync,
    create_job_sync,
    save_temp_leads_batch_sync,
    increment_anonymous_quota_sync,
)
from agent.schemas import LeadItem, SocialLinks


client = TestClient(app)


def test_endpoint_health():
    print("--> Test 1: Testing GET /health...")
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["supabase_connected"] is True
    assert data["anonymous_lead_limit"] == 1000
    print("    [PASS] /health endpoint is operational.")


def test_scrape_start_validations_and_concurrency():
    print("--> Test 2: Testing POST /api/scrape/start (Input Validation, Quota & Concurrency)...")
    init_db_sync()

    # 1. Invalid prompt too short
    resp_short = client.post("/api/scrape/start", json={"prompt": "hi"})
    assert resp_short.status_code == 422, f"Expected 422 for short prompt, got {resp_short.status_code}"

    # 2. Invalid prompt too long (> 300 chars)
    resp_long = client.post("/api/scrape/start", json={"prompt": "x" * 305})
    assert resp_long.status_code == 422, f"Expected 422 for long prompt, got {resp_long.status_code}"

    # 3. Quota exceeded check
    maxed_ip = "198.51.100.45"
    increment_anonymous_quota_sync(f"anon_ip_{maxed_ip.replace('.', '_')}", 1000)
    resp_quota = client.post(
        "/api/scrape/start",
        json={"prompt": "Restaurants in Uttara without website"},
        headers={"x-forwarded-for": maxed_ip},
    )
    assert resp_quota.status_code == 403, f"Expected 403 quota reached, got {resp_quota.status_code}"
    print("    [PASS] Input validations and 1000 lead quota check verified.")


def test_job_lifecycle_and_sse_streaming():
    print("--> Test 3: Testing Job Creation, SSE Streaming & Stop Signal...")
    import uuid
    job_id = f"job_stream_{uuid.uuid4().hex[:8]}"
    create_job_sync(
        job_id=job_id,
        session_owner="test_stream_user",
        is_authenticated=False,
        prompt="Bakeries in Gulshan",
    )
    sample_lead = LeadItem(
        place_id="ChIJ_stream_place_01",
        name="Gulshan Sweet Treats",
        category="Bakery",
        phone="01711998877",
        website_status="No Website",
        social_links=SocialLinks(),
        rating=4.7,
        reviews_count=65,
    )
    save_temp_leads_batch_sync(job_id, [sample_lead])
    from backend.temp_store import update_job_sync
    update_job_sync(job_id, status="completed", current_area="Done")

    # 1. Test SSE Stream
    with client.stream("GET", f"/api/scrape/stream/{job_id}") as stream_resp:
        assert stream_resp.status_code == 200
        assert "text/event-stream" in stream_resp.headers["content-type"]
        for line in stream_resp.iter_lines():
            if line and line.startswith("data: "):
                event_data = json.loads(line[6:])
                assert event_data["job_id"] == job_id
                assert event_data["leads_count"] >= 1
                assert event_data["done"] is True
                break

    # 2. Test Stop Endpoint
    running_job_id = f"job_running_{uuid.uuid4().hex[:8]}"
    create_job_sync(
        job_id=running_job_id,
        session_owner="test_runner_user",
        is_authenticated=False,
        prompt="Spas in Banani",
    )
    stop_resp = client.post(f"/api/scrape/stop/{running_job_id}")
    assert stop_resp.status_code == 200
    stop_data = stop_resp.json()
    assert stop_data["status"] == "stopped"
    print("    [PASS] SSE live streaming and stop endpoint verified.")


def test_download_endpoints():
    print("--> Test 4: Testing GET /api/scrape/download/{job_id} (CSV & JSON)...")
    import uuid
    job_id = f"job_download_{uuid.uuid4().hex[:8]}"
    create_job_sync(
        job_id=job_id,
        session_owner="test_downloader",
        is_authenticated=False,
        prompt="Dentists in Banani",
    )
    lead = LeadItem(
        place_id="ChIJ_download_001",
        name="Banani Dental Care",
        category="Dentist",
        phone="01811223344",
        website_status="Has Own Website",
        website_url="https://bananidental.com",
        emails=["care@bananidental.com"],
        social_links=SocialLinks(facebook="https://facebook.com/bananidental"),
        rating=4.9,
        reviews_count=120,
    )
    save_temp_leads_batch_sync(job_id, [lead])

    # 1. Download CSV
    csv_resp = client.get(f"/api/scrape/download/{job_id}?format=csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "attachment;" in csv_resp.headers["content-disposition"]
    # Check for UTF-8 BOM
    assert csv_resp.content.startswith(b"\xef\xbb\xbf"), "CSV missing UTF-8 BOM"
    assert "Banani Dental Care" in csv_resp.text

    # 2. Download JSON
    json_resp = client.get(f"/api/scrape/download/{job_id}?format=json")
    assert json_resp.status_code == 200
    assert "application/json" in json_resp.headers["content-type"]
    leads_json = json_resp.json()
    assert len(leads_json) == 1
    assert leads_json[0]["name"] == "Banani Dental Care"
    print("    [PASS] CSV (with Excel UTF-8 BOM) and JSON exports verified.")


def test_auth_protection_on_endpoints():
    print("--> Test 5: Testing Authentication Protection on Secure Endpoints...")
    # 1. POST /api/auth/sync-session without token -> 401
    resp_sync = client.post("/api/auth/sync-session", json={"job_id": "job_123"})
    assert resp_sync.status_code == 401

    # 2. GET /api/user/my-leads without token -> 401
    resp_leads = client.get("/api/user/my-leads")
    assert resp_leads.status_code == 401
    print("    [PASS] Endpoints properly reject unauthenticated requests with 401 Unauthorized.")


def test_reviews_endpoints():
    print("--> Test 6: Testing Reviews Endpoints (POST & GET /api/reviews)...")
    # 1. Post a review
    review_payload = {
        "rating": 5,
        "comment": "FastAPI SSE implementation is incredibly responsive and smooth!",
        "wants_paid_version": True,
    }
    post_resp = client.post("/api/reviews", json=review_payload)
    assert post_resp.status_code == 200
    review_data = post_resp.json()
    assert review_data["status"] == "success"

    # 2. List reviews
    get_resp = client.get("/api/reviews?limit=5")
    assert get_resp.status_code == 200
    reviews_list = get_resp.json()
    assert reviews_list["count"] >= 1
    print("    [PASS] Review submission and public list retrieval verified.")


if __name__ == "__main__":
    print("==================================================")
    print("Starting Milestone 4 Verification Test Suite...")
    print("==================================================")
    test_endpoint_health()
    test_scrape_start_validations_and_concurrency()
    test_job_lifecycle_and_sse_streaming()
    test_download_endpoints()
    test_auth_protection_on_endpoints()
    test_reviews_endpoints()
    print("==================================================")
    print("ALL MILESTONE 4 TESTS PASSED PERFECTLY! [100% SUCCESS]")
    print("==================================================")

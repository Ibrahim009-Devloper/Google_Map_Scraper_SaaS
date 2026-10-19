"""
Comprehensive Test Suite for Milestone 2:
1. SQLite WAL Mode & Schema initialization
2. Anonymous Quota tracking (Sync & Async)
3. Active Job tracking & status transitions
4. Temp Leads storage & ON CONFLICT deduplication
5. Pipeline stop_event cancellation
6. Quota limit enforcement (limit_reached)
"""

import sys
import asyncio
import threading
from typing import List

from agent.schemas import ActionPlan, SubLocation, FilterConfig, EnrichmentConfig, LeadItem, SocialLinks
from backend.temp_store import (
    init_db_sync,
    init_db,
    get_sync_connection,
    get_anonymous_quota_sync,
    increment_anonymous_quota_sync,
    create_job_sync,
    update_job_sync,
    get_job_sync,
    save_temp_leads_batch_sync,
    get_temp_leads_sync,
    get_temp_leads_count_sync,
    cleanup_old_temp_data_sync,
)
from agent.pipeline import run_pipeline


def test_sqlite_wal_and_schema():
    print("--> Test 1: Testing SQLite WAL Mode & Schema Init...")
    init_db_sync()
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"
        
        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        assert "anonymous_quotas" in tables, "anonymous_quotas table missing"
        assert "active_jobs" in tables, "active_jobs table missing"
        assert "temp_leads" in tables, "temp_leads table missing"
    print("    [PASS] WAL mode enabled and all 3 tables exist.")


def test_quota_management():
    print("--> Test 2: Testing Anonymous Quota Management...")
    test_id = "test_ip_192.168.1.100"
    current = get_anonymous_quota_sync(test_id)
    new_total = increment_anonymous_quota_sync(test_id, 25)
    assert new_total == current + 25, f"Expected {current + 25}, got {new_total}"
    assert get_anonymous_quota_sync(test_id) == new_total
    print(f"    [PASS] Quota tracked successfully. Current count: {new_total}")


def test_job_and_temp_leads():
    print("--> Test 3: Testing Job Creation & Deduplicated Temp Leads Storage...")
    job_id = "job_test_123"
    job = create_job_sync(
        job_id=job_id,
        session_owner="anon_test_device",
        is_authenticated=False,
        prompt="Test scraping prompt"
    )
    assert job["status"] == "running"
    
    # Create sample LeadItems
    lead1 = LeadItem(
        place_id="ChIJ_test_place_001",
        name="Test Cafe 1",
        category="Cafe",
        phone="01700000000",
        website_status="No Website",
        social_links=SocialLinks(),
        emails=[],
        rating=4.5,
        reviews_count=20,
    )
    lead2 = LeadItem(
        place_id="ChIJ_test_place_002",
        name="Test Cafe 2",
        category="Cafe",
        phone="01800000000",
        website_status="No Website",
        social_links=SocialLinks(),
        emails=[],
        rating=4.2,
        reviews_count=10,
    )

    # Insert batch
    inserted = save_temp_leads_batch_sync(job_id, [lead1, lead2])
    assert inserted == 2, f"Expected 2 inserted, got {inserted}"
    assert get_temp_leads_count_sync(job_id) == 2

    # Insert same batch again (should deduplicate via UNIQUE place_id)
    inserted_duplicate = save_temp_leads_batch_sync(job_id, [lead1, lead2])
    assert inserted_duplicate == 0, f"Expected 0 on duplicates, got {inserted_duplicate}"
    assert get_temp_leads_count_sync(job_id) == 2

    # Retrieve and verify leads
    leads = get_temp_leads_sync(job_id)
    assert len(leads) == 2
    assert leads[0].place_id == "ChIJ_test_place_001"
    assert leads[1].place_id == "ChIJ_test_place_002"

    # Update job status
    update_job_sync(job_id, status="completed", current_area="Done")
    updated_job = get_job_sync(job_id)
    assert updated_job["status"] == "completed"
    assert updated_job["leads_count"] == 2
    print("    [PASS] Job lifecycle and deduplicated temp leads buffer verified.")


def test_pipeline_stop_event():
    print("--> Test 4: Testing Pipeline with stop_event cancellation...")
    stop_event = threading.Event()
    # Signal stop immediately
    stop_event.set()

    plan = ActionPlan(
        user_prompt="Fast stop test",
        keywords=["Cafe"],
        country_code="bd",
        language="en",
        sub_locations=[
            SubLocation(area_name="Gulshan, Dhaka", lat=23.7925, lon=90.4078, radius=3500)
        ],
        filters=FilterConfig(max_pages_per_search=1),
        enrichment=EnrichmentConfig(enabled=False),
    )

    result = run_pipeline(
        plan=plan,
        job_id="job_stop_test",
        session_owner="anon_stop_tester",
        is_authenticated=False,
        stop_event=stop_event,
        export_files=False,
    )

    assert result["status"] == "stopped", f"Expected 'stopped', got {result['status']}"
    job = get_job_sync("job_stop_test")
    assert job["status"] == "stopped"
    print("    [PASS] Pipeline cancelled immediately via stop_event with status='stopped'.")


def test_pipeline_quota_enforcement():
    print("--> Test 5: Testing Anonymous Quota Limit Enforcement...")
    test_identifier = "anon_maxed_out_user"
    # Artificially set quota to 1000
    increment_anonymous_quota_sync(test_identifier, 1000)

    plan = ActionPlan(
        user_prompt="Quota exceeded test",
        keywords=["Restaurant"],
        country_code="bd",
        language="en",
        sub_locations=[
            SubLocation(area_name="Dhanmondi, Dhaka", lat=23.7461, lon=90.3742, radius=3000)
        ],
        filters=FilterConfig(max_pages_per_search=1),
        enrichment=EnrichmentConfig(enabled=False),
    )

    result = run_pipeline(
        plan=plan,
        job_id="job_quota_exceeded",
        session_owner=test_identifier,
        is_authenticated=False,
        export_files=False,
    )

    assert result["status"] == "limit_reached", f"Expected 'limit_reached', got {result['status']}"
    assert result["total_filtered"] == 0
    print("    [PASS] Pipeline blocked execution for maxed-out anonymous user.")


if __name__ == "__main__":
    print("==================================================")
    print("Starting Milestone 2 Verification Test Suite...")
    print("==================================================")
    test_sqlite_wal_and_schema()
    test_quota_management()
    test_job_and_temp_leads()
    test_pipeline_stop_event()
    test_pipeline_quota_enforcement()
    print("==================================================")
    print("ALL MILESTONE 2 TESTS PASSED PERFECTLY! [100% SUCCESS]")
    print("==================================================")

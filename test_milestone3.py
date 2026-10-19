"""
Comprehensive Test Suite for Milestone 3:
1. Security & Token Utilities (user_uid generation, disposable email filter, IP/Device Fingerprint extraction)
2. Live Supabase Connection & Healthcheck
3. Verified User Upsert (verified_users table)
4. Persistent Lead Storage & Deduplication (saved_leads table)
5. SQLite-to-Supabase Session Sync (/api/auth/sync-session logic)
6. Product Feedback & Reviews (product_reviews table)
"""

import sys
import hashlib
from fastapi import Request
from starlette.datastructures import Headers

from backend.security import (
    generate_user_uid,
    is_disposable_email,
    get_client_identifier,
    verify_auth_token,
)
from backend.supabase_db import (
    get_supabase_client,
    is_supabase_connected,
    ensure_verified_user,
    save_leads_to_supabase,
    get_user_saved_leads,
    sync_temp_session_to_supabase,
    create_product_review,
    get_product_reviews,
)
from backend.temp_store import (
    init_db_sync,
    create_job_sync,
    save_temp_leads_batch_sync,
    get_job_sync,
)
from agent.schemas import LeadItem, SocialLinks


def test_security_utilities():
    print("--> Test 1: Testing Security Utilities...")
    # 1. user_uid generation
    email = "test.lead.hunter@gmail.com"
    expected_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()[:20]
    expected_uid = f"usr_{expected_hash}"
    actual_uid = generate_user_uid(email)
    assert actual_uid == expected_uid, f"Expected {expected_uid}, got {actual_uid}"

    # 2. Disposable email blocking
    assert is_disposable_email("spammer@10minutemail.com") is True
    assert is_disposable_email("fake@yopmail.com") is True
    assert is_disposable_email("test@guerrillamail.com") is True
    assert is_disposable_email("legit@gmail.com") is False
    assert is_disposable_email("founder@mycompany.com") is False

    # 3. Client identifier from mock request
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.195, 10.0.0.1"), (b"x-device-fingerprint", b"fp_abc123")]}
    req = Request(scope)
    ident = get_client_identifier(req)
    assert ident == "anon_fp_abc123", f"Expected anon_fp_abc123, got {ident}"

    scope_ip_only = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.195")]}
    req_ip = Request(scope_ip_only)
    ident_ip = get_client_identifier(req_ip)
    assert ident_ip == "anon_ip_203_0_113_195"

    print("    [PASS] Security utilities (user_uid, temp-mail blocker, client fingerprint) verified.")


def test_supabase_connection():
    print("--> Test 2: Testing Live Supabase Connection...")
    connected = is_supabase_connected()
    assert connected is True, "Failed to connect to Supabase Cloud Database"
    print("    [PASS] Live Supabase connection is active and healthy.")


def test_supabase_user_and_leads():
    print("--> Test 3: Testing User Creation & Persistent Lead Storage in Supabase...")
    test_email = "tester_milestone3@gmail.com"
    test_uid = generate_user_uid(test_email)
    test_name = "Milestone 3 Tester"

    # Step A: Ensure user in verified_users
    user_data = ensure_verified_user(user_uid=test_uid, email=test_email, full_name=test_name)
    assert user_data["user_uid"] == test_uid
    assert user_data["email"] == test_email

    # Step B: Prepare sample leads
    lead1 = LeadItem(
        place_id="ChIJ_sb_test_001",
        name="Supabase Cloud Cafe",
        category="Coffee shop",
        phone="+8801711223344",
        website_status="Has Own Website",
        website_url="https://cloudcafe.example.com",
        emails=["contact@cloudcafe.example.com"],
        social_links=SocialLinks(facebook="https://facebook.com/cloudcafe"),
        cms_tech="WordPress",
        rating=4.9,
        reviews_count=150,
        address="House 12, Road 5, Gulshan, Dhaka",
        neighborhood="Gulshan",
        lat=23.7925,
        lon=90.4078,
    )

    lead2 = LeadItem(
        place_id="ChIJ_sb_test_002",
        name="Supabase Bistro",
        category="Bistro",
        phone="+8801811223344",
        website_status="No Website",
        emails=[],
        social_links=SocialLinks(),
        rating=4.3,
        reviews_count=45,
    )

    # Step C: Save leads
    saved_count = save_leads_to_supabase(
        user_uid=test_uid,
        job_id="job_milestone3_test",
        leads=[lead1, lead2],
    )
    assert saved_count == 2, f"Expected 2 saved, got {saved_count}"

    # Step D: Test Deduplication on same (user_uid, place_id)
    saved_again = save_leads_to_supabase(
        user_uid=test_uid,
        job_id="job_milestone3_test",
        leads=[lead1],
    )
    assert saved_again == 1, "Upsert should cleanly update existing place_id without duplicate keys"

    # Step E: Query back user leads
    user_leads = get_user_saved_leads(user_uid=test_uid, limit=10)
    assert len(user_leads) >= 2
    place_ids = [l["place_id"] for l in user_leads]
    assert "ChIJ_sb_test_001" in place_ids
    assert "ChIJ_sb_test_002" in place_ids
    print(f"    [PASS] User and leads persisted in Supabase with deduplication. (Retrieved {len(user_leads)} leads)")


def test_session_sync():
    print("--> Test 4: Testing SQLite Temp Buffer to Supabase Cloud Sync (/api/auth/sync-session)...")
    init_db_sync()

    job_id = "job_sync_test_999"
    anon_owner = "anon_device_xyz"
    user_email = "sync_user@gmail.com"
    user_uid = generate_user_uid(user_email)

    # 1. Create anonymous job in local SQLite
    create_job_sync(
        job_id=job_id,
        session_owner=anon_owner,
        is_authenticated=False,
        prompt="Restaurants in Banani",
    )

    # 2. Store leads in local SQLite temp_leads
    lead = LeadItem(
        place_id="ChIJ_sync_place_001",
        name="Banani Live Kitchen",
        category="Restaurant",
        phone="01999888777",
        website_status="No Website",
        social_links=SocialLinks(),
        emails=[],
        rating=4.6,
        reviews_count=80,
    )
    save_temp_leads_batch_sync(job_id, [lead])

    # 3. Simulate sync endpoint invocation
    sync_result = sync_temp_session_to_supabase(
        user_uid=user_uid,
        email=user_email,
        job_id=job_id,
        full_name="Sync User",
    )

    assert sync_result["status"] == "success"
    assert sync_result["synced_leads_count"] == 1

    # 4. Verify SQLite job updated
    local_job = get_job_sync(job_id)
    assert local_job["is_authenticated"] == 1
    assert local_job["session_owner"] == user_uid

    # 5. Verify lead in Supabase
    synced_leads = get_user_saved_leads(user_uid=user_uid, limit=5)
    synced_pids = [l["place_id"] for l in synced_leads]
    assert "ChIJ_sync_place_001" in synced_pids
    print("    [PASS] Session sync migrated SQLite buffer to Supabase Cloud and updated job owner.")


def test_product_reviews():
    print("--> Test 5: Testing Product Reviews & Feedback Submission...")
    review = create_product_review(
        rating=5,
        comment="Antigravity GMap Scraper is blazing fast! Need export to HubSpot.",
        user_email="happy_client@gmail.com",
        wants_paid_version=True,
    )
    assert review["rating"] == 5
    assert review["wants_paid_version"] is True

    reviews = get_product_reviews(limit=5)
    assert len(reviews) > 0
    assert any("HubSpot" in r.get("comment", "") for r in reviews)
    print(f"    [PASS] Product reviews stored and retrieved successfully. (Found {len(reviews)} reviews)")


def cleanup_test_records():
    """Tidies up the test records inserted into Supabase."""
    print("--> Cleaning up test records from Supabase...")
    try:
        client = get_supabase_client()
        test_uids = [
            generate_user_uid("tester_milestone3@gmail.com"),
            generate_user_uid("sync_user@gmail.com"),
        ]
        for uid in test_uids:
            client.table("saved_leads").delete().eq("user_uid", uid).execute()
            client.table("verified_users").delete().eq("user_uid", uid).execute()
        print("    [PASS] Test records cleaned up.")
    except Exception as e:
        print(f"    [Notice] Cleanup note: {e}")


if __name__ == "__main__":
    print("==================================================")
    print("Starting Milestone 3 Verification Test Suite...")
    print("==================================================")
    test_security_utilities()
    test_supabase_connection()
    test_supabase_user_and_leads()
    test_session_sync()
    test_product_reviews()
    cleanup_test_records()
    print("==================================================")
    print("ALL MILESTONE 3 TESTS PASSED PERFECTLY! [100% SUCCESS]")
    print("==================================================")

"""
Tests for Admin CRM mock data cleanup.
"""
from backend.temp_store import get_sync_connection, clean_mock_jobs_sync

def test_clean_mock_jobs():
    with get_sync_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO active_jobs (job_id, session_owner, prompt, user_email) VALUES ('job_test_dummy_unit_01', 'anon_test', 'mock query', 'client.alex@gmail.com')")
        conn.commit()

    cleaned = clean_mock_jobs_sync()
    assert cleaned >= 1

    with get_sync_connection() as conn:
        r = conn.execute("SELECT job_id FROM active_jobs WHERE job_id = 'job_test_dummy_unit_01'").fetchone()
        assert r is None

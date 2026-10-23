"""
Tests for Admin CRM User / Guest filtering.
"""
from backend.supabase_db import get_admin_jobs

def test_get_admin_jobs_user_type_filter():
    # Fetch guests
    guest_jobs = get_admin_jobs(limit=50, user_type="guest")
    for j in guest_jobs:
        assert (not j.get("is_authenticated")) or (j.get("user_role") == "guest")

    # Fetch registered users
    reg_jobs = get_admin_jobs(limit=50, user_type="user")
    for j in reg_jobs:
        assert j.get("is_authenticated") and j.get("user_role") != "guest"

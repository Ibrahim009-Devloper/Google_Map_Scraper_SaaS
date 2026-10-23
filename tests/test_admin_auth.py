"""
Test Suite for Admin Authentication & Role Enforcement.
Validates that admin endpoints correctly authenticate verified admin accounts
and reject null, missing, or unauthorized tokens.
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
import backend.supabase_db as sdb
import backend.security as sec

client = TestClient(app)

def test_admin_endpoints_reject_missing_and_null_tokens():
    # 1. Completely missing header
    res = client.get("/api/admin/overview")
    assert res.status_code == 401
    assert "Missing Authorization header" in res.json()["detail"]

    # 2. Bearer null
    res = client.get("/api/admin/overview", headers={"Authorization": "Bearer null"})
    assert res.status_code == 401

    # 3. Bearer undefined
    res = client.get("/api/admin/users", headers={"Authorization": "Bearer undefined"})
    assert res.status_code == 401


def test_admin_endpoints_with_valid_admin_tokens():
    sb = sdb.get_supabase_client()

    # 1. Test full endpoint flow with email-based admin (ibrahim009.developer@gmail.com)
    admin_email = "ibrahim009.developer@gmail.com"
    link = sb.auth.admin.generate_link({"type": "magiclink", "email": admin_email})
    otp = link.properties.email_otp
    auth_res = sb.auth.verify_otp({"email": admin_email, "token": otp, "type": "magiclink"})
    token = auth_res.session.access_token
    headers = {"Authorization": f"Bearer {token}"}

    # Test /api/user/me
    me_res = client.get("/api/user/me", headers=headers)
    assert me_res.status_code == 200, f"Failed for {admin_email}: {me_res.text}"
    me_data = me_res.json()
    assert me_data["is_admin"] is True, f"User {admin_email} should have is_admin=True"

    # Test /api/admin/overview
    ov_res = client.get("/api/admin/overview", headers=headers)
    assert ov_res.status_code == 200, f"Overview failed for {admin_email}: {ov_res.text}"
    assert "total_users" in ov_res.json()

    # Test /api/admin/users
    u_res = client.get("/api/admin/users", headers=headers)
    assert u_res.status_code == 200, f"Users failed for {admin_email}: {u_res.text}"
    assert "users" in u_res.json()

    # Test /api/admin/crm/metrics
    crm_res = client.get("/api/admin/crm/metrics", headers=headers)
    assert crm_res.status_code == 200, f"CRM failed for {admin_email}: {crm_res.text}"

    # Test /api/admin/jobs
    jobs_res = client.get("/api/admin/jobs?limit=10", headers=headers)
    assert jobs_res.status_code == 200, f"Jobs failed for {admin_email}: {jobs_res.text}"

    # Test /api/admin/payments
    pay_res = client.get("/api/admin/payments", headers=headers)
    assert pay_res.status_code == 200, f"Payments failed for {admin_email}: {pay_res.text}"
    assert isinstance(pay_res.json()["payments"], list)

    # 2. Test that ibrahimshake100@gmail.com is strictly REJECTED with 403 Forbidden from admin endpoints
    sb.auth.sign_out()
    prof = sb.table("profiles").select("role").eq("id", "8f64b14b-8601-422a-b3a4-f9b2f346950a").execute()
    assert prof.data and prof.data[0]["role"] == "user", f"Expected role 'user', got: {prof.data}"

    # Generate token for ibrahimshake100@gmail.com to test live API rejection
    user_email = "ibrahimshake100@gmail.com"
    user_link = sb.auth.admin.generate_link({"type": "magiclink", "email": user_email})
    user_otp = user_link.properties.email_otp
    user_auth = sb.auth.verify_otp({"email": user_email, "token": user_otp, "type": "magiclink"})
    user_token = user_auth.session.access_token
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # /api/user/me should report is_admin = False
    user_me = client.get("/api/user/me", headers=user_headers)
    assert user_me.status_code == 200
    assert user_me.json()["is_admin"] is False, "ibrahimshake100@gmail.com must have is_admin=False"

    # All admin endpoints MUST strictly return 403 Forbidden
    forbidden_ov = client.get("/api/admin/overview", headers=user_headers)
    assert forbidden_ov.status_code == 403, f"Expected 403, got {forbidden_ov.status_code}"

    forbidden_users = client.get("/api/admin/users", headers=user_headers)
    assert forbidden_users.status_code == 403, f"Expected 403, got {forbidden_users.status_code}"

    forbidden_crm = client.get("/api/admin/crm/metrics", headers=user_headers)
    assert forbidden_crm.status_code == 403, f"Expected 403, got {forbidden_crm.status_code}"

    forbidden_jobs = client.get("/api/admin/jobs", headers=user_headers)
    assert forbidden_jobs.status_code == 403, f"Expected 403, got {forbidden_jobs.status_code}"

    forbidden_pay = client.get("/api/admin/payments", headers=user_headers)
    assert forbidden_pay.status_code == 403, f"Expected 403, got {forbidden_pay.status_code}"

    sb.auth.sign_out()


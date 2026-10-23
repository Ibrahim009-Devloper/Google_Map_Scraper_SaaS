# Strict Single-Admin Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revoke administrator privileges from `ibrahimshake100@gmail.com`, demote it to a standard user in the Supabase database via Supabase MCP, enforce a strict code-level cryptographic hard-lock ensuring ONLY `ibrahim009.developer@gmail.com` can access admin APIs, and hide admin UI controls from all other accounts.

**Architecture:** Identity-First Cryptographic Security. The backend validates the asymmetric signature of JWT tokens from Supabase Auth/Google OAuth and matches the verified email strictly against the primary admin email (`ibrahim009.developer@gmail.com`). All unauthorized attempts to access `/api/admin/*` are immediately rejected with `403 Forbidden`. Admin role assignment in `profiles` is strictly guarded so that unauthorized users cannot retain or gain admin status.

**Tech Stack:** FastAPI, Supabase Postgres (via Supabase MCP), Pytest, Vanilla JS frontend.

**Spec:** Approach 1 (Cryptographic Identity Hard-Lock) approved by user.

---

## Global Constraints

- Never use browser automation for Google Maps scraping (`GEMINI.md`).
- Do not use brittle IP-level permanent lockouts that could block the legitimate administrator on dynamic/mobile IPs.
- Only `ibrahim009.developer@gmail.com` is granted administrative access.
- Any request to `/api/admin/*` by `ibrahimshake100@gmail.com` or any non-whitelisted account MUST return HTTP `403 Forbidden`.

## Review Focus

1. `ibrahimshake100@gmail.com` attempting to call `/api/admin/overview` -> Must receive HTTP 403 Forbidden.
2. `ibrahimshake100@gmail.com` attempting to call `/api/admin/users` -> Must receive HTTP 403 Forbidden.
3. Random authenticated user attempting to call `/api/admin/jobs` -> Must receive HTTP 403 Forbidden.
4. `ibrahim009.developer@gmail.com` calling `/api/admin/overview` -> Must receive HTTP 200 OK.
5. Frontend UI -> Admin button must ONLY be rendered for `ibrahim009.developer@gmail.com`.

---

### Task 1: Supabase Database Demotion via Supabase MCP

**Files:**
- Modify: Supabase Cloud Database `profiles` table (via MCP `supabase:execute_sql`)

- [ ] **Step 1: Execute SQL update to demote `ibrahimshake100@gmail.com`**
  - Run SQL via Supabase MCP on project `wigcpvaqnlcafzbixmuk`:
    ```sql
    UPDATE profiles
    SET role = 'user'
    WHERE email = 'ibrahimshake100@gmail.com';
    ```
- [ ] **Step 2: Verify Supabase database state**
  - Query `profiles` table to confirm `ibrahimshake100@gmail.com` has `role = 'user'` and only `ibrahim009.developer@gmail.com` has `role = 'admin'`.

---

### Task 2: Backend Security Hard-Lock & Configuration

**Files:**
- Modify: `config.py`
- Modify: `backend/security.py`

- [ ] **Step 1: Update `config.py` to define `PRIMARY_ADMIN_EMAIL`**
  - Add:
    ```python
    PRIMARY_ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "ibrahim009.developer@gmail.com").strip().lower()
    ```
- [ ] **Step 2: Update `backend/security.py`**
  - Import `PRIMARY_ADMIN_EMAIL` from `config`.
  - Set `ADMIN_EMAILS = {PRIMARY_ADMIN_EMAIL}`.
  - In `verify_auth_token`:
    - If user email is NOT in `ADMIN_EMAILS`, ensure `role = "user"` even if database profile row says otherwise (self-healing security downgrade).
  - In `require_admin_user`:
    - Verify `user.get("email") == PRIMARY_ADMIN_EMAIL` and `user.get("role") == "admin"`.
    - If either fails, log security warning: `[SECURITY ALERT] Unauthorized admin access attempt from <email>` and raise `HTTPException(403, detail="Forbidden: You do not have administrator permissions.")`.

---

### Task 3: Frontend UI Admin Visibility Hardening

**Files:**
- Modify: `frontend/js/app.js`

- [ ] **Step 1: Restrict Admin button visibility in `frontend/js/app.js`**
  - Ensure the admin button toggle strictly checks:
    ```javascript
    const isAdmin = currentUser && currentUser.role === 'admin' && currentUser.email === 'ibrahim009.developer@gmail.com';
    ```
  - For `ibrahimshake100@gmail.com` or any non-whitelisted account, hide the admin nav button completely.

---

### Task 4: Automated Verification Test Suite

**Files:**
- Modify: `tests/test_admin_auth.py`

- [ ] **Step 1: Update `tests/test_admin_auth.py` to assert strict single-admin security**
  - Test `ibrahimshake100@gmail.com` gets `403 Forbidden` across all admin endpoints.
  - Test arbitrary email gets `403 Forbidden`.
  - Test `ibrahim009.developer@gmail.com` gets `200 OK`.
- [ ] **Step 2: Run pytest**
  - Command: `python -m pytest tests/ -v`
  - Expected: All tests PASS.
- [ ] **Step 3: Document Render.com Environment Variable settings for the user**

-- ============================================================================
-- Master Supabase Schema Migration: SaaS Multi-Tenant Lead Platform
-- Tables: plans, profiles, usage_monthly, jobs, payments
-- Features: Row Level Security (RLS), Auto Profile Trigger, Admin Security
-- ============================================================================

-- 1. Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. PLANS TABLE
CREATE TABLE IF NOT EXISTS public.plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    leads_per_day INTEGER NOT NULL DEFAULT 1000,
    jobs_per_day INTEGER NOT NULL DEFAULT 3,
    leads_per_job INTEGER NOT NULL DEFAULT 300,
    website_enrichment_enabled BOOLEAN NOT NULL DEFAULT true,
    price_bdt NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    price_usd NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Insert Default Free Test Plan if not present
INSERT INTO public.plans (id, name, leads_per_day, jobs_per_day, leads_per_job, website_enrichment_enabled, price_bdt, price_usd)
VALUES ('free', 'Free Test Plan', 1000, 3, 300, true, 0.00, 0.00)
ON CONFLICT (id) DO UPDATE SET
    leads_per_day = EXCLUDED.leads_per_day,
    jobs_per_day = EXCLUDED.jobs_per_day,
    leads_per_job = EXCLUDED.leads_per_job,
    website_enrichment_enabled = EXCLUDED.website_enrichment_enabled;

-- Insert Pro Plan placeholder for upcoming payment tier
INSERT INTO public.plans (id, name, leads_per_day, jobs_per_day, leads_per_job, website_enrichment_enabled, price_bdt, price_usd)
VALUES ('pro', 'Pro Harvester Plan', 10000, 50, 10000, true, 2500.00, 25.00)
ON CONFLICT (id) DO UPDATE SET
    leads_per_day = EXCLUDED.leads_per_day,
    jobs_per_day = EXCLUDED.jobs_per_day,
    leads_per_job = EXCLUDED.leads_per_job;

-- 3. PROFILES TABLE (Linked to auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    plan_id TEXT NOT NULL DEFAULT 'free' REFERENCES public.plans(id),
    email_verified BOOLEAN NOT NULL DEFAULT false,
    custom_leads_per_day INTEGER DEFAULT NULL,
    custom_leads_per_job INTEGER DEFAULT NULL,
    custom_jobs_per_day INTEGER DEFAULT NULL,
    custom_plan_name TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Index on email & role
CREATE INDEX IF NOT EXISTS idx_profiles_email ON public.profiles(email);
CREATE INDEX IF NOT EXISTS idx_profiles_role ON public.profiles(role);

-- Helper Security Function for RLS Admin Check
CREATE OR REPLACE FUNCTION public.is_admin(user_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id AND role = 'admin'
    );
$$;

-- 4. USAGE_MONTHLY TABLE (Tracks Daily & Monthly Scrapes, Jobs & Costly Enrichment)
CREATE TABLE IF NOT EXISTS public.usage_monthly (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    month TEXT NOT NULL, -- Format: YYYY-MM
    jobs_count INTEGER NOT NULL DEFAULT 0,
    leads_scraped INTEGER NOT NULL DEFAULT 0,
    enrichment_calls INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_user_usage_date UNIQUE (user_id, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_usage_user_date ON public.usage_monthly(user_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_usage_user_month ON public.usage_monthly(user_id, month);

-- 5. JOBS TABLE (Session Audit, Progress, & Error Logging)
CREATE TABLE IF NOT EXISTS public.jobs (
    id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'stopped', 'failed', 'limit_reached')),
    target_leads INTEGER NOT NULL DEFAULT 100,
    leads_scraped INTEGER NOT NULL DEFAULT 0,
    enrichment_enabled BOOLEAN NOT NULL DEFAULT false,
    current_area TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON public.jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON public.jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON public.jobs(created_at DESC);

-- 6. PAYMENTS TABLE (Audit Ledger for verified webhooks)
CREATE TABLE IF NOT EXISTS public.payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL REFERENCES public.plans(id),
    amount NUMERIC(10, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'BDT',
    provider TEXT NOT NULL DEFAULT 'manual', -- 'bkash', 'sslcommerz', 'stripe', 'manual'
    transaction_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
    raw_webhook_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    verified_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON public.payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON public.payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_txn ON public.payments(transaction_id);

-- 7. TRIGGER: Auto-create Profile when a user Signs Up via Supabase Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, email_verified, plan_id, role)
    VALUES (
        new.id,
        lower(new.email),
        COALESCE(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
        COALESCE((new.email_confirmed_at IS NOT NULL), false),
        'free',
        CASE WHEN lower(new.email) = 'ibrahim009.developer@gmail.com' THEN 'admin' ELSE 'user' END
    )
    ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        email_verified = (new.email_confirmed_at IS NOT NULL),
        updated_at = timezone('utc'::text, now());
    RETURN new;
END;
$$;

-- Drop trigger if exists and recreate
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT OR UPDATE OF email_confirmed_at ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================================================
-- 8. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_monthly ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;

-- PLANS POLICIES
DROP POLICY IF EXISTS "Public can view plans" ON public.plans;
CREATE POLICY "Public can view plans" ON public.plans
    FOR SELECT USING (true);

DROP POLICY IF EXISTS "Admins can manage plans" ON public.plans;
CREATE POLICY "Admins can manage plans" ON public.plans
    FOR ALL TO authenticated USING (public.is_admin(auth.uid()));

-- PROFILES POLICIES
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
CREATE POLICY "Users can view own profile" ON public.profiles
    FOR SELECT TO authenticated
    USING (auth.uid() = id OR public.is_admin(auth.uid()));

DROP POLICY IF EXISTS "Users can update own profile name" ON public.profiles;
CREATE POLICY "Users can update own profile name" ON public.profiles
    FOR UPDATE TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

DROP POLICY IF EXISTS "Admins can manage all profiles" ON public.profiles;
CREATE POLICY "Admins can manage all profiles" ON public.profiles
    FOR ALL TO authenticated
    USING (public.is_admin(auth.uid()));

-- USAGE_MONTHLY POLICIES
DROP POLICY IF EXISTS "Users can view own usage" ON public.usage_monthly;
CREATE POLICY "Users can view own usage" ON public.usage_monthly
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id OR public.is_admin(auth.uid()));

-- JOBS POLICIES
DROP POLICY IF EXISTS "Users can view own jobs" ON public.jobs;
CREATE POLICY "Users can view own jobs" ON public.jobs
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id OR public.is_admin(auth.uid()));

DROP POLICY IF EXISTS "Users can insert own jobs" ON public.jobs;
CREATE POLICY "Users can insert own jobs" ON public.jobs
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own jobs" ON public.jobs;
CREATE POLICY "Users can update own jobs" ON public.jobs
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id OR public.is_admin(auth.uid()));

-- PAYMENTS POLICIES
DROP POLICY IF EXISTS "Users can view own payments" ON public.payments;
CREATE POLICY "Users can view own payments" ON public.payments
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id OR public.is_admin(auth.uid()));

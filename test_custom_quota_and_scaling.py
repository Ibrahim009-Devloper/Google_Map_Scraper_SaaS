"""
Verification script for:
1. Dynamic Sub-Location & Geo-Grid scaling for large lead targets (10,000 to 500,000 leads).
2. Preservation of user's core keywords without dilution.
3. High lead target extraction (commas, 'k' suffix, Bengali numerals).
4. Pro Plan 1,000 capping elimination & Custom Quota assignment.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from agent.planner import (
    extract_target_count,
    detect_and_preserve_core_keyword,
    expand_sub_locations_for_target,
    get_default_sub_locations,
    generate_plan,
)
from backend.supabase_db import get_user_profile, check_user_limits

def run_tests():
    print("=" * 60)
    print("RUNNING VERIFICATION TESTS FOR SCALING & CUSTOM QUOTAS")
    print("=" * 60)

    # 1. Test Number Parsing & Unit Extraction
    print("\n--- 1. Testing Target Count Extraction ---")
    test_prompts = [
        ("ঢাকার 50টি রেস্টুরেন্ট", 50),
        ("50 ta restaurant in Banani", 50),
        ("ঢাকার 10000 রেস্টুরেন্টগুলোর লিড দাও", 10000),
        ("scrape 10,000 software companies in USA", 10000),
        ("need 20k dental clinics in London", 20000),
        ("collect 50,000 leads in New York", 50000),
        ("scrape 500k businesses in Bangladesh", 500000),
        ("১০০০০টি রেস্টুরেন্ট", 10000),
        ("৫০০০০০ লিড দাও", 500000),
    ]
    for prompt, expected in test_prompts:
        extracted = extract_target_count(prompt)
        print(f"  Prompt: '{prompt}' -> Extracted: {extracted} (Expected: {expected})")
        assert extracted == expected, f"Failed for '{prompt}': got {extracted}, expected {expected}"
    print("  [PASS] Target count extraction verified up to 500,000+.")

    # 2. Test Keyword Preservation Rule
    print("\n--- 2. Testing Core Keyword Preservation ---")
    kw1 = detect_and_preserve_core_keyword("ঢাকার রেস্টুরেন্টগুলোর লিড দাও", ["Diner", "Cafe", "Fast food"])
    print(f"  Restaurant prompt keywords: {kw1}")
    assert kw1[0].lower() == "restaurant", f"Core keyword was not at index 0: {kw1}"

    kw2 = detect_and_preserve_core_keyword("Software companies in Banani without websites", ["IT Services", "Tech support"])
    print(f"  Software prompt keywords: {kw2}")
    assert kw2[0].lower() == "software company", f"Core keyword was not at index 0: {kw2}"
    print("  [PASS] User's core keyword preserved at index 0 without dilution.")

    # 3. Test Dynamic Sub-Location Geo-Grid Scaling
    print("\n--- 3. Testing Dynamic Sub-Location Scaling ---")
    base_locs = get_default_sub_locations("bd")
    print(f"  Base sub-locations count: {len(base_locs)}")

    # For 100 leads:
    locs_100 = expand_sub_locations_for_target(base_locs, target_leads=100, keywords=["Restaurant", "Cafe"], country_code="bd")
    print(f"  100 leads -> Sub-locations: {len(locs_100)}")
    assert len(locs_100) == len(base_locs)

    # For 10,000 leads:
    # 10,000 / 70 = 143 searches. With 3 keywords = 48 locations needed
    locs_10k = expand_sub_locations_for_target(base_locs, target_leads=10000, keywords=["Restaurant", "Cafe", "Diner"], country_code="bd")
    print(f"  10,000 leads -> Sub-locations: {len(locs_10k)}")
    assert len(locs_10k) >= 48, f"Expected at least 48 locations for 10k leads, got {len(locs_10k)}"

    # For 50,000 leads:
    # 50,000 / 70 = 715 searches. With 3 keywords = 239 locations needed
    locs_50k = expand_sub_locations_for_target(base_locs, target_leads=50000, keywords=["Restaurant", "Cafe", "Diner"], country_code="bd")
    print(f"  50,000 leads -> Sub-locations: {len(locs_50k)}")
    assert len(locs_50k) >= 239, f"Expected at least 239 locations for 50k leads, got {len(locs_50k)}"

    # For 500,000 leads:
    # 500,000 / 70 = 7143 searches. With 3 keywords = 2381 locations needed
    locs_500k = expand_sub_locations_for_target(base_locs, target_leads=500000, keywords=["Restaurant", "Cafe", "Diner"], country_code="bd")
    print(f"  500,000 leads -> Sub-locations: {len(locs_500k)}")
    assert len(locs_500k) >= 2381, f"Expected at least 2381 locations for 500k leads, got {len(locs_500k)}"
    print("  [PASS] Dynamic sub-location scaling verified for 10k, 50k, and 500k leads.")

    # 4. Test Pro Plan 1,000 Capping Elimination
    print("\n--- 4. Testing Pro Plan Quota Limits ---")
    # Test user ibrahimshake100@gmail.com (Pro plan user in database)
    user_id = "8f64b14b-8601-422a-b3a4-f9b2f346950a"
    profile = get_user_profile(user_id)
    print(f"  User profile plan: {profile.get('plan')}")
    assert profile is not None, "Profile should exist"
    assert profile.get("plan", {}).get("leads_per_job") >= 10000, f"leads_per_job should be >= 10000, got {profile.get('plan', {}).get('leads_per_job')}"

    # Check user limits for 10,000 leads
    check_10k = check_user_limits(user_id, requested_target_leads=10000)
    print(f"  Check limits for 10,000 leads: allowed={check_10k['allowed']}, effective_target={check_10k['effective_target']}")
    assert check_10k["allowed"] is True
    assert check_10k["effective_target"] == 10000, f"effective_target should be 10000, got {check_10k['effective_target']}"
    print("  [PASS] Pro plan user can scrape 10,000 leads (NO 1,000 cap).")

    # 5. Test Full Offline/Online Plan Generation with Target
    print("\n--- 5. Testing Plan Generation with Large Target ---")
    plan = generate_plan("scrape 10000 restaurants in Dhaka without website", target_leads=10000, save_to_disk=False)
    total_searches = len(plan.sub_locations) * len(plan.keywords)
    print(f"  Generated plan: target_leads={plan.target_leads}, keywords={plan.keywords}, sub_locations={len(plan.sub_locations)}, total_searches={total_searches}, max_pages={plan.filters.max_pages_per_search}")
    assert plan.target_leads == 10000
    assert plan.keywords[0].lower() == "restaurant"
    # 6. Test Admin Custom Quota Assignment (e.g. 20,000 or 500,000 leads)
    print("\n--- 6. Testing Admin Custom Quota Assignment (e.g. 20,000 & 500,000 leads) ---")
    from backend.supabase_db import update_user_plan_or_role
    test_user_id = "8f64b14b-8601-422a-b3a4-f9b2f346950a"

    # Assign 20,000 custom leads
    update_user_plan_or_role(
        target_user_id=test_user_id,
        custom_leads_per_day=20000,
        custom_plan_name="VIP Client (20K Daily)"
    )
    prof_custom = get_user_profile(test_user_id)
    print(f"  Custom 20k profile plan: {prof_custom.get('plan')}")
    assert prof_custom.get("plan", {}).get("daily_leads_limit") == 20000
    assert prof_custom.get("plan", {}).get("name") == "VIP Client (20K Daily)"
    chk_20k = check_user_limits(test_user_id, requested_target_leads=20000)
    assert chk_20k["allowed"] is True
    assert chk_20k["effective_target"] == 20000
    print("  [PASS] 20,000 custom quota verified.")

    # Assign 500,000 custom leads
    update_user_plan_or_role(
        target_user_id=test_user_id,
        custom_leads_per_day=500000,
        custom_plan_name="Enterprise VIP (500K Daily)"
    )
    prof_500k = get_user_profile(test_user_id)
    print(f"  Custom 500k profile plan: {prof_500k.get('plan')}")
    assert prof_500k.get("plan", {}).get("daily_leads_limit") == 500000
    chk_500k = check_user_limits(test_user_id, requested_target_leads=500000)
    assert chk_500k["allowed"] is True
    assert chk_500k["effective_target"] == 500000
    print("  [PASS] 500,000 custom quota verified.")

    # Reset custom quota back to standard Pro plan
    update_user_plan_or_role(target_user_id=test_user_id, custom_leads_per_day=0)
    prof_reset = get_user_profile(test_user_id)
    print(f"  Reset profile plan: {prof_reset.get('plan')}")
    assert prof_reset.get("plan", {}).get("id") == "pro"
    assert prof_reset.get("plan", {}).get("daily_leads_limit") == 10000
    print("  [PASS] Reset custom quota back to base plan verified.")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()

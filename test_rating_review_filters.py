"""
Unit and integration tests for rating and review filter extraction and enforcement.
Verifies that leads strictly adhere to min/max rating and review constraints.
"""

import pytest
from agent.schemas import ActionPlan, SubLocation, FilterConfig, LeadItem, SocialLinks
from agent.planner import (
    extract_rating_range,
    extract_review_range,
    generate_plan,
    expand_sub_locations_for_target,
)
from agent.pipeline import filter_lead


def test_rating_extraction_regex():
    """Tests various natural language rating range expressions."""
    # User's exact prompt spelling: "ratting 3.5 to 3.99"
    min_r, max_r = extract_rating_range("i need 30 electrician lead in USA,Phoenix,Arizona, with no website, ratting 3.5 to 3.99 and review 5-30")
    assert min_r == 3.5
    assert max_r == 3.99

    # Standard "rating 3.5 - 4.2"
    min_r, max_r = extract_rating_range("find restaurants with rating 3.5-4.2")
    assert min_r == 3.5
    assert max_r == 4.2

    # "between 3.0 and 4.0 rating"
    min_r, max_r = extract_rating_range("between 3.0 and 4.0 rating")
    assert min_r == 3.0
    assert max_r == 4.0

    # Upper bound only: "rating under 4" or "rating below 3.5"
    min_r, max_r = extract_rating_range("dentists with rating under 4.0")
    assert min_r == 0.0
    assert max_r == 4.0

    # Lower bound only: "rating above 4.2" or "4.5+ star"
    min_r, max_r = extract_rating_range("hotels with rating above 4.2")
    assert min_r == 4.2
    assert max_r is None


def test_review_extraction_regex():
    """Tests various natural language review range expressions."""
    # User's exact prompt spelling: "review 5-30"
    min_rev, max_rev = extract_review_range("i need 30 electrician lead in USA,Phoenix,Arizona, with no website, ratting 3.5 to 3.99 and review 5-30")
    assert min_rev == 5
    assert max_rev == 30

    # "5 to 50 reviews"
    min_rev, max_rev = extract_review_range("plumbers with 5 to 50 reviews")
    assert min_rev == 5
    assert max_rev == 50

    # "under 25 reviews"
    min_rev, max_rev = extract_review_range("lawyers with under 25 reviews")
    assert min_rev == 0
    assert max_rev == 25

    # "100+ reviews"
    min_rev, max_rev = extract_review_range("shops with 100+ reviews")
    assert min_rev == 100
    assert max_rev is None


def test_generate_plan_extracts_and_enforces_filters():
    """Verifies that generate_plan populates min_rating, max_rating, min_reviews, max_reviews."""
    prompt = "i need 30 electrician lead in USA,Phoenix,Arizona, with no website, ratting 3.5 to 3.99 and review 5-30"
    plan = generate_plan(prompt, save_to_disk=False)

    assert plan.target_leads == 30
    assert plan.filters.website_requirement == "no_website"
    assert plan.filters.min_rating == 3.5
    assert plan.filters.max_rating == 3.99
    assert plan.filters.min_reviews == 5
    assert plan.filters.max_reviews == 30


def test_filter_lead_strict_rules():
    """Verifies that filter_lead rejects any lead outside user constraints."""
    plan = ActionPlan(
        user_prompt="test",
        keywords=["Electrician"],
        sub_locations=[SubLocation(area_name="Phoenix", lat=33.4484, lon=-112.074)],
        filters=FilterConfig(
            website_requirement="no_website",
            min_rating=3.5,
            max_rating=3.99,
            min_reviews=5,
            max_reviews=30,
        ),
    )

    # 1. Qualified lead (rating 3.7, reviews 15, no website) -> MUST PASS
    good_lead = LeadItem(
        place_id="p1",
        name="Good Electrician",
        website_status="No Website",
        rating=3.7,
        reviews_count=15,
    )
    assert filter_lead(good_lead, plan) is True

    # 2. Rating 5.0 (BUG REPRODUCTION: previously passed!) -> MUST BE REJECTED
    five_star_lead = LeadItem(
        place_id="p2",
        name="Five Star Electrician",
        website_status="No Website",
        rating=5.0,
        reviews_count=15,
    )
    assert filter_lead(five_star_lead, plan) is False

    # 3. Rating 3.4 (below min 3.5) -> MUST BE REJECTED
    low_rating_lead = LeadItem(
        place_id="p3",
        name="Low Rating Electrician",
        website_status="No Website",
        rating=3.4,
        reviews_count=15,
    )
    assert filter_lead(low_rating_lead, plan) is False

    # 4. Rating 4.0 (above max 3.99) -> MUST BE REJECTED
    above_max_rating_lead = LeadItem(
        place_id="p4",
        name="Four Star Electrician",
        website_status="No Website",
        rating=4.0,
        reviews_count=15,
    )
    assert filter_lead(above_max_rating_lead, plan) is False

    # 5. Reviews 40 (above max 30) -> MUST BE REJECTED
    too_many_reviews_lead = LeadItem(
        place_id="p5",
        name="Popular Electrician",
        website_status="No Website",
        rating=3.8,
        reviews_count=40,
    )
    assert filter_lead(too_many_reviews_lead, plan) is False

    # 6. Reviews 3 (below min 5) -> MUST BE REJECTED
    too_few_reviews_lead = LeadItem(
        place_id="p6",
        name="New Electrician",
        website_status="No Website",
        rating=3.8,
        reviews_count=3,
    )
    assert filter_lead(too_few_reviews_lead, plan) is False

    # 7. Real website present -> MUST BE REJECTED
    has_website_lead = LeadItem(
        place_id="p7",
        name="Web Electrician",
        website_status="Has Own Website",
        website_url="https://example.com",
        rating=3.8,
        reviews_count=15,
    )
    assert filter_lead(has_website_lead, plan) is False

    # 8. Unrated lead (rating is None) -> MUST BE REJECTED
    unrated_lead = LeadItem(
        place_id="p8",
        name="Unrated Electrician",
        website_status="No Website",
        rating=None,
        reviews_count=0,
    )
    assert filter_lead(unrated_lead, plan) is False


def test_expand_sub_locations_when_target_small_with_strict_filters():
    """Verifies that sub-locations expand properly when explicitly requested during search rounds."""
    base = [SubLocation(area_name="Downtown Phoenix", lat=33.4484, lon=-112.074, radius=3500.0)]
    expanded = expand_sub_locations_for_target(
        base_sub_locations=base,
        target_leads=30,
        keywords=["Electrician"],
        country_code="us",
        min_additional_locations=6,
    )
    assert len(expanded) >= 7

"""
AI Planner Module for Autonomous Google Maps Lead Generation Agent.
Converts natural language user requests into a strict JSON ActionPlan.
"""

import os
import json
import re
import math
import datetime
from typing import Optional, List

from config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    DEFAULT_LLM_PROVIDER,
    GEMINI_MODEL,
    GROQ_MODEL,
    PLANS_DIR,
)
from agent.schemas import ActionPlan, SubLocation, FilterConfig, EnrichmentConfig

PLANNER_SYSTEM_PROMPT = """You are an expert B2B Lead Generation Strategist and Geographic Data Planner.
Your job is to convert a user's natural language lead request into a strict JSON execution plan.

RULES:
1. KEYWORDS (CRITICAL - PRESERVE USER'S CORE INTENT):
   - Always retain the user's explicit requested business category as the FIRST and PRIMARY keyword (e.g., if user asks for "restaurants in Dhaka", "Restaurant" MUST be the first keyword).
   - Generate 2 to 4 closely related Google Maps category keywords (e.g. ["Restaurant", "Bangladeshi restaurant", "Diner", "Fast food restaurant"]).
   - NEVER generate distant, unrelated, or random categories to artificially inflate results. The user's core requested category must NEVER be forgotten or diluted!
2. GEO-SPLITTING & SUB-LOCATIONS (CRITICAL - MUST NEVER BE EMPTY):
   - "sub_locations" MUST NEVER BE EMPTY! Return at least 5 to 20 sub-locations with valid center Latitude (`lat`), Longitude (`lon`), and `radius` in meters (usually 2500 to 4000).
   - If the user specifies a city or neighborhood (e.g. "Dhaka", "Banani", "London", "New York", "Mumbai"), break it down into smaller neighborhoods/sub-areas.
   - If the user specifies a country or nationality (e.g. "India", "Indian", "USA", "American", "Canada", "UK", "Bangladesh") without a specific city, generate sub-locations covering major metropolitan commercial hubs across that country.
   - If the user specifies NO location at all, infer the country from the query context or default to Bangladesh (Dhaka: Dhanmondi, Gulshan, Banani, Uttara, Mirpur, etc.).
   - UNDER NO CIRCUMSTANCES should "sub_locations" be an empty array `[]`!
3. TARGET LEADS (CRITICAL):
   - If the user specifies an exact quantity of leads in natural language (e.g., "50 ta lead", "50টি রেস্টুরেন্ট", "10,000 restaurants", "10k leads", "500000 companies"), extract this integer into "target_leads" (e.g. 10000 or 500000).
   - If no specific number is mentioned, set "target_leads": null.
4. WEBSITE FILTER:
   - Set "website_requirement": "no_website" if the user wants leads without websites (or businesses that only have Facebook/Instagram pages).
   - Set "website_requirement": "has_real_website" if the user explicitly asks for businesses with real websites.
   - Set "website_requirement": "any" if the user wants all leads regardless of website status.
5. WEBSITE ENRICHMENT & LOCAL SEO AUDIT:
   - Unless the user specifically asks for "no_website" (leads without websites), ALWAYS enable website enrichment by default ("enabled": true, "extract_emails": true, "extract_socials": true, "detect_cms": true) so that emails and social links are scraped from business websites.
   - Set "audit_seo": true if the user mentions SEO, audit, website review, page score, or technical analysis. Otherwise set "audit_seo": false.
6. RATING & REVIEWS FILTERS:
   - "min_rating": float (default 0.0). If user says e.g. "rating 3.5 to 3.99" or "above 4 star", min_rating = 3.5 (or 4.0).
   - "max_rating": float or null. If user specifies an upper rating bound (e.g. "rating 3.5 to 3.99", "under 4.0 rating"), max_rating = 3.99 (or 4.0). Otherwise null.
   - "min_reviews": integer (default 0). If user says e.g. "review 5-30" or "at least 10 reviews", min_reviews = 5 (or 10).
   - "max_reviews": integer or null. If user specifies an upper review bound (e.g. "review 5-30", "under 50 reviews"), max_reviews = 30 (or 50). Otherwise null.
7. COUNTRY & LANGUAGE:
   - Infer the country code (e.g., "bd" for Bangladesh, "us" for USA, "gb" for UK) from the requested location.
   - Default language is "en".
8. PAGINATION & SPEED:
   - Set "max_pages_per_search": 6 (fetching all 6 pagination offsets for up to 120 leads per zone) to maximize yield per location.
9. OUTPUT: Respond ONLY with valid JSON matching the exact schema. No markdown fences or extra conversational text.

Output JSON Schema:
{
  "user_prompt": string,
  "keywords": [string, ...],
  "country_code": string,
  "language": string,
  "target_leads": integer | null,
  "sub_locations": [
    {
      "area_name": string,
      "lat": float,
      "lon": float,
      "radius": float
    }
  ],
  "filters": {
    "website_requirement": "no_website" | "has_real_website" | "any",
    "must_have_phone": boolean,
    "min_rating": float,
    "max_rating": float | null,
    "min_reviews": integer,
    "max_reviews": integer | null,
    "max_pages_per_search": integer
  },
  "enrichment": {
    "enabled": boolean,
    "extract_emails": boolean,
    "extract_socials": boolean,
    "detect_cms": boolean,
    "audit_seo": boolean
  }
}
"""


def clean_json_response(raw_text: str) -> str:
    """Removes markdown code fences and extraneous text from LLM response."""
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def plan_with_gemini(user_prompt: str, api_key: str) -> ActionPlan:
    """Generates execution plan using Google GenAI SDK."""
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config=dict(
            system_instruction=PLANNER_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ActionPlan,
            temperature=0.2,
        ),
    )
    raw_text = response.text or ""
    data = json.loads(clean_json_response(raw_text))
    return ActionPlan.model_validate(data)


def plan_with_groq(user_prompt: str, api_key: str) -> ActionPlan:
    """Generates execution plan using Groq SDK."""
    from groq import Groq

    client = Groq(api_key=api_key)
    chat_completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw_text = chat_completion.choices[0].message.content or ""
    data = json.loads(clean_json_response(raw_text))
    return ActionPlan.model_validate(data)


def _parse_target_leads_num(raw_str: str) -> Optional[int]:
    """Helper to parse numeric strings, handling commas, underscores, and 'k'/'m' suffixes."""
    if not raw_str:
        return None
    clean = raw_str.lower().replace(",", "").replace("_", "").strip()
    if clean.endswith("k"):
        try:
            val = float(clean[:-1]) * 1000
            return int(val)
        except ValueError:
            return None
    elif clean.endswith("m"):
        try:
            val = float(clean[:-1]) * 1000000
            return int(val)
        except ValueError:
            return None
    try:
        val = int(clean)
        return val
    except ValueError:
        return None


def extract_target_count(prompt: str) -> Optional[int]:
    """
    Intelligently extracts the requested target leads count from natural language prompts.
    Handles Bengali numerals ('৫০ টা', '১০০০০টি', '৫০০০০০'), English markers ('50 leads', '10,000 restaurants', '500k leads'),
    and 'k' suffixes ('10k', '50k', '500k') up to 1,000,000 leads.
    """
    if not prompt:
        return None

    # Normalize Bengali numerals: ০-৯ -> 0-9
    bengali_digits = "০১২৩৪৫৬৭৮৯"
    text = prompt
    for i, b_char in enumerate(bengali_digits):
        text = text.replace(b_char, str(i))

    # 1. Match explicit quantity indicators with units (e.g., "10,000 leads", "500k ta", "500000 companies")
    match = re.search(
        r'(?:top\s+|find\s+|get\s+|scrape\s+|need\s+|lagbe\s+)?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k|\d{1,7})\s*(?:ta|ti|টি|টা|leads?|লিড|entities|businesses|companies|restaurants?|রেস্টুরেন্ট|hotels?|shops?|দোকান|items?)',
        text,
        re.IGNORECASE,
    )
    if match:
        val = _parse_target_leads_num(match.group(1))
        if val and 1 <= val <= 1000000:
            return val

    # 2. Match patterns like "50টি", "10000টা", "500kটি" anywhere
    match = re.search(r'(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k|\d{1,7})\s*(?:ta|ti|টি|টা)', text, re.IGNORECASE)
    if match:
        val = _parse_target_leads_num(match.group(1))
        if val and 1 <= val <= 1000000:
            return val

    # 3. Match "top 50", "scrape 10000", "need 500k" without unit suffix
    match = re.search(r'\b(?:top|scrape|extract|collect|need|give\s+me)\s+(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k|\d{1,7})\b', text, re.IGNORECASE)
    if match:
        val = _parse_target_leads_num(match.group(1))
        if val and 1 <= val <= 1000000:
            return val

    # 4. Match general number followed by noun, avoiding "sector 4", "road 12", etc.
    for m in re.finditer(r'\b(\d{1,3}(?:,\d{3})+|\d{2,7})\b', text):
        val = _parse_target_leads_num(m.group(1))
        if not val or not (5 <= val <= 1000000):
            continue
        start = m.start()
        prefix = text[max(0, start - 15):start].lower()
        if any(w in prefix for w in ["sector", "road", "plot", "house", "block", "ward", "st", "ave", "lane"]):
            continue
        return val

    return None


def extract_rating_range(prompt: str) -> tuple[Optional[float], Optional[float]]:
    """
    Extracts min_rating and max_rating from natural language queries.
    Handles 'rating 3.5 to 3.99', 'ratting 3.5-4.0', 'between 3.5 and 4.0 rating',
    'rating under 4.0', 'rating above 4.2', '4+ star', Bengali numbers, etc.
    """
    if not prompt:
        return None, None

    # Normalize Bengali numerals
    bengali_digits = "০১২৩৪৫৬৭৮৯"
    text = prompt
    for i, b_char in enumerate(bengali_digits):
        text = text.replace(b_char, str(i))

    text_lower = text.lower()

    # 1. Two-sided range: "ratting/rating/star 3.5 to 3.99", "3.5 - 3.99 star/rating", "between 3.5 and 3.99"
    patterns_two_sided = [
        r'(?:rat+ings?|stars?)\s*(?:of|is|between)?\s*([0-5](?:\.\d{1,2})?)\s*(?:to|-|and|থেকে|হতে)\s*([0-5](?:\.\d{1,2})?)',
        r'(?:between\s+)?([0-5](?:\.\d{1,2})?)\s*(?:to|-|and|থেকে|হতে)\s*([0-5](?:\.\d{1,2})?)\s*(?:rat+ings?|stars?|স্টার|রেটিং)',
    ]
    for pattern in patterns_two_sided:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v1 = float(m.group(1))
                v2 = float(m.group(2))
                return min(v1, v2), max(v1, v2)
            except ValueError:
                pass

    # 2. Upper bound only: "rating under 4", "rating below 3.5", "rating less than 4", "max rating 4"
    patterns_upper = [
        r'(?:rat+ings?|stars?)\s*(?:under|below|less than|up to|maximum|max|সর্বোচ্চ|নিচে)\s*([0-5](?:\.\d{1,2})?)',
        r'(?:under|below|less than|up to|maximum|max|সর্বোচ্চ)\s*([0-5](?:\.\d{1,2})?)\s*(?:rat+ings?|stars?|স্টার|রেটিং)',
    ]
    for pattern in patterns_upper:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v = float(m.group(1))
                return 0.0, v
            except ValueError:
                pass

    # 3. Lower bound only: "rating above 4", "rating over 3.5", "rating > 4", "min rating 4", "4+ star"
    patterns_lower = [
        r'(?:rat+ings?|stars?)\s*(?:above|over|greater than|at least|minimum|min|উপরে|নূন্যতম|\>)\s*([0-5](?:\.\d{1,2})?)',
        r'(?:above|over|greater than|at least|minimum|min|নূন্যতম)\s*([0-5](?:\.\d{1,2})?)\s*(?:rat+ings?|stars?|স্টার|রেটিং)',
        r'([0-5](?:\.\d{1,2})?)\s*\+\s*(?:rat+ings?|stars?|স্টার|রেটিং)',
        r'([0-5](?:\.\d{1,2})?)\s*(?:stars?|স্টার|রেটিং)\s*(?:and above|or higher|or more|বা তার বেশি)',
    ]
    for pattern in patterns_lower:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v = float(m.group(1))
                return v, None
            except ValueError:
                pass

    return None, None


def extract_review_range(prompt: str) -> tuple[Optional[int], Optional[int]]:
    """
    Extracts min_reviews and max_reviews from natural language queries.
    Handles 'review 5-30', '5 to 30 reviews', 'under 50 reviews', '100+ reviews', Bengali numbers, etc.
    """
    if not prompt:
        return None, None

    # Normalize Bengali numerals
    bengali_digits = "০১২৩৪৫৬৭৮৯"
    text = prompt
    for i, b_char in enumerate(bengali_digits):
        text = text.replace(b_char, str(i))

    text_lower = text.lower()

    # 1. Two-sided range: "review(s) 5-30", "5 to 30 reviews", "between 5 and 30 reviews"
    patterns_two_sided = [
        r'(?:reviews?|রিভিউ)\s*(?:of|is|between)?\s*(\d+)\s*(?:to|-|and|থেকে|হতে)\s*(\d+)',
        r'(?:between\s+)?(\d+)\s*(?:to|-|and|থেকে|হতে)\s*(\d+)\s*(?:reviews?|রিভিউ)',
    ]
    for pattern in patterns_two_sided:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v1 = int(m.group(1))
                v2 = int(m.group(2))
                return min(v1, v2), max(v1, v2)
            except ValueError:
                pass

    # 2. Upper bound only: "under 30 reviews", "reviews under 30", "max 30 reviews"
    patterns_upper = [
        r'(?:reviews?|রিভিউ)\s*(?:under|below|less than|up to|maximum|max|সর্বোচ্চ|নিচে)\s*(\d+)',
        r'(?:under|below|less than|up to|maximum|max|সর্বোচ্চ)\s*(\d+)\s*(?:reviews?|রিভিউ)',
    ]
    for pattern in patterns_upper:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v = int(m.group(1))
                return 0, v
            except ValueError:
                pass

    # 3. Lower bound only: "100+ reviews", "at least 50 reviews", "min 50 reviews", "reviews above 50"
    patterns_lower = [
        r'(?:reviews?|রিভিউ)\s*(?:above|over|greater than|at least|minimum|min|উপরে|নূন্যতম|\>)\s*(\d+)',
        r'(?:above|over|greater than|at least|minimum|min|নূন্যতম)\s*(\d+)\s*(?:reviews?|রিভিউ)',
        r'(\d+)\s*\+\s*(?:reviews?|রিভিউ)',
        r'(\d+)\s*(?:reviews?|রিভিউ)\s*(?:and above|or higher|or more|বা তার বেশি)',
    ]
    for pattern in patterns_lower:
        m = re.search(pattern, text_lower)
        if m:
            try:
                v = int(m.group(1))
                return v, None
            except ValueError:
                pass

    return None, None


def get_default_sub_locations(country_code: str = "bd") -> List[SubLocation]:
    """
    Returns verified, high-precision metropolitan micro-locations for a given country code.
    Guarantees that sub_locations is never empty under any circumstance.
    """
    code = (country_code or "bd").lower().strip()
    if code in ("in", "ind", "india"):
        return [
            SubLocation(area_name="Connaught Place, New Delhi", lat=28.6315, lon=77.2167, radius=3500.0),
            SubLocation(area_name="Bandra West, Mumbai", lat=19.0596, lon=72.8295, radius=3500.0),
            SubLocation(area_name="Indiranagar, Bangalore", lat=12.9784, lon=77.6408, radius=3500.0),
            SubLocation(area_name="Koramangala, Bangalore", lat=12.9352, lon=77.6245, radius=3500.0),
            SubLocation(area_name="Banjara Hills, Hyderabad", lat=17.4156, lon=78.4357, radius=3500.0),
            SubLocation(area_name="T. Nagar, Chennai", lat=13.0418, lon=80.2341, radius=3500.0),
            SubLocation(area_name="Park Street, Kolkata", lat=22.5519, lon=88.3516, radius=3500.0),
            SubLocation(area_name="Koregaon Park, Pune", lat=18.5362, lon=73.8940, radius=3500.0),
            SubLocation(area_name="SG Highway, Ahmedabad", lat=23.0525, lon=72.5086, radius=3500.0),
            SubLocation(area_name="C Scheme, Jaipur", lat=26.9089, lon=75.8016, radius=3500.0),
        ]
    elif code in ("us", "usa"):
        return [
            SubLocation(area_name="Midtown Manhattan, New York, NY", lat=40.7580, lon=-73.9855, radius=3500.0),
            SubLocation(area_name="Williamsburg, Brooklyn, NY", lat=40.7081, lon=-73.9571, radius=3500.0),
            SubLocation(area_name="Downtown Los Angeles, CA", lat=34.0407, lon=-118.2468, radius=3500.0),
            SubLocation(area_name="Chicago Loop, IL", lat=41.8781, lon=-87.6298, radius=3500.0),
            SubLocation(area_name="Downtown Houston, TX", lat=29.7604, lon=-95.3698, radius=3500.0),
            SubLocation(area_name="Brickell, Miami, FL", lat=25.7617, lon=-80.1918, radius=3500.0),
            SubLocation(area_name="Downtown Dallas, TX", lat=32.7767, lon=-96.7970, radius=3500.0),
            SubLocation(area_name="SoMa, San Francisco, CA", lat=37.7785, lon=-122.4056, radius=3500.0),
        ]
    elif code in ("gb", "uk"):
        return [
            SubLocation(area_name="Central London, UK", lat=51.5074, lon=-0.1278, radius=3500.0),
            SubLocation(area_name="Westminster, London, UK", lat=51.4975, lon=-0.1357, radius=3000.0),
            SubLocation(area_name="Camden, London, UK", lat=51.5455, lon=-0.1417, radius=3000.0),
            SubLocation(area_name="Soho, London, UK", lat=51.5136, lon=-0.1365, radius=2500.0),
            SubLocation(area_name="Manchester City Centre, UK", lat=53.4808, lon=-2.2426, radius=3500.0),
            SubLocation(area_name="Birmingham City Centre, UK", lat=52.4862, lon=-1.8904, radius=3500.0),
        ]
    elif code in ("ca", "can", "canada"):
        return [
            SubLocation(area_name="Downtown Toronto, ON", lat=43.6532, lon=-79.3832, radius=3500.0),
            SubLocation(area_name="North York, Toronto, ON", lat=43.7615, lon=-79.4111, radius=3500.0),
            SubLocation(area_name="Scarborough, Toronto, ON", lat=43.7764, lon=-79.2318, radius=3500.0),
            SubLocation(area_name="Mississauga, ON", lat=43.5890, lon=-79.6441, radius=4000.0),
            SubLocation(area_name="Downtown Vancouver, BC", lat=49.2827, lon=-123.1207, radius=3500.0),
            SubLocation(area_name="Downtown Montreal, QC", lat=45.5017, lon=-73.5673, radius=3500.0),
            SubLocation(area_name="Downtown Calgary, AB", lat=51.0447, lon=-114.0719, radius=3500.0),
        ]
    elif code in ("au", "aus", "australia"):
        return [
            SubLocation(area_name="Sydney CBD, NSW", lat=-33.8688, lon=151.2093, radius=3500.0),
            SubLocation(area_name="Melbourne CBD, VIC", lat=-37.8136, lon=144.9631, radius=3500.0),
            SubLocation(area_name="Brisbane City, QLD", lat=-27.4698, lon=153.0251, radius=3500.0),
            SubLocation(area_name="Perth CBD, WA", lat=-31.9505, lon=115.8605, radius=3500.0),
        ]
    elif code in ("ae", "uae", "dubai"):
        return [
            SubLocation(area_name="Downtown Dubai, UAE", lat=25.1972, lon=55.2744, radius=3500.0),
            SubLocation(area_name="Dubai Marina, UAE", lat=25.0805, lon=55.1403, radius=3500.0),
            SubLocation(area_name="Deira, Dubai, UAE", lat=25.2697, lon=55.3095, radius=3500.0),
            SubLocation(area_name="Abu Dhabi Downtown, UAE", lat=24.4539, lon=54.3773, radius=4000.0),
        ]
    else:
        # Default: Bangladesh major commercial hubs
        return [
            SubLocation(area_name="Dhanmondi, Dhaka", lat=23.7461, lon=90.3742, radius=3000.0),
            SubLocation(area_name="Gulshan, Dhaka", lat=23.7925, lon=90.4078, radius=3500.0),
            SubLocation(area_name="Banani, Dhaka", lat=23.7937, lon=90.4047, radius=3000.0),
            SubLocation(area_name="Uttara, Dhaka", lat=23.8759, lon=90.3795, radius=3500.0),
            SubLocation(area_name="Mirpur, Dhaka", lat=23.8070, lon=90.3686, radius=3500.0),
            SubLocation(area_name="Mohammadpur, Dhaka", lat=23.7658, lon=90.3584, radius=3000.0),
            SubLocation(area_name="Khilgaon, Dhaka", lat=23.7516, lon=90.4239, radius=3000.0),
            SubLocation(area_name="Badda, Dhaka", lat=23.7805, lon=90.4267, radius=3000.0),
            SubLocation(area_name="Motijheel, Dhaka", lat=23.7330, lon=90.4172, radius=3000.0),
            SubLocation(area_name="Agrabad, Chittagong", lat=22.3278, lon=91.8123, radius=3500.0),
        ]


def get_comprehensive_country_hubs(country_code: str = "bd") -> List[SubLocation]:
    """
    Returns extensive national and metropolitan commercial hubs for multi-location scaling.
    Covers major divisional hubs, commercial districts, and urban economic centers.
    """
    code = (country_code or "bd").lower().strip()
    if code in ("bd", "bangladesh"):
        return [
            # Dhaka Metro Commercial Hubs
            SubLocation(area_name="Dhanmondi, Dhaka", lat=23.7461, lon=90.3742, radius=3000.0),
            SubLocation(area_name="Gulshan-1 & 2, Dhaka", lat=23.7925, lon=90.4078, radius=3500.0),
            SubLocation(area_name="Banani & Kemal Ataturk, Dhaka", lat=23.7937, lon=90.4047, radius=3000.0),
            SubLocation(area_name="Uttara Sectors 1-14, Dhaka", lat=23.8759, lon=90.3795, radius=3500.0),
            SubLocation(area_name="Mirpur 1, 2 & 10, Dhaka", lat=23.8070, lon=90.3686, radius=3500.0),
            SubLocation(area_name="Mohammadpur & Ring Road, Dhaka", lat=23.7658, lon=90.3584, radius=3000.0),
            SubLocation(area_name="Khilgaon & Malibagh, Dhaka", lat=23.7516, lon=90.4239, radius=3000.0),
            SubLocation(area_name="Badda & Rampura, Dhaka", lat=23.7805, lon=90.4267, radius=3000.0),
            SubLocation(area_name="Motijheel & Dilkusha, Dhaka", lat=23.7330, lon=90.4172, radius=3000.0),
            SubLocation(area_name="Tejgaon Commercial Area, Dhaka", lat=23.7639, lon=90.3986, radius=3000.0),
            SubLocation(area_name="Bashundhara R/A & Kuril, Dhaka", lat=23.8151, lon=90.4255, radius=3500.0),
            SubLocation(area_name="Old Dhaka & Lalbagh, Dhaka", lat=23.7196, lon=90.3884, radius=3000.0),
            SubLocation(area_name="Paltan & Shantinagar, Dhaka", lat=23.7381, lon=90.4132, radius=3000.0),
            SubLocation(area_name="Wari & Sutrapur, Dhaka", lat=23.7180, lon=90.4190, radius=3000.0),
            SubLocation(area_name="Jatrabari & Sayedabad, Dhaka", lat=23.7118, lon=90.4344, radius=3500.0),
            SubLocation(area_name="Farmgate & Panthapath, Dhaka", lat=23.7533, lon=90.3889, radius=2500.0),
            SubLocation(area_name="Elephant Road & New Market, Dhaka", lat=23.7402, lon=90.3854, radius=2500.0),
            SubLocation(area_name="Savar Commercial Hub, Dhaka", lat=23.8442, lon=90.2592, radius=4000.0),
            SubLocation(area_name="Tongi Commercial Zone, Gazipur", lat=23.8967, lon=90.4005, radius=4000.0),
            SubLocation(area_name="Chashara & Narayanganj Sadar", lat=23.6238, lon=90.4990, radius=4000.0),
            SubLocation(area_name="Gazipur Chowrasta, Gazipur", lat=23.9999, lon=90.3795, radius=4000.0),
            # Chittagong Division
            SubLocation(area_name="Agrabad Commercial Area, Chittagong", lat=22.3278, lon=91.8123, radius=3500.0),
            SubLocation(area_name="GEC Circle & Nasirabad, Chittagong", lat=22.3592, lon=91.8215, radius=3500.0),
            SubLocation(area_name="Halishahar & Bandar, Chittagong", lat=22.3338, lon=91.7778, radius=4000.0),
            SubLocation(area_name="Panchlaish & Chawkbazar, Chittagong", lat=22.3601, lon=91.8385, radius=3500.0),
            SubLocation(area_name="Jhautola & Sugandha, Cox's Bazar", lat=21.4385, lon=91.9796, radius=4000.0),
            SubLocation(area_name="Kandirpar & Badurtala, Comilla", lat=23.4607, lon=91.1809, radius=3500.0),
            SubLocation(area_name="SSK Road, Feni", lat=23.0159, lon=91.3976, radius=3500.0),
            SubLocation(area_name="Court Road, Brahmanbaria", lat=23.9608, lon=91.1115, radius=3500.0),
            # Sylhet Division
            SubLocation(area_name="Zindabazar & Bandar Bazar, Sylhet", lat=24.8949, lon=91.8687, radius=3500.0),
            SubLocation(area_name="Shibganj & Tilagarh, Sylhet", lat=24.8973, lon=91.8920, radius=3500.0),
            SubLocation(area_name="Ambarkhana & Chourhatta, Sylhet", lat=24.9042, lon=91.8708, radius=3500.0),
            # Rajshahi & Rangpur Divisions
            SubLocation(area_name="Shaheb Bazar & Boalia, Rajshahi", lat=24.3636, lon=88.6042, radius=3500.0),
            SubLocation(area_name="Satmatha & Joleshworitola, Bogra", lat=24.8465, lon=89.3777, radius=3500.0),
            SubLocation(area_name="Jahaj Company Mor & Dhap, Rangpur", lat=25.7439, lon=89.2752, radius=3500.0),
            SubLocation(area_name="Dinajpur Sadar Commercial Area", lat=25.6217, lon=88.6355, radius=3500.0),
            # Khulna & Barisal Divisions
            SubLocation(area_name="Shibbari Mor & Daulatpur, Khulna", lat=22.8200, lon=89.5500, radius=4000.0),
            SubLocation(area_name="Garibshah Road, Jessore", lat=23.1664, lon=89.2081, radius=3500.0),
            SubLocation(area_name="Sadar Road & C&B Road, Barisal", lat=22.7010, lon=90.3535, radius=3500.0),
            SubLocation(area_name="Ganginarpar & Charpara, Mymensingh", lat=24.7471, lon=90.4203, radius=3500.0),
            SubLocation(area_name="NS Road, Kushtia", lat=23.9013, lon=89.1205, radius=3500.0),
        ]
    return get_default_sub_locations(country_code)


def detect_and_preserve_core_keyword(user_prompt: str, generated_keywords: List[str]) -> List[str]:
    """
    CRITICAL RULE ENFORCER:
    Ensures that the user's explicit requested business category is ALWAYS preserved
    as the PRIMARY keyword at index 0, and never forgotten or diluted by LLM variants.
    Keeps keyword list focused (2 to 4 keywords total).
    """
    if not generated_keywords:
        generated_keywords = ["Business"]

    p_lower = user_prompt.lower()
    core_kw: Optional[str] = None

    # Detect user's core business category from natural language
    if any(w in p_lower for w in ["restaurant", "restaurants", "রেস্টুরেন্ট", "খাবার", "food", "dining", "diner"]):
        core_kw = "Restaurant"
    elif any(w in p_lower for w in ["software", "tech", "it company", "it companies", "আইটি", "software company"]):
        core_kw = "Software company"
    elif any(w in p_lower for w in ["dentist", "dental", "dentists", "ডেন্টাল"]):
        core_kw = "Dentist"
    elif any(w in p_lower for w in ["hotel", "hotels", "resort", "motel", "হোটেল"]):
        core_kw = "Hotel"
    elif any(w in p_lower for w in ["cafe", "coffee", "cafes", "ক্যাফে"]):
        core_kw = "Cafe"
    elif any(w in p_lower for w in ["gym", "fitness", "workout", "জিম"]):
        core_kw = "Gym"
    elif any(w in p_lower for w in ["clothing", "boutique", "fashion", "garments", "দোকান", "shop", "store"]):
        core_kw = "Clothing store" if "clothing" in p_lower or "fashion" in p_lower else "Store"
    elif any(w in p_lower for w in ["hospital", "clinic", "medical", "হাসপাতাল"]):
        core_kw = "Hospital"
    elif any(w in p_lower for w in ["school", "college", "university", "coaching", "স্কুল"]):
        core_kw = "School"
    elif any(w in p_lower for w in ["real estate", "property", "developer", "বিল্ডার"]):
        core_kw = "Real estate agency"
    elif any(w in p_lower for w in ["lawyer", "attorney", "law firm", "আইনজীবী"]):
        core_kw = "Law firm"
    elif any(w in p_lower for w in ["electrician", "electricians", "electrical"]):
        core_kw = "Electrician"
    elif any(w in p_lower for w in ["plumber", "plumbers", "plumbing"]):
        core_kw = "Plumber"

    # Assemble cleaned keywords: core keyword first, followed by unique valid generated keywords
    final_keywords: List[str] = []
    if core_kw:
        final_keywords.append(core_kw)

    for kw in generated_keywords:
        cleaned = kw.strip()
        if cleaned and not any(cleaned.lower() == existing.lower() for existing in final_keywords):
            final_keywords.append(cleaned)
        if len(final_keywords) >= 4:
            break

    return final_keywords if final_keywords else generated_keywords[:4]


def expand_sub_locations_for_target(
    base_sub_locations: List[SubLocation],
    target_leads: int,
    keywords: List[str],
    country_code: str = "bd",
    min_additional_locations: int = 0,
) -> List[SubLocation]:
    """
    Dynamically scales sub-locations to ensure sufficient geographic coverage
    for large lead targets (e.g. 5,000, 10,000, 50,000, 500,000 leads)
    or when additional exploration zones are required to satisfy strict filters.
    Google Maps reverse API returns up to 120 leads per query (6 pages * 20 results).
    Assuming an average unique yield of ~70 leads per search:
        needed_searches = ceil(target_leads / 70)
        needed_locations = ceil(needed_searches / num_keywords)
    If needed_locations > len(base_sub_locations), scales up with regional hubs
    and a concentric hexagonal geo-spatial radial grid around center points.
    """
    if not base_sub_locations:
        base_sub_locations = get_default_sub_locations(country_code)

    if (not target_leads or target_leads <= 100) and min_additional_locations <= 0:
        return base_sub_locations

    num_keywords = max(1, len(keywords))
    avg_yield_per_search = 70.0
    needed_searches = max(1, math.ceil((target_leads or 100) / avg_yield_per_search))
    needed_locations = max(
        len(base_sub_locations) + min_additional_locations,
        math.ceil(needed_searches / num_keywords),
    )

    if len(base_sub_locations) >= needed_locations:
        return base_sub_locations

    expanded: List[SubLocation] = list(base_sub_locations)
    existing_coords = {(round(loc.lat, 3), round(loc.lon, 3)) for loc in expanded}

    # Step 1: Incorporate additional verified regional hubs for the country
    regional_pool = get_comprehensive_country_hubs(country_code)
    for hub in regional_pool:
        if len(expanded) >= needed_locations:
            break
        coord_key = (round(hub.lat, 3), round(hub.lon, 3))
        if coord_key not in existing_coords:
            existing_coords.add(coord_key)
            expanded.append(hub)

    if len(expanded) >= needed_locations:
        return expanded

    # Step 2: Geometric radial grid expansion (Hexagonal spatial rings matching 3500m radius)
    ring = 1
    base_seeds = list(expanded)
    while len(expanded) < needed_locations and ring <= 35:
        step_lat = 0.030 * ring
        step_lon = 0.033 * ring
        num_points = 6 * ring
        angle_step = 360.0 / num_points

        for seed in base_seeds:
            if len(expanded) >= needed_locations:
                break
            for i in range(num_points):
                if len(expanded) >= needed_locations:
                    break
                rad = math.radians(i * angle_step)
                d_lat = step_lat * math.cos(rad)
                d_lon = step_lon * math.sin(rad)
                new_lat = round(seed.lat + d_lat, 5)
                new_lon = round(seed.lon + d_lon, 5)

                coord_key = (round(new_lat, 3), round(new_lon, 3))
                if coord_key not in existing_coords:
                    existing_coords.add(coord_key)
                    base_name = seed.area_name.split(",")[0].strip()
                    parent_city = seed.area_name.split(",")[-1].strip() if "," in seed.area_name else ""
                    city_suffix = f", {parent_city}" if parent_city else ""
                    expanded.append(
                        SubLocation(
                            area_name=f"{base_name} Sector {ring}-{i+1}{city_suffix}",
                            lat=new_lat,
                            lon=new_lon,
                            radius=3500.0,
                        )
                    )
        ring += 1

    return expanded


def create_offline_fallback_plan(user_prompt: str, target_leads: Optional[int] = None) -> ActionPlan:
    """Provides a deterministic fallback plan if no API key is provided."""
    prompt_lower = user_prompt.lower()
    
    # Check if user wants no website
    is_no_website = any(w in prompt_lower for w in ["no website", "ওয়েবসাইট নেই", "without website", "website chara"])

    # Determine Country & Micro-zones
    if any(w in prompt_lower for w in ["india", "indian", "delhi", "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata", "pune", "ahmedabad", "jaipur"]):
        country_code = "in"
    elif any(w in prompt_lower for w in ["canada", "toronto", "vancouver", "montreal", "calgary", "ottawa", "ontario", "quebec", "alberta"]):
        country_code = "ca"
    elif any(w in prompt_lower for w in ["usa", "united states", "new york", "los angeles", "chicago", "miami", "houston", "texas", "california", "florida"]):
        country_code = "us"
    elif any(w in prompt_lower for w in ["uk", "united kingdom", "london", "manchester", "birmingham", "england"]):
        country_code = "gb"
    elif any(w in prompt_lower for w in ["australia", "sydney", "melbourne", "brisbane", "perth"]):
        country_code = "au"
    elif any(w in prompt_lower for w in ["uae", "dubai", "abu dhabi", "sharjah"]):
        country_code = "ae"
    else:
        country_code = "bd"

    sub_locations = get_default_sub_locations(country_code)

    # Dynamic Keywords based on query
    if any(w in prompt_lower for w in ["dentist", "dental", "clinic"]):
        keywords = ["Dentist", "Dental clinic"]
    elif any(w in prompt_lower for w in ["hotel", "motel", "resort"]):
        keywords = ["Hotel", "Boutique hotel", "Resort hotel"]
    elif any(w in prompt_lower for w in ["software", "tech", "it"]):
        keywords = ["Software company", "IT company"]
    elif any(w in prompt_lower for w in ["cafe", "coffee"]):
        keywords = ["Cafe", "Coffee shop"]
    else:
        keywords = ["Restaurant", "Bangladeshi restaurant", "Cafe"]

    keywords = detect_and_preserve_core_keyword(user_prompt, keywords)
    final_target = target_leads or extract_target_count(user_prompt)

    if final_target and final_target > 100:
        sub_locations = expand_sub_locations_for_target(sub_locations, final_target, keywords, country_code)

    fb_min_r, fb_max_r = extract_rating_range(user_prompt)
    fb_min_rev, fb_max_rev = extract_review_range(user_prompt)

    return ActionPlan(
        user_prompt=user_prompt,
        keywords=keywords,
        country_code=country_code,
        language="en",
        target_leads=final_target,
        sub_locations=sub_locations,
        filters=FilterConfig(
            website_requirement="no_website" if is_no_website else "any",
            must_have_phone=True,
            min_rating=fb_min_r if fb_min_r is not None else 0.0,
            max_rating=fb_max_r,
            min_reviews=fb_min_rev if fb_min_rev is not None else 0,
            max_reviews=fb_max_rev,
            max_pages_per_search=6 if (final_target and final_target >= 100) else 3,
        ),
        enrichment=EnrichmentConfig(
            enabled=not is_no_website,
            extract_emails=not is_no_website,
            extract_socials=not is_no_website,
            detect_cms=True,
        ),
    )


def generate_plan(
    user_prompt: str,
    provider: Optional[str] = None,
    target_leads: Optional[int] = None,
    save_to_disk: bool = True
) -> ActionPlan:
    """
    Main entry point for generating an ActionPlan.
    Tries configured LLM provider, falls back to alternative provider if key is available.
    Ensures user's core keywords are preserved and scales sub-locations dynamically to meet lead targets.
    """
    chosen_provider = (provider or DEFAULT_LLM_PROVIDER).lower().strip()
    plan: Optional[ActionPlan] = None

    if chosen_provider == "gemini" and GEMINI_API_KEY:
        try:
            plan = plan_with_gemini(user_prompt, GEMINI_API_KEY)
        except Exception as e:
            print(f"[Warning] Gemini planning failed: {e}. Trying fallback...")

    if not plan and (chosen_provider == "groq" or GROQ_API_KEY):
        if GROQ_API_KEY:
            try:
                plan = plan_with_groq(user_prompt, GROQ_API_KEY)
            except Exception as e:
                print(f"[Warning] Groq planning failed: {e}. Trying fallback...")

    if not plan and GEMINI_API_KEY and chosen_provider != "gemini":
        try:
            plan = plan_with_gemini(user_prompt, GEMINI_API_KEY)
        except Exception as e:
            print(f"[Warning] Gemini planning failed: {e}...")

    # If no API key or all providers failed, use intelligent fallback
    if not plan:
        print("[Info] No active LLM API key detected or API call failed. Using offline rule-based fallback planner.")
        plan = create_offline_fallback_plan(user_prompt, target_leads=target_leads)

    # Post-process plan to ensure target_leads, keywords preservation, and multi-location scaling
    if plan:
        effective_target = target_leads or plan.target_leads or extract_target_count(user_prompt)
        plan.target_leads = effective_target

        # 1. CRITICAL KEYWORD PRESERVATION: Always preserve user's core requested business category at index 0
        plan.keywords = detect_and_preserve_core_keyword(user_prompt, plan.keywords)

        # Smart Enrichment: If user did NOT say "no website", enable website enrichment by default
        prompt_lower = user_prompt.lower()
        is_no_website = (
            "no website" in prompt_lower
            or "without website" in prompt_lower
            or "website chara" in prompt_lower
            or "ওয়েবসাইট নেই" in user_prompt
            or "ওয়েবসাইট ছাড়া" in user_prompt
        )
        # Country detection post-processing
        if any(w in prompt_lower for w in ["india", "indian", "delhi", "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata"]):
            plan.country_code = "in"
        elif any(w in prompt_lower for w in ["canada", "toronto", "vancouver", "montreal", "calgary", "ottawa", "ontario", "quebec"]):
            plan.country_code = "ca"
        elif any(w in prompt_lower for w in ["usa", "united states", "new york", "los angeles", "chicago", "miami", "houston", "texas", "california", "florida"]):
            plan.country_code = "us"
        elif any(w in prompt_lower for w in ["uk", "united kingdom", "london", "manchester", "birmingham", "england"]):
            plan.country_code = "gb"
        elif any(w in prompt_lower for w in ["australia", "sydney", "melbourne", "brisbane", "perth"]):
            plan.country_code = "au"
        elif any(w in prompt_lower for w in ["uae", "dubai", "abu dhabi", "sharjah"]):
            plan.country_code = "ae"

        # CRITICAL SAFETY NET: sub_locations MUST NEVER BE EMPTY!
        if not plan.sub_locations or len(plan.sub_locations) == 0:
            print(f"[Warning] Plan returned 0 sub_locations for prompt '{user_prompt}'. Auto-generating major micro-zones for '{plan.country_code}'...", flush=True)
            plan.sub_locations = get_default_sub_locations(plan.country_code)

        # 2. DYNAMIC GEO-SCALING FOR LARGE TARGETS (up to 120 leads/query with 6 pagination offsets)
        if plan.target_leads and plan.target_leads > 0:
            if plan.target_leads >= 100:
                plan.filters.max_pages_per_search = 6
            plan.sub_locations = expand_sub_locations_for_target(
                base_sub_locations=plan.sub_locations,
                target_leads=plan.target_leads,
                keywords=plan.keywords,
                country_code=plan.country_code or "bd",
            )

        if not is_no_website and plan.filters.website_requirement != "no_website":
            plan.enrichment.enabled = True
            plan.enrichment.extract_emails = True
            plan.enrichment.extract_socials = True
            plan.enrichment.detect_cms = True

        # Rating & Reviews filters extraction & strict enforcement
        r_min, r_max = extract_rating_range(user_prompt)
        if r_min is not None:
            plan.filters.min_rating = r_min
        if r_max is not None:
            plan.filters.max_rating = r_max

        rev_min, rev_max = extract_review_range(user_prompt)
        if rev_min is not None:
            plan.filters.min_reviews = rev_min
        if rev_max is not None:
            plan.filters.max_reviews = rev_max

    # Save generated plan to output/plans/
    if save_to_disk:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = PLANS_DIR / f"plan_{timestamp}.json"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(plan.model_dump_json(indent=2))
        print(f"[Success] Action plan saved to: {filename}")

    return plan

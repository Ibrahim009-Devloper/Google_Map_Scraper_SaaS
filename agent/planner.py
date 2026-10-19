"""
AI Planner Module for Autonomous Google Maps Lead Generation Agent.
Converts natural language user requests into a strict JSON ActionPlan.
"""

import os
import json
import re
import datetime
from typing import Optional

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
1. KEYWORDS: Generate 2 to 4 highly relevant Google Maps business category keywords based on the user's request.
2. GEO-SPLITTING (CRITICAL): Google Maps limits results to 120 per search area. If the user specifies a large city or region (e.g., "Dhaka", "Chittagong", "London", "New York"), you MUST break it down into 10 to 20 smaller neighborhoods/sub-areas (e.g. for Dhaka: Dhanmondi, Gulshan, Banani, Uttara, Mirpur, Motijheel, Khilgaon, Mohammadpur, Badda, Bashundhara, Mohakhali, Old Dhaka, etc.) with accurate center Latitude (`lat`), Longitude (`lon`), and `radius` in meters (usually 2500 to 4000). If the user already specified a small neighborhood (e.g., "Banani"), return 1 to 2 sub-locations covering that neighborhood.
3. TARGET LEADS (CRITICAL):
   - If the user specifies an exact quantity of leads in natural language (e.g., "50 ta lead", "50টি রেস্টুরেন্ট", "50 restaurants", "100 companies", "20 leads"), extract this integer into "target_leads" (e.g. 50).
   - If no specific number is mentioned, set "target_leads": null.
4. WEBSITE FILTER:
   - Set "website_requirement": "no_website" if the user wants leads without websites (or businesses that only have Facebook/Instagram pages).
   - Set "website_requirement": "has_real_website" if the user explicitly asks for businesses with real websites.
   - Set "website_requirement": "any" if the user wants all leads regardless of website status.
5. WEBSITE ENRICHMENT (DEEP SCRAPER):
   - Unless the user specifically asks for "no_website" (leads without websites), ALWAYS enable website enrichment by default ("enabled": true, "extract_emails": true, "extract_socials": true, "detect_cms": true) so that emails and social links are scraped from business websites.
   - Set "enabled": false ONLY when "website_requirement" is "no_website".
6. COUNTRY & LANGUAGE:
   - Infer the country code (e.g., "bd" for Bangladesh, "us" for USA, "gb" for UK) from the requested location.
   - Default language is "en".
7. PAGINATION & SPEED:
   - Set "max_pages_per_search": 2 (default) or 3 (for deep coverage) so searches complete rapidly (40 to 60 leads per micro-zone).
8. OUTPUT: Respond ONLY with valid JSON matching the exact schema. No markdown fences or extra conversational text.

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
    "min_reviews": integer,
    "max_pages_per_search": integer
  },
  "enrichment": {
    "enabled": boolean,
    "extract_emails": boolean,
    "extract_socials": boolean,
    "detect_cms": boolean
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


def extract_target_count(prompt: str) -> Optional[int]:
    """
    Intelligently extracts the requested target leads count from natural language prompts.
    Handles Bengali markers ('50 ta', '50টি', '৫০ টা'), English markers ('50 leads', 'top 50', '50 restaurants'),
    while avoiding false positives like 'Road 11', 'Sector 4', 'Plot 12'.
    """
    if not prompt:
        return None

    # Normalize Bengali numerals: ০-৯ -> 0-9
    bengali_digits = "০১২৩৪৫৬৭৮৯"
    text = prompt
    for i, b_char in enumerate(bengali_digits):
        text = text.replace(b_char, str(i))

    # 1. Match explicit quantity indicators
    match = re.search(
        r'(?:top\s+|find\s+|get\s+|scrape\s+|need\s+|lagbe\s+)?(\d{1,4})\s*(?:ta|ti|টি|টা|leads?|লিড|entities|businesses|companies|restaurants?|রেস্টুরেন্ট|hotels?|shops?|দোকান|items?)',
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            val = int(match.group(1))
            if 1 <= val <= 1000:
                return val
        except ValueError:
            pass

    # 2. Match patterns like "50টি", "50টা" anywhere
    match = re.search(r'(\d{1,4})\s*(?:ta|ti|টি|টা)', text, re.IGNORECASE)
    if match:
        try:
            val = int(match.group(1))
            if 1 <= val <= 1000:
                return val
        except ValueError:
            pass

    # 3. Match "top 50" or "scrape 50" without suffix
    match = re.search(r'\b(?:top|scrape|extract|collect|need|give\s+me)\s+(\d{1,4})\b', text, re.IGNORECASE)
    if match:
        try:
            val = int(match.group(1))
            if 1 <= val <= 1000:
                return val
        except ValueError:
            pass

    # 4. Match general number followed by noun, avoiding "sector 4", "road 12", etc.
    for m in re.finditer(r'\b(\d{1,4})\b', text):
        num = int(m.group(1))
        start = m.start()
        prefix = text[max(0, start - 15):start].lower()
        if any(w in prefix for w in ["sector", "road", "plot", "house", "block", "ward", "st", "ave", "lane"]):
            continue
        if 5 <= num <= 1000:
            return num

    return None


def create_offline_fallback_plan(user_prompt: str) -> ActionPlan:
    """Provides a deterministic fallback plan if no API key is provided."""
    prompt_lower = user_prompt.lower()
    
    # Check if user wants no website
    is_no_website = any(w in prompt_lower for w in ["no website", "ওয়েবসাইট নেই", "without website", "website chara"])

    # Determine Country & Micro-zones
    if any(w in prompt_lower for w in ["canada", "toronto", "vancouver", "montreal", "calgary", "ottawa", "ontario", "quebec", "alberta"]):
        country_code = "ca"
        sub_locations = [
            SubLocation(area_name="Downtown Toronto, ON", lat=43.6532, lon=-79.3832, radius=3500.0),
            SubLocation(area_name="North York, Toronto, ON", lat=43.7615, lon=-79.4111, radius=3500.0),
            SubLocation(area_name="Scarborough, Toronto, ON", lat=43.7764, lon=-79.2318, radius=3500.0),
            SubLocation(area_name="Mississauga, ON", lat=43.5890, lon=-79.6441, radius=4000.0),
            SubLocation(area_name="Downtown Vancouver, BC", lat=49.2827, lon=-123.1207, radius=3500.0),
            SubLocation(area_name="Downtown Montreal, QC", lat=45.5017, lon=-73.5673, radius=3500.0),
            SubLocation(area_name="Downtown Calgary, AB", lat=51.0447, lon=-114.0719, radius=3500.0),
            SubLocation(area_name="Downtown Ottawa, ON", lat=45.4215, lon=-75.6972, radius=3500.0),
        ]
    elif any(w in prompt_lower for w in ["usa", "united states", "new york", "los angeles", "chicago", "miami", "houston", "texas", "california", "florida"]):
        country_code = "us"
        sub_locations = [
            SubLocation(area_name="Manhattan, New York, NY", lat=40.7831, lon=-73.9712, radius=3500.0),
            SubLocation(area_name="Brooklyn, New York, NY", lat=40.6782, lon=-73.9442, radius=3500.0),
            SubLocation(area_name="Downtown Los Angeles, CA", lat=34.0407, lon=-118.2468, radius=3500.0),
            SubLocation(area_name="Chicago Loop, IL", lat=41.8781, lon=-87.6298, radius=3500.0),
            SubLocation(area_name="Downtown Miami, FL", lat=25.7617, lon=-80.1918, radius=3500.0),
            SubLocation(area_name="Houston Downtown, TX", lat=29.7604, lon=-95.3698, radius=3500.0),
        ]
    elif any(w in prompt_lower for w in ["uk", "united kingdom", "london", "manchester", "birmingham", "england"]):
        country_code = "gb"
        sub_locations = [
            SubLocation(area_name="Central London, UK", lat=51.5074, lon=-0.1278, radius=3500.0),
            SubLocation(area_name="Westminster, London, UK", lat=51.4975, lon=-0.1357, radius=3000.0),
            SubLocation(area_name="Camden, London, UK", lat=51.5455, lon=-0.1417, radius=3000.0),
            SubLocation(area_name="Manchester City Centre, UK", lat=53.4808, lon=-2.2426, radius=3500.0),
        ]
    else:
        country_code = "bd"
        sub_locations = [
            SubLocation(area_name="Dhanmondi, Dhaka", lat=23.7461, lon=90.3742, radius=3000.0),
            SubLocation(area_name="Gulshan, Dhaka", lat=23.7925, lon=90.4078, radius=3500.0),
            SubLocation(area_name="Banani, Dhaka", lat=23.7937, lon=90.4047, radius=3000.0),
            SubLocation(area_name="Uttara, Dhaka", lat=23.8759, lon=90.3795, radius=3500.0),
            SubLocation(area_name="Mirpur, Dhaka", lat=23.8070, lon=90.3686, radius=3500.0),
            SubLocation(area_name="Mohammadpur, Dhaka", lat=23.7658, lon=90.3584, radius=3000.0),
            SubLocation(area_name="Khilgaon, Dhaka", lat=23.7516, lon=90.4239, radius=3000.0),
            SubLocation(area_name="Badda, Dhaka", lat=23.7805, lon=90.4267, radius=3000.0),
            SubLocation(area_name="Motijheel, Dhaka", lat=23.7330, lon=90.4172, radius=3000.0),
            SubLocation(area_name="Old Dhaka, Dhaka", lat=23.7104, lon=90.4074, radius=3000.0),
        ]

    # Dynamic Keywords
    if any(w in prompt_lower for w in ["dentist", "dental", "clinic"]):
        keywords = ["Dentist", "Dental clinic"]
    elif any(w in prompt_lower for w in ["hotel", "motel", "resort"]):
        keywords = ["Hotel", "Boutique hotel", "Resort hotel"]
    elif any(w in prompt_lower for w in ["software", "tech", "it"]):
        keywords = ["Software company", "IT company"]
    elif any(w in prompt_lower for w in ["cafe", "coffee"]):
        keywords = ["Cafe", "Coffee shop"]
    else:
        keywords = ["Restaurant", "Cafe", "Fast food restaurant"]

    target_leads = extract_target_count(user_prompt)

    return ActionPlan(
        user_prompt=user_prompt,
        keywords=keywords,
        country_code=country_code,
        language="en",
        target_leads=target_leads,
        sub_locations=sub_locations,
        filters=FilterConfig(
            website_requirement="no_website" if is_no_website else "any",
            must_have_phone=True,
            min_rating=0.0,
            min_reviews=0,
            max_pages_per_search=3,
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
    save_to_disk: bool = True
) -> ActionPlan:
    """
    Main entry point for generating an ActionPlan.
    Tries configured LLM provider, falls back to alternative provider if key is available.
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
        plan = create_offline_fallback_plan(user_prompt)

    # Post-process plan to ensure target_leads and website enrichment are strictly honored
    if plan:
        if plan.target_leads is None:
            plan.target_leads = extract_target_count(user_prompt)

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
        if any(w in prompt_lower for w in ["canada", "toronto", "vancouver", "montreal", "calgary", "ottawa", "ontario", "quebec"]):
            plan.country_code = "ca"
        elif any(w in prompt_lower for w in ["usa", "united states", "new york", "los angeles", "chicago", "miami", "houston", "texas", "california", "florida"]):
            plan.country_code = "us"
        elif any(w in prompt_lower for w in ["uk", "united kingdom", "london", "manchester", "birmingham", "england"]):
            plan.country_code = "gb"

        if not is_no_website and plan.filters.website_requirement != "no_website":
            plan.enrichment.enabled = True
            plan.enrichment.extract_emails = True
            plan.enrichment.extract_socials = True
            plan.enrichment.detect_cms = True

    # Save generated plan to output/plans/
    if save_to_disk:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = PLANS_DIR / f"plan_{timestamp}.json"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(plan.model_dump_json(indent=2))
        print(f"[Success] Action plan saved to: {filename}")

    return plan

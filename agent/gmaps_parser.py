"""
Google Maps Reverse API Response Parser.
Cleans XSSI prefixes, unwraps double-encoded JSON, and parses business attributes
using tested index mappings.
"""

import json
import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from config import SOCIAL_OR_DIRECTORY_DOMAINS
from agent.schemas import LeadItem, SocialLinks
from agent.cleaner import clean_lead_item


def safe_get(data: Any, path: List[int], default: Any = None) -> Any:
    """
    Safely navigates nested lists by index path without raising IndexError.
    """
    curr = data
    for idx in path:
        if isinstance(curr, list) and 0 <= idx < len(curr) and curr[idx] is not None:
            curr = curr[idx]
        else:
            return default
    return curr


def unwrap_gmaps_json(raw_response_text: str) -> list:
    """
    Unwraps Google Maps double-encoded response text.
    Handles outer {"c": 0, "d": ")]}'\\n[[..."} and XSSI prefix )]}'.
    """
    text = raw_response_text.strip()
    if not text:
        return []

    # Case 1: Outer JSON object {"c": 0, "d": ")]}'\n[[..."}
    if text.startswith("{"):
        try:
            outer_obj = json.loads(text)
            text = outer_obj.get("d", "")
        except json.JSONDecodeError:
            pass

    # Case 2: Strip Google's XSSI security prefix )]}'
    clean_text = text.lstrip(")]}'\n ")
    if not clean_text:
        return []

    try:
        parsed = json.loads(clean_text)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def classify_website(raw_url: Optional[str]) -> Tuple[str, Optional[str], SocialLinks]:
    """
    Classifies a business website into:
    - 'No Website'
    - 'Social Link Only'
    - 'Has Own Website'

    Returns: (website_status, clean_website_url, social_links)
    """
    socials = SocialLinks()

    if not raw_url or not str(raw_url).strip():
        return "No Website", None, socials

    url_str = str(raw_url).strip()
    url_lower = url_str.lower()

    # Unwrap Google redirect if present
    if "google." in url_lower and "/url" in url_lower:
        try:
            from urllib.parse import urlparse, parse_qs
            parsed_g = urlparse(url_str if url_str.startswith(("http://", "https://")) else "https://" + url_str)
            qs = parse_qs(parsed_g.query)
            if "q" in qs and qs["q"]:
                url_str = qs["q"][0]
                url_lower = url_str.lower()
        except Exception:
            pass

    # Check for social or directory domains
    is_social = any(d in url_lower for d in SOCIAL_OR_DIRECTORY_DOMAINS)
    if is_social:
        if "facebook.com" in url_lower or "fb.com" in url_lower:
            socials.facebook = url_str
        elif "instagram.com" in url_lower:
            socials.instagram = url_str
        elif "linkedin.com" in url_lower:
            socials.linkedin = url_str
        elif "wa.me" in url_lower or "whatsapp" in url_lower:
            socials.whatsapp = url_str
        return "Social Link Only", None, socials

    return "Has Own Website", url_str, socials


def check_is_unclaimed(b_data: list) -> bool:
    """
    Checks if a business listing is unclaimed on Google Maps.
    Primary: b_data[57][1] == 'Claim this business'.
    Fallback: Scans elements in b_data up to depth 3 for 'claim this business' or 'own this business'.
    """
    claim_text = safe_get(b_data, [57, 1])
    if claim_text and ("claim this business" in str(claim_text).lower() or "own this business" in str(claim_text).lower()):
        return True

    def _scan(item, depth=0):
        if depth > 3:
            return False
        if isinstance(item, str):
            low = item.lower()
            if "claim this business" in low or "own this business" in low:
                return True
        elif isinstance(item, list):
            for sub in item:
                if _scan(sub, depth + 1):
                    return True
        return False

    return _scan(b_data)


def parse_single_business(item: list, source_query: Optional[str] = None, country_code: str = "bd") -> Optional[LeadItem]:
    """
    Parses a single business result item from Google Maps raw results array.
    Uses exact tested indices from GEMINI.md Section 5.3.
    """
    b_data = safe_get(item, [14])
    if not isinstance(b_data, list):
        return None

    # Mandatory field: name and place_id
    name = safe_get(b_data, [11])
    place_id = safe_get(b_data, [78])
    if not name or not place_id:
        return None

    # Categories
    categories = safe_get(b_data, [13], [])
    primary_category = categories[0] if categories and isinstance(categories, list) else None

    # Neighborhood & Address
    neighborhood = safe_get(b_data, [14])
    full_address = safe_get(b_data, [39]) or safe_get(b_data, [18])

    # Phone numbers (prioritize international formatted, then local, then clean)
    phone = (
        safe_get(b_data, [178, 0, 1, 1, 0])
        or safe_get(b_data, [178, 0, 0])
        or safe_get(b_data, [178, 0, 3])
    )

    # Website classification
    raw_website_url = safe_get(b_data, [7, 0])
    website_status, clean_website_url, social_links = classify_website(raw_website_url)

    # Ratings & Reviews
    rating_val = safe_get(b_data, [4, 7])
    try:
        rating = float(rating_val) if rating_val is not None else None
    except (ValueError, TypeError):
        rating = None

    reviews_val = safe_get(b_data, [4, 8], 0)
    try:
        reviews_count = int(reviews_val) if reviews_val is not None else 0
    except (ValueError, TypeError):
        reviews_count = 0

    price_range = safe_get(b_data, [4, 2])

    # Geo coordinates
    lat = safe_get(b_data, [9, 2])
    lon = safe_get(b_data, [9, 3])

    # Order or booking link
    order_link = safe_get(b_data, [75, 0, 0, 2, 0, 1, 2, 0])

    # Unclaimed / Claim this business status (defensive check with recursive fallback)
    is_unclaimed = check_is_unclaimed(b_data)

    google_maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    lead = LeadItem(
        place_id=str(place_id),
        name=str(name),
        category=primary_category,
        phone=str(phone) if phone else None,
        website_status=website_status,
        website_url=clean_website_url,
        social_links=social_links,
        emails=[],
        cms_tech=None,
        rating=rating,
        reviews_count=reviews_count,
        price_range=price_range,
        is_unclaimed_business=is_unclaimed,
        neighborhood=neighborhood,
        address=full_address,
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        order_link=order_link,
        google_maps_url=google_maps_url,
        source_query=source_query,
    )
    return clean_lead_item(lead, country_code=country_code)


def parse_gmaps_leads(
    raw_response_text: str,
    source_query: Optional[str] = None,
    country_code: str = "bd"
) -> List[LeadItem]:
    """
    Parses all organic business leads from raw Google Maps response text.
    Filters out map boundary blocks and sponsored metadata.
    Includes defensive logging for 100% missing field anomalies to detect schema shifts.
    """
    root = unwrap_gmaps_json(raw_response_text)
    if not root:
        return []

    # Main results array is at root[0][1]
    raw_results = safe_get(root, [0, 1], [])
    if not isinstance(raw_results, list):
        return []

    leads: List[LeadItem] = []
    total_candidates = 0
    missing_name_or_id = 0

    for item in raw_results:
        if not isinstance(item, list):
            continue
        b_data = safe_get(item, [14])
        if not isinstance(b_data, list):
            continue

        total_candidates += 1
        name = safe_get(b_data, [11])
        place_id = safe_get(b_data, [78])
        if not name or not place_id:
            missing_name_or_id += 1

        lead = parse_single_business(item, source_query=source_query, country_code=country_code)
        if lead:
            leads.append(lead)

    # Defensive schema shift check
    if total_candidates > 0 and missing_name_or_id == total_candidates:
        logger.warning(
            "[GMaps Parser Alert] 100%% of candidate items (%d/%d) in batch are missing name or place_id! "
            "Google Maps internal protobuf/JSON schema may have shifted.",
            missing_name_or_id, total_candidates
        )
    elif leads and all(not l.phone and not l.address and not l.website_url for l in leads):
        logger.warning(
            "[GMaps Parser Alert] 100%% of parsed leads in batch (%d leads) have missing phone, address, and website! "
            "Possible Google schema shift.",
            len(leads)
        )

    return leads

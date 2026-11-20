"""
Google Maps Reverse API Client.
Constructs internal protobuf parameters and queries Google Maps reverse API
using curl_cffi with browser impersonation and simulated sidebar scrolling.
"""

import time
import random
from typing import List, Optional, Callable, Any
from urllib.parse import quote

from curl_cffi import requests

from config import DEFAULT_IMPERSONATE, DEFAULT_TIMEOUT, DEFAULT_MAX_PAGES_PER_SEARCH
from agent.schemas import LeadItem
from agent.gmaps_parser import parse_gmaps_leads


def build_pb_parameter(lat: float, lon: float, offset: int = 0, radius: float = 3500.0) -> str:
    """
    CRITICAL GEO RULE:
    !1d = Radius in meters (float)
    !2d = LONGITUDE (must be LON first!)
    !3d = LATITUDE (must be LAT second!)
    !7i20 = Results per page (20)
    !8i{offset} = Pagination offset (0, 20, 40, 60...)
    """
    return (
        f"!4m8!1m3!1d{radius}!2d{lon}!3d{lat}"
        f"!3m2!1i1024!2i768!4f13.1"
        f"!7i20!8i{offset}"
        f"!10b1!12m8!1m1!18b1!2m3!5m1!6e2!20e3!10b1!16b1"
    )


def build_search_url(
    keyword: str,
    area_name: str,
    lat: float,
    lon: float,
    offset: int = 0,
    radius: float = 3500.0,
    gl: str = "bd",
    hl: str = "en",
) -> str:
    """Constructs the internal Google Maps search endpoint URL."""
    full_query = f"{keyword} in {area_name}"
    encoded_q = quote(full_query)
    pb = build_pb_parameter(lat=lat, lon=lon, offset=offset, radius=radius)
    return f"https://www.google.com/search?tbm=map&authuser=0&hl={hl}&gl={gl}&q={encoded_q}&pb={pb}"


def fetch_single_page(
    keyword: str,
    area_name: str,
    lat: float,
    lon: float,
    offset: int = 0,
    radius: float = 3500.0,
    gl: str = "bd",
    hl: str = "en",
    retries: int = 3,
    stop_event: Optional[Any] = None,
) -> Optional[str]:
    """
    Fetches raw response text for a single offset page of Google Maps reverse API.
    Uses curl_cffi with chrome124 TLS/JA3 impersonation.
    Supports instant cancellation via stop_event.
    """
    if stop_event and stop_event.is_set():
        return None

    url = build_search_url(
        keyword=keyword,
        area_name=area_name,
        lat=lat,
        lon=lon,
        offset=offset,
        radius=radius,
        gl=gl,
        hl=hl,
    )

    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/maps",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Requested-With": "XMLHttpRequest",
    }

    for attempt in range(1, retries + 1):
        if stop_event and stop_event.is_set():
            return None
        try:
            response = requests.get(
                url,
                impersonate=DEFAULT_IMPERSONATE,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
            if response.status_code == 200:
                return response.text
            elif response.status_code in (429, 503):
                # Exponential backoff with jitter on 429 Too Many Requests or 503 Service Unavailable
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[RateLimit/Server] HTTP {response.status_code} on attempt {attempt}/{retries}. Backing off for {wait_time:.1f}s...")
                if stop_event and stop_event.wait(timeout=wait_time):
                    return None
                elif not stop_event:
                    time.sleep(wait_time)
            else:
                print(f"[Warning] HTTP {response.status_code} on attempt {attempt} for offset {offset}")
                wait_time = 1.0 + random.uniform(0.2, 0.8)
                if stop_event and stop_event.wait(timeout=wait_time):
                    return None
                elif not stop_event:
                    time.sleep(wait_time)
        except Exception as e:
            wait_time = (1.5 * attempt) + random.uniform(0.2, 0.8)
            print(f"[Error] Network exception on attempt {attempt}/{retries}: {e}. Retrying in {wait_time:.1f}s...")
            if stop_event and stop_event.wait(timeout=wait_time):
                return None
            elif not stop_event:
                time.sleep(wait_time)

    return None


def fetch_all_pages_for_location(
    keyword: str,
    area_name: str,
    lat: float,
    lon: float,
    radius: float = 3500.0,
    max_pages: int = DEFAULT_MAX_PAGES_PER_SEARCH,
    gl: str = "bd",
    hl: str = "en",
    stop_event: Optional[Any] = None,
    on_page_leads: Optional[Callable[[List[LeadItem]], None]] = None,
) -> List[LeadItem]:
    """
    Simulates Google Maps sidebar scrolling by incrementing !8i{offset} by 20.
    Fetches up to 120 leads per sub-location with intelligent early-stopping,
    cancellation check via stop_event, and real-time on_page_leads callback.
    """
    all_leads: List[LeadItem] = []
    seen_place_ids_in_session = set()
    source_query = f"{keyword} in {area_name}"

    for page_idx in range(max_pages):
        # Cancellation check before fetching
        if stop_event and stop_event.is_set():
            break

        offset = page_idx * 20  # 0, 20, 40, 60, 80, 100

        raw_json_text = fetch_single_page(
            keyword=keyword,
            area_name=area_name,
            lat=lat,
            lon=lon,
            offset=offset,
            radius=radius,
            gl=gl,
            hl=hl,
            stop_event=stop_event,
        )

        if not raw_json_text:
            break

        if stop_event and stop_event.is_set():
            break

        page_leads = parse_gmaps_leads(raw_json_text, source_query=source_query, country_code=gl)

        # Stop Condition 1: No more results found
        if not page_leads:
            break

        # Check for new unique leads in this page
        new_leads_in_page: List[LeadItem] = []
        for lead in page_leads:
            pid = lead.place_id
            if pid and pid not in seen_place_ids_in_session:
                seen_place_ids_in_session.add(pid)
                all_leads.append(lead)
                new_leads_in_page.append(lead)

        # Stop Condition 2: Google started repeating the same results
        if not new_leads_in_page:
            break

        # Real-time page callback
        if on_page_leads and new_leads_in_page:
            on_page_leads(new_leads_in_page)

        # Stop Condition 3: Less than 15 results returned means end of list
        if len(page_leads) < 15:
            break

        if stop_event and stop_event.is_set():
            break

        # Polite human-like jitter delay between pages (interruptible on stop)
        jitter_delay = random.uniform(0.8, 2.0)
        if stop_event:
            if stop_event.wait(timeout=jitter_delay):
                break
        else:
            time.sleep(jitter_delay)

    return all_leads

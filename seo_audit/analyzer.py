"""
11 Local SEO Check Engines for evaluating on-page, mobile, technical,
and Local Pack signals from static HTML.
"""

import re
import json
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from seo_audit.models import AuditIssue, AuditInput
from seo_audit.fetcher import FetchResult
from seo_audit.config import SEO_SLOW_LOAD_THRESHOLD, SEO_MODERATE_LOAD_THRESHOLD

GENERIC_TITLES = {"home", "welcome", "untitled", "homepage", "index", "default"}

# Common Schema.org LocalBusiness types and subtypes
LOCAL_BUSINESS_TYPES = {
    "localbusiness",
    "dentist",
    "plumber",
    "roofingcontractor",
    "electrician",
    "hvacbusiness",
    "legalservice",
    "attorney",
    "notary",
    "restaurant",
    "foodestablishment",
    "bakery",
    "barorpub",
    "cafeorcoffeeshop",
    "medicalbusiness",
    "physician",
    "pharmacy",
    "hospital",
    "autorepair",
    "autodealer",
    "automotivebusiness",
    "realestateagent",
    "financialservice",
    "accountingbusiness",
    "bankorcreditunion",
    "insuranceagency",
    "healthandbeautybusiness",
    "beautysalon",
    "hairsalon",
    "dayspa",
    "homeandconstructionbusiness",
    "generalservice",
    "professionalservice",
    "store",
    "grocerystore",
    "clothingstore",
    "lodgingbusiness",
    "hotel",
    "motel",
    "childcare",
    "drycleaningorlaundry",
    "emergencyservice",
    "employmentagency",
    "entertainmentbusiness",
    "recyclecenter",
    "selfstorage",
    "touristinformationcenter",
    "travelagency",
    "veterinarycare",
}


def normalize_phone_digits(phone: Optional[str]) -> str:
    """Extracts only digits from a phone string."""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def clean_words(text: str) -> List[str]:
    """Tokenizes text into lowercased alphanumeric words."""
    return [w.lower() for w in re.findall(r"[A-Za-z0-9]+", text)]


def check_website_speed(fetch_res: FetchResult) -> AuditIssue:
    """Check 1: HTTP Status, SSL & Load Time."""
    if fetch_res.status_code is None:
        return AuditIssue(
            check_name="website_speed",
            audit_status="Fail",
            priority="High",
            evidence=f"Failed to load website: {fetch_res.error_message or 'Unknown network error'}",
            recommended_fix="Verify DNS records, hosting status, and web server configuration.",
            xlsx_summary="Failed [High]",
        )

    code = fetch_res.status_code
    elapsed = fetch_res.elapsed_seconds or 0.0
    final_url = fetch_res.final_url or fetch_res.url
    is_https = final_url.startswith("https://") and not fetch_res.ssl_failed

    if code >= 400:
        return AuditIssue(
            check_name="website_speed",
            audit_status="Fail",
            priority="High",
            evidence=f"HTTP Status {code} returned from {final_url}.",
            recommended_fix="Fix broken web page or server misconfiguration.",
            xlsx_summary=f"Broken (HTTP {code}) [High]",
        )

    if not is_https:
        return AuditIssue(
            check_name="website_speed",
            audit_status="Fail",
            priority="High",
            evidence=f"Website uses insecure HTTP or has SSL certificate failures ({final_url}).",
            recommended_fix="Install a valid SSL certificate and enforce HTTPS redirection.",
            xlsx_summary="Insecure HTTP [High]",
        )

    if elapsed > SEO_SLOW_LOAD_THRESHOLD:
        return AuditIssue(
            check_name="website_speed",
            audit_status="Fail",
            priority="High",
            evidence=f"Slow response time: page loaded in {elapsed}s (threshold {SEO_SLOW_LOAD_THRESHOLD}s).",
            recommended_fix="Optimize server response time (TTFB), leverage CDN caching, and compress heavy assets.",
            xlsx_summary=f"Slow ({elapsed}s) [High]",
        )

    if elapsed > SEO_MODERATE_LOAD_THRESHOLD:
        return AuditIssue(
            check_name="website_speed",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Page loaded in {elapsed}s (recommended < {SEO_MODERATE_LOAD_THRESHOLD}s).",
            recommended_fix="Optimize server TTFB, compress images, and enable browser caching.",
            xlsx_summary=f"Moderate ({elapsed}s) [Medium]",
        )

    return AuditIssue(
        check_name="website_speed",
        audit_status="Pass",
        priority="None",
        evidence=f"Fast load time: {elapsed}s via HTTPS (HTTP {code}).",
        xlsx_summary=f"Fast ({elapsed}s)",
    )


def check_mobile_friendly(soup: BeautifulSoup) -> AuditIssue:
    """Check 2: Mobile Usability (Viewport)."""
    viewport_meta = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    if viewport_meta and viewport_meta.get("content"):
        content = viewport_meta["content"].strip()
        if "width=device-width" in content.lower():
            return AuditIssue(
                check_name="mobile_friendly",
                audit_status="Pass",
                priority="None",
                evidence=f"Viewport meta tag present: '{content}'.",
                xlsx_summary="Pass",
            )

    return AuditIssue(
        check_name="mobile_friendly",
        audit_status="Fail",
        priority="High",
        evidence="No <meta name='viewport'> tag found in HTML head.",
        recommended_fix="Add <meta name='viewport' content='width=device-width, initial-scale=1'> for mobile responsiveness.",
        xlsx_summary="Fail (No Viewport) [High]",
    )


def check_title_tag(soup: BeautifulSoup) -> AuditIssue:
    """Check 3: Title Tag presence, length, and boilerplate."""
    title_tag = soup.find("title")
    if not title_tag or not title_tag.get_text(strip=True):
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="High",
            evidence="No <title> tag found on the page.",
            recommended_fix="Add a unique 30-60 character title tag with primary keyword + city + brand name.",
            xlsx_summary="Missing [High]",
        )

    title_text = title_tag.get_text(strip=True)
    length = len(title_text)

    if title_text.lower() in GENERIC_TITLES or length < 15:
        return AuditIssue(
            check_name="title_tag",
            audit_status="Fail",
            priority="High",
            evidence=f"Title tag is too short or generic ({length} chars): '{title_text}'.",
            recommended_fix="Write a descriptive title tag (30-60 chars) including service keyword, target city, and business name.",
            xlsx_summary=f"Too Short ({length} chars) [High]",
        )

    if length > 75:
        return AuditIssue(
            check_name="title_tag",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Title tag is too long ({length} chars) and will truncate in Google search results: '{title_text[:60]}...'.",
            recommended_fix="Trim title tag to 30-60 characters focusing on primary keyword and city.",
            xlsx_summary=f"Too Long ({length} chars) [Medium]",
        )

    if (15 <= length < 30) or (61 <= length <= 75):
        return AuditIssue(
            check_name="title_tag",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Title length is suboptimal ({length} chars): '{title_text}'. Recommended range is 30-60 characters.",
            recommended_fix="Refine title tag length to 30-60 characters for optimal click-through rate.",
            xlsx_summary=f"Suboptimal ({length} chars) [Medium]",
        )

    return AuditIssue(
        check_name="title_tag",
        audit_status="Pass",
        priority="None",
        evidence=f"Title tag length optimal ({length} chars): '{title_text}'.",
        xlsx_summary=f"Optimal ({length} chars)",
    )


def check_meta_description(soup: BeautifulSoup) -> AuditIssue:
    """Check 4: Meta Description presence and length."""
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not meta_tag or not meta_tag.get("content", "").strip():
        return AuditIssue(
            check_name="meta_description",
            audit_status="Fail",
            priority="Medium",
            evidence="Missing <meta name='description'> tag.",
            recommended_fix="Write a compelling 70-160 character meta description including local service area and call-to-action.",
            xlsx_summary="Missing [Medium]",
        )

    desc_text = meta_tag["content"].strip()
    length = len(desc_text)

    if length < 70 or length > 160:
        label = "Too Short" if length < 70 else "Too Long"
        return AuditIssue(
            check_name="meta_description",
            audit_status="Warning",
            priority="Low",
            evidence=f"Meta description length is {length} chars (recommended 70-160).",
            recommended_fix="Optimize meta description to 70-160 characters with targeted local keywords.",
            xlsx_summary=f"{label} ({length} chars) [Low]",
        )

    return AuditIssue(
        check_name="meta_description",
        audit_status="Pass",
        priority="None",
        evidence=f"Meta description length optimal ({length} chars).",
        xlsx_summary=f"Optimal ({length} chars)",
    )


def check_h1_status(soup: BeautifulSoup) -> AuditIssue:
    """Check 5: Single descriptive H1 heading."""
    h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all("h1") if h1.get_text(strip=True)]
    count = len(h1_tags)

    if count == 0:
        return AuditIssue(
            check_name="h1_status",
            audit_status="Fail",
            priority="High",
            evidence="0 <h1> tags found on the page.",
            recommended_fix="Add exactly one descriptive <h1> heading containing the primary service and target city.",
            xlsx_summary="Missing H1 [High]",
        )

    if count > 1:
        samples = "', '".join(h1_tags[:2])
        return AuditIssue(
            check_name="h1_status",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Found {count} <h1> tags: ['{samples}', ...].",
            recommended_fix="Keep only one primary <h1> tag and convert secondary headings to <h2> or <h3>.",
            xlsx_summary=f"Multiple ({count} H1s) [Medium]",
        )

    return AuditIssue(
        check_name="h1_status",
        audit_status="Pass",
        priority="None",
        evidence=f"Exactly 1 descriptive H1 found: '{h1_tags[0]}'.",
        xlsx_summary="Optimal (1 H1)",
    )


def check_canonical_robots(soup: BeautifulSoup, fetch_res: FetchResult) -> AuditIssue:
    """Check 6: Canonical tag and Robots Indexability."""
    # Check noindex in meta tags or headers
    noindex_found = False
    noindex_source = ""

    robots_meta = soup.find("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)})
    if robots_meta and "noindex" in robots_meta.get("content", "").lower():
        noindex_found = True
        noindex_source = f"meta robots: '{robots_meta['content']}'"

    x_robots = fetch_res.headers.get("x-robots-tag", "").lower()
    if "noindex" in x_robots:
        noindex_found = True
        noindex_source = f"HTTP X-Robots-Tag: '{x_robots}'"

    if noindex_found:
        return AuditIssue(
            check_name="canonical_robots",
            audit_status="Fail",
            priority="High",
            evidence=f"Page is blocked from Google indexing via {noindex_source}.",
            recommended_fix="Remove 'noindex' directive immediately so the website can rank in Google Search.",
            xlsx_summary="Blocked (noindex) [Critical]",
        )

    canonical = soup.find("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    if not canonical or not canonical.get("href", "").strip():
        return AuditIssue(
            check_name="canonical_robots",
            audit_status="Warning",
            priority="Low",
            evidence="No <link rel='canonical'> tag found on page.",
            recommended_fix="Add a self-referencing canonical tag to prevent duplicate content issues.",
            xlsx_summary="Missing Canonical [Low]",
        )

    return AuditIssue(
        check_name="canonical_robots",
        audit_status="Pass",
        priority="None",
        evidence=f"Canonical URL set to '{canonical['href']}' and page is indexable.",
        xlsx_summary="Indexable",
    )


def check_image_alt(soup: BeautifulSoup) -> AuditIssue:
    """Check 7: Image Alt Text Coverage."""
    images = soup.find_all("img")
    total = len(images)
    if total == 0:
        return AuditIssue(
            check_name="image_alt",
            audit_status="Unverified",
            priority="None",
            evidence="No <img> tags detected in static HTML.",
            xlsx_summary="Unverified",
        )

    missing = sum(1 for img in images if not img.get("alt", "").strip())
    pct = round((missing / total) * 100)

    if pct > 30:
        return AuditIssue(
            check_name="image_alt",
            audit_status="Warning",
            priority="Low",
            evidence=f"{missing}/{total} images ({pct}%) are missing descriptive alt attributes.",
            recommended_fix="Add descriptive alt text with relevant service/location keywords to all key images.",
            xlsx_summary=f"Poor Alt ({pct}% missing) [Low]",
        )

    return AuditIssue(
        check_name="image_alt",
        audit_status="Pass",
        priority="None",
        evidence=f"Good image alt coverage ({missing}/{total} missing, {pct}%).",
        xlsx_summary=f"Good Alt ({pct}% missing)",
    )


def check_local_keywords(soup: BeautifulSoup, city: Optional[str], category: Optional[str]) -> AuditIssue:
    """Check 8: City + Category keyword in Title, H1, H2, or Meta Description."""
    if not city and not category:
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Unverified",
            priority="None",
            evidence="Target city and business category were not provided in Google Maps input.",
            xlsx_summary="Unverified",
        )

    city_terms = [t for t in clean_words(city) if len(t) > 2] if city else []
    cat_terms = [t for t in clean_words(category) if len(t) > 3 and t not in {"contractor", "services", "company", "store"}] if category else []

    title_text = (soup.find("title").get_text(strip=True) if soup.find("title") else "").lower()
    h1_text = " ".join(h.get_text(strip=True).lower() for h in soup.find_all("h1"))
    head_text = f"{title_text} {h1_text}"

    h2_text = " ".join(h.get_text(strip=True).lower() for h in soup.find_all("h2"))
    meta_desc = (soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}) or {}).get("content", "").lower()
    all_key_text = f"{head_text} {h2_text} {meta_desc}"

    city_found_head = any(ct in head_text for ct in city_terms) if city_terms else True
    cat_found_head = any(kt in head_text for kt in cat_terms) if cat_terms else True

    city_found_any = any(ct in all_key_text for ct in city_terms) if city_terms else True
    cat_found_any = any(kt in all_key_text for kt in cat_terms) if cat_terms else True

    if city_found_head and cat_found_head:
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Pass",
            priority="None",
            evidence=f"Found both city ('{city}') and niche keyword ('{category}') in Title or H1.",
            xlsx_summary="Pass (City + Niche)",
        )

    if city_found_any and cat_found_any:
        missing_in_head = "city" if not city_found_head else "service keyword"
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Local keywords found on page, but missing {missing_in_head} in Title/H1.",
            recommended_fix=f"Include both target city ('{city}') and primary service ('{category}') in <title> and <h1>.",
            xlsx_summary=f"Partial (Missing {missing_in_head} in Title/H1) [Medium]",
        )

    if city_found_any or cat_found_any:
        missing_item = "city" if not city_found_any else "service keyword"
        return AuditIssue(
            check_name="local_keywords",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Missing '{missing_item}' across Title, H1, and Meta Description.",
            recommended_fix=f"Add '{missing_item}' prominently to the homepage Title and H1.",
            xlsx_summary=f"Partial (Missing {missing_item}) [Medium]",
        )

    return AuditIssue(
        check_name="local_keywords",
        audit_status="Fail",
        priority="High",
        evidence=f"Neither target city ('{city}') nor primary service ('{category}') found in Title, H1, or Meta.",
        recommended_fix="Rewrite Title and H1 to explicitly include your primary service and target city.",
        xlsx_summary="Missing Local Keywords [High]",
    )


def check_nap_consistency(
    soup: BeautifulSoup,
    name: Optional[str],
    phone: Optional[str],
    address: Optional[str],
) -> AuditIssue:
    """Check 9: NAP Consistency (Name, Address, Phone)."""
    if not phone and not address:
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Unverified",
            priority="None",
            evidence="Google Maps input lacks both phone and address baseline.",
            xlsx_summary="Unverified",
        )

    full_page_text = soup.get_text(separator=" ", strip=True).lower()
    tel_links = [a.get("href", "").lower() for a in soup.find_all("a", href=True) if a["href"].lower().startswith("tel:")]
    all_phone_sources = full_page_text + " " + " ".join(tel_links)

    # Phone check: compare last 7 to 10 digits
    phone_matched = False
    if phone:
        phone_digits = normalize_phone_digits(phone)
        if len(phone_digits) >= 7:
            last_7 = phone_digits[-7:]
            last_10 = phone_digits[-10:] if len(phone_digits) >= 10 else last_7
            all_digits = normalize_phone_digits(all_phone_sources)
            if last_7 in all_digits or last_10 in all_digits:
                phone_matched = True

    # Address check: match street number or postal/zip code
    address_matched = False
    if address:
        address_parts = [p.strip().lower() for p in address.split(",") if p.strip()]
        # Check zip code (e.g. 5 digits) or street number (e.g. 123)
        zip_match = re.search(r"\b\d{4,6}\b", address)
        street_match = re.search(r"^\d+\b", address_parts[0]) if address_parts else None

        zip_val = zip_match.group(0) if zip_match else ""
        street_val = street_match.group(0) if street_match else ""

        if zip_val and zip_val in full_page_text:
            address_matched = True
        elif street_val and street_val in full_page_text:
            address_matched = True
        elif any(len(p) > 5 and p in full_page_text for p in address_parts):
            address_matched = True

    # Name check
    name_matched = True
    if name:
        name_clean = " ".join([w for w in clean_words(name) if len(w) > 2])
        if name_clean and name_clean not in full_page_text:
            name_matched = False

    if (phone and phone_matched) and (address and address_matched):
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Pass",
            priority="None",
            evidence="Google Maps Name, Phone, and Address matched on website.",
            xlsx_summary="Consistent",
        )

    if (phone and phone_matched) and not address_matched:
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            priority="Medium",
            evidence="Phone number matched, but street/zip address from Google Maps not found on homepage.",
            recommended_fix="Display full Name, Address, and Phone Number (NAP) in the website footer matching Google Business Profile.",
            xlsx_summary="Partial Mismatch (Address Missing) [Medium]",
        )

    if (address and address_matched) and not phone_matched:
        return AuditIssue(
            check_name="nap_consistency",
            audit_status="Warning",
            priority="Medium",
            evidence="Address matched, but Google Maps phone number was not found on website.",
            recommended_fix="Ensure website phone number exactly matches Google Business Profile phone number.",
            xlsx_summary="Partial Mismatch (Phone Missing) [Medium]",
        )

    return AuditIssue(
        check_name="nap_consistency",
        audit_status="Fail",
        priority="High",
        evidence=f"Neither Google Maps phone ('{phone}') nor address ('{address}') found on website.",
        recommended_fix="Ensure exact NAP consistency between the website and Google Business Profile to boost Local Pack rankings.",
        xlsx_summary="Mismatch (Phone & Address Missing) [High]",
    )


def extract_json_ld_types(data: Any) -> List[str]:
    """Recursively extracts all @type values from JSON-LD object or list."""
    types = []
    if isinstance(data, dict):
        if "@type" in data:
            t = data["@type"]
            if isinstance(t, list):
                types.extend(str(item).lower() for item in t)
            else:
                types.append(str(t).lower())
        for k, v in data.items():
            types.extend(extract_json_ld_types(v))
    elif isinstance(data, list):
        for item in data:
            types.extend(extract_json_ld_types(item))
    return types


def check_schema_markup(soup: BeautifulSoup) -> AuditIssue:
    """Check 10: JSON-LD LocalBusiness Schema markup."""
    script_tags = soup.find_all("script", attrs={"type": "application/ld+json"})
    if not script_tags:
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Fail",
            priority="High",
            evidence="No JSON-LD LocalBusiness schema markup found on page.",
            recommended_fix="Implement valid JSON-LD LocalBusiness schema markup in <head> to help Google verify local entity details.",
            xlsx_summary="Missing Schema [High]",
        )

    all_types = []
    has_parse_error = False
    for script in script_tags:
        content = script.string or script.get_text()
        if not content or not content.strip():
            continue
        try:
            parsed = json.loads(content)
            all_types.extend(extract_json_ld_types(parsed))
        except Exception:
            has_parse_error = True

    # Check for specific LocalBusiness or subtype
    local_match = [t for t in all_types if t in LOCAL_BUSINESS_TYPES or "business" in t or "store" in t]
    if local_match:
        matched_type = local_match[0].title()
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Pass",
            priority="None",
            evidence=f"Valid JSON-LD Schema detected (@type: {matched_type}).",
            xlsx_summary=f"Pass ({matched_type})",
        )

    if any(t in {"organization", "website", "corporation"} for t in all_types):
        org_type = next((t.title() for t in all_types if t in {"organization", "website"}), "Organization")
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Warning",
            priority="Medium",
            evidence=f"Found generic '{org_type}' schema, but missing specific 'LocalBusiness' markup with address and telephone.",
            recommended_fix="Upgrade JSON-LD structured data to 'LocalBusiness' (or niche subtype) with address, telephone, geo coordinates, and openingHours.",
            xlsx_summary="Weak Schema (No LocalBusiness) [Medium]",
        )

    if has_parse_error and not all_types:
        return AuditIssue(
            check_name="schema_markup",
            audit_status="Fail",
            priority="High",
            evidence="Found <script type='application/ld+json'> with broken or malformed JSON syntax.",
            recommended_fix="Fix JSON syntax errors in schema markup using Google Rich Results Test.",
            xlsx_summary="Malformed Schema [High]",
        )

    return AuditIssue(
        check_name="schema_markup",
        audit_status="Fail",
        priority="High",
        evidence="No LocalBusiness or recognized entity schema found in JSON-LD scripts.",
        recommended_fix="Add LocalBusiness schema markup to identify business name, address, and phone number.",
        xlsx_summary="Missing Schema [High]",
    )


def check_contact_maps_embed(soup: BeautifulSoup) -> AuditIssue:
    """Check 11: Clickable phone link and Google Maps embed."""
    has_tel = any(a.get("href", "").lower().startswith("tel:") for a in soup.find_all("a", href=True))

    has_map_embed = False
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "").lower()
        if "google.com/maps" in src or "maps.google.com" in src:
            has_map_embed = True
            break

    has_contact_link = any(
        any(k in a.get("href", "").lower() for k in ["/contact", "contact-us", "contactus"])
        for a in soup.find_all("a", href=True)
    )

    if has_tel and (has_map_embed or has_contact_link):
        return AuditIssue(
            check_name="contact_maps_embed",
            audit_status="Pass",
            priority="None",
            evidence="Found clickable tel: link and Google Maps iframe / contact link.",
            xlsx_summary="Pass (Maps + Click-to-Call)",
        )

    if has_tel and not has_map_embed:
        return AuditIssue(
            check_name="contact_maps_embed",
            audit_status="Warning",
            priority="Low",
            evidence="Has clickable phone link, but no Google Maps embed found.",
            recommended_fix="Embed an interactive Google Maps iframe in the footer or contact section.",
            xlsx_summary="No Maps Embed [Low]",
        )

    return AuditIssue(
        check_name="contact_maps_embed",
        audit_status="Fail",
        priority="Medium",
        evidence="Missing both clickable tel: link and Google Maps embed.",
        recommended_fix="Add a clickable click-to-call link (<a href='tel:...'>) and embed Google Maps.",
        xlsx_summary="Missing Maps & Click-to-Call [Medium]",
    )


def run_all_seo_checks(input_data: AuditInput, fetch_res: FetchResult) -> Dict[str, AuditIssue]:
    """Runs all 11 local SEO checks against the fetched webpage."""
    issues: Dict[str, AuditIssue] = {}

    # Check 1: Speed & HTTP Status
    issues["website_speed"] = check_website_speed(fetch_res)

    # If the website failed to load completely or returned 4xx/5xx, remaining DOM checks cannot be verified
    if fetch_res.status_code is None or fetch_res.status_code >= 400:
        for chk in [
            "mobile_friendly", "title_tag", "meta_description", "h1_status",
            "canonical_robots", "image_alt", "local_keywords", "nap_consistency",
            "schema_markup", "contact_maps_embed",
        ]:
            issues[chk] = AuditIssue(
                check_name=chk,
                audit_status="Unverified",
                priority="None",
                evidence="Could not evaluate check because website could not be reached.",
                xlsx_summary="Unverified",
            )
        return issues

    soup = BeautifulSoup(fetch_res.html, "html.parser")

    issues["mobile_friendly"] = check_mobile_friendly(soup)
    issues["title_tag"] = check_title_tag(soup)
    issues["meta_description"] = check_meta_description(soup)
    issues["h1_status"] = check_h1_status(soup)
    issues["canonical_robots"] = check_canonical_robots(soup, fetch_res)
    issues["image_alt"] = check_image_alt(soup)
    issues["local_keywords"] = check_local_keywords(soup, input_data.city, input_data.category)
    issues["nap_consistency"] = check_nap_consistency(
        soup, input_data.business_name, input_data.phone, input_data.address
    )
    issues["schema_markup"] = check_schema_markup(soup)
    issues["contact_maps_embed"] = check_contact_maps_embed(soup)

    return issues

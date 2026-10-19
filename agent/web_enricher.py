"""
Website Deep Scraping and Enrichment Module.
Extracts emails, social media profiles (Facebook, Instagram, LinkedIn, WhatsApp, YouTube, Twitter/X, TikTok),
phones, and detects CMS platforms (WordPress, Shopify, Wix, Squarespace, Webflow, Joomla)
using curl_cffi and BeautifulSoup4.

Crawls up to 5 prioritized pages per business website:
1. Homepage ('/')
2. '/contact'
3. '/contact-us'
4. '/about'
5. '/about-us'
PLUS any other internal contact/about links discovered on the homepage.
Features Cloudflare email de-obfuscation, mailto unquoting, and anti-bot regex.
"""

import html
import re
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple, Dict, Any

from bs4 import BeautifulSoup
from curl_cffi import requests

from config import DEFAULT_IMPERSONATE, WEB_TIMEOUT, MAX_CONCURRENT_ENRICHMENT
from agent.schemas import LeadItem, SocialLinks
from agent.cleaner import clean_phone_number, clean_website_url

# Comprehensive Email Regex
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)

JUNK_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".js", ".css", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".avi", ".mov", ".zip", ".pdf", ".map", ".tar", ".gz"
)

JUNK_DOMAINS = (
    "sentry.io", "example.com", "wixpress.com", "email.com",
    "domain.com", "yourdomain.com", "schema.org", "w3.org",
    "cloudflare.com", "gravatar.com", "wordpress.org", "wp.com",
    "googleapis.com", "gstatic.com", "facebook.com", "instagram.com"
)

# Canonical target subpages explicitly requested by user
CANONICAL_TARGETS = ["/contact", "/contact-us", "/about", "/about-us"]

SUBPAGE_PATTERNS = [
    # Top Priority (Score 10): Direct Contact & Get in Touch pages
    (re.compile(r"contact(?:-us|_us|us)?|reach(?:-us|_us)?|get-in-touch|contactpage", re.I), 10),
    # High Priority (Score 8): About, Story, Profile pages
    (re.compile(r"about(?:-us|_us|us)?|who-we-are|our-story|company|profile", re.I), 8),
    # Medium-High Priority (Score 6): Team, Branches, Location pages
    (re.compile(r"team|management|locations?|branches?|find-us|our-offices?", re.I), 6),
    # Medium Priority (Score 4): Support, Help, Info, Customer Care
    (re.compile(r"support|help|info|feedback|customer-care|helpdesk", re.I), 4),
    # Lower Priority (Score 2): Legal / Terms / Privacy (often contain corporate headquarters email)
    (re.compile(r"privacy|terms|impressum|legal|disclaimer|corporate", re.I), 2),
]


def decode_cloudflare_email(cf_hex: str) -> Optional[str]:
    """
    Decodes emails protected by Cloudflare's email protection XOR cipher.
    Found in data-cfemail="..." and /cdn-cgi/l/email-protection#...
    """
    try:
        cf_hex = cf_hex.strip()
        if len(cf_hex) < 4:
            return None
        k = int(cf_hex[:2], 16)
        email = "".join([chr(int(cf_hex[i:i+2], 16) ^ k) for i in range(2, len(cf_hex), 2)])
        return email.strip().lower()
    except Exception:
        return None


def deobfuscate_text(text: str) -> str:
    """
    Deobfuscates text containing HTML entities, URL encodings,
    and anti-bot patterns like 'info [at] domain [dot] com'.
    """
    if not text:
        return ""
    text = html.unescape(text)
    text = unquote(text)
    # Strip spaces around [at], (at), and replace with @
    text = re.sub(r'\s*(?:\[\s*(?:at|@)\s*\]|\(\s*(?:at|@)\s*\)|\s+at\s+)\s*', '@', text, flags=re.IGNORECASE)
    # Strip spaces around [dot], (dot), and replace with .
    text = re.sub(r'\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\s+dot\s+)\s*', '.', text, flags=re.IGNORECASE)
    return text


def is_valid_email(email: str) -> bool:
    """
    Strictly validates extracted email addresses and filters out garbage,
    file extensions, dummy placeholders, retina image filenames, and CDN domains.
    """
    if not email:
        return False
    # Strip whitespace and trailing punctuation marks (, . : ; " ' ) ] >)
    clean = email.strip().strip(".,;:\"')]>").lower()
    if len(clean) < 6 or len(clean) > 80:
        return False
    if clean.count("@") != 1:
        return False
    user_part, domain_part = clean.split("@")
    if not user_part or not domain_part:
        return False
    if "." not in domain_part:
        return False
    tld = domain_part.split(".")[-1]
    if len(tld) < 2 or len(tld) > 10 or not tld.isalpha():
        return False
    # Junk extensions check
    if clean.endswith(JUNK_EXTENSIONS) or tld in ("png", "jpg", "jpeg", "gif", "svg", "webp", "js", "css", "woff", "ttf", "pdf", "mp4"):
        return False
    # Filter out retina image assets like logo@2x.png or icon@3x.jpg
    if re.search(r"@\d+x\.", clean, re.I):
        return False
    # Junk domains check
    if any(junk in domain_part for junk in JUNK_DOMAINS):
        return False
    # Blacklisted placeholder usernames
    if user_part in ("user", "test", "yourname", "name", "username", "sample", "example", "admin_email"):
        return False
    return True


def extract_emails_from_page(soup: BeautifulSoup, raw_html: str) -> Set[str]:
    """
    Extracts all valid emails from a single webpage using a 7-stage detection strategy:
    1. Cloudflare data-cfemail XOR decoder
    2. Cloudflare email-protection href decoder
    3. mailto: links (with URL unquoting & multi-recipient support)
    4. JSON-LD structured data (<script type="application/ld+json">)
    5. Custom data-email HTML attributes & meta tags
    6. Deobfuscated raw HTML regex
    7. Visible soup text regex
    """
    found: Set[str] = set()

    # 1. Cloudflare data-cfemail
    for el in soup.find_all(attrs={"data-cfemail": True}):
        decoded = decode_cloudflare_email(el["data-cfemail"])
        if decoded and is_valid_email(decoded):
            found.add(decoded)

    # 2. Cloudflare href protection links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/cdn-cgi/l/email-protection#" in href:
            cf_hex = href.split("#")[-1]
            decoded = decode_cloudflare_email(cf_hex)
            if decoded and is_valid_email(decoded):
                found.add(decoded)

    # 3. mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            target = href.split(":", 1)[1].split("?")[0].strip()
            for em in re.split(r"[,;]", target):
                cleaned = unquote(em).strip().strip(".,;:\"')]>").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 4. JSON-LD structured data
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        if script.string:
            for match in EMAIL_REGEX.findall(script.string):
                cleaned = match.strip().strip(".,;:\"')]>").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 5. Attributes that frequently store emails
    for el in soup.find_all(attrs={"data-email": True}):
        em = el["data-email"].strip().strip(".,;:\"')]>").lower()
        if is_valid_email(em):
            found.add(em)

    for meta in soup.find_all("meta"):
        content = meta.get("content", "")
        if content and "@" in content:
            for match in EMAIL_REGEX.findall(content):
                cleaned = match.strip().strip(".,;:\"')]>").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 6. Deobfuscated raw HTML text
    deobfuscated_html = deobfuscate_text(raw_html)
    for match in EMAIL_REGEX.findall(deobfuscated_html):
        cleaned = match.strip().strip(".,;:\"')]>").lower()
        if is_valid_email(cleaned):
            found.add(cleaned)

    # 7. Visible soup text
    soup_text = deobfuscate_text(soup.get_text(separator=" "))
    for match in EMAIL_REGEX.findall(soup_text):
        cleaned = match.strip().strip(".,;:\"')]>").lower()
        if is_valid_email(cleaned):
            found.add(cleaned)

    return found


def extract_socials(soup: BeautifulSoup, current_socials: SocialLinks) -> SocialLinks:
    """Extracts Facebook, Instagram, LinkedIn, WhatsApp, YouTube, Twitter/X, and TikTok links."""
    socials = SocialLinks(
        facebook=current_socials.facebook,
        instagram=current_socials.instagram,
        linkedin=current_socials.linkedin,
        whatsapp=current_socials.whatsapp,
    )

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href_lower = href.lower()

        if not socials.facebook and ("facebook.com/" in href_lower or "fb.com/" in href_lower):
            if "sharer" not in href_lower and "share.php" not in href_lower:
                socials.facebook = href

        elif not socials.instagram and "instagram.com/" in href_lower:
            socials.instagram = href

        elif not socials.linkedin and "linkedin.com/" in href_lower:
            if "sharearticle" not in href_lower:
                socials.linkedin = href

        elif not socials.whatsapp and ("wa.me/" in href_lower or "api.whatsapp.com/send" in href_lower):
            socials.whatsapp = href

    return socials


def extract_phone_from_soup(soup: BeautifulSoup, country_code: str = "bd") -> Optional[str]:
    """
    Extracts business phone number from website if Google Maps phone was missing.
    Prioritizes tel: links and schema.org telephone attributes.
    """
    # 1. tel: links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            raw_phone = href.split(":", 1)[1].split("?")[0].strip()
            if raw_phone:
                return clean_phone_number(raw_phone, country_code=country_code)

    # 2. itemprop="telephone"
    el = soup.find(attrs={"itemprop": "telephone"})
    if el:
        text = el.get_text(strip=True)
        if text:
            return clean_phone_number(text, country_code=country_code)

    return None


def detect_cms(html_text: str) -> Optional[str]:
    """Detects content management systems from signatures in HTML source."""
    lower = html_text.lower()
    if "wp-content" in lower or "wp-includes" in lower:
        return "WordPress"
    elif "cdn.shopify.com" in lower or "shopify.com" in lower or "myshopify.com" in lower:
        return "Shopify"
    elif "wix.com" in lower or "_wix" in lower:
        return "Wix"
    elif "squarespace.com" in lower or "static1.squarespace.com" in lower:
        return "Squarespace"
    elif "webflow" in lower:
        return "Webflow"
    elif "joomla" in lower:
        return "Joomla"
    return None


def discover_target_pages(soup: BeautifulSoup, base_url: str, max_pages: int = 5) -> List[str]:
    """
    Discovers all target subpages to crawl for lead extraction:
    Guarantees coverage of user-requested canonical pages:
    - /contact
    - /contact-us
    - /about
    - /about-us
    PLUS any internal contact/team/location links discovered on the homepage.
    """
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    base_normalized = f"{parsed_base.scheme}://{parsed_base.netloc}".rstrip("/")

    target_queue: List[str] = []
    seen: Set[str] = {base_normalized, f"{base_normalized}/"}

    # 1. Always prioritize the canonical contact/about paths
    for path in CANONICAL_TARGETS:
        full = urljoin(base_normalized, path)
        norm = full.rstrip("/")
        if norm not in seen:
            seen.add(norm)
            target_queue.append(full)

    # 2. Discover additional internal candidate subpages from HTML links
    candidates: Dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        full_url = urljoin(base_url, href).split("#")[0].split("?")[0].rstrip("/")
        if full_url in seen:
            continue

        parsed_target = urlparse(full_url)
        target_domain = parsed_target.netloc.lower().replace("www.", "")

        # Must belong to the exact same domain
        if target_domain != base_domain and not target_domain.endswith("." + base_domain):
            continue

        if not parsed_target.path or parsed_target.path in ("/", ""):
            continue

        path_lower = parsed_target.path.lower()
        text_lower = a.get_text(strip=True).lower()
        combined = f"{path_lower} {text_lower}"

        best_score = 0
        for pattern, score in SUBPAGE_PATTERNS:
            if pattern.search(combined):
                if score > best_score:
                    best_score = score

        if best_score > 0:
            candidates[full_url] = max(candidates.get(full_url, 0), best_score)

    # Sort discovered internal links by score descending and append
    sorted_discovered = sorted(candidates.keys(), key=lambda u: candidates[u], reverse=True)
    for u in sorted_discovered:
        if u not in seen:
            seen.add(u)
            target_queue.append(u)

    # Return up to (max_pages - 1) subpages (since Homepage is already page 1)
    subpage_limit = max(1, max_pages - 1)
    return target_queue[:subpage_limit]


def fetch_html(url: str, timeout: int = WEB_TIMEOUT) -> Optional[str]:
    """
    Fetches HTML content with curl_cffi using chrome124 TLS fingerprint.
    Follows redirects, supports https -> http fallback, and unwraps Google redirects.
    """
    if not url:
        return None

    # Clean and unwrap URL
    clean_url = clean_website_url(url) or url

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    targets = [clean_url]
    if clean_url.startswith("https://"):
        targets.append(clean_url.replace("https://", "http://", 1))
    elif clean_url.startswith("http://"):
        targets.append(clean_url.replace("http://", "https://", 1))

    for target in targets:
        try:
            response = requests.get(
                target,
                impersonate=DEFAULT_IMPERSONATE,
                timeout=timeout,
                verify=False,
                allow_redirects=True,
                headers=headers,
            )
            if response.status_code == 200 and response.text:
                return response.text
        except Exception:
            continue

    return None


def enrich_single_lead(
    lead: LeadItem,
    country_code: str = "bd",
    extract_email_opt: bool = True,
    extract_social_opt: bool = True,
    detect_cms_opt: bool = True,
    max_pages: int = 5,
) -> LeadItem:
    """
    Deep-scrapes a business website across up to 5 prioritized pages:
    - Page 1: Homepage ('/')
    - Pages 2-5: '/contact', '/contact-us', '/about', '/about-us', and discovered contact pages.
    Crawls subpages concurrently using a sub-thread pool for rapid execution.
    Updates lead with extracted emails, socials, website phone, and detected CMS tech.
    """
    if lead.website_status != "Has Own Website" or not lead.website_url:
        return lead

    clean_url = clean_website_url(lead.website_url) or lead.website_url
    lead.website_url = clean_url

    # 1. Fetch Homepage (Page 1)
    html_home = fetch_html(clean_url)
    if not html_home:
        return lead

    soup_home = BeautifulSoup(html_home, "lxml")

    # Extract CMS from homepage
    if detect_cms_opt and not lead.cms_tech:
        lead.cms_tech = detect_cms(html_home)

    # Extract Socials from homepage
    if extract_social_opt:
        lead.social_links = extract_socials(soup_home, lead.social_links)

    # Extract Phone from website if missing from Google Maps
    if not lead.phone:
        lead.phone = extract_phone_from_soup(soup_home, country_code=country_code)

    # Extract Emails from homepage
    all_emails: Set[str] = set()
    if extract_email_opt:
        all_emails.update(extract_emails_from_page(soup_home, html_home))

    # 2. 5-Page Crawl: Visit /contact, /contact-us, /about, /about-us and discovered subpages
    subpage_urls = discover_target_pages(soup_home, clean_url, max_pages=max_pages)
    if subpage_urls:
        with ThreadPoolExecutor(max_workers=min(4, len(subpage_urls))) as sub_exec:
            future_to_url = {sub_exec.submit(fetch_html, u): u for u in subpage_urls}
            for fut in as_completed(future_to_url):
                try:
                    html_sub = fut.result()
                    if html_sub:
                        soup_sub = BeautifulSoup(html_sub, "lxml")
                        if extract_email_opt:
                            all_emails.update(extract_emails_from_page(soup_sub, html_sub))
                        if extract_social_opt:
                            lead.social_links = extract_socials(soup_sub, lead.social_links)
                        if not lead.phone:
                            lead.phone = extract_phone_from_soup(soup_sub, country_code=country_code)
                        if detect_cms_opt and not lead.cms_tech:
                            lead.cms_tech = detect_cms(html_sub)
                except Exception:
                    pass

    if extract_email_opt:
        lead.emails = sorted(list(all_emails))

    return lead


def enrich_leads_concurrently(
    leads: List[LeadItem],
    country_code: str = "bd",
    max_workers: int = MAX_CONCURRENT_ENRICHMENT,
    extract_email_opt: bool = True,
    extract_social_opt: bool = True,
    detect_cms_opt: bool = True,
    max_pages_per_site: int = 5,
    stop_event: Optional[Any] = None,
) -> List[LeadItem]:
    """
    Enriches multiple leads in parallel using ThreadPoolExecutor.
    Each qualified business website is crawled across:
    Homepage + /contact + /contact-us + /about + /about-us
    Leads without their own websites are skipped instantly.
    Supports graceful cancellation via stop_event.
    """
    leads_to_enrich = [l for l in leads if l.website_status == "Has Own Website" and l.website_url]
    if not leads_to_enrich:
        return leads

    lead_map = {l.place_id: l for l in leads}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pid = {}
        for lead in leads_to_enrich:
            if stop_event and stop_event.is_set():
                break
            future = executor.submit(
                enrich_single_lead,
                lead=lead,
                country_code=country_code,
                extract_email_opt=extract_email_opt,
                extract_social_opt=extract_social_opt,
                detect_cms_opt=detect_cms_opt,
                max_pages=max_pages_per_site,
            )
            future_to_pid[future] = lead.place_id

        for future in as_completed(future_to_pid):
            if stop_event and stop_event.is_set():
                break
            pid = future_to_pid[future]
            try:
                enriched_lead = future.result()
                lead_map[pid] = enriched_lead
            except Exception as e:
                print(f"[Warning] Error enriching lead {pid}: {e}")

    return [lead_map[l.place_id] for l in leads]

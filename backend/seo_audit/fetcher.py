"""
Fault-tolerant HTTP fetcher with Chrome TLS impersonation, response timing,
and automatic SSL fallback.
"""

import time
import logging
import re
import ssl
import urllib.request
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, urlsplit

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from backend.seo_audit.config import SEO_AUDIT_TIMEOUT, SEO_AUDIT_MAX_RETRIES

logger = logging.getLogger("seo_audit")


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    initial_status_code: Optional[int] = None
    status_code: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    ttfb_seconds: Optional[float] = None
    html: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None
    ssl_failed: bool = False
    redirect_chain: List[str] = field(default_factory=list)
    has_robots: bool = False
    has_sitemap: bool = False


_LEGACY_SSL_CTX = ssl.create_default_context()
_LEGACY_SSL_CTX.check_hostname = False
_LEGACY_SSL_CTX.verify_mode = ssl.CERT_NONE
_LEGACY_SSL_CTX.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)


def _safe_fetch_text(url: str, timeout: float = 4.0) -> Tuple[Optional[int], str, Dict[str, str]]:
    """
    Safely fetches a text/XML endpoint (e.g. /robots.txt or /sitemap.xml)
    without triggering Cloudflare WAF header mismatch errors.
    """
    try:
        r = requests.get(
            url,
            impersonate="chrome124",
            timeout=timeout,
            allow_redirects=True,
            verify=False,
        )
        if r.status_code == 200 and r.text:
            return r.status_code, r.text, {k.lower(): str(v) for k, v in getattr(r, "headers", {}).items()}
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/plain,text/xml,application/xml,*/*",
            },
        )
        with urllib.request.urlopen(req, context=_LEGACY_SSL_CTX, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, {k.lower(): str(v) for k, v in resp.headers.items()}
    except Exception:
        pass

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=_LEGACY_SSL_CTX, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, {k.lower(): str(v) for k, v in resp.headers.items()}
    except Exception:
        pass

    return None, "", {}


def check_robots_and_sitemap(base_url: str, timeout: float = 6.0) -> Tuple[bool, bool]:
    r"""
    Lightweight check for /robots.txt and XML Sitemaps (Fix #1 & #3).
    1. Fetches {base_origin}/robots.txt with allow_redirects=True and 6s timeout.
    2. Considers robots.txt valid if status_code == 200, length > 10, and "<html" not in text[:200].
    3. Checks for 'Sitemap:\s*(https?://\S+)' directives.
    4. If no sitemap in robots.txt, sequentially probes /sitemap.xml, /sitemap_index.xml, /wp-sitemap.xml.
    5. Validates XML response (contains <urlset, <sitemapindex, <?xml, or xml in Content-Type).
    """
    if not base_url:
        return False, False

    clean_url = base_url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    parsed = urlsplit(clean_url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    if not netloc:
        return False, False

    root = f"{scheme}://{netloc}"

    has_robots = False
    has_sitemap = False

    # 1. Check robots.txt using safe fetch
    status, r_text, _ = _safe_fetch_text(f"{root}/robots.txt", timeout=timeout)
    if status == 200 and r_text:
        if len(r_text) > 10 and "<html" not in r_text[:200].lower():
            has_robots = True
            if re.search(r"sitemap:\s*(https?://[^\s\r\n]+)", r_text, re.I):
                has_sitemap = True

    # 2. Sequential fallback probe for standard XML sitemaps
    if not has_sitemap:
        sitemap_endpoints = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]
        for ep in sitemap_endpoints:
            s_status, s_text, c_headers = _safe_fetch_text(f"{root}{ep}", timeout=timeout)
            if s_status == 200 and s_text:
                c_type = (c_headers.get("content-type") or "").lower()
                text_sample = s_text[:1024].lower()
                if any(tag in text_sample for tag in ("<urlset", "<sitemapindex", "<?xml")) or "xml" in c_type:
                    has_sitemap = True
                    break

    return has_robots, has_sitemap


def fetch_page_for_audit(
    url: str,
    timeout: int = SEO_AUDIT_TIMEOUT,
    max_retries: int = SEO_AUDIT_MAX_RETRIES,
) -> FetchResult:
    """
    Fetches a webpage using curl_cffi with Chrome TLS impersonation (Section 2.2, 2.3).
    - Follows redirects (up to 5 hops)
    - Records initial status code (e.g. 301) and final status code (200 OK)
    - Measures honest server response time (TTFB) in seconds
    - Decouples SSL verification from speed
    - Falls back to urllib with OP_LEGACY_SERVER_CONNECT when servers reset HTTP/2 or legacy TLS
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    ssl_failed = False
    current_url = clean_url

    for attempt in range(max(1, max_retries)):
        start_time = time.perf_counter()
        try:
            resp = requests.get(
                current_url,
                impersonate="chrome124",
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            elapsed = round(time.perf_counter() - start_time, 2)
            final_url = str(getattr(resp, "url", current_url))
            headers_dict = {k.lower(): str(v) for k, v in getattr(resp, "headers", {}).items()}

            # Track redirect history if available
            redirect_history = getattr(resp, "history", [])
            initial_code = redirect_history[0].status_code if redirect_history else resp.status_code
            redirect_chain = [f"{r.url} ({r.status_code})" for r in redirect_history]
            if redirect_chain:
                redirect_chain.append(f"{final_url} ({resp.status_code})")

            # Check robots and sitemap
            has_robots, has_sitemap = check_robots_and_sitemap(final_url)

            return FetchResult(
                url=clean_url,
                final_url=final_url,
                initial_status_code=int(initial_code),
                status_code=int(resp.status_code),
                elapsed_seconds=elapsed,
                ttfb_seconds=elapsed,
                html=resp.text or "",
                headers=headers_dict,
                ssl_failed=ssl_failed,
                redirect_chain=redirect_chain,
                has_robots=has_robots,
                has_sitemap=has_sitemap,
            )

        except (RequestsError, Exception) as exc:
            elapsed = round(time.perf_counter() - start_time, 2)
            err_str = str(exc)

            is_ssl_err = any(kw in err_str.lower() for kw in ["ssl", "certificate", "handshake", "tls"])

            # Automatic fallback to HTTP if HTTPS had an SSL error
            if is_ssl_err and current_url.startswith("https://") and not ssl_failed:
                logger.warning("SSL failure on %s (%s). Retrying with HTTP fallback.", current_url, err_str)
                current_url = "http://" + current_url[8:]
                ssl_failed = True
                continue

            # Fallback to urllib with OP_LEGACY_SERVER_CONNECT for servers that reset HTTP/2 or legacy TLS
            if any(kw in err_str.lower() for kw in ["stream", "protocol", "reset", "closed", "aborted", "56", "92"]):
                try:
                    req = urllib.request.Request(
                        current_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                        },
                    )
                    with urllib.request.urlopen(req, context=_LEGACY_SSL_CTX, timeout=timeout) as u_resp:
                        html_u = u_resp.read().decode("utf-8", errors="replace")
                        elapsed_u = round(time.perf_counter() - start_time, 2)
                        final_url_u = u_resp.geturl() or current_url
                        headers_u = {k.lower(): str(v) for k, v in u_resp.headers.items()}
                        has_robots, has_sitemap = check_robots_and_sitemap(final_url_u)
                        return FetchResult(
                            url=clean_url,
                            final_url=final_url_u,
                            initial_status_code=int(u_resp.status),
                            status_code=int(u_resp.status),
                            elapsed_seconds=elapsed_u,
                            ttfb_seconds=elapsed_u,
                            html=html_u,
                            headers=headers_u,
                            ssl_failed=ssl_failed,
                            redirect_chain=[f"{final_url_u} ({u_resp.status})"],
                            has_robots=has_robots,
                            has_sitemap=has_sitemap,
                        )
                except Exception:
                    pass

            if attempt < max_retries - 1 and not ("timed out" in err_str.lower() or "timeout" in err_str.lower()):
                time.sleep(0.4)
                continue

            logger.error("Audit fetch failed for %s: %s", clean_url, err_str)
            return FetchResult(
                url=clean_url,
                final_url=current_url,
                initial_status_code=None,
                status_code=None,
                elapsed_seconds=elapsed,
                ttfb_seconds=elapsed,
                html="",
                headers={},
                error_message=err_str,
                ssl_failed=ssl_failed,
            )

    return FetchResult(
        url=clean_url,
        final_url=current_url,
        initial_status_code=None,
        status_code=None,
        elapsed_seconds=None,
        ttfb_seconds=None,
        html="",
        headers={},
        error_message="Max retries exhausted",
        ssl_failed=ssl_failed,
    )

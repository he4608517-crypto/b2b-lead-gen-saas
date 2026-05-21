"""
Lead Scraper Service — live web search + email harvesting for B2B lead generation.

Uses Bing organic search (no API key) for company discovery across any region,
then visits each live website to harvest real email addresses from the HTML.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(
    r"(?:mailto:)?([a-zA-Z0-9][a-zA-Z0-9._%+\-]{0,63}@[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}\.[a-zA-Z]{2,})",
)


@dataclass
class CompanyLead:
    """Standardised lead record produced by every data source."""

    company_name: str
    website_url: str
    country: str
    raw_description: str
    source: str = ""
    source_rank: int = 0

    @property
    def dedup_key(self) -> str:
        raw = f"{self.company_name}|{self.website_url}".lower().strip()
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Real web search — Bing organic (free, no API key required)
# ---------------------------------------------------------------------------

_BING_SEARCH_URL = "https://www.bing.com/search"

# Market code lookup for region-specific results
_REGION_MARKET = {
    "germany": "de-DE", "de": "de-DE",
    "us": "en-US", "usa": "en-US", "united states": "en-US", "america": "en-US",
    "uk": "en-GB", "united kingdom": "en-GB", "england": "en-GB",
    "china": "zh-CN", "cn": "zh-CN",
    "japan": "ja-JP", "jp": "ja-JP",
    "france": "fr-FR", "fr": "fr-FR",
    "italy": "it-IT", "it": "it-IT",
    "india": "en-IN", "in": "en-IN",
    "canada": "en-CA", "ca": "en-CA",
    "australia": "en-AU", "au": "en-AU",
    "brazil": "pt-BR", "br": "pt-BR",
    "korea": "ko-KR", "kr": "ko-KR",
    "spain": "es-ES", "es": "es-ES",
    "netherlands": "nl-NL", "nl": "nl-NL",
    "taiwan": "zh-TW", "tw": "zh-TW",
}


def _region_market(region: str) -> str:
    r = region.lower().strip()
    for k, v in _REGION_MARKET.items():
        if k in r:
            return v
    return "en-US"


# Shared session with browser-like headers to avoid bot detection
_search_session: requests.Session | None = None


def _get_search_session() -> requests.Session:
    global _search_session
    if _search_session is None:
        _search_session = requests.Session()
        _search_session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        })
        # Prime the session with a homepage visit to get cookies
        try:
            _search_session.get("https://www.bing.com/", timeout=10)
        except Exception:
            pass
    return _search_session


def _extract_real_url(bing_href: str) -> str:
    """Decode the base64 'u' parameter from Bing tracking redirect URLs."""
    import base64 as _b64
    from urllib.parse import parse_qs, urlparse

    if "bing.com/ck/" in bing_href:
        try:
            qs = parse_qs(urlparse(bing_href).query)
            u_param = qs.get("u", [""])[0]
            if u_param:
                # Base64 padding: add the right number of = chars
                missing = len(u_param) % 4
                pad = (4 - missing) % 4
                return _b64.urlsafe_b64decode(u_param + "=" * pad).decode("utf-8", errors="replace")
        except Exception:
            pass
    return bing_href


def _extract_ddg_url(href: str) -> str:
    """Extract the real destination URL from a DuckDuckGo redirect link."""
    from urllib.parse import parse_qs, unquote

    # DDG ad links: duckduckgo.com/y.js?ad_domain=example.com&...
    if "ad_domain=" in href:
        try:
            idx = href.index("ad_domain=") + 10
            domain = href[idx:].split("&")[0]
            domain = unquote(domain)
            return f"https://{domain}"
        except Exception:
            pass

    # DDG organic result links with uddg= parameter
    if "uddg=" in href:
        try:
            idx = href.index("uddg=") + 5
            raw = href[idx:].split("&")[0]
            return unquote(raw)
        except Exception:
            pass

    # Protocol-relative URLs
    if href.startswith("//"):
        return "https:" + href
    return href


def _search_web(keyword: str, region: str, max_results: int) -> list[dict]:
    """
    Search for companies matching *keyword* in *region*.
    Primary: DuckDuckGo HTML (best results, no bot detection).
    Fallback: Bing organic search.
    """
    query = f"{keyword} company {region}"
    results: list[dict] = []

    _NON_COMPANY = (
        "wikipedia", "youtube", "amazon", "ebay", "definition",
        "merriam-webster", "dictionary", "britannica", "wiki",
        "imdb", "facebook.com", "twitter.com", "instagram.com",
        "pinterest", "reddit", "quora",
    )

    # --- Strategy 1: DuckDuckGo HTML (primary — best B2B results) ---
    try:
        ddg_resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36",
            },
            timeout=20,
        )
        soup = BeautifulSoup(ddg_resp.text, "html.parser")
        for item in soup.select(".result"):
            title_el = item.select_one(".result__title a, .result__a")
            snippet_el = item.select_one(".result__snippet")
            if title_el and title_el.get("href"):
                title = title_el.get_text(strip=True)
                href = title_el["href"]
                if len(title) < 3:
                    continue
                if any(kw in title.lower() for kw in _NON_COMPANY):
                    continue

                real_url = _extract_ddg_url(href)
                results.append({
                    "title": title,
                    "url": real_url,
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
            if len(results) >= max_results:
                break

        if results:
            logger.info("DuckDuckGo returned %d results", len(results))
            return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s — trying Bing fallback", exc)

    # --- Strategy 2: Bing fallback ---
    try:
        session = _get_search_session()
        market = _region_market(region)
        resp = session.get(
            _BING_SEARCH_URL,
            params={"q": query, "setmkt": market, "count": min(max_results, 15)},
            timeout=25,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("li.b_algo"):
            title_el = item.select_one("h2 a")
            snippet_el = item.select_one(".b_caption p, .b_lineclamp2, .b_algoSlug")
            if title_el and title_el.get("href"):
                title = title_el.get_text(strip=True)
                if len(title) < 3:
                    continue
                if any(kw in title.lower() for kw in _NON_COMPANY):
                    continue
                real_url = _extract_real_url(title_el["href"])
                results.append({
                    "title": title,
                    "url": real_url,
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
            if len(results) >= max_results:
                break
        if results:
            logger.info("Bing returned %d results (fallback)", len(results))
    except Exception as exc2:
        logger.warning("Bing fallback also failed: %s", exc2)

    return results


# ---------------------------------------------------------------------------
# Email harvesting from live company websites
# ---------------------------------------------------------------------------

# Common paths where contact emails are often listed
_CONTACT_PATHS = ["", "/contact"]


def _clean_url(url: str) -> str:
    """Normalise a URL to a root domain."""
    p = urlparse(url if "://" in url else f"https://{url}")
    scheme = p.scheme if p.scheme else "https"
    return f"{scheme}://{p.netloc}"


def _extract_emails_from_html(html: str, domain: str) -> set[str]:
    """Extract real-looking email addresses from HTML text."""
    found: set[str] = set()
    for m in EMAIL_RE.finditer(html):
        email = m.group(1).lower().strip().rstrip(".")
        # Skip if it starts with http (URL fragment, not real email)
        if email.startswith(("http:", "https:", "//")):
            continue
        # Skip image/programming artifacts and generic placeholders
        if email.endswith((".png", ".jpg", ".gif", ".svg", ".js", ".css", ".ico", ".woff")):
            continue
        if any(x in email for x in ("example.com", "domain.com", "email.com", "@localhost", "@127.", "test@")):
            continue
        if len(email) < 80:
            found.add(email)
    return found


def _harvest_emails(domain: str, timeout: int = 5) -> list[str]:
    """
    Visit a company's website and extract email addresses from
    the homepage and common contact pages.
    """
    root = _clean_url(domain)
    all_emails: set[str] = set()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for path in _CONTACT_PATHS:
        try:
            url = f"{root}{path}"
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if resp.status_code not in (200, 201):
                continue

            # Extract emails from raw HTML
            emails_from_text = _extract_emails_from_html(resp.text, domain)
            all_emails.update(emails_from_text)

            # Also extract mailto: links from parsed HTML
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("mailto:"):
                        email = href[7:].split("?")[0].strip().lower()
                        if "@" in email and "." in email.split("@")[-1]:
                            all_emails.add(email)
            except Exception:
                pass

        except (requests.ConnectionError, requests.Timeout):
            continue
        except Exception:
            continue

    # Deduplicate and sort (domain-matching emails first, then others)
    domain_part = domain.lower().replace("www.", "").split("/")[0]
    results = sorted(all_emails, key=lambda e: (0 if domain_part in e else 1, e))
    return results[:5]


# ---------------------------------------------------------------------------
# Unified scraper / aggregator
# ---------------------------------------------------------------------------


class LeadAggregator:
    """Live web search → email harvest → standardised leads."""

    def __init__(self) -> None:
        self._session = requests.Session()

    def scrape(
        self,
        keyword: str,
        region: str,
        sources: tuple[str, ...] = ("bing",),
        max_per_source: int = 15,
        progress_cb = None,
    ) -> list[CompanyLead]:
        """
        Search the web for companies matching *keyword* in *region*,
        then visit each website to harvest real contact emails.
        """
        logger.info("LeadAggregator.scrape(keyword=%r, region=%r)", keyword, region)

        # Stage 1 — Live search
        raw_results = _search_web(keyword, region, max_per_source)
        logger.info("Bing search returned %d results", len(raw_results))

        if not raw_results:
            logger.warning("No search results — check network or try a different keyword/region.")
            return []

        if progress_cb:
            progress_cb(18)

        # Stage 2 — Build leads, deduplicate by domain
        leads: list[CompanyLead] = []
        seen_domains: set[str] = set()

        for idx, r in enumerate(raw_results):
            url = r.get("url", "")
            if not url:
                continue

            domain = urlparse(url if "://" in url else f"https://{url}").netloc
            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)

            leads.append(CompanyLead(
                company_name=r.get("title", "")[:255],
                website_url=url,
                country=region[:128],
                raw_description=r.get("snippet", ""),
                source="bing_search",
                source_rank=idx + 1,
            ))

        # Stage 3 — Email harvesting (throttled)
        total_leads = len(leads)
        logger.info("Harvesting emails from %d domains …", total_leads)
        for i, lead in enumerate(leads):
            try:
                domain = urlparse(lead.website_url if "://" in lead.website_url else f"https://{lead.website_url}").netloc
                emails = _harvest_emails(domain)
                lead.contact_email = emails[0] if emails else ""
                logger.info(
                    "[%d/%d] %s → %d email(s)",
                    i + 1, total_leads, domain, len(emails),
                )
            except Exception:
                logger.debug("Email harvest failed for %s", lead.website_url)
            # Polite crawl delay
            time.sleep(random.uniform(0.3, 1.0))
            if progress_cb and total_leads > 0:
                progress_cb(18 + int((i + 1) / total_leads * 10))

        # Filter to leads that have at least a domain
        leads = [l for l in leads if l.website_url]
        leads.sort(key=lambda l: l.source_rank)
        logger.info("Scrape complete: %d leads with domains", len(leads))
        return leads


# ---------------------------------------------------------------------------
# Convenience factory (preserves API compatibility with main.py / app.py)
# ---------------------------------------------------------------------------


def create_aggregator(
    google_api_key: str = "",
    google_cse_id: str = "",
    linkedin_token: str = "",
    apollo_key: str = "",
) -> LeadAggregator:
    """Create a LeadAggregator. Extra kwargs kept for backward compatibility."""
    return LeadAggregator()

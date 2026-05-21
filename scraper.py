"""
Lead Scraper Service — unified aggregator for B2B lead generation.

Data Sources (mock skeletons):
  - Google Search API
  - LinkedIn Sales Navigator API
  - Apollo.io API

Outputs a standardized list of companies with:
  company_name, website_url, country, raw_description
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class CompanyLead:
    """Standardised lead record produced by every data source."""

    company_name: str
    website_url: str
    country: str
    raw_description: str
    source: str = ""  # e.g. "google_search", "linkedin", "apollo"
    source_rank: int = 0  # position in the original result list

    @property
    def dedup_key(self) -> str:
        """Deterministic key for cross-source deduplication."""
        raw = f"{self.company_name}|{self.website_url}".lower().strip()
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Keyword-aware mock company generator (shared by all mock APIs)
# ---------------------------------------------------------------------------

# Industry signals injected into mock descriptions based on keyword context
_TARGET_SIGNALS = [
    "with in-house R&D and custom engineering capabilities",
    "ISO 9001 certified manufacturer offering OEM/ODM partnerships",
    "vertically integrated production with global export network",
    "specialised in bespoke client solutions and private-label manufacturing",
    "patented technology with dedicated engineering support team",
]
_NON_TARGET_SIGNALS = [
    "Authorised reseller and distributor; does NOT manufacture",
    "Regional repair shop and maintenance service provider — purely service",
    "General trading company that sometimes ships used equipment — no OEM",
    "Local end-user facility; does NOT purchase or source at OEM scale",
]

# Region → primary country mapping
_REGION_COUNTRY = {
    "germany": "DE", "deutschland": "DE",
    "us": "US", "usa": "US", "united states": "US", "america": "US",
    "china": "CN", "uk": "UK", "united kingdom": "UK", "england": "UK",
    "japan": "JP", "india": "IN", "italy": "IT", "france": "FR",
    "brazil": "BR", "korea": "KR", "taiwan": "TW", "canada": "CA",
    "australia": "AU", "spain": "ES", "netherlands": "NL",
}


def _resolve_country(region: str) -> str:
    r = region.strip().lower()
    for key, cc in _REGION_COUNTRY.items():
        if key in r:
            return cc
    return r[:2].upper()


# Words that, if they appear in the keyword, shouldn't poison target descriptions
_NEGATIVE_SIGNAL_WORDS = {
    "distributor", "reseller", "dealer", "repair", "broker", "trader",
    "wholesaler", "retailer", "importer", "exporter",
}


def _clean_keyword(keyword: str) -> str:
    """Extract the core industry/product words, dropping negative-signal fluff."""
    words = [
        w for w in keyword.lower().replace(",", " ").split()
        if w not in ("the", "a", "an", "and", "or", "of", "in", "for", "with")
    ]
    if not words:
        return "industrial"
    # Use the first non-negative word as the primary, or fall back to the first word
    product_words = [w for w in words if w not in _NEGATIVE_SIGNAL_WORDS]
    return " ".join(product_words) if product_words else words[0]


def _generate_mock_companies(
    keyword: str, region: str, num: int, source: str
) -> list[CompanyLead]:
    """Build a diverse mock lead list that visibly responds to the keyword."""
    clean_kw = _clean_keyword(keyword)
    raw_kw = keyword.strip()

    words = [
        w for w in clean_kw.split()
        if w not in ("the", "a", "an", "and", "or", "of", "in", "for", "with")
    ]
    if not words:
        words = ["industrial"]
    main_word = random.choice(words).title()

    prefixes = ["Global", "Advanced", "Precision", "Elite", "Prime", "Apex", "Vertex", "Atlas"]
    geo_prefixes = ["Shanghai", "Shenzhen", "Mumbai", "Berlin", "London", "Chicago", "Tokyo", "Seoul"]
    suffixes = ["Industries", "Solutions", "Systems", "Technologies", "Group", "Enterprises", "Corp"]

    country = _resolve_country(region)
    leads: list[CompanyLead] = []

    for i in range(num):
        is_target = random.random() < 0.6

        if random.random() < 0.25:
            name = f"{random.choice(geo_prefixes)} {main_word} {random.choice(suffixes)}"
        elif random.random() < 0.5:
            name = f"{random.choice(prefixes)} {main_word} {random.choice(suffixes)}"
        else:
            name = f"{main_word} {random.choice(suffixes)}"

        slug = name.lower().replace(" ", "").replace(",", "")[:20]
        url = f"www.{slug}{random.choice(['.com', '.co', '.io'])}"

        if is_target:
            # Use CLEAN keyword (no "distributor" etc.) in target descriptions
            desc = (
                f"Established {clean_kw} manufacturer and OEM supplier. "
                f"{random.choice(_TARGET_SIGNALS)}. "
                f"Serves major industrial accounts across {region.strip()}."
            )
        else:
            # Use the RAW keyword (may include "distributor") in non-target descriptions
            desc = (
                f"{random.choice(_NON_TARGET_SIGNALS)} of {raw_kw} equipment. "
                f"Operates locally within {region.strip()}."
            )

        leads.append(CompanyLead(
            company_name=name,
            website_url=url,
            country=country,
            raw_description=desc,
            source=source,
            source_rank=i + 1,
        ))

    # Deduplicate by company name (random generation can produce collisions)
    seen: set[str] = set()
    unique: list[CompanyLead] = []
    for ld in leads:
        if ld.company_name.lower() not in seen:
            seen.add(ld.company_name.lower())
            unique.append(ld)
    for idx, ld in enumerate(unique):
        ld.source_rank = idx + 1
    return unique


# ---------------------------------------------------------------------------
# Mock API structures
# ---------------------------------------------------------------------------

class GoogleSearchAPI:
    """
    Mock skeleton for the Google Custom Search / Places API.

    In production this would call:
      https://www.googleapis.com/customsearch/v1
    or the Places API with a valid API key and CSE id.
    """

    BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str = "", cse_id: str = "") -> None:
        self.api_key = api_key or "MOCK_GOOGLE_API_KEY"
        self.cse_id = cse_id or "MOCK_GOOGLE_CSE_ID"
        self._session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def search(self, keyword: str, region: str, num: int = 10) -> list[CompanyLead]:
        """
        Search for companies matching *keyword* in *region*.

        Returns a list of CompanyLead objects (mock data in this skeleton).
        """
        logger.info("GoogleSearchAPI.search(keyword=%r, region=%r, num=%d)", keyword, region, num)

        # --- Production path: actual HTTP call ---
        if self.api_key != "MOCK_GOOGLE_API_KEY":
            params = {
                "key": self.api_key,
                "cx": self.cse_id,
                "q": f"{keyword} {region}",
                "num": min(num, 10),
            }
            resp = self._session.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            return self._parse_response(resp.json(), keyword, region)

        # --- Mock path for development / testing ---
        return self._mock_results(keyword, region, num)

    # ------------------------------------------------------------------
    # Mock data
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_results(keyword: str, region: str, num: int) -> list[CompanyLead]:
        time.sleep(random.uniform(0.05, 0.2))
        return _generate_mock_companies(keyword, region, num, "google_search")

    @staticmethod
    def _parse_response(data: dict, keyword: str, region: str) -> list[CompanyLead]:
        """Parse a real Google CSE JSON response into CompanyLead objects."""
        leads: list[CompanyLead] = []
        for idx, item in enumerate(data.get("items", [])):
            leads.append(CompanyLead(
                company_name=item.get("title", ""),
                website_url=item.get("link", ""),
                country=region,  # Google CSE does not reliably return country
                raw_description=item.get("snippet", ""),
                source="google_search",
                source_rank=idx + 1,
            ))
        return leads


class LinkedInAPI:
    """
    Mock skeleton for LinkedIn Sales Navigator / Company Search API.

    In production this would use the LinkedIn Marketing / Sales Navigator API
    with OAuth 2.0 access tokens.
    """

    BASE_URL = "https://api.linkedin.com/v2"

    def __init__(self, access_token: str = "") -> None:
        self.access_token = access_token or "MOCK_LINKEDIN_TOKEN"
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def search_companies(self, keyword: str, region: str, limit: int = 10) -> list[CompanyLead]:
        """
        Search for companies on LinkedIn matching *keyword* in *region*.
        """
        logger.info("LinkedInAPI.search_companies(keyword=%r, region=%r, limit=%d)", keyword, region, limit)

        if self.access_token != "MOCK_LINKEDIN_TOKEN":
            # Production: POST /v2/search with company search query
            # resp = self._session.post(f"{self.BASE_URL}/search", json=payload, timeout=15)
            # resp.raise_for_status()
            # return self._parse_response(resp.json())
            pass

        return self._mock_results(keyword, region, limit)

    @staticmethod
    def _mock_results(keyword: str, region: str, limit: int) -> list[CompanyLead]:
        time.sleep(random.uniform(0.05, 0.2))
        return _generate_mock_companies(keyword, region, limit, "linkedin")


class ApolloAPI:
    """
    Mock skeleton for Apollo.io People & Company Search API.

    In production this would use https://api.apollo.io/v1/ endpoints
    with an Apollo API key.
    """

    BASE_URL = "https://api.apollo.io/v1"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or "MOCK_APOLLO_KEY"
        self._session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def search_organizations(self, keyword: str, region: str, page: int = 1, per_page: int = 10) -> list[CompanyLead]:
        """
        Search Apollo's organisation database for companies matching *keyword* in *region*.
        """
        logger.info("ApolloAPI.search_organizations(keyword=%r, region=%r, page=%d)", keyword, region, page)

        if self.api_key != "MOCK_APOLLO_KEY":
            params = {
                "api_key": self.api_key,
                "q_organization_name": keyword,
                "organization_locations": [region],
                "page": page,
                "per_page": per_page,
            }
            resp = self._session.post(
                f"{self.BASE_URL}/mixed_companies/search",
                json=params,
                timeout=20,
            )
            resp.raise_for_status()
            return self._parse_response(resp.json())

        return self._mock_results(keyword, region, per_page)

    @staticmethod
    def _mock_results(keyword: str, region: str, per_page: int) -> list[CompanyLead]:
        time.sleep(random.uniform(0.05, 0.2))
        return _generate_mock_companies(keyword, region, per_page, "apollo")

    @staticmethod
    def _parse_response(data: dict) -> list[CompanyLead]:
        leads: list[CompanyLead] = []
        for idx, org in enumerate(data.get("organizations", [])):
            leads.append(CompanyLead(
                company_name=org.get("name", ""),
                website_url=org.get("website_url", ""),
                country=org.get("country", ""),
                raw_description=org.get("short_description", ""),
                source="apollo",
                source_rank=idx + 1,
            ))
        return leads


# ---------------------------------------------------------------------------
# Unified scraper / aggregator
# ---------------------------------------------------------------------------

class LeadAggregator:
    """
    Orchestrates all data sources, normalises results, and deduplicates.
    """

    def __init__(
        self,
        google: Optional[GoogleSearchAPI] = None,
        linkedin: Optional[LinkedInAPI] = None,
        apollo: Optional[ApolloAPI] = None,
    ) -> None:
        self.google = google
        self.linkedin = linkedin
        self.apollo = apollo

    def scrape(
        self,
        keyword: str,
        region: str,
        sources: tuple[str, ...] = ("google", "linkedin", "apollo"),
        max_per_source: int = 10,
    ) -> list[CompanyLead]:
        """
        Run all enabled sources, collect leads, and remove duplicates
        (keeping the highest-ranked entry for each company).
        """
        logger.info(
            "LeadAggregator.scrape(keyword=%r, region=%r, sources=%s)",
            keyword, region, sources,
        )
        all_leads: list[CompanyLead] = []

        if "google" in sources and self.google:
            all_leads.extend(self.google.search(keyword, region, num=max_per_source))
        if "linkedin" in sources and self.linkedin:
            all_leads.extend(self.linkedin.search_companies(keyword, region, limit=max_per_source))
        if "apollo" in sources and self.apollo:
            all_leads.extend(self.apollo.search_organizations(keyword, region, per_page=max_per_source))

        return self._deduplicate(all_leads)

    @staticmethod
    def _deduplicate(leads: list[CompanyLead]) -> list[CompanyLead]:
        seen: dict[str, CompanyLead] = {}
        for lead in leads:
            key = lead.dedup_key
            if key not in seen or lead.source_rank < seen[key].source_rank:
                seen[key] = lead
        deduped = sorted(seen.values(), key=lambda c: c.source_rank)
        logger.info("Deduplicated %d leads → %d unique", len(leads), len(deduped))
        return deduped


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_aggregator(
    google_api_key: str = "",
    google_cse_id: str = "",
    linkedin_token: str = "",
    apollo_key: str = "",
) -> LeadAggregator:
    """Create a LeadAggregator with real or mock API clients."""
    return LeadAggregator(
        google=GoogleSearchAPI(api_key=google_api_key, cse_id=google_cse_id),
        linkedin=LinkedInAPI(access_token=linkedin_token),
        apollo=ApolloAPI(api_key=apollo_key),
    )

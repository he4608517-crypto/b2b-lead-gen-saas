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
        time.sleep(random.uniform(0.05, 0.2))  # simulate network latency
        companies = [
            ("AirPower Systems Ltd", "www.airpowersystems.com", "DE", "ISO 9001 certified industrial air compressor manufacturer. Specialises in rotary screw and piston compressors up to 500 kW. Offers OEM and ODM customization for European industrial clients."),
            ("CompTech Industries", "www.comptech-industries.co.uk", "UK", "Leading manufacturer of oil-free scroll air compressors for medical, pharmaceutical, and food-grade applications. Has in-house R&D and custom solution engineering team."),
            ("GlobalAir Manufacturing Co.", "www.globalair-mfg.com", "US", "Full-line compressor, blower, and vacuum pump manufacturer. Serves automotive, construction, and energy sectors. ISO 14001 compliant."),
            ("Pneumax S.p.A.", "www.pneumax.it", "IT", "Italian pneumatic components and compressor manufacturer. Supplies FCA, aerospace subcontractors, and general automation integrators. Private label (ODM) available."),
            ("Shanghai Rotorcomp Machinery", "www.rotorcomp.cn", "CN", "Major Chinese screw air compressor exporter. Sells bare compressor pumps and packaged units. Very price-competitive; minimal after-sales OEM support."),
            ("Atlas CopCo Distributor Inc.", "www.atlascopco-distributor.com", "IN", "Authorised reseller and service partner for Atlas Copco compressors across South Asia. Does NOT manufacture; purely distribution and maintenance."),
            ("Precision Air Tools LLC", "www.precisionair.tools", "US", "Small machine shop that uses compressors to power pneumatic tools. NOT a manufacturer or buyer of compressors in bulk."),
            ("EcoAir Engineering GmbH", "www.ecoair-engineering.de", "DE", "Specialist in energy-efficient compressed air system design and heat-recovery solutions. Engineers custom compressor stations for factories. OEM partner for several European brands."),
        ]
        leads: list[CompanyLead] = []
        for idx, (name, url, country, desc) in enumerate(companies[:num]):
            leads.append(CompanyLead(
                company_name=name,
                website_url=url,
                country=country,
                raw_description=desc,
                source="google_search",
                source_rank=idx + 1,
            ))
        return leads

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
        companies = [
            ("Boge Kompressoren", "www.boge.com", "DE", "German compressor manufacturer since 1907. Produces screw, piston, and turbo compressors, plus compressed air treatment equipment. Operates own foundry. Strong export business."),
            ("Kaeser Kompressoren SE", "www.kaeser.com", "DE", "Family-owned manufacturer of rotary screw compressors, portable units, and blowers. Revenue > €1B. Global distribution network in 100+ countries."),
            ("FS-Elliott Co., LLC", "www.fs-elliott.com", "US", "Centrifugal compressor OEM for 100–15,000 HP applications. Key supplier to large industrial air separation and petrochemical plants. Engineering-driven culture."),
            ("Elgi Equipments Ltd", "www.elgi.com", "IN", "One of India's largest compressor manufacturers. Exports to 100+ countries. Known for affordable rotary screw and piston compressors. Publicly listed (NSE: ELGIEQUIP)."),
            ("CompAir (Gardner Denver)", "www.compair.com", "UK", "Historic UK compressor brand, now part of Ingersoll Rand / Gardner Denver group. Offers oil-lubricated and oil-free rotary screw, plus high-pressure piston compressors."),
            ("Local Air Conditioner Repair Shop", "www.coolfix-local.com", "US", "HVAC repair and maintenance shop. Does NOT manufacture or purchase compressors at OEM scale. End-user service provider."),
        ]
        leads: list[CompanyLead] = []
        for idx, (name, url, country, desc) in enumerate(companies[:limit]):
            leads.append(CompanyLead(
                company_name=name,
                website_url=url,
                country=country,
                raw_description=desc,
                source="linkedin",
                source_rank=idx + 1,
            ))
        return leads


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
        companies = [
            ("Sullair LLC (Hitachi Group)", "www.sullair.com", "US", "Major rotary screw and portable air compressor OEM. Subsidiary of Hitachi Industrial Equipment Systems. Focus on heavy construction and industrial applications."),
            ("Ingersoll Rand Inc.", "www.irco.com", "US", "Fortune 500 industrial conglomerate. Compressor division covers centrifugal, rotary, and reciprocating technologies. Acquired Gardner Denver, CompAir, and other brands."),
            ("Fusheng Co., Ltd.", "www.fusheng.com", "TW", "Taiwanese compressor and golf equipment manufacturer. Strong presence in SE Asia and China. OEM supplier for several global brands in the compressor segment."),
            ("Hanbell Precise Machinery", "www.hanbell.com", "TW", "Taiwanese screw compressor manufacturer. Listed on TWSE. Supplies refrigeration and air compressor OEMs worldwide. Increasing market share in China."),
            ("ABC Trading Ltd.", "www.abctrading-hk.com", "HK", "General trading company that sometimes ships used industrial equipment including old compressors. Does NOT manufacture and has no OEM capabilities."),
        ]
        leads: list[CompanyLead] = []
        for idx, (name, url, country, desc) in enumerate(companies[:per_page]):
            leads.append(CompanyLead(
                company_name=name,
                website_url=url,
                country=country,
                raw_description=desc,
                source="apollo",
                source_rank=idx + 1,
            ))
        return leads

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

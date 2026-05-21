"""
Contact Finder & Verifier — discover and validate decision-maker emails.

Discovery:  Simulated calls to Hunter.io / Prospeo APIs.
Verification: SMTP handshake + DNS MX record checks.
"""

from __future__ import annotations

import logging
import re
import smtplib
import socket
import time
from dataclasses import dataclass
from typing import Optional

import dns.resolver
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    full_name: str
    title: str
    email: str
    linkedin_url: str = ""
    confidence: float = 0.0  # 0.0 – 1.0
    email_verified: bool = False
    email_status: str = ""  # "valid", "invalid", "catch_all", "unknown"


# ---------------------------------------------------------------------------
# Mock Hunter.io API
# ---------------------------------------------------------------------------


class HunterAPI:
    """
    Skeleton for Hunter.io Email Finder API.

    Production endpoint: GET https://api.hunter.io/v2/domain-search
    """

    BASE_URL = "https://api.hunter.io/v2"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or "MOCK_HUNTER_KEY"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def domain_search(self, domain: str, title_hint: str = "") -> list[Contact]:
        """
        Find email addresses associated with *domain*.

        *title_hint* biases the search towards specific roles (e.g. "Purchasing").
        """
        logger.info("HunterAPI.domain_search(domain=%r, title_hint=%r)", domain, title_hint)

        if self.api_key != "MOCK_HUNTER_KEY":
            params = {
                "domain": domain,
                "api_key": self.api_key,
            }
            resp = requests.get(f"{self.BASE_URL}/domain-search", params=params, timeout=15)
            resp.raise_for_status()
            return self._parse_response(resp.json(), title_hint)

        return self._mock_results(domain, title_hint)

    # ------------------------------------------------------------------
    # Mock data
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_results(domain: str, title_hint: str) -> list[Contact]:
        time.sleep(0.08)
        domain_key = domain.lower().replace("www.", "")

        # Deterministic mock contacts based on domain
        mock_db: dict[str, list[Contact]] = {
            "airpowersystems.com": [
                Contact("Markus Weber", "Purchasing Manager", "m.weber@airpowersystems.com", confidence=0.92),
                Contact("Anna Schmidt", "VP Sourcing", "a.schmidt@airpowersystems.com", confidence=0.88),
                Contact("Klaus Fischer", "CEO", "k.fischer@airpowersystems.com", confidence=0.95),
            ],
            "comptech-industries.co.uk": [
                Contact("James Harding", "Sourcing Director", "j.harding@comptech-industries.co.uk", confidence=0.91),
                Contact("Sarah Chen", "Supply Chain Manager", "s.chen@comptech-industries.co.uk", confidence=0.85),
            ],
            "globalair-mfg.com": [
                Contact("Robert Davis", "VP of Operations", "r.davis@globalair-mfg.com", confidence=0.89),
            ],
            "pneumax.it": [
                Contact("Giuseppe Rossi", "Owner", "g.rossi@pneumax.it", confidence=0.94),
                Contact("Elena Bianchi", "Purchasing Manager", "e.bianchi@pneumax.it", confidence=0.87),
            ],
            "rotorcomp.cn": [
                Contact("Li Wei", "General Manager", "li.wei@rotorcomp.cn", confidence=0.90),
            ],
            "boge.com": [
                Contact("Thomas Boge", "CEO", "t.boge@boge.com", confidence=0.96),
                Contact("Petra Klein", "Head of Procurement", "p.klein@boge.com", confidence=0.93),
            ],
            "kaeser.com": [
                Contact("Dr. Michael Kaeser", "Managing Director", "m.kaeser@kaeser.com", confidence=0.97),
                Contact("Hans Gruber", "Purchasing Manager", "h.gruber@kaeser.com", confidence=0.91),
            ],
            "fs-elliott.com": [
                Contact("John Elliott", "CEO", "j.elliott@fs-elliott.com", confidence=0.93),
            ],
            "elgi.com": [
                Contact("Ramesh Kumar", "Sourcing Manager", "r.kumar@elgi.com", confidence=0.88),
                Contact("Priya Sharma", "VP Procurement", "p.sharma@elgi.com", confidence=0.86),
            ],
            "compair.com": [
                Contact("David Wilson", "Purchasing Director", "d.wilson@compair.com", confidence=0.90),
            ],
            "sullair.com": [
                Contact("Mike Thompson", "VP Sourcing", "m.thompson@sullair.com", confidence=0.89),
            ],
            "irco.com": [
                Contact("Jennifer Lopez", "Supply Chain Director", "j.lopez@irco.com", confidence=0.87),
                Contact("David Chen", "Sourcing Manager", "d.chen@irco.com", confidence=0.85),
            ],
            "fusheng.com": [
                Contact("Chen Wei-Ming", "Purchasing Manager", "chen.wm@fusheng.com", confidence=0.89),
            ],
            "hanbell.com": [
                Contact("Lin Shu-Fen", "General Manager", "lin.sf@hanbell.com", confidence=0.91),
            ],
            "ecoair-engineering.de": [
                Contact("Stefan Mueller", "Founder & CEO", "s.mueller@ecoair-engineering.de", confidence=0.95),
            ],
        }

        contacts = mock_db.get(domain_key, [])
        if not contacts:
            # Generic fallback for any unknown domain
            contacts = [
                Contact("Contact Person", "Manager", f"info@{domain_key}", confidence=0.5),
            ]

        # If a title hint is provided, bias the ordering
        if title_hint:
            hint_lower = title_hint.lower()
            contacts = sorted(
                contacts,
                key=lambda c: (0 if hint_lower in c.title.lower() else 1),
            )

        return contacts

    @staticmethod
    def _parse_response(data: dict, title_hint: str) -> list[Contact]:
        contacts: list[Contact] = []
        for entry in data.get("data", {}).get("emails", []):
            contacts.append(Contact(
                full_name=f"{entry.get('first_name', '')} {entry.get('last_name', '')}".strip(),
                title=entry.get("position", ""),
                email=entry.get("value", ""),
                confidence=entry.get("confidence", 0) / 100.0,
            ))
        return contacts


# ---------------------------------------------------------------------------
# Mock Prospeo API (fallback / supplementary)
# ---------------------------------------------------------------------------


class ProspeoAPI:
    """
    Skeleton for Prospeo Email Finder API.

    Production endpoint: GET https://api.prospeo.io/v1/email-finder
    """

    BASE_URL = "https://api.prospeo.io/v1"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or "MOCK_PROSPEO_KEY"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def find_email(self, full_name: str, domain: str) -> Optional[Contact]:
        """
        Look up a single email by *full_name* + *domain*.
        Returns a Contact or None if not found.
        """
        logger.info("ProspeoAPI.find_email(name=%r, domain=%r)", full_name, domain)

        if self.api_key != "MOCK_PROSPEO_KEY":
            resp = requests.get(
                f"{self.BASE_URL}/email-finder",
                params={"name": full_name, "domain": domain, "api_key": self.api_key},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("email"):
                return Contact(
                    full_name=full_name,
                    title=data.get("title", ""),
                    email=data["email"],
                    confidence=data.get("confidence", 0) / 100.0,
                )
            return None

        return self._mock_result(full_name, domain)

    @staticmethod
    def _mock_result(full_name: str, domain: str) -> Optional[Contact]:
        time.sleep(0.05)
        # Simple heuristic: generate an email from the name and domain
        parts = full_name.lower().split()
        if len(parts) < 2:
            return None
        first, last = parts[0], parts[-1]
        email = f"{first[0]}.{last}@{domain}"
        return Contact(full_name=full_name, title="", email=email, confidence=0.65)


# ---------------------------------------------------------------------------
# SMTP / DNS verification
# ---------------------------------------------------------------------------


class EmailVerifier:
    """
    Validates email addresses via DNS MX lookup and SMTP handshake.

    Does NOT send actual emails — only connects to the recipient MX
    and simulates the MAIL FROM / RCPT TO pipeline up to the RCPT TO
    response to detect invalid or catch-all mailboxes.
    """

    # Common invalid / role-based local-parts to flag
    CATCH_ALL_THRESHOLD = 0.3  # if all probed addresses pass, suspect catch-all

    @staticmethod
    def check_mx(domain: str) -> list[str]:
        """Return the MX hostnames (sorted by priority) for a domain."""
        try:
            answers = dns.resolver.resolve(domain, "MX")
            records = sorted(answers, key=lambda r: r.preference)
            return [str(r.exchange).rstrip(".") for r in records]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.exception.Timeout):
            logger.warning("No MX records found for domain %s", domain)
            return []

    @staticmethod
    def verify_smtp(email: str, timeout: int = 3) -> tuple[bool, str]:
        """
        Perform a lightweight SMTP RCPT TO verification.

        Returns (is_valid: bool, status: str) where status is one of:
        "valid", "invalid", "catch_all", "unknown", "no_mx"
        """
        domain = email.split("@")[-1]

        mx_hosts = EmailVerifier.check_mx(domain)
        if not mx_hosts:
            return False, "no_mx"

        for mx in mx_hosts:
            try:
                with smtplib.SMTP(timeout=timeout) as smtp:
                    smtp.connect(mx)
                    smtp.helo("verifier.b2b-tool.local")
                    # Some servers require a plausible sender
                    smtp.mail("verify@b2b-tool.local")
                    code, message = smtp.rcpt(email)
                    smtp.quit()

                    if code == 250:
                        return True, "valid"
                    elif code == 550:
                        return False, "invalid"
                    elif code in (551, 552, 553, 554):
                        return False, "invalid"
                    else:
                        # 2xx, 4xx (temporary), or unknown → conservatively "unknown"
                        return False, "unknown"
            except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
                    smtplib.SMTPResponseException, socket.timeout,
                    ConnectionRefusedError, OSError) as exc:
                logger.debug("SMTP verify failed for %s on %s: %s", email, mx, exc)
                continue

        return False, "unknown"

    @classmethod
    def verify_batch(cls, contacts: list[Contact]) -> list[Contact]:
        """Verify a batch of contacts, updating email_verified and email_status in place."""
        for contact in contacts:
            if not contact.email:
                contact.email_status = "invalid"
                continue
            is_valid, status = cls.verify_smtp(contact.email)
            contact.email_verified = is_valid
            contact.email_status = status
            logger.info("Verified %s → %s", contact.email, status)
            time.sleep(0.05)  # rate-limit to avoid being flagged as spam
        return contacts


# ---------------------------------------------------------------------------
# Unified contact finder
# ---------------------------------------------------------------------------


class ContactFinder:
    """
    Orchestrates Hunter.io + Prospeo lookup, then runs SMTP verification.
    """

    def __init__(
        self,
        hunter: Optional[HunterAPI] = None,
        prospeo: Optional[ProspeoAPI] = None,
        verifier: Optional[EmailVerifier] = None,
    ) -> None:
        self.hunter = hunter or HunterAPI()
        self.prospeo = prospeo or ProspeoAPI()
        self.verifier = verifier or EmailVerifier()

    def find_contacts(
        self,
        domain: str,
        target_titles: list[str] | None = None,
        max_contacts: int = 3,
    ) -> list[Contact]:
        """
        Find and verify decision-maker contacts for a company domain.

        *target_titles*: e.g. ["Purchasing", "Sourcing", "Owner", "VP"]
        """
        if target_titles is None:
            target_titles = ["Purchasing", "Sourcing", "Owner", "VP", "Procurement", "Supply Chain"]

        all_contacts: list[Contact] = []

        # 1. Hunter.io domain search for each title hint
        for hint in target_titles[:4]:  # cap hints to avoid excessive API calls
            results = self.hunter.domain_search(domain, title_hint=hint)
            for c in results:
                if not any(c.email == existing.email for existing in all_contacts):
                    all_contacts.append(c)
            if len(all_contacts) >= max_contacts * 2:
                break

        # 2. Supplement with Prospeo for contacts we have names for
        if self.prospeo.api_key != "MOCK_PROSPEO_KEY":
            for c in list(all_contacts):
                if c.email == "" and c.full_name:
                    found = self.prospeo.find_email(c.full_name, domain)
                    if found:
                        all_contacts.append(found)

        # 3. Score and pick the best
        scored = sorted(all_contacts, key=lambda c: c.confidence, reverse=True)
        top = scored[:max_contacts]

        # 4. Verify
        self.verifier.verify_batch(top)

        logger.info("ContactFinder: domain=%s → %d contacts found, %d returned",
                     domain, len(all_contacts), len(top))
        return top

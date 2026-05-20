#!/usr/bin/env python3
"""
main.py — Unified entry point for the B2B Lead Generation Pipeline.

Pipeline:
  1. Scrape leads from multiple sources by keyword + region.
  2. Apply LLM semantic filtering to keep only high-intent targets.
  3. Discover & verify decision-maker contacts for qualified leads.
  4. Generate and send personalised outreach (email / WhatsApp).

Usage:
  python main.py --keyword "air compressor manufacturer" --region Germany
  python main.py --keyword "screw compressor OEM" --region China --dry-run
  python main.py --keyword "industrial pump maker" --region US --channels email,whatsapp
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv

# Load .env before any module that reads os.getenv
load_dotenv()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)-7s] %(name)s — %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")

    # Quiet down noisy third-party loggers
    for noisy in ("urllib3", "requests", "httpx", "httpcore", "smtplib", "dns"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    keyword: str,
    region: str,
    channels: tuple[str, ...] = ("email",),
    max_leads: int = 15,
    dry_run: bool = False,
    llm_provider: Optional[str] = None,
) -> int:
    """
    Execute the full B2B lead generation pipeline.

    Returns the number of outreach messages successfully sent.
    """
    logger = logging.getLogger("pipeline")

    # ------------------------------------------------------------------
    # Stage 1 — Scrape
    # ------------------------------------------------------------------
    logger.info("=== STAGE 1: Scraping leads (keyword=%r, region=%r) ===", keyword, region)

    from scraper import create_aggregator

    aggregator = create_aggregator(
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
        linkedin_token=os.getenv("LINKEDIN_ACCESS_TOKEN", ""),
        apollo_key=os.getenv("APOLLO_API_KEY", ""),
    )
    raw_leads = aggregator.scrape(keyword=keyword, region=region, max_per_source=max_leads)
    logger.info("Scraped %d raw leads", len(raw_leads))

    if not raw_leads:
        logger.warning("No leads found — check your keyword and region.")
        return 0

    # ------------------------------------------------------------------
    # Stage 2 — LLM Filter
    # ------------------------------------------------------------------
    logger.info("=== STAGE 2: LLM semantic filtering ===")

    from filters import LeadFilter, FilterCriteria, LLMClient

    # Build criteria: exclude non-target regions, require OEM/ODM capabilities
    criteria = FilterCriteria(
        required_capabilities=["OEM", "ODM", "manufacturing", "customization"],
        excluded_regions=[],
    )
    llm_client = LLMClient(provider=llm_provider)
    filter_engine = LeadFilter(criteria=criteria, llm=llm_client)

    # Convert CompanyLead dataclasses to dicts for the filter
    lead_dicts = [
        {
            "company_name": lead.company_name,
            "website_url": lead.website_url,
            "country": lead.country,
            "raw_description": lead.raw_description,
            "source": lead.source,
            "source_rank": str(lead.source_rank),
        }
        for lead in raw_leads
    ]
    passed = filter_engine.filter_batch_sync(lead_dicts)
    logger.info("Filter: %d → %d qualified leads", len(raw_leads), len(passed))

    if not passed:
        logger.warning("No leads passed the LLM filter. Try broadening your criteria.")
        return 0

    # ------------------------------------------------------------------
    # Stage 3 — Contact Discovery & Verification
    # ------------------------------------------------------------------
    logger.info("=== STAGE 3: Contact discovery & verification ===")

    from contacts import ContactFinder

    finder = ContactFinder()
    enriched_targets: list[dict] = []

    for lead in passed:
        domain = lead.get("website_url", "").replace("www.", "").strip()
        if not domain:
            continue

        target_titles = [lead.get("decision_maker_title", "")]
        if not target_titles[0]:
            target_titles = ["Purchasing Manager", "Sourcing Manager", "Owner", "VP"]

        contacts = finder.find_contacts(
            domain=domain,
            target_titles=target_titles,
            max_contacts=2,
        )

        if contacts:
            best = contacts[0]
            enriched = dict(lead)
            enriched["contact_name"] = best.full_name
            enriched["contact_email"] = best.email
            enriched["contact_title"] = best.title
            enriched["contact_email_verified"] = str(best.email_verified)
            enriched["contact_email_status"] = best.email_status
            enriched["contact_confidence"] = str(best.confidence)
            enriched_targets.append(enriched)
            logger.info(
                "Contact found: %s <%s> (%s) — verified=%s",
                best.full_name, best.email, best.title, best.email_verified,
            )
        else:
            logger.info("No contact found for %s (%s)", lead["company_name"], domain)

    if not enriched_targets:
        logger.warning("No contacts found for any qualified leads.")
        return 0

    # ------------------------------------------------------------------
    # Stage 4 — Outreach
    # ------------------------------------------------------------------
    logger.info("=== STAGE 4: AI-powered outreach (channels=%s) ===", channels)

    from outreach import (
        OutreachTarget,
        OutreachOrchestrator,
    )

    targets = [
        OutreachTarget(
            company_name=t["company_name"],
            website_url=t.get("website_url", ""),
            country=t.get("country", ""),
            raw_description=t.get("raw_description", ""),
            decision_maker_title=t.get("decision_maker_title", ""),
            intent_score=int(t.get("intent_score", 0)),
            filter_reason=t.get("filter_reason", ""),
            contact_name=t.get("contact_name", ""),
            contact_email=t.get("contact_email", ""),
            contact_title=t.get("contact_title", ""),
            contact_phone=t.get("contact_phone", ""),
        )
        for t in enriched_targets
    ]

    orchestrator = OutreachOrchestrator(
        sender_name=os.getenv("SENDER_NAME", "Alex Chen"),
        sender_company=os.getenv("SENDER_COMPANY", "GlobalComp Manufacturing"),
    )

    results = orchestrator.run(targets=targets, channels=channels, dry_run=dry_run)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Keyword:            {keyword}")
    print(f"  Region:             {region}")
    print(f"  Raw leads scraped:  {len(raw_leads)}")
    print(f"  After LLM filter:   {len(passed)}")
    print(f"  With contacts:      {len(enriched_targets)}")
    print(f"  Outreach attempted: {len(results)}")
    print(f"  Outreach succeeded: {sum(1 for r in results if r.success)}")
    print(f"  Dry run:            {dry_run}")
    print("=" * 60 + "\n")

    # Print per-target detail
    for i, result in enumerate(results, 1):
        status = "OK" if result.success else f"FAILED: {result.error}"
        print(f"  [{i}] {result.target.company_name} | {result.channel} | {status}")
        if result.message_id:
            print(f"       Message-ID: {result.message_id}")

    return sum(1 for r in results if r.success)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="B2B Lead Generation — Scrape → Filter → Contacts → Outreach",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--keyword", "-k",
        required=True,
        help="Industry keyword, e.g. 'air compressor manufacturer'",
    )
    parser.add_argument(
        "--region", "-r",
        required=True,
        help="Target region, e.g. 'Germany', 'US', 'China'",
    )
    parser.add_argument(
        "--channels", "-c",
        default="email",
        help="Comma-separated outreach channels: email,whatsapp (default: email)",
    )
    parser.add_argument(
        "--max-leads", "-n",
        type=int,
        default=15,
        help="Max leads per data source (default: 15)",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Personalise and log but do NOT send any messages",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("gemini", "claude"),
        default=None,
        help="LLM backend (default: $LLM_PROVIDER or gemini)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    channels = tuple(c.strip() for c in args.channels.split(",") if c.strip())
    valid_channels = {"email", "whatsapp"}
    for ch in channels:
        if ch not in valid_channels:
            print(f"Error: unknown channel '{ch}'. Valid: email, whatsapp", file=sys.stderr)
            sys.exit(1)

    try:
        sent = run_pipeline(
            keyword=args.keyword,
            region=args.region,
            channels=channels,
            max_leads=args.max_leads,
            dry_run=args.dry_run,
            llm_provider=args.llm_provider,
        )
        print(f"\nPipeline complete. {sent} message(s) sent.")
        if args.dry_run:
            print("(Dry run — no messages were actually delivered.)")
    except KeyboardInterrupt:
        print("\nAborted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception:
        logging.getLogger("pipeline").exception("Pipeline failed with unhandled error")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Automated follow-up worker for the B2B Lead Gen CRM.

Scans the database for leads that need a follow-up touch:
  - In 'Contacted' stage
  - last_contacted_at is older than FOLLOW_UP_DAYS (default 3) days ago
  - follow_up_count < MAX_FOLLOW_UPS (default 3)

For each qualifying lead:
  1. Loads the owner's per-tenant SMTP config from the DB
  2. Generates a personalised email in the lead's LOCAL LANGUAGE using the LLM
  3. Sends the email via SMTP
  4. Saves the email to outreach_logs (subject + body)
  5. Increments follow_up_count and updates last_contacted_at

Usage:
  python cron_followup.py                  # check and send (real sends)
  python cron_followup.py --dry-run        # preview what WOULD be sent
  python cron_followup.py --days 5         # leads not contacted in 5+ days
  python cron_followup.py --max-followups 5  # allow up to 5 follow-ups
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from database import init_db, SessionLocal
from models import User, CompanyLead, OutreachLog
from outreach import OutreachPersonaliser, OutreachTarget, EmailSender

logger = logging.getLogger("cron_followup")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

FOLLOW_UP_DAYS = 3
MAX_FOLLOW_UPS = 3


def find_leads_needing_followup(days: int = FOLLOW_UP_DAYS, max_followups: int = MAX_FOLLOW_UPS):
    """Return (user, lead) pairs for every lead that is due for a follow-up."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        rows = (
            db.query(User, CompanyLead)
            .join(CompanyLead, CompanyLead.user_id == User.id)
            .filter(
                CompanyLead.lead_stage == "Contacted",
                CompanyLead.follow_up_count < max_followups,
                CompanyLead.contact_email != "",
                CompanyLead.contact_email.isnot(None),
            )
            .all()
        )
        # Filter last_contacted_at in Python (SQLite DateTime comparison is string-based)
        result = []
        for user, lead in rows:
            lc = lead.last_contacted_at
            if lc is None or lc < cutoff or lc == datetime.utcnow():
                # lc == utcnow() means never contacted, or lc is older than cutoff
                if lc is not None and lc >= cutoff:
                    continue  # was contacted recently, skip
                result.append((user, lead))
        return result
    finally:
        db.close()


def process_followups(dry_run: bool = False, days: int = FOLLOW_UP_DAYS, max_followups: int = MAX_FOLLOW_UPS):
    """Main worker: find leads, generate emails, send, log."""
    pairs = find_leads_needing_followup(days, max_followups)

    if not pairs:
        logger.info("No leads need follow-up right now.")
        return 0

    logger.info("Found %d lead(s) needing follow-up", len(pairs))
    personaliser = OutreachPersonaliser()
    sent_count = 0

    for user, lead in pairs:
        logger.info("--- Lead #%d: %s (%s) ---", lead.id, lead.company_name, lead.contact_email)

        # 1. Build SMTP sender from user's per-tenant config
        sender = EmailSender(
            host=user.smtp_host,
            port=user.smtp_port or 0,
            username=user.smtp_username,
            password=user.smtp_password,
        )

        if not sender.is_configured:
            logger.warning(
                "User %s has no SMTP configured — skipping lead #%d. "
                "Configure SMTP in Settings to enable follow-ups.",
                user.email, lead.id,
            )
            continue

        # 2. Build OutreachTarget from lead
        target = OutreachTarget(
            company_name=lead.company_name,
            website_url=lead.website_url or "",
            country=lead.country or "",
            raw_description=lead.raw_description or "",
            decision_maker_title=lead.decision_maker_title or "",
            intent_score=lead.intent_score or 0,
            filter_reason=lead.filter_reason or "",
            contact_name=lead.contact_name or "",
            contact_email=lead.contact_email or "",
            contact_title=lead.contact_title or "",
            contact_phone=lead.contact_phone or "",
        )

        sender_name = os.getenv("SENDER_NAME", user.display_name or "Alex Chen")
        sender_company = os.getenv("SENDER_COMPANY", user.company or "GlobalComp Manufacturing")

        # 3. Generate multi-language email
        subject, body, language = personaliser.generate_multilingual_email(
            target,
            sender_name,
            sender_company,
            country=lead.country or "",
        )
        logger.info("Generated %s email: subject=%r", language, subject)

        if dry_run:
            logger.info("[DRY RUN] Would send to %s:", lead.contact_email)
            logger.info("  Language: %s", language)
            logger.info("  Subject: %s", subject)
            logger.info("  Body: %s", body[:200])
            sent_count += 1
            continue

        # 4. Send via SMTP
        try:
            msg_id = sender.send(
                to_email=lead.contact_email,
                subject=subject,
                body_text=body,
                from_name=sender_name,
                from_email=sender.username,
            )
            success = True
            error_msg = ""
            logger.info("Sent successfully — Message-ID: %s", msg_id)
            sent_count += 1
        except Exception as exc:
            msg_id = ""
            success = False
            error_msg = str(exc)
            logger.error("Send failed: %s", exc)

        # 5. Save to outreach_logs
        db = SessionLocal()
        try:
            db.add(OutreachLog(
                user_id=user.id,
                lead_id=lead.id,
                channel="email",
                recipient_email=lead.contact_email,
                subject=subject,
                body=body,
                message_id=msg_id,
                success=success,
                error_message=error_msg,
            ))

            # 6. Increment follow_up_count + update last_contacted_at
            the_lead = db.query(CompanyLead).filter(CompanyLead.id == lead.id).first()
            if the_lead:
                the_lead.follow_up_count = (the_lead.follow_up_count or 0) + 1
                the_lead.last_contacted_at = datetime.utcnow()
                the_lead.updated_at = datetime.utcnow()

            db.commit()
            logger.info("Logged to outreach_logs + follow_up_count=%d", (lead.follow_up_count or 0) + 1)
        except Exception:
            db.rollback()
            logger.exception("Failed to save outreach log for lead #%d", lead.id)
        finally:
            db.close()

    logger.info("Done. %d follow-up email(s) %s.", sent_count, "previewed" if dry_run else "sent")
    return sent_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="B2B CRM automated follow-up worker"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--days", type=int, default=FOLLOW_UP_DAYS, help=f"Days since last contact (default: {FOLLOW_UP_DAYS})")
    parser.add_argument("--max-followups", type=int, default=MAX_FOLLOW_UPS, help=f"Max follow-up count (default: {MAX_FOLLOW_UPS})")
    args = parser.parse_args()

    # Ensure DB tables exist
    init_db()

    try:
        process_followups(dry_run=args.dry_run, days=args.days, max_followups=args.max_followups)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception:
        logger.exception("Follow-up worker failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

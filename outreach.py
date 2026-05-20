"""
Multi-Channel AI Outreach — personalised cold emails & WhatsApp messages.

Channels:
  - Email via SMTP (with plain-text and HTML variants)
  - WhatsApp via a mock Business API (Twilio / Meta pattern)

Features: LLM personalisation, rate limiting, retry with backoff, structured logging.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
import uuid
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable, Optional, Literal

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Reuse filter's LLM client for email generation
from filters import FilterVerdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class OutreachError(Exception):
    """Base exception for outreach delivery failures."""


class RateLimitExceeded(OutreachError):
    """Raised when the rate limiter blocks a send."""


class DeliveryFailure(OutreachError):
    """Raised when the delivery API returns a non-retriable error."""


@dataclass
class OutreachTarget:
    """Fully enriched lead + contact ready for outreach."""

    company_name: str
    website_url: str
    country: str
    raw_description: str
    decision_maker_title: str
    intent_score: int
    filter_reason: str
    contact_name: str = ""
    contact_email: str = ""
    contact_title: str = ""
    contact_phone: str = ""


@dataclass
class OutreachResult:
    """Outcome of a single outreach attempt."""

    target: OutreachTarget
    channel: Literal["email", "whatsapp"]
    success: bool
    message_id: str = ""
    error: str = ""
    sent_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Rate limiter (token bucket)
# ---------------------------------------------------------------------------


class TokenBucketRateLimiter:
    """
    Simple token-bucket rate limiter.

    Example: 10 calls per minute → rate=10, period=60
    """

    def __init__(self, rate: int, period: float = 60.0) -> None:
        self.rate = rate
        self.period = period
        self._tokens = float(rate)
        self._last_refill = time.monotonic()

    def acquire(self) -> bool:
        """Try to consume one token. Returns True if allowed, False if rate-limited."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.rate, self._tokens + elapsed * (self.rate / self.period))
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def wait_and_acquire(self, timeout: float = 30.0) -> bool:
        """Block until a token is available or *timeout* elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.5)
        return False


# ---------------------------------------------------------------------------
# LLM personalisation engine (shared by email & WhatsApp)
# ---------------------------------------------------------------------------


PERSONALISATION_SYSTEM_PROMPT = """\
You are an elite B2B cold outreach copywriter specialising in industrial / OEM / manufacturing sectors.

## Rules
1. Write a 1-to-1, highly personalised message. NEVER use spammy templates or placeholders like [Company Name].
2. Reference a SPECIFIC detail from the company description or filter reason — prove you did your homework.
3. Tone: professional but warm, concise (100-150 words for email; 80-100 words for WhatsApp), value-first.
4. Include a clear, low-friction CTA (e.g., a 15-min discovery call, not "buy now").
5. The message must feel like it was written by a human who genuinely understands their business.

## Output Format
Return ONLY a valid JSON object:
{
  "subject": "string (email only; empty for WhatsApp)",
  "body": "string (the full message body)"
}
"""


class OutreachPersonaliser:
    """Generates tailored messages via LLM."""

    def __init__(self, llm=None) -> None:
        from filters import LLMClient
        self.llm = llm or LLMClient()

    def generate_email(self, target: OutreachTarget, sender_name: str, sender_company: str) -> tuple[str, str]:
        """
        Return (subject, body) for a personalised cold email.
        """
        user_prompt = self._build_email_prompt(target, sender_name, sender_company)
        raw = self.llm.generate(PERSONALISATION_SYSTEM_PROMPT, user_prompt)
        data = self._parse_json(raw)
        return data.get("subject", ""), data.get("body", raw)

    def generate_whatsapp(self, target: OutreachTarget, sender_name: str, sender_company: str) -> str:
        """
        Return the body text for a WhatsApp message.
        """
        user_prompt = self._build_whatsapp_prompt(target, sender_name, sender_company)
        raw = self.llm.generate(PERSONALISATION_SYSTEM_PROMPT, user_prompt)
        data = self._parse_json(raw)
        return data.get("body", raw)

    # ------------------------------------------------------------------
    @staticmethod
    def _build_email_prompt(target: OutreachTarget, sender_name: str, sender_company: str) -> str:
        return f"""\
Write a personalised B2B cold email.

## Target Company
- Name: {target.company_name}
- Country: {target.country}
- Description: {target.raw_description}
- Why they were selected: {target.filter_reason}
- Intent Score: {target.intent_score}/100
- Contact: {target.contact_name}, {target.contact_title or target.decision_maker_title}

## Sender
- Name: {sender_name}
- Company: {sender_company}

Include a compelling subject line and a clear CTA."""

    @staticmethod
    def _build_whatsapp_prompt(target: OutreachTarget, sender_name: str, sender_company: str) -> str:
        return f"""\
Write a short, personalised WhatsApp cold outreach message.

## Target Company
- Name: {target.company_name}
- Country: {target.country}
- Description: {target.raw_description}
- Why they were selected: {target.filter_reason}
- Intent Score: {target.intent_score}/100
- Contact: {target.contact_name}, {target.contact_title or target.decision_maker_title}

## Sender
- Name: {sender_name}
- Company: {sender_company}

Keep it under 100 words. WhatsApp messages are informal — friendly opening, one value sentence, one CTA. No subject line needed."""

    @staticmethod
    def _parse_json(raw: str) -> dict:
        import re
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[^{}]*\}", cleaned)
            if match:
                return json.loads(match.group())
            return {"subject": "", "body": cleaned}


# ---------------------------------------------------------------------------
# Email delivery engine
# ---------------------------------------------------------------------------


class EmailSender:
    """
    Sends personalised emails via SMTP.

    Config via env vars:
      SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
      SMTP_USE_TLS (default true)
    """

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
    ) -> None:
        self.host = host or os.getenv("SMTP_HOST", "")
        self.port = port or int(os.getenv("SMTP_PORT", "0") or "0")
        self.username = username or os.getenv("SMTP_USERNAME", "")
        self.password = password or os.getenv("SMTP_PASSWORD", "")
        self.use_tls = use_tls
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate=20, period=60)

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.port and self.username and self.password)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((smtplib.SMTPException, ConnectionError, OSError)),
    )
    def send(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        from_name: str = "",
        from_email: str = "",
    ) -> str:
        """
        Send a personalised email. Returns a unique message_id string.

        Raises RateLimitExceeded if the rate limiter denies the send.
        Raises DeliveryFailure on non-retriable SMTP errors.
        """
        if not self.rate_limiter.acquire():
            raise RateLimitExceeded(f"Email rate limit exceeded for {to_email}")

        message_id = f"<{uuid.uuid4().hex}@b2b-outreach.local>"

        if not self.is_configured:
            logger.warning(
                "SMTP not configured (missing SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD). "
                "Skipping send to %s — set these env vars or use --dry-run.",
                to_email,
            )
            return message_id

        from_addr = from_email or self.username
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Message-ID"] = message_id

        # Plain-text part
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Simple HTML part (auto-converted from plain text)
        html_body = body_text.replace("\n", "<br>")
        msg.attach(MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8"))

        logger.info("Sending email to %s (Message-ID: %s) …", to_email, message_id)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.ehlo()
                if self.use_tls:
                    server.starttls()
                    server.ehlo()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.sendmail(from_addr, to_email, msg.as_string())
        except smtplib.SMTPAuthenticationError as exc:
            raise DeliveryFailure(f"SMTP auth failed: {exc}") from exc
        except smtplib.SMTPSenderRefused as exc:
            raise DeliveryFailure(f"Sender refused (check SMTP_USERNAME/SMTP_PASSWORD): {exc}") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise DeliveryFailure(f"Recipient refused: {exc}") from exc

        logger.info("Email sent successfully to %s", to_email)
        return message_id


# ---------------------------------------------------------------------------
# WhatsApp delivery engine (mock / Meta API skeleton)
# ---------------------------------------------------------------------------


class WhatsAppSender:
    """
    Sends WhatsApp messages via the Meta / Twilio Business API.

    Config via env vars:
      WHATSAPP_API_URL, WHATSAPP_API_TOKEN, WHATSAPP_PHONE_NUMBER_ID
    """

    BASE_URL = "https://graph.facebook.com/v18.0"

    def __init__(
        self,
        api_token: str = "",
        phone_number_id: str = "",
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
    ) -> None:
        self.api_token = api_token or os.getenv("WHATSAPP_API_TOKEN", "")
        self.phone_number_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate=10, period=60)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def send(self, to_phone: str, body_text: str) -> str:
        """
        Send a WhatsApp template / text message.

        *to_phone* must include country code, e.g. "491234567890".

        Returns a message ID.
        """
        if not self.rate_limiter.acquire():
            raise RateLimitExceeded(f"WhatsApp rate limit exceeded for {to_phone}")

        message_id = f"wa_{uuid.uuid4().hex[:16]}"
        logger.info("Sending WhatsApp to %s (Message-ID: %s) …", to_phone, message_id)

        # --- Production path ---
        if self.api_token and self.phone_number_id:
            url = f"{self.BASE_URL}/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "text",
                "text": {"body": body_text},
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            if resp.status_code != 200:
                raise DeliveryFailure(
                    f"WhatsApp API returned {resp.status_code}: {resp.text[:300]}"
                )
        else:
            # Mock path: log the message that would have been sent
            logger.info("[MOCK WhatsApp] to=%s | body=%s", to_phone, body_text[:120])

        logger.info("WhatsApp sent to %s", to_phone)
        return message_id


# ---------------------------------------------------------------------------
# Unified outreach orchestrator
# ---------------------------------------------------------------------------


class OutreachOrchestrator:
    """
    Runs the full outreach pipeline for a list of qualified targets:
      personalise → send via email (+ optionally WhatsApp) → collect results.
    """

    def __init__(
        self,
        personaliser: Optional[OutreachPersonaliser] = None,
        email_sender: Optional[EmailSender] = None,
        whatsapp_sender: Optional[WhatsAppSender] = None,
        sender_name: str = "",
        sender_company: str = "",
    ) -> None:
        self.personaliser = personaliser or OutreachPersonaliser()
        self.email = email_sender or EmailSender()
        self.whatsapp = whatsapp_sender or WhatsAppSender()
        self.sender_name = sender_name or os.getenv("SENDER_NAME", "Alex Chen")
        self.sender_company = sender_company or os.getenv("SENDER_COMPANY", "GlobalComp Manufacturing")

    def run(
        self,
        targets: list[OutreachTarget],
        channels: tuple[str, ...] = ("email",),
        dry_run: bool = False,
    ) -> list[OutreachResult]:
        """
        Process a batch of targets through the selected channels.

        *dry_run*: personalise and log but do not actually send.
        """
        results: list[OutreachResult] = []

        for target in targets:
            # ---- Email ----
            if "email" in channels:
                try:
                    subject, body = self.personaliser.generate_email(
                        target, self.sender_name, self.sender_company
                    )
                    logger.info(
                        "Generated email for %s (subject=%r)",
                        target.company_name, subject,
                    )
                    if dry_run:
                        logger.info(
                            "[DRY RUN] Would email %s <%s>:\nSubject: %s\n%s",
                            target.contact_name, target.contact_email, subject, body,
                        )
                        results.append(OutreachResult(
                            target=target, channel="email", success=True,
                            message_id="dry_run",
                        ))
                    elif target.contact_email:
                        msg_id = self.email.send(
                            to_email=target.contact_email,
                            subject=subject,
                            body_text=body,
                            from_name=self.sender_name,
                        )
                        results.append(OutreachResult(
                            target=target, channel="email", success=True,
                            message_id=msg_id,
                        ))
                    else:
                        results.append(OutreachResult(
                            target=target, channel="email", success=False,
                            error="No contact email available",
                        ))
                except RateLimitExceeded:
                    logger.warning("Email rate-limited for %s — skipping", target.company_name)
                    results.append(OutreachResult(
                        target=target, channel="email", success=False,
                        error="Rate limit exceeded",
                    ))
                except OutreachError as exc:
                    logger.error("Email delivery failed for %s: %s", target.company_name, exc)
                    results.append(OutreachResult(
                        target=target, channel="email", success=False,
                        error=str(exc),
                    ))

            # ---- WhatsApp ----
            if "whatsapp" in channels:
                try:
                    body = self.personaliser.generate_whatsapp(
                        target, self.sender_name, self.sender_company
                    )
                    if dry_run:
                        logger.info(
                            "[DRY RUN] Would WhatsApp %s:\n%s",
                            target.contact_phone or "(no phone)", body,
                        )
                        results.append(OutreachResult(
                            target=target, channel="whatsapp", success=True,
                            message_id="dry_run",
                        ))
                    elif target.contact_phone:
                        msg_id = self.whatsapp.send(target.contact_phone, body)
                        results.append(OutreachResult(
                            target=target, channel="whatsapp", success=True,
                            message_id=msg_id,
                        ))
                    else:
                        results.append(OutreachResult(
                            target=target, channel="whatsapp", success=False,
                            error="No contact phone available",
                        ))
                except RateLimitExceeded:
                    logger.warning("WhatsApp rate-limited for %s — skipping", target.company_name)
                    results.append(OutreachResult(
                        target=target, channel="whatsapp", success=False,
                        error="Rate limit exceeded",
                    ))
                except OutreachError as exc:
                    logger.error("WhatsApp delivery failed for %s: %s", target.company_name, exc)
                    results.append(OutreachResult(
                        target=target, channel="whatsapp", success=False,
                        error=str(exc),
                    ))

        succeeded = sum(1 for r in results if r.success)
        logger.info("Outreach batch complete: %d/%d messages sent", succeeded, len(results))
        return results

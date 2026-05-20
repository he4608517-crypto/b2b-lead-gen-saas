"""
LLM Semantic Filter — deep profile matching for B2B lead qualification.

Uses Gemini (google-genai) or Claude (Anthropic) to evaluate each lead
against user-defined criteria and return structured verdicts via Pydantic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------


class FilterVerdict(BaseModel):
    """Structured output enforced by the LLM for every lead."""

    is_target: bool = Field(description="True if the company is a valid target buyer")
    intent_score: int = Field(ge=0, le=100, description="0=definitely NOT, 100=perfect ICP match")
    decision_maker_title: str = Field(
        default="",
        description="Suggested target title, e.g. 'Purchasing Manager', 'Owner', 'VP Sourcing'. Empty if is_target=False.",
    )
    reason: str = Field(
        description="Structured reason for the decision (3-5 bullet-ready sentences)"
    )


# ---------------------------------------------------------------------------
# User-defined filtering criteria
# ---------------------------------------------------------------------------


class FilterCriteria(BaseModel):
    """Configurable gate used in the LLM prompt to reject non-target leads."""

    required_capabilities: list[str] = Field(
        default_factory=lambda: ["OEM", "ODM", "manufacturing", "customization"]
    )
    excluded_regions: list[str] = Field(default_factory=lambda: [])
    required_decision_maker_titles: list[str] = Field(
        default_factory=lambda: [
            "Purchasing Manager",
            "Sourcing Manager",
            "Procurement Director",
            "Supply Chain Manager",
            "Owner",
            "CEO",
            "VP of Operations",
            "VP of Sourcing",
            "Head of Procurement",
            "General Manager",
            "Managing Director",
            "Founder",
            "Co-Founder",
        ]
    )
    negative_keywords: list[str] = Field(
        default_factory=lambda: [
            "distributor only",
            "reseller",
            "repair shop",
            "end-user",
            "service provider",
            "trading company",
            "used equipment dealer",
            "not a manufacturer",
            "does not manufacture",
            "purely distribution",
        ]
    )


# ---------------------------------------------------------------------------
# Provider-agnostic LLM client
# ---------------------------------------------------------------------------


class LLMClient:
    """
    Thin abstraction over Gemini (google-genai) and Claude (Anthropic).

    Selects the provider based on the LLM_PROVIDER env var
    (``gemini`` or ``claude``), defaulting to ``gemini``.
    """

    def __init__(self, provider: Optional[str] = None) -> None:
        self.provider: Literal["gemini", "claude"] = (
            (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
        )  # type: ignore[assignment]
        if self.provider not in ("gemini", "claude"):
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        self._mock_mode = not self._has_api_key()

        if not self._mock_mode:
            if self.provider == "gemini":
                self._init_gemini()
            else:
                self._init_claude()

    def _has_api_key(self) -> bool:
        if self.provider == "gemini":
            return bool(os.getenv("GEMINI_API_KEY", ""))
        return bool(os.getenv("ANTHROPIC_API_KEY", ""))

    # ---- Gemini ----------------------------------------------------------

    def _init_gemini(self) -> None:
        try:
            from google import genai  # type: ignore
        except ImportError:
            raise ImportError("google-genai is required for Gemini. pip install google-genai")

        self._gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
        self._gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        response = self._gemini_client.models.generate_content(
            model=self._gemini_model,
            contents=user_prompt,
            config={"system_instruction": system_prompt},
        )
        return response.text.strip()

    # ---- Claude -----------------------------------------------------------

    def _init_claude(self) -> None:
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError:
            raise ImportError("anthropic SDK is required for Claude. pip install anthropic")

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._claude_client = Anthropic(api_key=api_key)
        self._claude_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        resp = self._claude_client.messages.create(
            model=self._claude_model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text.strip()

    # ---- Public API -------------------------------------------------------

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self._mock_mode:
            return self._mock_generate(user_prompt)
        if self.provider == "gemini":
            return self._call_gemini(system_prompt, user_prompt)
        return self._call_claude(system_prompt, user_prompt)

    @staticmethod
    def _mock_generate(user_prompt: str) -> str:
        """
        Rule-based mock LLM for demos without an API key.
        Handles both lead filtering and outreach personalisation prompts.
        """
        import json as _json
        text = user_prompt.lower()

        # ---- Outreach / email generation prompts ----
        if "write a personalised b2b cold email" in text or "write a short, personalised whatsapp" in text:
            # Extract company name from the prompt
            import re as _re
            name_match = _re.search(r"- Name:\s*(.+?)(?:\n|$)", user_prompt)
            company = name_match.group(1).strip() if name_match else "your company"
            contact_match = _re.search(r"- Contact:\s*(.+?)(?:\n|$)", user_prompt)
            contact = contact_match.group(1).strip() if contact_match else "your team"
            is_whatsapp = "whatsapp" in text

            subject = "" if is_whatsapp else f"Exploring supply chain partnership with {company}"
            body = (
                f"Hi {contact.split(',')[0]},\n\n"
                f"I've been following {company}'s work in the industrial manufacturing space "
                f"and I'm impressed by your team's capabilities. At GlobalComp Manufacturing, "
                f"we specialise in OEM/ODM partnerships that help manufacturers like {company} "
                f"scale their supply chain efficiently.\n\n"
                f"Would you be open to a brief 15-minute call next week to explore "
                f"whether there's a mutual fit?\n\n"
                f"Best regards,\nAlex Chen\nGlobalComp Manufacturing"
            ) if not is_whatsapp else (
                f"Hi {contact.split(',')[0]}, I've been following {company}'s work — "
                f"really impressive manufacturing capabilities. We specialise in OEM/ODM "
                f"partnerships that could complement your supply chain. Open to a quick chat next week? "
                f"Best, Alex Chen / GlobalComp Manufacturing"
            )
            return _json.dumps({"subject": subject, "body": body})

        # ---- Lead filtering prompts ----
        negative = [
            "distributor", "reseller", "repair shop", "end-user",
            "trading company", "used equipment", "not a manufacturer",
            "does not manufacture", "purely distribution",
            "does not manufacture and has no oem",
        ]
        for kw in negative:
            if kw in text:
                return _json.dumps({
                    "is_target": False, "intent_score": 0,
                    "decision_maker_title": "", "reason": f"Mock: matched negative keyword '{kw}'.",
                })

        positive_signals = ["oem", "odm", "manufacturer", "manufacturing", "customization",
                            "engineers custom", "in-house r&d", "foundry", "iso 9001"]
        score = sum(15 for s in positive_signals if s in text)
        score = min(score + 50, 100)

        title_hierarchy = [
            ("purchasing", "Purchasing Manager"),
            ("sourcing", "Sourcing Manager"),
            ("procurement", "Procurement Director"),
            ("owner", "Owner"),
            ("ceo", "CEO"),
            ("vp", "VP of Operations"),
            ("managing director", "Managing Director"),
            ("general manager", "General Manager"),
        ]
        best_title = "Purchasing Manager"
        for kw, title in title_hierarchy:
            if kw in text:
                best_title = title
                break

        return _json.dumps({
            "is_target": True,
            "intent_score": score,
            "decision_maker_title": best_title,
            "reason": f"Mock evaluation: intent_score={score}. Matched positive signals in company description.",
        })


# ---------------------------------------------------------------------------
# Filter engine
# ---------------------------------------------------------------------------


BUILT_IN_SYSTEM_PROMPT = """\
You are an expert B2B lead qualification analyst. Your job is to evaluate a company description and decide whether the company is a valid target buyer for an industrial OEM/ODM manufacturer.

## Rules (apply strictly)
1. The company must be a MANUFACTURER or a company that actively procures custom/OEM/ODM industrial products. Distributors, resellers, repair shops, trading companies, and end-users are NOT targets.
2. The company must have in-house engineering, manufacturing, or customization capabilities — or explicitly state that they outsource manufacturing (i.e., they are a buyer of OEM/ODM services).
3. If the description says the company is a "distributor", "reseller", "repair shop", "trading company", or explicitly says "does NOT manufacture", it is automatically NOT a target.
4. Chinese / Taiwanese / Indian manufacturers are generally valid targets (they often OEM for Western brands or are expanding their supply chain).
5. Give an intent_score from 0 (definitely not) to 100 (perfect ICP match). A score >= 60 means the company is worth contacting.

## Output format
Return ONLY a valid JSON object with these keys:
- "is_target": boolean
- "intent_score": integer 0-100
- "decision_maker_title": string (best title to contact; empty string if is_target is false)
- "reason": string (3-5 sentences explaining the decision)
"""


class LeadFilter:
    """
    Evaluates each CompanyLead through the LLM and returns a FilterVerdict.

    Also applies a fast pre-filter using keyword heuristics to avoid
    wasting LLM tokens on obviously bad leads.
    """

    def __init__(
        self,
        criteria: Optional[FilterCriteria] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self.criteria = criteria or FilterCriteria()
        self.llm = llm or LLMClient()

    # -- Fast pre-filter (no LLM call) -------------------------------------

    def pre_filter(self, description: str) -> Optional[FilterVerdict]:
        """
        Return a FilterVerdict if the lead can be ruled out by keyword
        matching alone, otherwise None (needs LLM evaluation).
        """
        desc_lower = description.lower()

        for kw in self.criteria.negative_keywords:
            if kw.lower() in desc_lower:
                return FilterVerdict(
                    is_target=False,
                    intent_score=0,
                    decision_maker_title="",
                    reason=f"Pre-filter rejected: description matched negative keyword '{kw}'.",
                )
        return None

    # -- LLM evaluation ----------------------------------------------------

    def evaluate(self, company_name: str, description: str, country: str) -> FilterVerdict:
        """
        Run the full LLM semantic evaluation on a single lead.
        Falls back to pre_filter first to save tokens.
        """

        # Stage 1: fast keyword pre-filter
        pre = self.pre_filter(description)
        if pre is not None:
            logger.info("Pre-filter rejected %s", company_name)
            return pre

        # Stage 2: LLM deep evaluation
        user_prompt = self._build_user_prompt(company_name, description, country)
        logger.info("LLM evaluation for %s …", company_name)

        try:
            raw = self.llm.generate(BUILT_IN_SYSTEM_PROMPT, user_prompt)
            return self._parse_llm_response(raw, company_name)
        except Exception:
            logger.exception("LLM call failed for %s — falling back to safe rejection", company_name)
            return FilterVerdict(
                is_target=False,
                intent_score=0,
                decision_maker_title="",
                reason="LLM evaluation failed; lead rejected conservatively.",
            )

    def _build_user_prompt(self, company_name: str, description: str, country: str) -> str:
        """Construct the per-lead prompt for the LLM."""
        excluded = ", ".join(self.criteria.excluded_regions) if self.criteria.excluded_regions else "none"
        titles = ", ".join(self.criteria.required_decision_maker_titles)
        return f"""\
Evaluate the following company:

Company Name: {company_name}
Country: {country}
Description: {description}

Excluded regions (auto-reject if the company is headquartered here): {excluded}
Valid decision-maker titles to consider: {titles}

Return ONLY the JSON object."""

    @staticmethod
    def _parse_llm_response(raw: str, company_name: str) -> FilterVerdict:
        """Extract JSON from the LLM response and hydrate a FilterVerdict."""
        # Many LLMs wrap JSON in ``` fences — strip them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to find a JSON object with a regex
            match = re.search(r"\{[^{}]*\}", cleaned)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse LLM JSON response for {company_name}: {raw[:200]}")

        return FilterVerdict(**data)

    # -- Batch evaluation --------------------------------------------------

    def filter_batch(
        self,
        leads: list[dict[str, str]],
    ) -> list[tuple[dict[str, str], FilterVerdict]]:
        """
        Accept a list of lead dicts (each must have 'company_name', 'raw_description', 'country')
        and return (lead, verdict) pairs.
        """
        results: list[tuple[dict[str, str], FilterVerdict]] = []
        for lead in leads:
            verdict = self.evaluate(
                company_name=lead["company_name"],
                description=lead.get("raw_description", ""),
                country=lead.get("country", ""),
            )
            results.append((lead, verdict))
        return results

    def filter_batch_sync(
        self,
        leads: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        Convenience: return only the leads that passed the filter,
        enriched with verdict fields.
        """
        passed: list[dict[str, str]] = []
        for lead, verdict in self.filter_batch(leads):
            if verdict.is_target:
                enriched = dict(lead)
                enriched["intent_score"] = str(verdict.intent_score)
                enriched["decision_maker_title"] = verdict.decision_maker_title
                enriched["filter_reason"] = verdict.reason
                passed.append(enriched)
        logger.info("Filter: %d in → %d passed", len(leads), len(passed))
        return passed

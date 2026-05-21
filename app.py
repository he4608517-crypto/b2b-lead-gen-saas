"""
FastAPI SaaS backend for the B2B Lead Generation Platform.

Endpoints:
  POST   /api/auth/register        Create account
  POST   /api/auth/login           Login, get JWT
  GET    /api/auth/me              Get current user profile
  GET    /api/leads                List user's leads (paginated, filterable)
  POST   /api/leads                Create a lead manually
  GET    /api/leads/{id}           Get a single lead
  PATCH  /api/leads/{id}           Update a lead
  DELETE /api/leads/{id}           Delete a lead
  GET    /api/outreach             List user's outreach logs
  GET    /api/dashboard/stats      Dashboard aggregate statistics
  POST   /api/pipeline/run         Trigger the scraping pipeline (async)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from base64 import urlsafe_b64encode, urlsafe_b64decode
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import SessionLocal, get_db, init_db
from models import User, CompanyLead, OutreachLog

logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# JWT helpers (no extra deps — HMAC-SHA256 + base64url)
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32)).encode()
JWT_ALGORITHM = "HS256"


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def create_token(user_id: int, expires_in: int = 86400 * 7) -> str:
    header = _b64url(json.dumps({"alg": JWT_ALGORITHM, "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({"sub": user_id, "iat": now, "exp": now + expires_in}).encode())
    sig = hmac.new(JWT_SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def verify_token(token: str) -> int | None:
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(hmac.new(JWT_SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(urlsafe_b64decode(payload + "=="))
        if data.get("exp", 0) < time.time():
            return None
        return data["sub"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Password hashing (hashlib scrypt — no extra deps)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return f"scrypt:{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt_hex, key_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(key_hex)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return hmac.compare_digest(key, expected)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


EMAIL_RE = r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_RE)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    company: str = Field(default="", max_length=255)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_RE)
    password: str = Field(min_length=1, max_length=128)


class LeadCreateRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    website_url: str = ""
    country: str = ""
    raw_description: str = ""
    source: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_title: str = ""
    contact_phone: str = ""


class LeadUpdateRequest(BaseModel):
    company_name: str | None = None
    website_url: str | None = None
    country: str | None = None
    raw_description: str | None = None
    is_target: bool | None = None
    intent_score: int | None = None
    decision_maker_title: str | None = None
    filter_reason: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_title: str | None = None
    contact_phone: str | None = None
    outreach_status: str | None = None
    outreach_channel: str | None = None


class PipelineRequest(BaseModel):
    keyword: str = Field(min_length=1)
    region: str = Field(min_length=1)
    channels: str = "email"
    max_leads: int = Field(default=15, ge=1, le=50)
    dry_run: bool = False


class SMTPConfigRequest(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_username: str = ""
    smtp_password: str = ""


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: str
    company: str
    plan: str
    created_at: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# FastAPI app lifecycle
# ---------------------------------------------------------------------------


def _seed_user():
    """Ensure the default dev account exists after a fresh DB reset."""
    from database import SessionLocal as _SessionLocal
    db = _SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "he4608517@gmail.com").first()
        if not existing:
            db.add(User(
                email="he4608517@gmail.com",
                display_name="Cooper",
                password_hash=hash_password("Zzj20040717@"),
                company="",
            ))
            db.commit()
            logger.info("Seeded default user: he4608517@gmail.com")
    except Exception:
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_user()
    yield


app = FastAPI(title="B2B Lead Gen SaaS", version="1.0.0", lifespan=lifespan)

# Local dev: any port on localhost, 127.0.0.1, or IPv6 [::1] (python -m http.server binds ::)
_LOCAL_DEV_ORIGIN = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=_LOCAL_DEV_ORIGIN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def current_user(request: Request) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    user_id = verify_token(auth[7:])
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.post("/api/auth/register")
def register(body: RegisterRequest):
    with get_db() as db:
        if db.query(User).filter(User.email == body.email).first():
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            email=body.email,
            display_name=body.display_name,
            password_hash=hash_password(body.password),
            company=body.company,
        )
        db.add(user)
        db.flush()
        token = create_token(user.id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "company": user.company,
                "plan": user.plan,
                "created_at": user.created_at.isoformat() if user.created_at else "",
            },
        }


@app.post("/api/auth/login")
def login(body: LoginRequest):
    with get_db() as db:
        user = db.query(User).filter(User.email == body.email).first()
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        token = create_token(user.id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "company": user.company,
                "plan": user.plan,
                "created_at": user.created_at.isoformat() if user.created_at else "",
            },
        }


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    smtp_ok = bool(user.smtp_host and user.smtp_port and user.smtp_username and user.smtp_password)
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "company": user.company,
        "plan": user.plan,
        "smtp_configured": smtp_ok,
        "smtp_host": user.smtp_host or "",
        "smtp_port": user.smtp_port or 0,
        "smtp_username": user.smtp_username or "",
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


# ---------------------------------------------------------------------------
# User SMTP config
# ---------------------------------------------------------------------------


@app.post("/api/users/smtp-config")
def save_smtp_config(body: SMTPConfigRequest, user: User = Depends(current_user)):
    with get_db() as db:
        u = db.query(User).filter(User.id == user.id).first()
        u.smtp_host = body.smtp_host
        u.smtp_port = body.smtp_port
        u.smtp_username = body.smtp_username
        if body.smtp_password:
            u.smtp_password = body.smtp_password
        u.updated_at = datetime.utcnow()
        db.flush()
        smtp_ok = bool(u.smtp_host and u.smtp_port and u.smtp_username and u.smtp_password)
        return {
            "smtp_configured": smtp_ok,
            "smtp_host": u.smtp_host,
            "smtp_port": u.smtp_port,
            "smtp_username": u.smtp_username,
        }


@app.get("/api/users/smtp-config")
def get_smtp_config(user: User = Depends(current_user)):
    return {
        "smtp_host": user.smtp_host or "",
        "smtp_port": user.smtp_port or 0,
        "smtp_username": user.smtp_username or "",
        "smtp_configured": bool(user.smtp_host and user.smtp_port and user.smtp_username and user.smtp_password),
    }


# ---------------------------------------------------------------------------
# Leads CRUD
# ---------------------------------------------------------------------------


@app.get("/api/leads")
def list_leads(
    user: User = Depends(current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = "",
    outreach_status: str = "",
    is_target: bool | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    with get_db() as db:
        q = db.query(CompanyLead).filter(CompanyLead.user_id == user.id)

        if search:
            like = f"%{search}%"
            q = q.filter(
                CompanyLead.company_name.ilike(like)
                | CompanyLead.website_url.ilike(like)
                | CompanyLead.country.ilike(like)
                | CompanyLead.contact_name.ilike(like)
            )
        if outreach_status:
            q = q.filter(CompanyLead.outreach_status == outreach_status)
        if is_target is not None:
            q = q.filter(CompanyLead.is_target == is_target)

        sort_col = getattr(CompanyLead, sort_by, CompanyLead.created_at)
        if sort_dir == "asc":
            q = q.order_by(sort_col.asc())
        else:
            q = q.order_by(sort_col.desc())

        total = q.count()
        leads = q.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "leads": [_lead_to_dict(l) for l in leads],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, user: User = Depends(current_user)):
    with get_db() as db:
        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id, CompanyLead.user_id == user.id).first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return _lead_to_dict(lead)


@app.post("/api/leads")
def create_lead(body: LeadCreateRequest, user: User = Depends(current_user)):
    with get_db() as db:
        lead = CompanyLead(
            user_id=user.id,
            company_name=body.company_name,
            website_url=body.website_url,
            country=body.country,
            raw_description=body.raw_description,
            source=body.source or "manual",
            contact_name=body.contact_name,
            contact_email=body.contact_email,
            contact_title=body.contact_title,
            contact_phone=body.contact_phone,
        )
        db.add(lead)
        db.flush()
        return _lead_to_dict(lead)


@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id: int, body: LeadUpdateRequest, user: User = Depends(current_user)):
    with get_db() as db:
        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id, CompanyLead.user_id == user.id).first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        updates = body.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(lead, key, value)
        lead.updated_at = datetime.utcnow()
        db.flush()
        return _lead_to_dict(lead)


@app.delete("/api/leads/{lead_id}")
def delete_lead(lead_id: int, user: User = Depends(current_user)):
    with get_db() as db:
        lead = db.query(CompanyLead).filter(CompanyLead.id == lead_id, CompanyLead.user_id == user.id).first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        db.delete(lead)
        return {"deleted": True}


# ---------------------------------------------------------------------------
# Outreach logs
# ---------------------------------------------------------------------------


@app.get("/api/outreach")
def list_outreach(
    user: User = Depends(current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    channel: str = "",
    success: bool | None = None,
):
    with get_db() as db:
        q = db.query(OutreachLog).filter(OutreachLog.user_id == user.id)
        if channel:
            q = q.filter(OutreachLog.channel == channel)
        if success is not None:
            q = q.filter(OutreachLog.success == success)

        total = q.count()
        logs = q.order_by(OutreachLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

        return {
            "logs": [
                {
                    "id": l.id,
                    "lead_id": l.lead_id,
                    "channel": l.channel,
                    "recipient_email": l.recipient_email,
                    "recipient_phone": l.recipient_phone,
                    "subject": l.subject,
                    "body": l.body,
                    "message_id": l.message_id,
                    "success": l.success,
                    "error_message": l.error_message,
                    "created_at": l.created_at.isoformat() if l.created_at else "",
                }
                for l in logs
            ],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------


@app.get("/api/dashboard/stats")
def dashboard_stats(user: User = Depends(current_user)):
    with get_db() as db:
        total_leads = db.query(CompanyLead).filter(CompanyLead.user_id == user.id).count()
        target_leads = db.query(CompanyLead).filter(
            CompanyLead.user_id == user.id, CompanyLead.is_target == True
        ).count()
        contacted = db.query(CompanyLead).filter(
            CompanyLead.user_id == user.id,
            CompanyLead.outreach_status.in_(["sent", "replied"]),
        ).count()
        replied = db.query(CompanyLead).filter(
            CompanyLead.user_id == user.id, CompanyLead.outreach_status == "replied"
        ).count()
        total_outreach = db.query(OutreachLog).filter(OutreachLog.user_id == user.id).count()
        successful_outreach = db.query(OutreachLog).filter(
            OutreachLog.user_id == user.id, OutreachLog.success == True
        ).count()

        # Leads by country (top 10)
        from sqlalchemy import func
        country_rows = (
            db.query(CompanyLead.country, func.count(CompanyLead.id))
            .filter(CompanyLead.user_id == user.id, CompanyLead.country != "")
            .group_by(CompanyLead.country)
            .order_by(func.count(CompanyLead.id).desc())
            .limit(10)
            .all()
        )

        # Leads by source
        source_rows = (
            db.query(CompanyLead.source, func.count(CompanyLead.id))
            .filter(CompanyLead.user_id == user.id)
            .group_by(CompanyLead.source)
            .all()
        )

        # Recent activity (last 30 days)
        thirty_days_ago = datetime.utcnow().timestamp() - 86400 * 30
        recent_added = db.query(CompanyLead).filter(
            CompanyLead.user_id == user.id,
        ).all()
        recent_added = sum(1 for l in recent_added if l.created_at and l.created_at.timestamp() > thirty_days_ago)

        return {
            "total_leads": total_leads,
            "target_leads": target_leads,
            "contacted": contacted,
            "replied": replied,
            "total_outreach": total_outreach,
            "successful_outreach": successful_outreach,
            "conversion_rate": round(replied / max(contacted, 1) * 100, 1),
            "by_country": [{"country": c or "Unknown", "count": n} for c, n in country_rows],
            "by_source": [{"source": s or "Unknown", "count": n} for s, n in source_rows],
            "recent_added": recent_added,
        }


# ---------------------------------------------------------------------------
# Pipeline trigger (runs scraper → filter → contacts → outreach in background)
# ---------------------------------------------------------------------------


_pipeline_status: dict[str, dict] = {}


@app.post("/api/pipeline/run")
def run_pipeline(body: PipelineRequest, user: User = Depends(current_user)):
    job_id = secrets.token_hex(8)
    _pipeline_status[job_id] = {"status": "queued", "progress": 0, "result": None, "error": None}

    def _execute():
        try:
            _pipeline_status[job_id]["status"] = "running"
            _pipeline_status[job_id]["progress"] = 10

            # Stage 1: Scrape
            from scraper import create_aggregator
            aggregator = create_aggregator(
                google_api_key=os.getenv("GOOGLE_API_KEY", ""),
                google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
                linkedin_token=os.getenv("LINKEDIN_ACCESS_TOKEN", ""),
                apollo_key=os.getenv("APOLLO_API_KEY", ""),
            )
            raw_leads = aggregator.scrape(
                keyword=body.keyword, region=body.region, max_per_source=body.max_leads,
                progress_cb=lambda p: _pipeline_status.__setitem__(job_id, {**_pipeline_status[job_id], "progress": p}),
            )
            _pipeline_status[job_id]["progress"] = 30

            if not raw_leads:
                _pipeline_status[job_id]["status"] = "completed"
                _pipeline_status[job_id]["result"] = {"leads_found": 0, "leads_passed": 0, "contacts_found": 0, "outreach_sent": 0}
                return

            # Stage 2: LLM Filter
            from filters import LeadFilter, FilterCriteria, LLMClient
            criteria = FilterCriteria(
                required_capabilities=["OEM", "ODM", "manufacturing", "customization"],
                excluded_regions=[],
            )
            llm_client = LLMClient()
            filter_engine = LeadFilter(criteria=criteria, llm=llm_client)
            lead_dicts = [
                {
                    "company_name": l.company_name,
                    "website_url": l.website_url,
                    "country": l.country,
                    "raw_description": l.raw_description,
                    "source": l.source,
                    "source_rank": str(l.source_rank),
                }
                for l in raw_leads
            ]
            passed = filter_engine.filter_batch_sync(lead_dicts)
            _pipeline_status[job_id]["progress"] = 50

            if not passed:
                _pipeline_status[job_id]["status"] = "completed"
                _pipeline_status[job_id]["result"] = {"leads_found": len(raw_leads), "leads_passed": 0, "contacts_found": 0, "outreach_sent": 0}
                return

            # Stage 3: Contact Discovery
            from contacts import ContactFinder
            finder = ContactFinder()
            total_passed = len(passed)
            enriched = []
            for i, lead in enumerate(passed):
                try:
                    domain = lead.get("website_url", "").replace("www.", "").strip()
                    if not domain:
                        continue
                    target_titles = [lead.get("decision_maker_title", "")]
                    if not target_titles[0]:
                        target_titles = ["Purchasing Manager", "Sourcing Manager", "Owner", "VP"]
                    contacts = finder.find_contacts(domain=domain, target_titles=target_titles, max_contacts=2)
                    if contacts:
                        best = contacts[0]
                        e = dict(lead)
                        e["contact_name"] = best.full_name
                        e["contact_email"] = best.email
                        e["contact_title"] = best.title
                        enriched.append(e)
                except Exception:
                    logger.warning("Contact discovery failed for %s", lead.get("company_name", "?"))
                # Stepped progress from 50 → 65 during contact discovery
                _pipeline_status[job_id]["progress"] = 50 + int((i + 1) / max(total_passed, 1) * 15)

            _pipeline_status[job_id]["progress"] = 70

            # Stage 4: Outreach
            from outreach import OutreachTarget, OutreachOrchestrator, EmailSender
            channels = tuple(c.strip() for c in body.channels.split(",") if c.strip())
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
                for t in enriched
            ]

            # Build per-user EmailSender from their saved SMTP config
            email_sender = None
            if user.smtp_host and user.smtp_port and user.smtp_username and user.smtp_password:
                email_sender = EmailSender(
                    host=user.smtp_host,
                    port=user.smtp_port,
                    username=user.smtp_username,
                    password=user.smtp_password,
                )
            orchestrator = OutreachOrchestrator(
                sender_name=os.getenv("SENDER_NAME", "Alex Chen"),
                sender_company=os.getenv("SENDER_COMPANY", "GlobalComp Manufacturing"),
                email_sender=email_sender,
            )
            results = orchestrator.run(targets=targets, channels=channels, dry_run=body.dry_run)
            _pipeline_status[job_id]["progress"] = 90

            # Persist results to the database
            db = SessionLocal()
            try:
                for t in enriched:
                    existing = db.query(CompanyLead).filter(
                        CompanyLead.user_id == user.id,
                        CompanyLead.company_name == t["company_name"],
                        CompanyLead.website_url == t.get("website_url", ""),
                    ).first()
                    if not existing:
                        lead = CompanyLead(
                            user_id=user.id,
                            company_name=t["company_name"],
                            website_url=t.get("website_url", ""),
                            country=t.get("country", ""),
                            raw_description=t.get("raw_description", ""),
                            source=t.get("source", ""),
                            is_target=True,
                            intent_score=int(t.get("intent_score", 0)),
                            decision_maker_title=t.get("decision_maker_title", ""),
                            filter_reason=t.get("filter_reason", ""),
                            contact_name=t.get("contact_name", ""),
                            contact_email=t.get("contact_email", ""),
                            contact_title=t.get("contact_title", ""),
                            contact_phone=t.get("contact_phone", ""),
                            outreach_status="sent" if not body.dry_run else "pending",
                            outreach_channel=body.channels,
                        )
                        db.add(lead)
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

            _pipeline_status[job_id]["status"] = "completed"
            _pipeline_status[job_id]["progress"] = 100
            _pipeline_status[job_id]["result"] = {
                "leads_found": len(raw_leads),
                "leads_passed": len(passed),
                "contacts_found": len(enriched),
                "outreach_sent": sum(1 for r in results if r.success),
                "dry_run": body.dry_run,
            }
        except Exception as exc:
            logger.exception("Pipeline job %s failed", job_id)
            _pipeline_status[job_id]["status"] = "failed"
            _pipeline_status[job_id]["error"] = str(exc)

    thread = threading.Thread(target=_execute, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/pipeline/status/{job_id}")
def pipeline_status(job_id: str, user: User = Depends(current_user)):
    job = _pipeline_status.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lead_to_dict(lead: CompanyLead) -> dict:
    return {
        "id": lead.id,
        "company_name": lead.company_name,
        "website_url": lead.website_url,
        "country": lead.country,
        "raw_description": lead.raw_description,
        "source": lead.source,
        "is_target": lead.is_target,
        "intent_score": lead.intent_score,
        "decision_maker_title": lead.decision_maker_title,
        "filter_reason": lead.filter_reason,
        "contact_name": lead.contact_name,
        "contact_email": lead.contact_email,
        "contact_title": lead.contact_title,
        "contact_phone": lead.contact_phone,
        "email_verified": lead.email_verified,
        "email_status": lead.email_status,
        "outreach_status": lead.outreach_status,
        "outreach_channel": lead.outreach_channel,
        "created_at": lead.created_at.isoformat() if lead.created_at else "",
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else "",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

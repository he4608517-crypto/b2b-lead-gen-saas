"""
SQLAlchemy ORM models for the multi-tenant B2B Lead Gen SaaS.

Tables:
  - users           (authentication / tenant identity)
  - companies_pool  (filtered leads tied to a user)
  - outreach_logs   (outreach attempts tied to a user)
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(255), nullable=False)
    company = Column(String(255), default="")
    plan = Column(String(32), default="free")  # free / pro / enterprise

    # Per-tenant SMTP configuration (stored per-user for multi-tenant isolation)
    smtp_host = Column(String(255), default="")
    smtp_port = Column(Integer, default=0)
    smtp_username = Column(String(255), default="")
    smtp_password = Column(String(255), default="")  # NOTE: production should encrypt at rest

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # relationships
    leads = relationship("CompanyLead", back_populates="owner", cascade="all, delete-orphan")
    outreach_entries = relationship("OutreachLog", back_populates="owner", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# companies_pool
# ---------------------------------------------------------------------------


class CompanyLead(Base):
    __tablename__ = "companies_pool"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # lead data
    company_name = Column(String(255), nullable=False)
    website_url = Column(String(512), default="")
    country = Column(String(128), default="")
    raw_description = Column(Text, default="")
    source = Column(String(64), default="")  # google_search / linkedin / apollo

    # filter results
    is_target = Column(Boolean, default=False)
    intent_score = Column(Integer, default=0)
    decision_maker_title = Column(String(255), default="")
    filter_reason = Column(Text, default="")

    # contact info
    contact_name = Column(String(255), default="")
    contact_email = Column(String(255), default="")
    contact_title = Column(String(255), default="")
    contact_phone = Column(String(64), default="")
    email_verified = Column(Boolean, default=False)
    email_status = Column(String(32), default="")

    # outreach state
    outreach_status = Column(String(32), default="pending")  # pending / sent / failed / replied
    outreach_channel = Column(String(32), default="")

    # CRM sales pipeline
    lead_stage = Column(String(32), default="New")  # New / Contacted / Replied / Negotiating / Won / Lost
    last_contacted_at = Column(DateTime, default=None)
    follow_up_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # relationships
    owner = relationship("User", back_populates="leads")


# ---------------------------------------------------------------------------
# outreach_logs
# ---------------------------------------------------------------------------


class OutreachLog(Base):
    __tablename__ = "outreach_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("companies_pool.id", ondelete="SET NULL"), nullable=True)

    channel = Column(String(32), nullable=False)  # email / whatsapp
    recipient_email = Column(String(255), default="")
    recipient_phone = Column(String(64), default="")
    subject = Column(String(512), default="")
    body = Column(Text, default="")
    message_id = Column(String(128), default="")
    success = Column(Boolean, default=False)
    error_message = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # relationships
    owner = relationship("User", back_populates="outreach_entries")

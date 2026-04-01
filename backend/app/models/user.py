"""
EWC Compute — User Pydantic models.

Hierarchy: Organization → User → Project
Every API request resolves to a User via JWT (JSON Web Token). Role governs RBAC.

Collections:
  users         — one document per user
  organizations — one document per org (Team / Enterprise tiers)

Data isolation rule: every database query that returns project or engineering
objects MUST include a user_id or org_id filter. Isolation at the query level,
not only at the API level. See CONTRIBUTING.md §Code Standards.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from beanie import Document, Indexed
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────

class UserRole(StrEnum):
    """
    RBAC roles. Checked in route dependencies, not in business logic.

    individual  — solo engineer or consultant (Free / Professional tier)
    team_lead   — manages shared projects and invites members (Team tier)
    admin       — full platform access including user management (Enterprise)
    """
    INDIVIDUAL = "individual"
    TEAM_LEAD  = "team_lead"
    ADMIN      = "admin"


class SubscriptionTier(StrEnum):
    """
    Commercial tier. Controls feature gates and usage limits.

    free         — 1 project, 3 twin creations/month, community templates
    professional — 10 projects, unlimited twins, full template library, AI Assistant
    team         — all professional + shared workspaces, up to 10 seats
    enterprise   — custom limits, on-premise option, dedicated SLA
    """
    FREE         = "free"
    PROFESSIONAL = "professional"
    TEAM         = "team"
    ENTERPRISE   = "enterprise"


# ── Token models ──────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    """JWT payload — validated by security.py on every authenticated request."""
    sub: str                              # user_id (MongoDB ObjectId as string)
    role: UserRole
    org_id: str | None = None             # None for individual / free tier
    exp: int                              # Unix timestamp


class TokenPair(BaseModel):
    """Returned by /auth/login and /auth/refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ── Request / Response models ─────────────────────────────────────────────

class UserCreate(BaseModel):
    """POST /auth/register request body."""
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    full_name: Annotated[str, Field(min_length=1, max_length=120)]

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        """Basic complexity: at least one digit and one letter."""
        has_digit  = any(c.isdigit() for c in v)
        has_letter = any(c.isalpha() for c in v)
        if not (has_digit and has_letter):
            raise ValueError("Password must contain at least one letter and one digit.")
        return v


class UserLogin(BaseModel):
    """POST /auth/login request body."""
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """Safe user representation returned in API responses — no hashed_password."""
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    tier: SubscriptionTier
    org_id: str | None
    created_at: datetime
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    """PATCH /users/me — partial update."""
    full_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None


# ── Database document ─────────────────────────────────────────────────────

class User(Document):
    """
    MongoDB document. Stored in the 'users' collection.

    hashed_password is NEVER returned in API responses.
    UserPublic is the outward-facing model.
    """
    email: Annotated[str, Indexed(unique=True)]
    hashed_password: str
    full_name: str
    role: UserRole = UserRole.INDIVIDUAL
    tier: SubscriptionTier = SubscriptionTier.FREE
    org_id: str | None = None              # None = individual; set for Team / Enterprise
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [
            "email",                       # Unique index (enforced by Indexed above)
            "org_id",                      # Organisation membership lookup
        ]

    def to_public(self) -> UserPublic:
        """Return safe public representation — never expose hashed_password."""
        return UserPublic(
            id=str(self.id),
            email=self.email,
            full_name=self.full_name,
            role=self.role,
            tier=self.tier,
            org_id=self.org_id,
            created_at=self.created_at,
            last_login_at=self.last_login_at,
        )

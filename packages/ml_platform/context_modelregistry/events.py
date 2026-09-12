"""Domain events shared across contexts.

Events are the *only* way bounded contexts communicate. They carry enough
context to be attributable (who/when) — the auditability requirement — and
drive both the audit log and Sentry attribution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Stage(str, Enum):
    NONE = "none"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DomainEvent:
    """Base event — every event carries attribution + timestamp (ALCOA-aware).

    kw_only on the defaulted fields keeps them out of positional ordering so
    subclasses can declare required fields freely.
    """

    occurred_at: datetime = field(default_factory=utcnow, kw_only=True)
    actor: str = field(default="system", kw_only=True)  # user id or "system"
    actor_role: str = field(default="system", kw_only=True)


@dataclass(frozen=True)
class ModelVersionRegistered(DomainEvent):
    version_id: str
    model_name: str
    run_id: str
    artifact_uri: str


@dataclass(frozen=True)
class ModelPromotedToStaging(DomainEvent):
    version_id: str
    model_name: str


@dataclass(frozen=True)
class PromotionApprovalRequested(DomainEvent):
    """Raised when a version enters the staging->production approval gate."""

    version_id: str
    model_name: str
    workflow_id: str


@dataclass(frozen=True)
class ModelPromotedToProduction(DomainEvent):
    version_id: str
    model_name: str
    workflow_id: str
    approved_by: str


@dataclass(frozen=True)
class ModelRolledBack(DomainEvent):
    version_id: str
    model_name: str
    previous_version_id: str


@dataclass(frozen=True)
class RoutingWeightsChanged(DomainEvent):
    model_name: str
    weights: dict


@dataclass(frozen=True)
class DriftDetected(DomainEvent):
    model_name: str
    version_id: str
    metric: str
    value: float
    threshold: float

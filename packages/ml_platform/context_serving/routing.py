"""Serving bounded context.

The aggregate here is `RoutingPolicy` — the weight-based canary / blue-green
traffic table for one model. Weights map version_id -> int %, normalised to 100.
A rollback is just a policy set to 100% on the target version (blue-green flip).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingPolicy:
    model_name: str
    _weights: dict[str, int] = field(default_factory=dict)
    _production: str = ""

    def set_weights(self, weights: dict[str, int]) -> None:
        """Set per-version percentages (canary). Caller ensures they sum to 100."""
        total = sum(weights.values())
        if not weights:
            raise ValueError("weights must be non-empty")
        if total != 100:
            raise ValueError(f"weights must sum to 100, got {total}")
        self._weights = dict(weights)

    def add_canary(self, version_id: str, percent: int) -> None:
        """Carve `percent` out of the current production version for a canary."""
        current = dict(self._weights)
        live = current.get(self._production)
        if live is not None and live > percent:
            current[self._production] = live - percent
        elif live is not None:
            del current[self._production]
        current[version_id] = percent
        self.set_weights(current)

    def rollback_to(self, version_id: str) -> None:
        """Blue-green rollback: route 100% to the target version."""
        self._weights = {version_id: 100}
        self._production = version_id

    def promote_to(self, version_id: str) -> None:
        """Promotion = clean blue-green flip: 100% to the new version.

        A canary slice is then carved out separately via add_canary.
        """
        self._production = version_id
        self._weights = {version_id: 100}

    @property
    def weights(self) -> dict[str, int]:
        return dict(self._weights)

    @property
    def production_version(self) -> str:
        return self._production

    @property
    def canary_versions(self) -> list[str]:
        return [v for v, w in self._weights.items() if v != self._production]

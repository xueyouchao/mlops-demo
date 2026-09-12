"""HTTP client for syncing the serving router from the api lifecycle facade."""
from __future__ import annotations

import httpx

from .config import get_settings

_settings = get_settings()


def _headers() -> dict:
    return {"X-Internal-Token": _settings.internal_service_token}


def sync_routing(weights: dict[str, int]) -> None:
    """Push the current routing weights to the serving router (canary config)."""
    try:
        resp = httpx.post(
            f"{_settings.serving_url}/v1/routing",
            json={"weights": weights},
            headers=_headers(),
            timeout=3.0,
        )
        resp.raise_for_status()
    except Exception:
        # Serving sync is best-effort for the demo; do not break the lifecycle.
        # In production this retries with backoff and raises on persistent failure.
        import logging
        logging.getLogger("build1.api").warning("serving routing sync failed", exc_info=True)


def sync_rollback(version_id: str) -> None:
    try:
        resp = httpx.post(
            f"{_settings.serving_url}/v1/rollback",
            json={"version_id": version_id},
            headers=_headers(),
            timeout=3.0,
        )
        resp.raise_for_status()
    except Exception:
        import logging
        logging.getLogger("build1.api").warning("serving rollback sync failed", exc_info=True)

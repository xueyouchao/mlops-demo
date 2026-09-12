"""Temporal worker entrypoint.

Runs the workflows/activities and registers against the Temporal server so the
api service's promote/rollback calls are durably executed.
"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from activities import promote_stage, rollback_stage
from workflows import PromotionWorkflow, RollbackWorkflow

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))

SENTRY_DSN = os.getenv("SENTRY_DSN", "")


async def main() -> None:
    if SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, environment=os.getenv("SENTRY_ENV", "development"))

    client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
    worker = Worker(
        client,
        task_queue="ml-lifecycle",
        workflows=[PromotionWorkflow, RollbackWorkflow],
        activities=[promote_stage, rollback_stage],
        activity_executor=ThreadPoolExecutor(max_workers=4),
    )
    print("mlops-demo worker connected, starting...", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

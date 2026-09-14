"""Temporal worker entrypoint.

Runs the workflows/activities and registers against the Temporal server so the
api service's promote and train calls are durably executed.
"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from activities import brain_decide, promote_stage, train_and_register
from tools import (
    conclude,
    evaluate_version,
    promotion_outcome,
    propose_promotion,
    read_registry,
    read_run_metrics,
    train_candidate,
)
from workflows import InvestigationWorkflow, PromotionWorkflow, TrainingWorkflow

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))

SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Tracing, not just error capture. The worker is where the agent's brain runs,
# and until this was set it produced no span at all: `sentry_sdk.init` without a
# sample rate means every span `brain.py` opens is created, finished, and then
# dropped at the transport — so Sentry's LLM views had nothing to read even once
# the model call was instrumented. A demo makes a handful of calls per run, so
# the default keeps all of them; `SENTRY_TRACES_SAMPLE_RATE=0` turns it off
# without touching the code. The api keeps its own, separate 0.25.
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0"))

# Prompt and output capture is a *privacy* decision, not a technical one, so it
# is off by default and the operator turns it on — deliberately at the call site
# rather than in this file, so a deployment that configures nothing captures
# nothing. Python's SDK gates `gen_ai.input.messages` / `gen_ai.output.messages`
# behind `send_default_pii`, and Explore > Conversations reconstructs the chat
# from exactly those attributes — so without this the conversation is still
# grouped (the run's `gen_ai.conversation.id` is set either way) but its timeline
# renders empty. What would be captured here is the operator's goal and the
# registry/metric digests the agent read, not end-user content.
# `docker-compose.yml` sets it to 1 for this demo's worker — a choice made
# explicitly by the operator, after being told what it captures, not a default.
SENTRY_SEND_DEFAULT_PII = os.getenv("SENTRY_SEND_DEFAULT_PII", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


async def main() -> None:
    if SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=os.getenv("SENTRY_ENV", "development"),
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            # Explicit, though it is the default from 2.64 on: it is why the
            # agent and model spans travel as their own envelope items in the
            # format the Sentry LLM views read, instead of riding inside a
            # transaction payload. Stated here so that a future default cannot
            # change the shape silently.
            stream_gen_ai_spans=True,
            send_default_pii=SENTRY_SEND_DEFAULT_PII,
        )

    client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
    worker = Worker(
        client,
        task_queue="ml-lifecycle",
        workflows=[PromotionWorkflow, TrainingWorkflow, InvestigationWorkflow],
        activities=[
            promote_stage, train_and_register, brain_decide,
            # the agent's six tools — every tool is an activity (T01)
            read_registry, read_run_metrics, evaluate_version,
            train_candidate, propose_promotion, conclude,
            promotion_outcome,
        ],
        activity_executor=ThreadPoolExecutor(max_workers=4),
    )
    print("mlops-demo worker connected, starting...", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

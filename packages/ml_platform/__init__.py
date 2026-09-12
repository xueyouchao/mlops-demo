"""Shared domain package for Build1 — the DDD core.

Bounded contexts (each its own subpackage):
  - context_modelregistry : what *is* a registered model version, and its stage.
  - context_lifecycle     : the orchestration of promotion / rollback / retrain.
  - context_serving       : how traffic is routed to versions (canary / blue-green).

Each context owns its aggregates, value objects, domain events, and repository
interfaces. Cross-context communication happens only via domain events.
"""

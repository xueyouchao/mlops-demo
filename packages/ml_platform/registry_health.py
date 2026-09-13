"""Pre-flight check: can this model version actually serve traffic?

A version is servable only if its artifact can be read back out of the registry.
Promotion is effectively irreversible in this platform — serving re-points at
whatever the registry calls Production — so this is answered *before* a version
is allowed into Production, rather than discovered when the first prediction
arrives as a 503.

This is deliberately a reachability check and not a model load. The api and the
worker do not pin the same scikit-learn version as the trainer, so unpickling
here could reject a perfectly good model because of a local dependency mismatch.
Listing the artifact exercises the same resolution path serving uses, so
"reachable here" means "reachable there".
"""
from __future__ import annotations

from mlflow.tracking import MlflowClient

_MODEL_SUBDIR = "model"
_MARKER = "MLmodel"


def artifact_problem(tracking_uri: str, model_name: str, version: str) -> str | None:
    """Return why `version` cannot serve, or None when its artifact reads back fine."""
    try:
        client = MlflowClient(tracking_uri=tracking_uri)
        mv = client.get_model_version(model_name, version)
        if not mv.run_id:
            return "the registry records no run for it"
        entries = client.list_artifacts(mv.run_id, _MODEL_SUBDIR)
    except Exception as exc:
        # Missing/unreadable artifact, unreachable tracking server, unknown
        # version: all of them mean the same thing to a caller — not servable.
        return f"its artifact cannot be read from the registry ({type(exc).__name__})"

    if not entries:
        return "its artifact directory is missing from the registry"
    if not any(e.path.endswith(_MARKER) for e in entries):
        return f"its artifact directory has no {_MARKER} marker"
    return None

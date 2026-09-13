"""Model Registry bounded context.

The aggregate here is `Model` — the stable identity that owns a family of
registered versions. The `ModelVersion` value records one immutable version
and its lifecycle stage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .events import (
    DomainEvent,
    ModelPromotedToProduction,
    ModelRolledBack,
    ModelVersionRegistered,
    Stage,
)


@dataclass(frozen=True)
class ModelVersion:
    """An immutable, registered version of a model.

    Immutability is what makes rollback cheap: a version never changes after
    registration, so it is always a valid rollback target.
    """

    version_id: str
    model_name: str
    run_id: str
    artifact_uri: str
    stage: Stage = Stage.NONE

    @property
    def is_live(self) -> bool:
        return self.stage == Stage.PRODUCTION


@dataclass
class Model:
    """Aggregate root for a named model and its version family."""

    name: str
    _versions: dict = field(default_factory=dict)
    _production_pointer: str | None = None

    def add_version(self, version_id: str, run_id: str, artifact_uri: str) -> ModelVersion:
        v = ModelVersion(
            version_id=version_id,
            model_name=self.name,
            run_id=run_id,
            artifact_uri=artifact_uri,
            stage=Stage.STAGING,  # freshly registered -> staging, awaiting human gate
        )
        self._versions[version_id] = v
        return v

    def sync_from_registry(self, records: list[tuple[str, str, str, Stage]]) -> list[str]:
        """Adopt versions the read model does not know about yet.

        The aggregates here are an in-memory read model, while MLflow is the
        registry of record, so the model has to be re-built from MLflow after a
        restart. Hydration is deliberately *additive*: a version already held in
        memory is never rewritten, so the running process's own promotions and
        canary decisions stay authoritative until it restarts.

        If more than one version is live in the registry (MLflow permits that
        unless promotions archive their predecessor), the *highest* one wins —
        it is the most recent promotion, and it is what an operator expects to
        be serving.

        `records` is `(version_id, run_id, artifact_uri, stage)`, oldest first.
        Returns the ids that were added.
        """
        added: list[str] = []
        live: str | None = None

        for version_id, run_id, artifact_uri, stage in records:
            if stage is Stage.PRODUCTION:
                live = version_id
            if version_id in self._versions:
                continue
            self._versions[version_id] = ModelVersion(
                version_id=version_id,
                model_name=self.name,
                run_id=run_id,
                artifact_uri=artifact_uri,
                stage=stage,
            )
            added.append(version_id)

        # Only adopt the registry's live version if we do not already point at
        # one, so an in-session promotion is not overwritten by a later refresh.
        if self._production_pointer is None and live is not None:
            self._production_pointer = live

        return added

    def promote_to_production(self, version_id: str, approved_by: str = "system") -> ModelVersion:
        v = self._versions[version_id]
        self._versions[version_id] = _with_stage(v, Stage.PRODUCTION)
        self._production_pointer = version_id
        return v

    def rollback(self, to_version_id: str) -> ModelVersion:
        target = self._versions[to_version_id]
        self._versions[to_version_id] = _with_stage(target, Stage.PRODUCTION)
        # un-stage the current production pointer (demote to staging)
        if self._production_pointer and self._production_pointer in self._versions:
            cur = self._versions[self._production_pointer]
            self._versions[self._production_pointer] = _with_stage(cur, Stage.STAGING)
        self._production_pointer = to_version_id
        return target

    @property
    def production_version(self) -> ModelVersion | None:
        if self._production_pointer:
            return self._versions.get(self._production_pointer)
        return None

    @property
    def versions(self) -> list[ModelVersion]:
        return list(self._versions.values())


def _with_stage(v: ModelVersion, stage: Stage) -> ModelVersion:
    return ModelVersion(**{**v.__dict__, "stage": stage})

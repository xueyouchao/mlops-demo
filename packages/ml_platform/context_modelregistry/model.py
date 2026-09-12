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

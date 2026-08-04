from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Literal, TypeAlias

from sqlmodel import Session, select

from app.db.models import utc_now
from app.platform_assistant.governance import record_governance_event
from app.platform_assistant.safety_models import AssistantTenantFeatureFlag


AssistantStage: TypeAlias = Literal[
    "disabled",
    "read_only",
    "requirement_copilot",
    "beta",
]
VALID_STAGES = frozenset(
    {"disabled", "read_only", "requirement_copilot", "beta"}
)
FEATURE_KEY = "platform_assistant"


@dataclass(frozen=True, slots=True)
class FeatureFlagDefaults:
    stage: AssistantStage = "requirement_copilot"
    rollout_percentage: int = 100
    bucket_salt: str = "kx7-v1"

    def __post_init__(self) -> None:
        _validate_stage(self.stage)
        _validate_percentage(self.rollout_percentage)
        if not self.bucket_salt.strip():
            raise ValueError("bucket_salt is required")

    @classmethod
    def from_environment(cls) -> FeatureFlagDefaults:
        """Load deploy-time defaults while preserving current behaviour.

        With no environment variables, every authenticated tenant remains in
        the requirement-copilot cohort, matching the pre-KX-7 behaviour.
        """

        stage = os.getenv(
            "KGB_PLATFORM_ASSISTANT_DEFAULT_STAGE", "requirement_copilot"
        ).strip()
        percentage_text = os.getenv(
            "KGB_PLATFORM_ASSISTANT_DEFAULT_ROLLOUT_PERCENTAGE", "100"
        ).strip()
        salt = os.getenv("KGB_PLATFORM_ASSISTANT_ROLLOUT_SALT", "kx7-v1").strip()
        try:
            percentage = int(percentage_text)
        except ValueError as exc:
            raise ValueError(
                "KGB_PLATFORM_ASSISTANT_DEFAULT_ROLLOUT_PERCENTAGE must be an integer"
            ) from exc
        return cls(
            stage=_validate_stage(stage),
            rollout_percentage=percentage,
            bucket_salt=salt,
        )


@dataclass(frozen=True, slots=True)
class FeatureFlagDecision:
    tenant_id: str
    user_id: str
    configured_stage: AssistantStage
    effective_stage: AssistantStage
    rollout_percentage: int
    bucket: int
    included: bool
    source: Literal["tenant", "default"]
    reason: str

    @property
    def assistant_enabled(self) -> bool:
        return self.effective_stage != "disabled"

    @property
    def read_allowed(self) -> bool:
        return self.effective_stage in {
            "read_only",
            "requirement_copilot",
            "beta",
        }

    @property
    def requirement_draft_write_allowed(self) -> bool:
        return self.effective_stage in {"requirement_copilot", "beta"}

    @property
    def beta_allowed(self) -> bool:
        return self.effective_stage == "beta"


class AssistantFeatureFlagService:
    def __init__(
        self,
        db: Session,
        *,
        defaults: FeatureFlagDefaults | None = None,
    ) -> None:
        self.db = db
        self.defaults = defaults or FeatureFlagDefaults.from_environment()

    def evaluate(self, *, tenant_id: str, user_id: str) -> FeatureFlagDecision:
        tenant = _required_id("tenant_id", tenant_id)
        user = _required_id("user_id", user_id)
        row = self.db.exec(
            select(AssistantTenantFeatureFlag).where(
                AssistantTenantFeatureFlag.tenant_id == tenant,
                AssistantTenantFeatureFlag.feature_key == FEATURE_KEY,
            )
        ).first()
        stage: AssistantStage
        source: Literal["tenant", "default"]
        if row is None:
            stage = self.defaults.stage
            percentage = self.defaults.rollout_percentage
            salt = self.defaults.bucket_salt
            source = "default"
        else:
            stage = _validate_stage(row.stage)
            percentage = _validate_percentage(row.rollout_percentage)
            salt = row.bucket_salt
            source = "tenant"
        bucket = stable_user_bucket(
            tenant_id=tenant,
            user_id=user,
            feature_key=FEATURE_KEY,
            salt=salt,
        )
        included = bucket < percentage * 100
        effective: AssistantStage = stage if included else "disabled"
        return FeatureFlagDecision(
            tenant_id=tenant,
            user_id=user,
            configured_stage=stage,
            effective_stage=effective,
            rollout_percentage=percentage,
            bucket=bucket,
            included=included,
            source=source,
            reason="configured_stage" if included else "rollout_excluded",
        )

    def configure_tenant(
        self,
        *,
        tenant_id: str,
        stage: AssistantStage,
        rollout_percentage: int,
        actor_user_id: str,
        expected_row_version: int | None = None,
        bucket_salt: str = "kx7-v1",
    ) -> AssistantTenantFeatureFlag:
        tenant = _required_id("tenant_id", tenant_id)
        actor = _required_id("actor_user_id", actor_user_id)
        resolved_stage = _validate_stage(stage)
        percentage = _validate_percentage(rollout_percentage)
        salt = _required_id("bucket_salt", bucket_salt)
        row = self.db.exec(
            select(AssistantTenantFeatureFlag).where(
                AssistantTenantFeatureFlag.tenant_id == tenant,
                AssistantTenantFeatureFlag.feature_key == FEATURE_KEY,
            )
        ).first()
        previous: dict[str, object] | None = None
        if row is None:
            if expected_row_version not in (None, 0):
                raise FeatureFlagVersionConflict("feature flag does not yet exist")
            row = AssistantTenantFeatureFlag(
                tenant_id=tenant,
                stage=resolved_stage,
                rollout_percentage=percentage,
                bucket_salt=salt,
                created_by_user_id=actor,
                updated_by_user_id=actor,
            )
        else:
            if (
                expected_row_version is not None
                and row.row_version != expected_row_version
            ):
                raise FeatureFlagVersionConflict(
                    f"expected row version {expected_row_version}, current is {row.row_version}"
                )
            previous = {
                "stage": row.stage,
                "rollout_percentage": row.rollout_percentage,
                "row_version": row.row_version,
            }
            row.stage = resolved_stage
            row.rollout_percentage = percentage
            row.bucket_salt = salt
            row.row_version += 1
            row.updated_by_user_id = actor
            row.updated_at = utc_now()
        self.db.add(row)
        self.db.flush()
        record_governance_event(
            self.db,
            tenant_id=tenant,
            user_id=actor,
            event_type="assistant.feature_flag.configured",
            outcome="applied",
            payload={
                "feature_key": FEATURE_KEY,
                "previous": previous,
                "stage": resolved_stage,
                "rollout_percentage": percentage,
                "row_version": row.row_version,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(row)
        return row


class FeatureFlagVersionConflict(RuntimeError):
    code = "FEATURE_FLAG_VERSION_CONFLICT"


def stable_user_bucket(
    *,
    tenant_id: str,
    user_id: str,
    feature_key: str = FEATURE_KEY,
    salt: str = "kx7-v1",
) -> int:
    """Return a deterministic 0..9999 cohort bucket."""

    parts = (
        _required_id("tenant_id", tenant_id),
        _required_id("user_id", user_id),
        _required_id("feature_key", feature_key),
        _required_id("salt", salt),
    )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def _validate_stage(value: str) -> AssistantStage:
    if value not in VALID_STAGES:
        raise ValueError(f"unsupported platform assistant stage: {value!r}")
    return value  # type: ignore[return-value]


def _validate_percentage(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("rollout_percentage must be an integer from 0 to 100")
    return value


def _required_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "AssistantFeatureFlagService",
    "AssistantStage",
    "FEATURE_KEY",
    "FeatureFlagDecision",
    "FeatureFlagDefaults",
    "FeatureFlagVersionConflict",
    "stable_user_bucket",
]

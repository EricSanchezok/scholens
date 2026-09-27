"""Metadata-only protocol for fenced execution and immutable result artifacts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scholens_job_contracts.callbacks import MAX_JOBS_CALLBACK_BODY_BYTES

EXECUTION_LEASE_SECONDS = 180
EXECUTION_HEARTBEAT_SECONDS = 30


class JobExecutionClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claimed: bool
    claim_generation: int | None = Field(default=None, ge=1)
    lease_seconds: int = EXECUTION_LEASE_SECONDS
    retry_after_seconds: int | None = Field(default=None, ge=1, le=180)
    recover_only: bool = False


class JobResultManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_generation: int = Field(ge=1)
    storage_key: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=MAX_JOBS_CALLBACK_BODY_BYTES)
    failure_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$")

    @model_validator(mode="after")
    def validate_immutable_key(self) -> "JobResultManifest":
        parts = self.storage_key.split("/")
        if len(parts) != 5 or parts[:2] != ["jobs", "results"]:
            raise ValueError("Invalid result artifact namespace")
        job_id = UUID(parts[2])
        if self.storage_key != self.key_for(job_id):
            raise ValueError("Result artifact key does not match its manifest")
        return self

    def key_for(self, job_id: UUID) -> str:
        return f"jobs/results/{job_id}/{self.claim_generation}/{self.sha256}.json"


class JobResultReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    claim_generation: int

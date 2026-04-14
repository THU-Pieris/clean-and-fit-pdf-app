from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]


class ArtifactResponse(BaseModel):
    filename: str
    url: str


class JobResultResponse(BaseModel):
    output_filename: str
    page: int
    wrapper_groups: int
    renderer: str
    bbox_pt: dict[str, float]
    size_pt: dict[str, float]
    output_bytes: int
    repair_stats: dict[str, Any] | None = None
    summary_lines: list[str] = Field(default_factory=list)
    download_url: str
    artifacts: dict[str, ArtifactResponse] = Field(default_factory=dict)


class JobStatusResponse(BaseModel):
    job_id: str
    filename: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    result: JobResultResponse | None = None


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    download_url: str

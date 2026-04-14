from __future__ import annotations

import shutil
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from clean_and_fit_pdf import (
    OBJECT_STREAM_CHOICES,
    ProcessingOptions,
    ProcessingResult,
    format_result_summary,
    process_pdf,
)

from .schemas import (
    ArtifactResponse,
    JobCreatedResponse,
    JobResultResponse,
    JobStatusResponse,
)

FINAL_STATUSES = {"succeeded", "failed"}


@dataclass(frozen=True)
class JobSettings:
    page: int = 1
    wrapper_groups: int = 2
    padding: float = 0.0
    acrobat_fix: bool = True
    dpi: int = 1200
    precision: int = 6
    linearize: bool = False
    object_streams: str = "disable"
    keep_temp: bool = False

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("Page must be 1 or greater.")
        if self.wrapper_groups < 0:
            raise ValueError("Wrapper groups must be 0 or greater.")
        if self.padding < 0:
            raise ValueError("Padding must be 0 or greater.")
        if self.dpi <= 0:
            raise ValueError("DPI must be positive.")
        if self.precision < 0:
            raise ValueError("Precision must be 0 or greater.")
        if self.object_streams not in OBJECT_STREAM_CHOICES:
            raise ValueError(
                "Object streams must be one of "
                + ", ".join(sorted(OBJECT_STREAM_CHOICES))
                + "."
            )

    def to_processing_options(
        self,
        input_pdf: Path,
        output_pdf: Path,
        tmp_dir: Path,
    ) -> ProcessingOptions:
        return ProcessingOptions(
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            page=self.page,
            wrapper_groups=self.wrapper_groups,
            padding=self.padding,
            acrobat_fix=self.acrobat_fix,
            dpi=self.dpi,
            precision=self.precision,
            linearize=self.linearize,
            object_streams=self.object_streams,
            tmp_dir=tmp_dir,
            keep_temp=self.keep_temp,
        )


@dataclass
class JobRecord:
    job_id: str
    filename: str
    workdir: Path
    input_path: Path
    output_path: Path
    created_at: datetime
    updated_at: datetime
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: JobResultResponse | None = None
    artifacts: dict[str, Path] = field(default_factory=dict)


class JobStore:
    def __init__(self, data_dir: Path, job_ttl: timedelta) -> None:
        self.data_dir = data_dir
        self.job_ttl = job_ttl
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, filename: str, content: bytes, settings: JobSettings) -> JobCreatedResponse:
        self.cleanup_expired_jobs()

        safe_name = Path(filename or "input.pdf").name or "input.pdf"
        stem = Path(safe_name).stem or "output"
        now = datetime.now(timezone.utc)
        job_id = uuid4().hex
        workdir = self.data_dir / job_id
        input_path = workdir / "input" / safe_name
        output_path = workdir / "output" / f"{stem}.no-outer-rects.exact-fit.pdf"
        temp_dir = workdir / "tmp"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(content)

        record = JobRecord(
            job_id=job_id,
            filename=safe_name,
            workdir=workdir,
            input_path=input_path,
            output_path=output_path,
            created_at=now,
            updated_at=now,
            logs=["Upload received.", "Job queued."],
        )
        with self._lock:
            self._jobs[job_id] = record

        worker = threading.Thread(
            target=self._run_job,
            args=(job_id, settings, temp_dir),
            daemon=True,
        )
        worker.start()

        return JobCreatedResponse(
            job_id=job_id,
            status="queued",
            status_url=f"/api/jobs/{job_id}",
            download_url=f"/api/jobs/{job_id}/download",
        )

    def cleanup_expired_jobs(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.job_ttl
        expired: list[Path] = []

        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.status in FINAL_STATUSES and job.updated_at < cutoff:
                    expired.append(job.workdir)
                    del self._jobs[job_id]

        for workdir in expired:
            shutil.rmtree(workdir, ignore_errors=True)

    def get_status(self, job_id: str) -> JobStatusResponse | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None

            return JobStatusResponse(
                job_id=job.job_id,
                filename=job.filename,
                status=job.status,
                created_at=job.created_at,
                updated_at=job.updated_at,
                logs=list(job.logs),
                error=job.error,
                result=job.result,
            )

    def get_output_path(self, job_id: str) -> tuple[Path, str] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "succeeded" or not job.output_path.exists():
                return None
            return job.output_path, job.output_path.name

    def get_artifact_path(self, job_id: str, artifact_name: str) -> tuple[Path, str] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "succeeded":
                return None
            path = job.artifacts.get(artifact_name)
            if path is None or not path.exists():
                return None
            return path, path.name

    def _append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(message)
            job.updated_at = datetime.now(timezone.utc)

    def _set_status(self, job_id: str, status: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            job.updated_at = datetime.now(timezone.utc)

    def _set_failure(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "failed"
            job.error = error
            job.updated_at = datetime.now(timezone.utc)

    def _set_success(
        self,
        job_id: str,
        result: ProcessingResult,
        artifacts: dict[str, Path],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "succeeded"
            job.result = self._serialize_result(job_id, result, artifacts)
            job.artifacts = dict(artifacts)
            job.updated_at = datetime.now(timezone.utc)

    def _run_job(self, job_id: str, settings: JobSettings, temp_dir: Path) -> None:
        self._set_status(job_id, "running")
        self._append_log(job_id, "Starting PDF cleanup and fit job.")

        with self._lock:
            job = self._jobs[job_id]
            input_path = job.input_path
            output_path = job.output_path

        try:
            result = process_pdf(
                settings.to_processing_options(
                    input_pdf=input_path,
                    output_pdf=output_path,
                    tmp_dir=temp_dir,
                ),
                progress=lambda message: self._append_log(job_id, message),
            )
        except Exception as exc:
            details = "".join(traceback.format_exception(exc))
            self._append_log(job_id, "The job failed.")
            self._append_log(job_id, str(exc))
            self._append_log(job_id, details.rstrip())
            self._set_failure(job_id, str(exc))
            return

        artifacts = result.kept_files or {}
        for line in format_result_summary(result):
            self._append_log(job_id, line)
        self._set_success(job_id, result, artifacts)

    def _serialize_result(
        self,
        job_id: str,
        result: ProcessingResult,
        artifacts: dict[str, Path],
    ) -> JobResultResponse:
        x0, y0, x1, y1 = result.bbox_pt
        width, height = result.size_pt

        return JobResultResponse(
            output_filename=result.output_pdf.name,
            page=result.page,
            wrapper_groups=result.wrapper_groups,
            renderer=result.renderer,
            bbox_pt={
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            },
            size_pt={"width": width, "height": height},
            output_bytes=result.output_bytes,
            repair_stats=result.repair_stats,
            summary_lines=format_result_summary(result),
            download_url=f"/api/jobs/{job_id}/download",
            artifacts={
                name: ArtifactResponse(
                    filename=path.name,
                    url=f"/api/jobs/{job_id}/artifacts/{name}",
                )
                for name, path in artifacts.items()
            },
        )

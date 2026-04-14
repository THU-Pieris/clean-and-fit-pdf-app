from __future__ import annotations

import mimetypes
import os
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .jobs import JobSettings, JobStore
from .schemas import JobCreatedResponse, JobStatusResponse


def create_app(
    data_dir: Path | None = None,
    job_ttl: timedelta | None = None,
) -> FastAPI:
    resolved_data_dir = data_dir or Path(os.getenv("APP_DATA_DIR", "backend/data"))
    resolved_job_ttl = job_ttl or timedelta(hours=int(os.getenv("JOB_TTL_HOURS", "24")))

    app = FastAPI(
        title="Clean and Fit PDF API",
        version="1.0.0",
        description="Docker-friendly API wrapper around the Clean and Fit PDF processor.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.jobs = JobStore(data_dir=resolved_data_dir, job_ttl=resolved_job_ttl)

    @app.get("/api/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/jobs", response_model=JobCreatedResponse, status_code=202)
    async def create_job(
        file: Annotated[UploadFile, File(...)],
        page: Annotated[int, Form()] = 1,
        wrapper_groups: Annotated[int, Form()] = 2,
        padding: Annotated[float, Form()] = 0.0,
        dpi: Annotated[int, Form()] = 1200,
        acrobat_fix: Annotated[bool, Form()] = True,
        precision: Annotated[int, Form()] = 6,
        linearize: Annotated[bool, Form()] = False,
        object_streams: Annotated[str, Form()] = "disable",
        keep_temp: Annotated[bool, Form()] = False,
    ) -> JobCreatedResponse:
        filename = Path(file.filename or "input.pdf").name or "input.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Please upload a PDF file.")

        content = await file.read()
        await file.close()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        try:
            settings = JobSettings(
                page=page,
                wrapper_groups=wrapper_groups,
                padding=padding,
                acrobat_fix=acrobat_fix,
                dpi=dpi,
                precision=precision,
                linearize=linearize,
                object_streams=object_streams,
                keep_temp=keep_temp,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            return app.state.jobs.create_job(filename=filename, content=content, settings=settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job(job_id: str) -> JobStatusResponse:
        status = app.state.jobs.get_status(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return status

    @app.get("/api/jobs/{job_id}/download")
    def download_result(job_id: str) -> FileResponse:
        payload = app.state.jobs.get_output_path(job_id)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="Processed PDF is not available for this job.",
            )
        path, filename = payload
        return FileResponse(path, media_type="application/pdf", filename=filename)

    @app.get("/api/jobs/{job_id}/artifacts/{artifact_name}")
    def download_artifact(job_id: str, artifact_name: str) -> FileResponse:
        payload = app.state.jobs.get_artifact_path(job_id, artifact_name)
        if payload is None:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        path, filename = payload
        media_type, _ = mimetypes.guess_type(path.name)
        return FileResponse(
            path,
            media_type=media_type or "application/octet-stream",
            filename=filename,
        )

    return app


app = create_app()

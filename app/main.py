from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse

from .config import Settings
from .database import initialize
from .schemas import CreateJobRequest, JobResponse
from .service import JobService, JobWorker


def to_response(job, certificates) -> JobResponse:
    return JobResponse(
        id=job["id"], status=job["status"], organization_name=job["organization_name"], event_name=job["event_name"],
        total_count=job["total_count"], processed_count=job["processed_count"], succeeded_count=job["succeeded_count"],
        failed_count=job["failed_count"], created_at=job["created_at"], started_at=job["started_at"], completed_at=job["completed_at"],
        certificates=[dict(id=c["id"], recipient_name=c["recipient_name"], course_name=c["course_name"],
                           issue_date=c["issue_date"], status=c["status"], error_message=c["error_message"])
                      for c in certificates],
    )


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize(settings.database_path)
        worker = JobWorker(app.state.service, settings.worker_poll_seconds)
        app.state.worker = worker
        if start_worker:
            worker.start()
        yield
        if start_worker:
            worker.stop()

    app = FastAPI(title="Bulk Certificate Generator", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = JobService(settings)

    def service(request: Request) -> JobService:
        return request.app.state.service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/certificate-jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
    def create_job(payload: CreateJobRequest, job_service: JobService = Depends(service)) -> JobResponse:
        job_id = job_service.create_job(payload)
        job, certificates = job_service.get_job(job_id)
        return to_response(job, certificates)

    @app.get("/api/v1/certificate-jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, job_service: JobService = Depends(service)) -> JobResponse:
        result = job_service.get_job(job_id)
        if not result:
            raise HTTPException(404, "Generation job not found")
        return to_response(*result)

    @app.get("/api/v1/certificate-jobs/{job_id}/certificates/{certificate_id}")
    def download_certificate(job_id: str, certificate_id: str, job_service: JobService = Depends(service)) -> FileResponse:
        certificate = job_service.get_certificate(job_id, certificate_id)
        if not certificate:
            raise HTTPException(404, "Certificate not found")
        if certificate["status"] != "completed" or not certificate["artifact_path"]:
            raise HTTPException(409, "Certificate is not available")
        path = Path(certificate["artifact_path"])
        if not path.is_file():
            raise HTTPException(404, "Certificate artifact not found")
        return FileResponse(path, media_type="application/pdf", filename=f"{certificate['recipient_name']}.pdf")

    @app.get("/api/v1/certificate-jobs/{job_id}/download")
    def download_zip(job_id: str, job_service: JobService = Depends(service)) -> FileResponse:
        result = job_service.get_job(job_id)
        if not result:
            raise HTTPException(404, "Generation job not found")
        job, _ = result
        if job["status"] not in {"completed", "completed_with_errors"}:
            raise HTTPException(409, "Job is not finished")
        if not job["zip_path"] or not Path(job["zip_path"]).is_file():
            raise HTTPException(404, "No generated certificates are available")
        return FileResponse(job["zip_path"], media_type="application/zip", filename=f"certificates-{job_id}.zip")

    return app


app = create_app()

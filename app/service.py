from __future__ import annotations

import threading
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .database import connect
from .renderer import CertificateRenderer
from .schemas import CreateJobRequest


def now() -> str:
    return datetime.now(UTC).isoformat()


class JobService:
    def __init__(self, settings: Settings, renderer: CertificateRenderer | None = None):
        self.settings = settings
        self.renderer = renderer or CertificateRenderer()

    def create_job(self, request: CreateJobRequest) -> str:
        job_id = str(uuid.uuid4())
        timestamp = now()
        with connect(self.settings.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO generation_jobs
                (id, organization_name, event_name, status, total_count, created_at)
                VALUES (?, ?, ?, 'queued', ?, ?)""",
                (job_id, request.organization_name, request.event_name, len(request.recipients), timestamp))
            db.executemany("""INSERT INTO certificates
                (id, job_id, recipient_name, course_name, issue_date, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                [(str(uuid.uuid4()), job_id, recipient.name, recipient.course,
                  recipient.issue_date.isoformat(), timestamp) for recipient in request.recipients])
        return job_id

    def get_job(self, job_id: str):
        with connect(self.settings.database_path) as db:
            job = db.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return None
            certificates = db.execute("SELECT * FROM certificates WHERE job_id = ? ORDER BY created_at, id", (job_id,)).fetchall()
        return job, certificates

    def get_certificate(self, job_id: str, certificate_id: str):
        with connect(self.settings.database_path) as db:
            return db.execute("SELECT * FROM certificates WHERE id = ? AND job_id = ?", (certificate_id, job_id)).fetchone()

    def claim_next_job(self):
        with connect(self.settings.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM generation_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
            if not job:
                return None
            db.execute("UPDATE generation_jobs SET status = 'processing', started_at = ? WHERE id = ?", (now(), job["id"]))
            return job["id"]

    def recover_interrupted_jobs(self) -> None:
        with connect(self.settings.database_path) as db:
            db.execute("UPDATE generation_jobs SET status = 'queued', started_at = NULL WHERE status = 'processing'")
            db.execute("UPDATE certificates SET status = 'pending' WHERE status = 'processing'")

    def process_job(self, job_id: str) -> None:
        try:
            job, certificates = self.get_job(job_id) or (None, None)
            if not job:
                return
            job_dir = self.settings.artifact_dir / job_id
            for certificate in certificates:
                if certificate["status"] == "completed":
                    continue
                self._process_certificate(job, certificate, job_dir)
            self._finalize_job(job_id, job_dir)
        except Exception as exc:
            with connect(self.settings.database_path) as db:
                db.execute("UPDATE generation_jobs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                           (str(exc), now(), job_id))

    def _process_certificate(self, job, certificate, job_dir: Path) -> None:
        filename = f"{certificate['id']}.pdf"
        artifact = job_dir / filename
        with connect(self.settings.database_path) as db:
            db.execute("UPDATE certificates SET status = 'processing' WHERE id = ?", (certificate["id"],))
        try:
            self.renderer.render(artifact, recipient_name=certificate["recipient_name"],
                                 course_name=certificate["course_name"], issue_date=certificate["issue_date"],
                                 organization_name=job["organization_name"], event_name=job["event_name"])
            with connect(self.settings.database_path) as db:
                db.execute("""UPDATE certificates SET status = 'completed', artifact_path = ?, completed_at = ?
                            WHERE id = ?""", (str(artifact), now(), certificate["id"]))
                db.execute("""UPDATE generation_jobs SET processed_count = processed_count + 1,
                            succeeded_count = succeeded_count + 1 WHERE id = ?""", (job["id"],))
        except Exception as exc:
            artifact.unlink(missing_ok=True)
            with connect(self.settings.database_path) as db:
                db.execute("""UPDATE certificates SET status = 'failed', error_message = ?, completed_at = ?
                            WHERE id = ?""", (str(exc), now(), certificate["id"]))
                db.execute("""UPDATE generation_jobs SET processed_count = processed_count + 1,
                            failed_count = failed_count + 1 WHERE id = ?""", (job["id"],))

    def _finalize_job(self, job_id: str, job_dir: Path) -> None:
        job, certificates = self.get_job(job_id) or (None, None)
        if not job:
            return
        completed = [c for c in certificates if c["status"] == "completed"]
        zip_path = None
        if completed:
            zip_file = job_dir / "certificates.zip"
            with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as archive:
                for certificate in completed:
                    archive.write(
                        certificate["artifact_path"],
                        f"{certificate['recipient_name']}-{certificate['id'][:8]}.pdf",
                    )
            zip_path = str(zip_file)
        status = "completed" if job["failed_count"] == 0 else "completed_with_errors"
        with connect(self.settings.database_path) as db:
            db.execute("""UPDATE generation_jobs SET status = ?, zip_path = ?, completed_at = ? WHERE id = ?""",
                       (status, zip_path, now(), job_id))


class JobWorker:
    def __init__(self, service: JobService, poll_seconds: float):
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.service.recover_interrupted_jobs()
        self._thread = threading.Thread(target=self._run, name="certificate-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self.service.claim_next_job()
            if job_id:
                self.service.process_job(job_id)
            else:
                self._stop.wait(self.poll_seconds)

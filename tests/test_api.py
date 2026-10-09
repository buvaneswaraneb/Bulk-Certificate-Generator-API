from __future__ import annotations

import time
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.renderer import CertificateRenderer
from app.service import JobService


def payload() -> dict:
    return {
        "organization_name": "Acme Learning",
        "event_name": "Python Foundations 2026",
        "recipients": [
            {"name": "Ada Lovelace", "course": "Python Foundations", "issue_date": "2026-10-08"},
            {"name": "Grace Hopper", "course": "Python Foundations", "issue_date": "2026-10-08"},
        ],
    }


@pytest.fixture
def app_settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", artifact_dir=tmp_path / "artifacts", worker_poll_seconds=.01)


def test_health(app_settings):
    with TestClient(create_app(app_settings, start_worker=False)) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_create_job_validates_and_persists_atomically(app_settings):
    with TestClient(create_app(app_settings, start_worker=False)) as client:
        response = client.post("/api/v1/certificate-jobs", json=payload())
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "queued"
        assert body["total_count"] == 2
        assert len(body["certificates"]) == 2

        invalid = payload()
        invalid["recipients"][1]["name"] = " "
        assert client.post("/api/v1/certificate-jobs", json=invalid).status_code == 422

        duplicate = payload()
        duplicate["recipients"][1] = duplicate["recipients"][0].copy()
        assert client.post("/api/v1/certificate-jobs", json=duplicate).status_code == 422


def test_generation_progress_and_downloads(app_settings):
    app = create_app(app_settings, start_worker=False)
    with TestClient(app) as client:
        created = client.post("/api/v1/certificate-jobs", json=payload()).json()
        job_id = created["id"]
        assert client.get(f"/api/v1/certificate-jobs/{job_id}/download").status_code == 409
        app.state.service.process_job(app.state.service.claim_next_job())
        completed = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
        assert completed["status"] == "completed"
        assert (completed["processed_count"], completed["succeeded_count"], completed["failed_count"]) == (2, 2, 0)

        certificate = completed["certificates"][0]
        pdf = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates/{certificate['id']}")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF")
        archive = client.get(f"/api/v1/certificate-jobs/{job_id}/download")
        assert archive.status_code == 200
        zip_path = app_settings.artifact_dir / job_id / "certificates.zip"
        with zipfile.ZipFile(zip_path) as contents:
            assert len(contents.namelist()) == 2


class FailsForGrace(CertificateRenderer):
    def render(self, destination, **kwargs):
        if kwargs["recipient_name"] == "Grace Hopper":
            raise RuntimeError("renderer unavailable")
        return super().render(destination, **kwargs)


def test_one_certificate_failure_does_not_stop_job(app_settings):
    app = create_app(app_settings, start_worker=False)
    app.state.service = JobService(app_settings, renderer=FailsForGrace())
    with TestClient(app) as client:
        created = client.post("/api/v1/certificate-jobs", json=payload()).json()
        app.state.service.process_job(app.state.service.claim_next_job())
        job = client.get(f"/api/v1/certificate-jobs/{created['id']}").json()
        assert job["status"] == "completed_with_errors"
        assert (job["succeeded_count"], job["failed_count"]) == (1, 1)
        failed = next(c for c in job["certificates"] if c["status"] == "failed")
        assert failed["error_message"] == "renderer unavailable"
        assert client.get(f"/api/v1/certificate-jobs/{created['id']}/certificates/{failed['id']}").status_code == 409


def test_worker_recovers_interrupted_jobs(app_settings):
    app = create_app(app_settings, start_worker=False)
    with TestClient(app) as client:
        created = client.post("/api/v1/certificate-jobs", json=payload()).json()
        job_id = created["id"]
        assert app.state.service.claim_next_job() == job_id
        app.state.service.recover_interrupted_jobs()
        assert app.state.service.claim_next_job() == job_id


def test_background_worker_completes_job(app_settings):
    with TestClient(create_app(app_settings, start_worker=True)) as client:
        created = client.post("/api/v1/certificate-jobs", json=payload()).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/v1/certificate-jobs/{created['id']}").json()
            if job["status"] in {"completed", "completed_with_errors", "failed"}:
                break
            time.sleep(.03)
        assert job["status"] == "completed"

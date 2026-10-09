# Bulk Certificate Generator

A FastAPI service for creating a single bulk certificate job, tracking asynchronous generation, and downloading individual PDF certificates or the completed batch as a ZIP.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The interactive OpenAPI UI is available at `http://127.0.0.1:8000/docs`.

## API example

Create a job:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/certificate-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "organization_name": "Acme Learning",
    "event_name": "Python Foundations 2026",
    "recipients": [
      {"name": "Ada Lovelace", "course": "Python Foundations", "issue_date": "2026-10-08"},
      {"name": "Grace Hopper", "course": "Python Foundations", "issue_date": "2026-10-08"}
    ]
  }'
```

Use the returned job ID to poll `GET /api/v1/certificate-jobs/{job_id}`. Its `certificates` array contains the individual certificate IDs. Download a completed item with `GET /api/v1/certificate-jobs/{job_id}/certificates/{certificate_id}`, or the finished batch at `GET /api/v1/certificate-jobs/{job_id}/download`.

## Tests

```bash
pytest
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./certificate_generator.db` | SQLite database path |
| `ARTIFACT_DIR` | `./artifacts` | PDFs and ZIP artifacts |
| `WORKER_POLL_SECONDS` | `0.2` | Background worker polling interval |

## Design decisions

- **Asynchronous database-backed jobs:** the create endpoint returns quickly, progress survives process boundaries, and an individual failed render is captured without preventing remaining recipients from completing.
- **In-process worker:** ideal for a take-home project: no Redis/Celery deployment, yet the `JobService` and `CertificateRenderer` boundaries make moving to a dedicated queue/worker straightforward.
- **Atomic request validation:** no job is created if any recipient is invalid or duplicated, preventing ambiguous partial submissions.
- **Local SQLite/filesystem defaults:** provides zero-setup evaluation. For production, set PostgreSQL-compatible persistence behind the repository boundary and replace local artifact paths with object storage.

No authentication or template editing is included because they are outside the assignment scope.

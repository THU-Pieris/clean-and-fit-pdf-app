from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import create_app


def test_process_sample_pdf(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path / "jobs", job_ttl=timedelta(hours=1))
    client = TestClient(app)

    sample_path = ROOT / "backend" / "tests" / "fixtures" / "sample.pdf"
    with sample_path.open("rb") as handle:
        response = client.post(
            "/api/jobs",
            files={"file": ("sample.pdf", handle, "application/pdf")},
            data={"dpi": "150"},
        )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status = None
    for _ in range(100):
        poll = client.get(f"/api/jobs/{job_id}")
        assert poll.status_code == 200
        status = poll.json()
        if status["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.1)

    assert status is not None
    assert status["status"] == "succeeded", status
    assert status["result"]["renderer"] == "PyMuPDF"

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")

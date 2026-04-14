# Clean and Fit PDF

Web-based PDF cleanup tool built around the original Python processing pipeline.

This repo ships as:

- a Docker-friendly FastAPI backend
- a browser frontend served by Nginx
- the original Python PDF-processing engine, reused as the domain layer

## What It Does

The processing pipeline:

1. Opens a selected PDF page.
2. Removes the first configurable number of nested wrapper drawing groups.
3. Renders the cleaned page to an image with `PyMuPDF`.
4. Measures the non-white content bounds.
5. Rewrites the PDF page so the page size tightly fits the content.
6. Optionally runs an Acrobat-friendly rewrite with `pikepdf`.

The output remains vector-based.

## Architecture

### Core Processing

- `clean_and_fit_pdf.py`: processing engine and CLI
- `repair_pdf_for_acrobat.py`: standalone Acrobat-fix wrapper

### Backend

- `backend/app/main.py`: FastAPI entry point
- `backend/app/jobs.py`: background job runner and job state storage
- `backend/app/schemas.py`: API response models

Backend API endpoints:

- `GET /api/health`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/download`
- `GET /api/jobs/{job_id}/artifacts/{artifact_name}`

### Frontend

- `frontend/index.html`: browser UI
- `frontend/app.js`: upload, polling, and download logic
- `frontend/styles.css`: app styling
- `frontend/nginx.conf`: static hosting plus `/api` reverse proxy to backend

## Run With Docker

Requirements:

- Docker
- Docker Compose

Start the stack:

```bash
docker compose up --build
```

Open:

- Frontend: `http://localhost:8091`
- Backend API docs: `http://localhost:8000/docs`

The frontend proxies `/api` requests to the backend container, so the browser
only needs the frontend URL during normal use.

## Local Backend Development

Run the backend directly without Docker:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

Then open the frontend through Docker, Nginx, or any static server that proxies
`/api` to `http://localhost:8000`.

## Using The Web App

1. Open the frontend in your browser.
2. Upload a PDF.
3. Adjust page number, wrapper-group count, padding, DPI, and Acrobat options.
4. Start the job.
5. Watch the progress log.
6. Download the fitted PDF when the job completes.

If you enable `Keep intermediate debug files`, the UI also exposes download links
for the cleaned intermediate PDF, the fitted intermediate PDF, and the
measurement PNG.

## API Example

Submit a job:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -F "file=@your-file.pdf" \
  -F "dpi=150"
```

Poll status:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

Download the result:

```bash
curl -L http://localhost:8000/api/jobs/<job_id>/download -o output.pdf
```

## Tests

Run the backend smoke test:

```bash
pytest backend/tests
```

The test generates a temporary vector PDF, submits it through the API, and
checks that the response returns a valid PDF.

## Notes

- The current implementation is still aimed at one-page vector PDFs and
  plot-like exports.
- Backend job state is stored on disk under `backend/data/`.
- Completed jobs are cleaned up automatically after the configured TTL
  (`JOB_TTL_HOURS`, default `24`).

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

After pulling frontend changes, rebuild and recreate the frontend container:

```bash
docker compose up -d --build --no-deps frontend
```

The image contains a snapshot of the frontend files; Git updates do not change
an already running container. During the image build, CSS and JavaScript receive
content-hashed filenames and the HTML is updated to reference them. Nginx asks
browsers to revalidate HTML while allowing immutable caching of hashed assets,
so a new release does not reuse an old stylesheet or script.

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
2. Drop a PDF into the source area or browse for a file (up to 64 MB).
3. Set the page, edge padding, and wrapper-group count. Open **Advanced settings**
   for measurement DPI, precision, object streams, web optimization, and debug files.
4. Select **Clean & fit PDF**.
5. Follow the job status, or expand **Processing details** for the full log.
6. Download the fitted PDF and review its page dimensions and file size.

If the connection drops while checking progress, use **Reconnect to job** to
resume checking the existing job without uploading the document again.

If you enable **Keep intermediate files**, the UI also exposes download links
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

Check the built frontend's asset URLs, content hashes, MIME types, and cache
headers against the running container (standard library only):

```bash
python3 -m unittest discover -s frontend/tests -v
```

Set `FRONTEND_URL` to check a different origin, including the public URL behind
a reverse proxy or Cloudflare Tunnel.

## Notes

- The current implementation is still aimed at one-page vector PDFs and
  plot-like exports.
- Backend job state is stored on disk under `backend/data/`.
- Completed jobs are cleaned up automatically after the configured TTL
  (`JOB_TTL_HOURS`, default `24`).

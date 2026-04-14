# Clean And Fit PDF App

Windows desktop app and Python tooling for cleaning a one-page vector PDF, removing outer wrapper groups, measuring the painted content, and rewriting the page to an exact-fit size.

The project supports two ways of running:

- As a portable Windows executable: `dist\CleanAndFitPdf.exe`
- From source: `clean_and_fit_pdf_app.pyw` or `clean_and_fit_pdf.py`

## What It Does

This project is aimed at PDFs such as exported plots, diagrams, or figures where the visible content is surrounded by redundant wrapper groups and excess page margins.

The processing pipeline does this:

1. Opens a selected PDF page.
2. Removes the first configurable number of nested wrapper drawing groups.
3. Renders the cleaned page to an image using the built-in `PyMuPDF` renderer.
4. Measures the non-white content bounds.
5. Rewrites the PDF page so the page size tightly fits the content.
6. Optionally runs an Acrobat-friendly rewrite using `pikepdf`.

The output stays vector-based.

## Project Files

- `clean_and_fit_pdf.py`: core processing logic and CLI
- `clean_and_fit_pdf_app.pyw`: Tkinter desktop app
- `repair_pdf_for_acrobat.py`: standalone wrapper for the Acrobat-fix stage
- `start_clean_and_fit_pdf_app.cmd`: launches the packaged EXE if present, otherwise launches the source app
- `build_clean_and_fit_pdf_app.cmd`: creates a one-file portable EXE
- `requirements.txt`: runtime Python dependencies
- `requirements-build.txt`: build-time dependencies

## Quick Start

### Option 1: Run The Portable App

If `dist\CleanAndFitPdf.exe` exists, just run it directly.

You can also use:

```bat
start_clean_and_fit_pdf_app.cmd
```

That launcher prefers the packaged EXE when it exists.

### Option 2: Run From Source

Install Python 3.11, then from this folder run:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe clean_and_fit_pdf_app.pyw
```

For the command-line workflow:

```bat
.venv\Scripts\python.exe clean_and_fit_pdf.py input.pdf
```

## Building The Portable EXE

The build script bootstraps its own local build environment in `.venv-build`, installs the required packages, and creates a single-file Windows executable with PyInstaller.

Run:

```bat
build_clean_and_fit_pdf_app.cmd
```

Requirements:

- Windows
- Python 3.11 installed and available through `py -3.11`

Build output:

```text
dist\CleanAndFitPdf.exe
```

The packaged EXE includes:

- its own Python runtime
- `pypdf`
- `Pillow`
- `PyMuPDF`
- `pikepdf`

It does not require a separate Python installation on the target machine.

## Desktop App Notes

The desktop app lets you:

- choose an input PDF
- choose an output PDF
- set page number, wrapper-group count, padding, DPI, and Acrobat-fix options
- watch progress in a log window
- open the output folder after processing

The app runs the processing job in a background thread so the window stays responsive.

## Command-Line Usage

Basic example:

```bat
py -3.11 clean_and_fit_pdf.py figure.pdf
```

Example with explicit options:

```bat
py -3.11 clean_and_fit_pdf.py figure.pdf ^
  -o figure.cleaned.pdf ^
  --page 1 ^
  --wrapper-groups 2 ^
  --padding 0 ^
  --dpi 1200 ^
  --linearize
```

To skip the Acrobat-fix stage:

```bat
py -3.11 clean_and_fit_pdf.py figure.pdf --no-acrobat-fix
```

## Git Repo Setup

This folder is ready to become its own repository.

Typical setup:

```bat
git init
git add .
git commit -m "Initial import"
```

The included `.gitignore` excludes local build products, virtual environments, temporary files, and generated PDFs.

## Notes

- The renderer is built in through `PyMuPDF`, so no external `pdftoppm.exe` is required for normal use.
- The optional Acrobat compatibility stage depends on `pikepdf`.
- The current implementation is intended for one-page vector PDFs and plot-like exports.

@echo off
setlocal
cd /d "%~dp0"

where py.exe >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py.exe" was not found.
    echo Install Python 3.11 for Windows, then rerun this script.
    exit /b 1
)

py -3.11 -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 was not found.
    echo Install Python 3.11, then rerun this script.
    exit /b 1
)

set "VENV_DIR=%~dp0.venv-build"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Creating local build environment...
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b %errorlevel%
)

echo Installing build dependencies...
call "%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 exit /b %errorlevel%
call "%VENV_PY%" -m pip install -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b %errorlevel%

"%VENV_PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed in .venv-build.
    exit /b 1
)

if exist "%~dp0dist\CleanAndFitPdf.exe" (
    del /f /q "%~dp0dist\CleanAndFitPdf.exe" >nul 2>nul
    if exist "%~dp0dist\CleanAndFitPdf.exe" (
        echo Could not replace dist\CleanAndFitPdf.exe.
        echo Close any running copies of the app and try again.
        exit /b 1
    )
)

"%VENV_PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name CleanAndFitPdf ^
    --hidden-import pypdf ^
    --hidden-import PyPDF2 ^
    --hidden-import PIL ^
    --hidden-import pymupdf ^
    --hidden-import fitz ^
    --hidden-import pikepdf ^
    --collect-all PIL ^
    --collect-all pymupdf ^
    --collect-all pikepdf ^
    clean_and_fit_pdf_app.pyw

if errorlevel 1 exit /b %errorlevel%

echo.
echo Built executable:
echo   %~dp0dist\CleanAndFitPdf.exe
echo.
echo This EXE contains its own Python runtime and PDF dependencies.

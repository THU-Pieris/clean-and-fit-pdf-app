@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0dist\CleanAndFitPdf.exe" (
    start "" "%~dp0dist\CleanAndFitPdf.exe"
    exit /b 0
)

where pyw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pyw.exe "%~dp0clean_and_fit_pdf_app.pyw"
    exit /b 0
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0clean_and_fit_pdf_app.pyw"
    exit /b 0
)

where py.exe >nul 2>nul
if %errorlevel%==0 (
    start "" py.exe "%~dp0clean_and_fit_pdf_app.pyw"
    exit /b 0
)

python "%~dp0clean_and_fit_pdf_app.pyw"

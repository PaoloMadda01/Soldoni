@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto setup
if exist ".venv\.soldoni-ready" goto start

:setup
echo Preparing Soldoni...
call setup.cmd
if errorlevel 1 goto error
type nul > ".venv\.soldoni-ready"
if errorlevel 1 goto error

:start
echo Starting Soldoni. Keep this window open while using the application.
".venv\Scripts\python.exe" -m streamlit run soldoni/app/dashboard.py
if errorlevel 1 goto error
exit /b 0

:error
echo ERROR: Soldoni could not start. Fix the error above, then run Start Soldoni.cmd again.
echo Press any key to close this window...
pause >nul
exit /b 1

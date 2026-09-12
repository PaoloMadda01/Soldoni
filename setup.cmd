@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 13))" >nul 2>nul
    if errorlevel 1 (
        echo ERROR: The existing virtual environment does not use Python 3.13.
        exit /b 1
    )
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)

if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -0p 2>nul | findstr /r /c:"3\.13" >nul
        if not errorlevel 1 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3.13"
        )
    )
)

if not defined PYTHON_EXE (
    echo ERROR: Python 3.13 was not found.
    echo Install it from https://www.python.org/downloads/windows/ and run Start Soldoni.cmd again.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the virtual environment...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Virtual environment creation failed.
        exit /b 1
    )
)

echo Updating dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip update failed.
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    exit /b 1
)

echo Setup completed successfully.
exit /b 0

@echo off
REM CrewOps360 Streamlit App Launcher for Windows
REM This script creates a virtual environment and starts the Streamlit app

setlocal enabledelayedexpansion

echo ========================================
echo CrewOps360 Streamlit App Launcher
echo ========================================
echo.

REM Change to the script directory
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Pick an interpreter this app can actually run on.
REM
REM "python" on PATH is whatever was installed last, which is how a machine with
REM Python 3.14 ends up building a venv that cannot import altair. Ask the py
REM launcher for a supported version first and only fall back to PATH.
REM scripts\check_python.py is the single source of truth for what counts as
REM supported, and prints the fix when nothing does.
REM ---------------------------------------------------------------------------

set PY_CMD=
for %%V in (3.13 3.12 3.11) do (
    if "!PY_CMD!"=="" (
        py -%%V -c "import sys" >nul 2>&1
        if not errorlevel 1 set PY_CMD=py -%%V
    )
)

if "!PY_CMD!"=="" (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed or not in PATH
        echo Please install Python 3.13 from https://www.python.org/
        pause
        exit /b 1
    )
    set PY_CMD=python
)

echo Using interpreter: !PY_CMD!
!PY_CMD! scripts\check_python.py
if errorlevel 1 (
    pause
    exit /b 1
)
echo.

REM ---------------------------------------------------------------------------
REM An existing venv is checked too. Upgrading Python on the machine does not
REM change a venv that was already built, so a stale one has to be caught here
REM rather than 40 lines into an import traceback.
REM ---------------------------------------------------------------------------

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe scripts\check_python.py >nul 2>&1
    if errorlevel 1 (
        echo The existing 'venv' folder was built with an unsupported Python.
        venv\Scripts\python.exe scripts\check_python.py
        echo.
        echo Delete the 'venv' folder and run this script again to rebuild it.
        pause
        exit /b 1
    )
)

REM Check if virtual environment exists
if not exist "venv\" (
    echo Creating virtual environment...
    !PY_CMD! -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created successfully!
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    echo Try deleting the 'venv' folder and running this script again
    pause
    exit /b 1
)

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

REM Install requirements
echo Installing/updating requirements...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install requirements
    pause
    exit /b 1
)

REM Start Streamlit
echo.
echo ========================================
echo Starting Streamlit app...
echo ========================================
echo.
echo The app will open in your default browser.
echo To stop the app, press Ctrl+C in this window.
echo.

streamlit run app.py

REM If streamlit command failed
if errorlevel 1 (
    echo.
    echo ERROR: Failed to start Streamlit
    echo This might be because Streamlit is not installed correctly.
    pause
    exit /b 1
)

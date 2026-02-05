@echo off
REM CrewOps360 Streamlit App Launcher for Windows
REM This script creates a virtual environment and starts the Streamlit app

echo ========================================
echo CrewOps360 Streamlit App Launcher
echo ========================================
echo.

REM Change to the script directory
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or later from https://www.python.org/
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
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

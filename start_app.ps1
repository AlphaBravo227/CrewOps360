# CrewOps360 Streamlit App Launcher for Windows (PowerShell)
# This script creates a virtual environment and starts the Streamlit app

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CrewOps360 Streamlit App Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Change to the script directory
Set-Location $PSScriptRoot

# ---------------------------------------------------------------------------
# Pick an interpreter this app can actually run on.
#
# "python" on PATH is whatever was installed last, which is how a machine with
# Python 3.14 ends up building a venv that cannot import altair. Ask the py
# launcher for a supported version first and only fall back to PATH.
# scripts\check_python.py is the single source of truth for what counts as
# supported, and prints the fix when nothing does.
# ---------------------------------------------------------------------------

$pyExe = $null
$pyArgs = @()
foreach ($v in @("3.13", "3.12", "3.11")) {
    & py "-$v" -c "import sys" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $pyExe = "py"
        $pyArgs = @("-$v")
        break
    }
}

if (-not $pyExe) {
    & python --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
        Write-Host "Please install Python 3.13 from https://www.python.org/" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
    $pyExe = "python"
}

Write-Host "Using interpreter: $pyExe $pyArgs" -ForegroundColor Green
& $pyExe @pyArgs "scripts\check_python.py"
if ($LASTEXITCODE -ne 0) {
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# An existing venv is checked too. Upgrading Python on the machine does not
# change a venv that was already built, so a stale one has to be caught here
# rather than 40 lines into an import traceback.
if (Test-Path "venv\Scripts\python.exe") {
    & ".\venv\Scripts\python.exe" "scripts\check_python.py" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "The existing 'venv' folder was built with an unsupported Python." -ForegroundColor Red
        & ".\venv\Scripts\python.exe" "scripts\check_python.py"
        Write-Host ""
        Write-Host "Delete the 'venv' folder and run this script again to rebuild it." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    & $pyExe @pyArgs -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Virtual environment created successfully!" -ForegroundColor Green
    Write-Host ""
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to activate virtual environment" -ForegroundColor Red
    Write-Host "If you see an execution policy error, run this command in PowerShell as Administrator:" -ForegroundColor Yellow
    Write-Host "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Or use the start_app.bat file instead (batch files don't have this restriction)" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet

# Install requirements
Write-Host "Installing/updating requirements..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install requirements" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Start Streamlit
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Streamlit app..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "The app will open in your default browser." -ForegroundColor Green
Write-Host "To stop the app, press Ctrl+C in this window." -ForegroundColor Yellow
Write-Host ""

streamlit run app.py

# If streamlit command failed
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Failed to start Streamlit" -ForegroundColor Red
    Write-Host "This might be because Streamlit is not installed correctly." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

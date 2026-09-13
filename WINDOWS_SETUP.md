# Windows 11 Setup Instructions for CrewOps360

## Python version — read this first

**CrewOps360 needs Python 3.11, 3.12 or 3.13. It does not run on 3.14 or newer.**

Install **Python 3.13**:

```powershell
winget install Python.Python.3.13
```

Then open a *new* terminal and check what the launcher can see:

```powershell
py -0
```

You want a `3.13` (or `3.12`/`3.11`) in that list. Having 3.14 as well is fine —
`start_app.bat` picks a supported one on purpose rather than taking whatever
`python` on PATH happens to be.

To check any particular interpreter:

```powershell
py -3.13 scripts\check_python.py
venv\Scripts\python scripts\check_python.py   # an existing venv
```

**Why the ceiling:** the app pins `altair<6` so local charts render the way
production's do. altair 5.5.0 is the last 5.x release ever made, and it cannot
be imported on Python 3.14+ — it fails with a `TypedDict ... 'closed'`
`TypeError` before any app code runs. No package upgrade works around it. See
the header of `requirements.txt` for the full story.

**If you already have a `venv` built on 3.14:** upgrading Python on the machine
does not repair it — a virtual environment keeps the interpreter it was created
with. Delete the folder and let the launcher rebuild it:

```powershell
deactivate
.\start_app.bat
```

`start_app.bat` notices the stale venv and offers to delete and rebuild it for
you. To remove it by hand, note that the command differs by shell — `rmdir /s /q`
is `cmd.exe` only and fails in PowerShell, where `rmdir` is an alias for
`Remove-Item`:

```powershell
Remove-Item -Recurse -Force venv    # PowerShell
```
```cmd
rmdir /s /q venv                    :: cmd.exe
```

---

## Quick Start (Recommended Method)

The easiest way to start the app on Windows is using the batch file:

1. **Double-click `start_app.bat`** in the project folder
2. If Windows shows a security warning, click "More info" → "Run anyway"
3. The app will open in your browser automatically

---

## Fixing Windows Security Errors

If you encounter security errors when trying to run the app, follow these steps:

### Method 1: Use the Batch File (Easiest)
The `start_app.bat` file is specifically designed for Windows and is less likely to trigger security warnings than Python scripts.

1. Right-click `start_app.bat` → **Run as administrator** (first time only)
2. If Windows SmartScreen blocks it:
   - Click **"More info"**
   - Click **"Run anyway"**
3. Future runs won't require administrator privileges

### Method 2: Fix PowerShell Execution Policy
If you prefer using PowerShell (`start_app.ps1`), you may need to change the execution policy:

1. **Open PowerShell as Administrator**:
   - Press `Win + X`
   - Select "Windows PowerShell (Admin)" or "Terminal (Admin)"

2. **Run this command**:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

3. **Type `Y` and press Enter** to confirm

4. **Now you can run**:
   ```powershell
   .\start_app.ps1
   ```

### Method 3: Fix Corrupted Virtual Environment
If the security error stopped the script mid-way, your virtual environment might be corrupted:

1. **Delete the `venv` folder** in the project directory
2. **Run `start_app.bat` again** - it will recreate the virtual environment

---

## Alternative: Manual Setup

If automated scripts continue to have issues, you can set up manually:

1. **Open Command Prompt or PowerShell** in the project folder:
   - Hold `Shift` + Right-click in the folder → "Open PowerShell window here"

2. **Create virtual environment** (name the version — do not use bare `python`,
   which may be 3.14):
   ```cmd
   py -3.13 -m venv venv
   ```

3. **Activate virtual environment**:
   - **Command Prompt**: `venv\Scripts\activate.bat`
   - **PowerShell**: `venv\Scripts\Activate.ps1`

4. **Install requirements**:
   ```cmd
   pip install -r requirements.txt
   ```

5. **Run the app**:
   ```cmd
   streamlit run app.py
   ```

---

## Troubleshooting

### "Python is not recognized"
- Install Python 3.13 from https://www.python.org/ (or `winget install Python.Python.3.13`)
- During installation, **check "Add Python to PATH"**
- Restart your computer after installation

### `TypeError: _TypedDictMeta.__new__() got an unexpected keyword argument 'closed'`
Your virtual environment is on Python 3.14+, which altair 5.x cannot import.
See **Python version** at the top of this file: install 3.13, then run
`start_app.bat`, which offers to rebuild the venv for you.
`python scripts\check_python.py` confirms which version a given interpreter is.

### `Remove-Item : A positional parameter cannot be found that accepts argument '/q'`
You ran a `cmd.exe` command in PowerShell. `rmdir /s /q venv` only works in
`cmd.exe`; in PowerShell use `Remove-Item -Recurse -Force venv`.

### "Access is denied" or "Permission error"
- Run Command Prompt or PowerShell as Administrator
- Or move the project folder to a location without admin restrictions (like `C:\Users\YourName\Documents\`)

### Windows Defender blocking the script
1. Open **Windows Security** (search in Start menu)
2. Go to **Virus & threat protection** → **Protection history**
3. Find the blocked action for `run_app.py` or `start_app.bat`
4. Click **Actions** → **Allow**
5. Try running the script again

### "Streamlit not found" after installation
- Make sure you activated the virtual environment first
- Try reinstalling: `pip install --force-reinstall streamlit`

### Port already in use
If you see "Address already in use":
```cmd
streamlit run app.py --server.port 8502
```

---

## Why These Scripts?

- **`start_app.bat`**: Windows batch file - most compatible, rarely blocked
- **`start_app.ps1`**: PowerShell script - more features, better error messages
- **`run_app.py`**: Original Python script - works on all platforms but may trigger Windows security

For Windows, we recommend using `start_app.bat` as it's the most reliable option.

---

## Need Help?

If you continue to experience issues:
1. Check which Python version you have: `python scripts\check_python.py`
   (must be 3.11, 3.12 or 3.13 — **not** 3.14)
2. Make sure you're in the correct project directory
3. Try running as Administrator
4. Check Windows Event Viewer for detailed error messages

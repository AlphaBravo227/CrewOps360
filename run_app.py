#!/usr/bin/env python3
"""Create the virtual environment if needed, install requirements, run the app.

Refuses to build a venv on a Python this app cannot run on. It used to build one
with whatever interpreter happened to launch it, which on a machine that has
moved on to Python 3.14 produces a venv that cannot import altair at all — and
the failure surfaced 40 lines into a traceback at first launch rather than here.
scripts/check_python.py owns the version rule and explains the fix.
"""

import os
import shutil
import subprocess
import sys
import venv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
from check_python import is_supported  # noqa: E402


def _venv_python(venv_path):
    if sys.platform == "win32":
        return os.path.join(venv_path, 'Scripts', 'python.exe')
    return os.path.join(venv_path, 'bin', 'python')


def _version_of(python_path):
    """The (major, minor) an existing interpreter reports, or None if unusable."""
    try:
        out = subprocess.run(
            [python_path, '-c',
             'import sys; print("%d %d" % sys.version_info[:2])'],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return tuple(int(part) for part in out.stdout.split())
    except ValueError:
        return None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    checker = os.path.join('scripts', 'check_python.py')

    # The interpreter that will build the venv has to be one the app can use.
    if not is_supported():
        subprocess.run([sys.executable, checker])
        return 1

    venv_path = os.path.join(script_dir, 'venv')
    python_path = _venv_python(venv_path)

    # An existing venv keeps the Python it was built with, so upgrading the
    # machine's Python does not repair it. Say so rather than installing into it.
    if os.path.exists(python_path):
        existing = _version_of(python_path)
        if existing is not None and not is_supported(existing):
            print("The existing 'venv' folder was built with an unsupported Python.")
            subprocess.run([python_path, checker])
            print("Removing it and rebuilding with Python %d.%d..."
                  % sys.version_info[:2])
            try:
                shutil.rmtree(venv_path)
            except OSError as e:
                # Usually a file still open inside it: an active venv in this
                # shell, another terminal, or OneDrive mid-sync.
                print("ERROR: could not remove %s\n  %s" % (venv_path, e))
                print("Close anything using this project (run 'deactivate' if the "
                      "venv is active here), then run this script again.")
                return 1

    if not os.path.exists(venv_path):
        print("Creating virtual environment with Python %d.%d..." % sys.version_info[:2])
        venv.create(venv_path, with_pip=True)
        python_path = _venv_python(venv_path)

    print("Installing requirements...")
    subprocess.run([python_path, '-m', 'pip', 'install', '-r', 'requirements.txt'])

    print("Starting Streamlit app...")
    return subprocess.run([python_path, '-m', 'streamlit', 'run', 'app.py']).returncode


if __name__ == "__main__":
    sys.exit(main())

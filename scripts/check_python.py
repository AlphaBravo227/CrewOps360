#!/usr/bin/env python3
"""Check that the interpreter running this script can run CrewOps360.

Run it with the interpreter you want to test:

    python scripts/check_python.py          # the one on PATH
    py -3.13 scripts/check_python.py        # a specific one, Windows
    venv\\Scripts\\python scripts/check_python.py   # an existing venv

Exits 0 when the version is supported, 1 when it is not, printing why and
what to do about it. Deliberately dependency-free and 3.x-wide in its own
syntax: it has to be able to run on the very interpreter it is rejecting,
before anything has been pip-installed.

The upper bound is not caution, it is a hard incompatibility. See
requirements.txt for the full story; the short version is that this app pins
`altair<6` to match production, altair 5.5.0 is the last 5.x release ever, and
it cannot be imported at all on Python 3.14+. Nothing installable works around
that — only a supported interpreter, or moving the whole app to altair 6.
"""

import sys

# Inclusive floor, exclusive ceiling.
#
# Floor: the newest pandas and numpy allowed by requirements.txt need 3.11.
# Ceiling: altair 5.x fails to import on 3.14+ (see the module docstring).
MIN_VERSION = (3, 11)
MAX_VERSION_EXCLUSIVE = (3, 14)

PREFERRED = "3.13"


def _fmt(version):
    return ".".join(str(part) for part in version)


def is_supported(version=None):
    """Whether a (major, minor) tuple is a version this app runs on."""
    version = tuple(version or sys.version_info[:2])
    return MIN_VERSION <= version[:2] < MAX_VERSION_EXCLUSIVE


def main():
    running = sys.version_info[:2]

    if is_supported(running):
        print("OK: Python %s at %s" % (_fmt(running), sys.executable))
        return 0

    print("")
    print("=" * 68)
    print("  This Python cannot run CrewOps360.")
    print("=" * 68)
    print("")
    print("  Found:     Python %s" % sys.version.split()[0])
    print("             %s" % sys.executable)
    print("  Supported: Python %s up to but not including %s"
          % (_fmt(MIN_VERSION), _fmt(MAX_VERSION_EXCLUSIVE)))
    print("  Preferred: Python %s" % PREFERRED)
    print("")

    if running >= MAX_VERSION_EXCLUSIVE:
        print("  Why: this app pins altair<6 so local development renders charts")
        print("  the same way production does. altair 5.5.0 is the final 5.x")
        print("  release and cannot be imported on Python %s or newer -- it fails"
              % _fmt(MAX_VERSION_EXCLUSIVE))
        print("  with a TypedDict 'closed' TypeError before any app code runs.")
        print("  No package upgrade fixes this; the 5.x line is closed.")
    else:
        print("  Why: the pandas and numpy versions this app requires need")
        print("  Python %s or newer." % _fmt(MIN_VERSION))

    print("")
    print("  What to do:")
    print("")
    print("    1. Install Python %s" % PREFERRED)
    print("         Windows:  winget install Python.Python.%s" % PREFERRED)
    print("         macOS:    brew install python@%s" % PREFERRED)
    print("         Or from https://www.python.org/downloads/")
    print("")
    print("    2. Rebuild the virtual environment with it, from the repo root:")
    print("         Windows:  rmdir /s /q venv")
    print("                   py -%s -m venv venv" % PREFERRED)
    print("                   venv\\Scripts\\activate")
    print("         macOS:    rm -rf venv")
    print("                   python%s -m venv venv" % PREFERRED)
    print("                   source venv/bin/activate")
    print("")
    print("    3. pip install -r requirements.txt")
    print("")
    return 1


if __name__ == "__main__":
    sys.exit(main())

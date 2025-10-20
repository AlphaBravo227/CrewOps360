#!/usr/bin/env python3
import os
import stat
import sys

def setup():
    script = "run_app.py"
    
    if os.path.exists(script):
        current_permissions = os.stat(script).st_mode
        os.chmod(script, current_permissions | stat.S_IEXEC)
        print(f"Made {script} executable ✅")
        print("\nSetup complete! You can now run:")
        print("• ./run_app.py (or python3 run_app.py)")
    else:
        print(f"Error: {script} not found ⚠️")
        sys.exit(1)

if __name__ == "__main__":
    setup()
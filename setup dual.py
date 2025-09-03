#!/usr/bin/env python3
import os
import stat
import sys

def setup():
    # List of scripts to make executable
    scripts = ["run_app.py", "sync_branches.py"]
    
    success_count = 0
    
    for script in scripts:
        if os.path.exists(script):
            current_permissions = os.stat(script).st_mode
            os.chmod(script, current_permissions | stat.S_IEXEC)
            print(f"Made {script} executable ✅")
            success_count += 1
        else:
            print(f"Warning: {script} not found ⚠️")
    
    if success_count > 0:
        print(f"\nSetup complete! Made {success_count} script(s) executable.")
        print("\nYou can now run:")
        if os.path.exists("run_app.py"):
            print("• ./run_app.py (or python3 run_app.py)")
        if os.path.exists("sync_branches.py"):
            print("• ./sync_branches.py (or python3 sync_branches.py)")
    else:
        print("No scripts were found to make executable.")

if __name__ == "__main__":
    setup()
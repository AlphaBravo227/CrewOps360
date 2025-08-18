#!/usr/bin/env python3
import os
import stat
import sys

def setup():
    # Make Python launcher executable
    launcher = "run_app.py"
    
    if os.path.exists(launcher):
        current_permissions = os.stat(launcher).st_mode
        os.chmod(launcher, current_permissions | stat.S_IEXEC)
        print(f"Made {launcher} executable")
    else:
        print(f"Error: {launcher} not found")
        return
    
    print("Setup complete!")
    print("\nTo start your app:")
    print("1. Double-click run_app.py, or")
    print("2. Run: python3 run_app.py")

if __name__ == "__main__":
    setup()
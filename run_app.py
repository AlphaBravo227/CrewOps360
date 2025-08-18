#!/usr/bin/env python3
import os
import sys
import subprocess
import venv

def main():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    venv_path = os.path.join(script_dir, 'venv')
    
    # Create virtual environment if it doesn't exist
    if not os.path.exists(venv_path):
        print("Creating virtual environment...")
        venv.create(venv_path, with_pip=True)
    
    # Determine the correct pip and python paths
    if sys.platform == "win32":
        pip_path = os.path.join(venv_path, 'Scripts', 'pip')
        python_path = os.path.join(venv_path, 'Scripts', 'python')
    else:
        pip_path = os.path.join(venv_path, 'bin', 'pip')
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    # Install requirements
    print("Installing requirements...")
    subprocess.run([pip_path, 'install', '-r', 'requirements.txt'])
    
    # Run Streamlit
    print("Starting Streamlit app...")
    subprocess.run([pip_path, 'install', 'streamlit'])  # Ensure streamlit is installed
    subprocess.run([python_path, '-m', 'streamlit', 'run', 'app.py'])

if __name__ == "__main__":
    main()
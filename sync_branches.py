#!/usr/bin/env python3
"""
Git Branch Sync Script
Switches to main, pulls latest changes, then merges into Development branch
"""

import subprocess
import sys
import time

def run_git_command(command, description):
    """Run a git command and handle errors"""
    print(f"\n{'='*50}")
    print(f"EXECUTING: {description}")
    print(f"Command: {' '.join(command)}")
    print(f"{'='*50}")
    
    try:
        result = subprocess.run(
            command, 
            check=True, 
            capture_output=True, 
            text=True,
            cwd='.'
        )
        
        if result.stdout:
            print("Output:")
            print(result.stdout)
        
        if result.stderr:
            print("Info/Warnings:")
            print(result.stderr)
            
        print(f"✅ SUCCESS: {description}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ ERROR: {description} failed!")
        print(f"Return code: {e.returncode}")
        if e.stdout:
            print(f"Output: {e.stdout}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False

def main():
    """Main function to sync branches"""
    print("🔄 Starting Git Branch Sync Process")
    print("This script will:")
    print("1. Switch to main branch")
    print("2. Pull latest changes from origin")
    print("3. Switch to Development branch") 
    print("4. Merge main into Development")
    
    # Confirm before proceeding
    response = input("\nProceed? (y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("Operation cancelled.")
        sys.exit(0)
    
    # Step 1: Switch to main branch
    if not run_git_command(['git', 'checkout', 'main'], "Switching to main branch"):
        sys.exit(1)
    
    # Pause to ensure checkout completes
    print("\n⏳ Pausing for 2 seconds to ensure checkout completes...")
    time.sleep(2)
    
    # Step 2: Pull latest changes from main
    if not run_git_command(['git', 'pull', 'origin', 'main'], "Pulling latest changes from main"):
        sys.exit(1)
    
    # Pause to ensure pull completes
    print("\n⏳ Pausing for 2 seconds to ensure pull completes...")
    time.sleep(2)
    
    # Step 3: Switch to Development branch
    if not run_git_command(['git', 'checkout', 'Development'], "Switching to Development branch"):
        sys.exit(1)
    
    # Pause to ensure checkout completes
    print("\n⏳ Pausing for 2 seconds to ensure checkout completes...")
    time.sleep(2)
    
    # Step 4: Merge main into Development
    if not run_git_command(['git', 'merge', 'main'], "Merging main into Development"):
        print("\n⚠️  Merge may have conflicts that need manual resolution.")
        print("Please resolve any conflicts and commit the merge manually.")
        sys.exit(1)
    
    print("\n🎉 SUCCESS: Branch sync completed successfully!")
    print("Development branch is now up to date with main.")

if __name__ == "__main__":
    main()
import os
import subprocess
import sys
import shutil

def run_cmd(cmd):
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"Error executing: {cmd}")
        sys.exit(1)

def main():
    print("=== Step 1: Building Uninstaller ===")
    uninstaller_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed '
        '--name "uninstall" '
        'uninstaller_gui.py'
    )
    run_cmd(uninstaller_cmd)

    print("=== Step 2: Building Main Application ===")
    run_cmd("python -m PyInstaller --clean setup_pyinstaller.spec")
    
    # Check if builds succeeded
    main_exe = os.path.join("dist", "Beta_NeDotify.exe")
    uninstall_exe = os.path.join("dist", "uninstall.exe")
    
    if not os.path.exists(main_exe):
        print("Failed to build main app. File 'dist/Beta_NeDotify.exe' not found.")
        sys.exit(1)

    if not os.path.exists(uninstall_exe):
        print("Failed to build uninstaller. File 'dist/uninstall.exe' not found.")
        sys.exit(1)
        
    print("=== Step 3: Building Setup Executable ===")
    installer_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed '
        '--name "NeDotify_beta5_Setup" '
        '--add-data "dist/Beta_NeDotify.exe;." '
        '--add-data "dist/uninstall.exe;." '
        'installer_gui.py'
    )
    run_cmd(installer_cmd)
    
    print("=== DONE! ===")
    print("Installer is ready at: dist/NeDotify_beta5_Setup.exe")

if __name__ == "__main__":
    main()

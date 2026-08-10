import os
import subprocess
import sys
import shutil

def run_cmd(cmd):
    print(f"\n==========================================")
    print(f"Executing: {cmd}")
    print(f"==========================================\n")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"Error executing: {cmd}")
        sys.exit(1)

def main():
    print("=== Step 0: Ensuring Icon ===")
    run_cmd("python make_icon.py")

    print("\n=== Step 1: Building Uninstaller ===")
    uninstaller_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed --icon=icon.ico '
        '--name "uninstall" '
        'uninstaller_gui.py'
    )
    run_cmd(uninstaller_cmd)

    print("\n=== Step 2: Building Main NeDotify Application ===")
    run_cmd("python -m PyInstaller --clean setup_pyinstaller.spec")
    
    # Check if builds succeeded
    main_exe = os.path.join("dist", "NeDotify.exe")
    uninstall_exe = os.path.join("dist", "uninstall.exe")
    
    if not os.path.exists(main_exe):
        print("Failed to build main app. File 'dist/NeDotify.exe' not found.")
        sys.exit(1)

    if not os.path.exists(uninstall_exe):
        print("Failed to build uninstaller. File 'dist/uninstall.exe' not found.")
        sys.exit(1)
        
    print("\n=== Step 3: Building Setup Executable (NeDotify_v1.5.0.exe) ===")
    installer_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed --icon=icon.ico '
        '--name "NeDotify_v1.5.0" '
        '--add-data "dist/NeDotify.exe;." '
        '--add-data "dist/uninstall.exe;." '
        'installer_gui.py'
    )
    run_cmd(installer_cmd)

    setup_exe = os.path.join("dist", "NeDotify_v1.5.0.exe")
    
    print("\n==========================================")
    print("=== BUILD SUCCESSFUL! ===")
    print(f"Installer created at: {setup_exe}")
    print("==========================================\n")

if __name__ == "__main__":
    main()

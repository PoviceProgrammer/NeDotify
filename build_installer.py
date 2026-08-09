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
    print("=== Step 1: Building Uninstaller ===")
    uninstaller_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed '
        '--name "uninstall" '
        'uninstaller_gui.py'
    )
    run_cmd(uninstaller_cmd)

    print("=== Step 2: Building Main NeDotify Application ===")
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
        
    print("=== Step 3: Building Setup Executable (NeDotify_Setup.exe) ===")
    installer_cmd = (
        'python -m PyInstaller --noconfirm --onefile --windowed '
        '--name "NeDotify_Setup" '
        '--add-data "dist/NeDotify.exe;." '
        '--add-data "dist/uninstall.exe;." '
        'installer_gui.py'
    )
    run_cmd(installer_cmd)

    # Also create NeDotify_beta5_Setup.exe copy for backward compatibility if needed by vk_bot.py
    setup_exe = os.path.join("dist", "NeDotify_Setup.exe")
    setup_b5 = os.path.join("dist", "NeDotify_beta5_Setup.exe")
    if os.path.exists(setup_exe):
        shutil.copyfile(setup_exe, setup_b5)
        print(f"Copied {setup_exe} to {setup_b5}")
    
    print("\n=== BUILD SUCCESSFUL! ===")
    print("Installer created at: dist/NeDotify_Setup.exe")

if __name__ == "__main__":
    main()

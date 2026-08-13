"""
Builds the NeDotify_v1.5.1 installer (onefile):
  uninstall.exe  <- uninstaller_gui.py
  NeDotify.exe   <- main.py  (via setup_pyinstaller.spec)
  NeDotify_v1.5.1.exe <- installer_gui.py (+ embedded NeDotify.exe + uninstall.exe)

Run: python build_v151_installer.py
"""
import os
import subprocess
import sys

APP_KEY = "NeDotify_v2.0.0"


def run_cmd(cmd):
    print("\n==========================================")
    print(f"Executing: {cmd}")
    print("==========================================\n")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"Error executing: {cmd}")
        sys.exit(1)


def main():
    print("=== Step 0: Generating icon (icon.ico / icon.png) ===")
    run_cmd("python make_icon_v151.py")

    print("\n=== Step 1: Building Uninstaller ===")
    run_cmd(
        'python -m PyInstaller --noconfirm --onefile --windowed --icon=icon.ico '
        '--name "uninstall" uninstaller_gui.py'
    )

    print("\n=== Step 2: Building Main NeDotify Application ===")
    run_cmd("python -m PyInstaller --clean setup_pyinstaller.spec")

    main_exe = os.path.join("dist", "NeDotify.exe")
    uninstall_exe = os.path.join("dist", "uninstall.exe")

    if not os.path.exists(main_exe):
        print("Failed to build main app. File 'dist/NeDotify.exe' not found.")
        sys.exit(1)

    if not os.path.exists(uninstall_exe):
        print("Failed to build uninstaller. File 'dist/uninstall.exe' not found.")
        sys.exit(1)

    print(f"\n=== Step 3: Building Setup Executable ({APP_KEY}.exe) ===")
    run_cmd(
        f'python -m PyInstaller --noconfirm --onefile --windowed --icon=icon.ico '
        f'--name "{APP_KEY}" '
        f'--add-data "dist/NeDotify.exe;." '
        f'--add-data "dist/uninstall.exe;." '
        f'installer_gui.py'
    )

    setup_exe = os.path.join("dist", f"{APP_KEY}.exe")

    print("\n==========================================")
    print("=== BUILD SUCCESSFUL! ===")
    print(f"Installer created at: {setup_exe}")
    print("==========================================\n")


if __name__ == "__main__":
    main()
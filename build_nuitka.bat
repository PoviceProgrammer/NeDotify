@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo    NeDotify - Nuitka Build Script
echo ==============================================

echo [1/4] Checking Python environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install nuitka

echo [3/4] Cleaning old builds...
if exist "dist" rmdir /s /q "dist"
if exist "main.build" rmdir /s /q "main.build"
if exist "main.dist" rmdir /s /q "main.dist"

echo [4/4] Starting Nuitka compilation...
echo This will take 5-20 minutes depending on your CPU.
echo Note: Nuitka will automatically download a C compiler (gcc/MinGW64) if one is not found.

REM --standalone is generally safer for pywebview than --onefile
python -m nuitka ^
    --standalone ^
    --windows-disable-console ^
    --windows-icon-from-ico=ui\assets\icon.ico ^
    --include-package=webview ^
    --include-package-data=webview ^
    --include-data-dir=ui=ui ^
    --assume-yes-for-downloads ^
    --output-dir=dist ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo ==============================================
    echo    Build Successful!
    echo    Executable is located in: dist\main.dist\main.exe
    echo ==============================================
) else (
    echo.
    echo ==============================================
    echo    Build Failed. Please check the logs above.
    echo ==============================================
)

pause

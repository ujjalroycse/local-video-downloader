@echo off
title Local Video Downloader - Setup

echo.
echo ==========================================
echo      LOCAL VIDEO DOWNLOADER SETUP
echo ==========================================
echo.

echo [1/5] Checking Python...
python --version >nul 2>&1

if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed.
    echo.
    echo Please install Python first:
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo Python found.
python --version

echo.
echo [2/5] Upgrading pip...
python -m pip install --upgrade pip

echo.
echo [3/5] Installing Python dependencies...
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install Python dependencies.
    echo.
    pause
    exit /b 1
)

echo.
echo [4/5] Checking FFmpeg...
ffmpeg -version >nul 2>&1

if errorlevel 1 (
    echo.
    echo FFmpeg was not found.
    echo Attempting to install FFmpeg using Winget...
    echo.

    winget install -e --id Gyan.FFmpeg

    if errorlevel 1 (
        echo.
        echo WARNING: FFmpeg installation failed.
        echo Please install FFmpeg manually.
        echo.
        echo Command:
        echo winget install -e --id Gyan.FFmpeg
        echo.
    )
) else (
    echo FFmpeg found.
)

echo.
echo [5/5] Creating required folders...

if not exist "downloads" mkdir "downloads"

echo.
echo ==========================================
echo          SETUP COMPLETED
echo ==========================================
echo.
echo To start the downloader:
echo.
echo     python app.py
echo.
echo Then open:
echo.
echo     http://127.0.0.1:5000
echo.
echo ==========================================
echo.

pause
@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Universal Video Downloader - EXE Builder
echo.
echo ==========================================================
echo          UNIVERSAL VIDEO DOWNLOADER
echo                 WINDOWS EXE BUILDER
echo ==========================================================
echo.
REM ==========================================================
REM Configuration
REM ==========================================================
set "APP_NAME=LocalVideoDownloader"
REM ==========================================================
REM Step 1 - Check Python
REM ==========================================================
echo [1/7] Checking Python...
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo.
    echo Please install Python first.
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
python --version
echo.
echo Python found.
echo.
REM ==========================================================
REM Step 2 - Install / Update PyInstaller
REM ==========================================================
echo [2/7] Checking PyInstaller...
echo.
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller is not installed.
    echo Installing PyInstaller...
    echo.
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install PyInstaller.
        echo.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller is already installed.
)
echo.
python -m PyInstaller --version
echo.
REM ==========================================================
REM Step 3 - Check yt-dlp
REM ==========================================================
echo [3/7] Checking yt-dlp...
echo.
python -m pip show yt-dlp >nul 2>&1
if errorlevel 1 (
    echo yt-dlp is not installed.
    echo Installing yt-dlp...
    echo.
    python -m pip install yt-dlp
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install yt-dlp.
        echo.
        pause
        exit /b 1
    )
) else (
    echo yt-dlp found.
)
echo.
REM ==========================================================
REM Step 4 - Find FFmpeg
REM ==========================================================
echo [4/7] Locating FFmpeg...
echo.
set "FFMPEG_EXE="
for /f "delims=" %%F in ('where ffmpeg 2^>nul') do (
    if not defined FFMPEG_EXE set "FFMPEG_EXE=%%F"
)
if not defined FFMPEG_EXE (
    echo ERROR: FFmpeg was not found.
    echo.
    echo Please install FFmpeg first.
    echo.
    echo You can use:
    echo winget install -e --id Gyan.FFmpeg
    echo.
    pause
    exit /b 1
)
echo FFmpeg:
echo !FFMPEG_EXE!
echo.
REM ==========================================================
REM Step 5 - Prepare FFmpeg Folder
REM ==========================================================
echo [5/7] Preparing bundled FFmpeg...
echo.
if not exist "ffmpeg" (
    mkdir "ffmpeg"
)
echo Copying ffmpeg.exe...
copy /Y "!FFMPEG_EXE!" "ffmpeg\ffmpeg.exe" >nul
if errorlevel 1 (
    echo.
    echo ERROR: Could not copy ffmpeg.exe.
    echo.
    pause
    exit /b 1
)
echo.
echo Bundled FFmpeg is ready.
echo FFprobe will NOT be bundled.
echo.
REM ==========================================================
REM Step 6 - Clean Previous Build
REM ==========================================================
echo [6/7] Cleaning previous build...
echo.
if exist "build" (
    rmdir /S /Q "build"
)
if exist "dist" (
    rmdir /S /Q "dist"
)
if exist "%APP_NAME%.spec" (
    del /Q "%APP_NAME%.spec"
)
echo Previous build files removed.
echo.
REM ==========================================================
REM Step 7 - Build EXE
REM ==========================================================
echo [7/7] Building Windows EXE...
echo.
echo This may take several minutes.
echo.
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --noconsole ^
    --name "%APP_NAME%" ^
    --collect-all yt_dlp ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    app.py
if errorlevel 1 (
    echo.
    echo ==========================================================
    echo                  BUILD FAILED
    echo ==========================================================
    echo.
    echo PyInstaller could not build the application.
    echo.
    pause
    exit /b 1
)
REM ==========================================================
REM Copy FFmpeg into final application
REM ==========================================================
echo.
echo Copying FFmpeg into final application...
echo.
if not exist "dist\%APP_NAME%\ffmpeg" (
    mkdir "dist\%APP_NAME%\ffmpeg"
)
copy /Y "ffmpeg\ffmpeg.exe" "dist\%APP_NAME%\ffmpeg\ffmpeg.exe" >nul
if errorlevel 1 (
    echo.
    echo ERROR: Could not copy FFmpeg into final application.
    echo.
    pause
    exit /b 1
)
REM ==========================================================
REM Create Downloads Folder
REM ==========================================================
if not exist "dist\%APP_NAME%\downloads" (
    mkdir "dist\%APP_NAME%\downloads"
)
REM ==========================================================
REM Create Start Script
REM ==========================================================
(
echo @echo off
echo start "" "LocalVideoDownloader.exe"
) > "dist\%APP_NAME%\Start Downloader.bat"
REM ==========================================================
REM Finished
REM ==========================================================
echo.
echo ==========================================================
echo                  BUILD COMPLETED
echo ==========================================================
echo.
echo Your Windows application is here:
echo.
echo dist\%APP_NAME%\
echo.
echo Main EXE:
echo.
echo dist\%APP_NAME%\LocalVideoDownloader.exe
echo.
echo ==========================================================
echo.
echo FFmpeg bundled: YES
echo FFprobe bundled: NO
echo.
echo You can now double-click:
echo.
echo LocalVideoDownloader.exe
echo.
echo ==========================================================
echo.
pause
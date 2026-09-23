# Local Video Downloader

A local video downloader built with Python, Flask, yt-dlp and FFmpeg.

The application runs locally on your computer and provides a simple web interface for downloading supported online videos.

---

## Features

- Download supported online videos
- YouTube support
- Pinterest support
- TikTok support
- Other yt-dlp supported platforms
- MP4 output
- MKV output
- MP3 audio extraction
- Multiple video quality options
- YouTube audio language selection
- Download progress tracking
- Local file storage
- FFmpeg-based video/audio processing

---

## Requirements

Before running the application, make sure you have:

- Windows 10/11
- Python 3.10 or newer
- FFmpeg
- Internet connection

Python:

https://www.python.org/downloads/

---

## Quick Setup

### 1. Download or copy the project

Copy the complete `downloder` folder to your computer.

### 2. Run setup

Double-click:

`setup.bat`

The setup script will:

- Check Python
- Install Python dependencies
- Check FFmpeg
- Try to install FFmpeg using Winget
- Create the downloads folder

---

## Manual Setup

If you prefer to install everything manually:

### Install Python

Download Python from:

https://www.python.org/downloads/

During installation, make sure:

`Add Python to PATH`

is enabled.

### Install Python dependencies

Open PowerShell inside the project folder:

```powershell
python -m pip install -r requirements.txt
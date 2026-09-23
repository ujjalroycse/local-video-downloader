import os
import shutil
import sys
from pathlib import Path


def get_app_directory():
    """
    Returns the directory where the application is running.

    Normal Python:
        project root

    PyInstaller EXE:
        directory containing the EXE
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


def get_bundled_ffmpeg_directory():
    """
    Returns the bundled FFmpeg directory.

    Expected structure:

    LocalVideoDownloader/
    ├── LocalVideoDownloader.exe
    └── ffmpeg/
        ├── ffmpeg.exe
        └── ffprobe.exe
    """

    return get_app_directory() / "ffmpeg"


def get_ffmpeg_path():
    """
    Find FFmpeg executable.

    Priority:

    1. Bundled FFmpeg
    2. System PATH
    """

    bundled_dir = get_bundled_ffmpeg_directory()

    if os.name == "nt":
        bundled_ffmpeg = bundled_dir / "ffmpeg.exe"
    else:
        bundled_ffmpeg = bundled_dir / "ffmpeg"

    if bundled_ffmpeg.exists():
        return str(bundled_ffmpeg)

    system_ffmpeg = shutil.which("ffmpeg")

    if system_ffmpeg:
        return system_ffmpeg

    return None


def get_ffprobe_path():
    """
    Find FFprobe executable.

    Priority:

    1. Bundled FFprobe
    2. System PATH
    """

    bundled_dir = get_bundled_ffmpeg_directory()

    if os.name == "nt":
        bundled_ffprobe = bundled_dir / "ffprobe.exe"
    else:
        bundled_ffprobe = bundled_dir / "ffprobe"

    if bundled_ffprobe.exists():
        return str(bundled_ffprobe)

    system_ffprobe = shutil.which("ffprobe")

    if system_ffprobe:
        return system_ffprobe

    return None


def get_ffmpeg_directory():
    """
    Returns the directory containing FFmpeg.
    """

    ffmpeg_path = get_ffmpeg_path()

    if not ffmpeg_path:
        return None

    return str(Path(ffmpeg_path).parent)


def is_ffmpeg_installed():
    """
    Check whether FFmpeg is available.
    """

    return get_ffmpeg_path() is not None


def is_ffprobe_installed():
    """
    Check whether FFprobe is available.
    """

    return get_ffprobe_path() is not None


def get_ffmpeg_status():
    """
    Returns FFmpeg availability information.
    """

    ffmpeg_path = get_ffmpeg_path()
    ffprobe_path = get_ffprobe_path()

    return {
        "ffmpeg": ffmpeg_path,
        "ffprobe": ffprobe_path,
        "available": ffmpeg_path is not None,
    }
import sys
from pathlib import Path


# =========================================================
# Base Directory
# =========================================================

if getattr(sys, "frozen", False):
    # Running as a PyInstaller EXE
    BASE_DIR = Path(sys.executable).resolve().parent

else:
    # Running normally from Python
    BASE_DIR = Path(__file__).resolve().parent.parent


# =========================================================
# Flask Server
# =========================================================

# Flask listens on the local machine
HOST = "127.0.0.1"

# Local server port
PORT = 5000

# Address opened automatically in the browser
BROWSER_HOST = "localhost"

DEBUG = True


# =========================================================
# Download Folder
# =========================================================

DOWNLOAD_FOLDER = BASE_DIR / "downloads"


# =========================================================
# Download Settings
# =========================================================

MAX_CONCURRENT_DOWNLOADS = 1


# =========================================================
# Create Required Folder
# =========================================================

DOWNLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)
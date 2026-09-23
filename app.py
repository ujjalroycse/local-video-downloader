from flask import (
    Flask,
    Response,
    render_template,
    request,
    jsonify,
    send_from_directory,
    stream_with_context,
)
import os
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from config import settings
from services.analyzer import analyze_url
from services.downloader import (
    start_download_thread,
    get_progress,
    cancel_download,
)
from services.ffmpeg_service import (
    is_ffmpeg_installed,
)
# =========================================================
# Application Resource Paths
# =========================================================
if getattr(sys, "frozen", False):
    APP_RESOURCE_DIR = Path(
        getattr(
            sys,
            "_MEIPASS",
            Path(sys.executable).resolve().parent
        )
    )
else:
    APP_RESOURCE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_RESOURCE_DIR / "templates"
STATIC_DIR = APP_RESOURCE_DIR / "static"
# =========================================================
# Flask Application
# =========================================================
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
)
# =========================================================
# Browser Lifecycle / Automatic Shutdown
# =========================================================
#
# The downloader page maintains one persistent Server-Sent
# Events (SSE) connection to this backend.
#
# IMPORTANT:
#
# Browser tab OPEN
#       ↓
# Persistent SSE connection
#       ↓
# EXE keeps running
#
# Switch to another Chrome tab
#       ↓
# SSE connection remains alive
#       ↓
# EXE keeps running
#
# Reload downloader page
#       ↓
# Old connection closes
#       ↓
# New connection reconnects
#       ↓
# Grace period prevents shutdown
#
# Actually close downloader tab
#       ↓
# SSE connection closes
#       ↓
# Grace period
#       ↓
# EXE shuts down
#
# This replaces the old heartbeat system.
# =========================================================
LIFECYCLE_LOCK = threading.Lock()
LIFECYCLE_GENERATION = 0
LIFECYCLE_CONNECTED = False
LIFECYCLE_GRACE_PERIOD = 5
def mark_lifecycle_connected():
    """
    Mark the current browser page as connected.
    A generation number is returned so an old connection
    cannot accidentally shut down a newer connection after
    a page reload.
    """
    global LIFECYCLE_GENERATION
    global LIFECYCLE_CONNECTED
    with LIFECYCLE_LOCK:
        LIFECYCLE_GENERATION += 1
        connection_generation = (
            LIFECYCLE_GENERATION
        )
        LIFECYCLE_CONNECTED = True
    return connection_generation
def mark_lifecycle_disconnected(
    connection_generation
):
    """
    Mark the browser connection as disconnected only if this
    connection is still the current connection.
    """
    global LIFECYCLE_CONNECTED
    with LIFECYCLE_LOCK:
        # A newer connection already exists.
        #
        # This normally happens during a page reload.
        if (
            connection_generation
            != LIFECYCLE_GENERATION
        ):
            return False
        LIFECYCLE_CONNECTED = False
    return True
def wait_for_download_to_stop(
    timeout=10
):
    """
    Wait for an active download to reach a terminal state
    after cancellation has been requested.
    """
    deadline = (
        time.time()
        + timeout
    )
    terminal_states = {
        "cancelled",
        "completed",
        "error",
        "idle",
    }
    while time.time() < deadline:
        try:
            current_status = (
                get_progress().get(
                    "status"
                )
            )
        except Exception:
            current_status = None
        if (
            current_status
            in terminal_states
        ):
            return
        time.sleep(0.2)
def shutdown_after_disconnect(
    connection_generation
):
    """
    Wait briefly after a browser disconnect.
    The grace period allows a normal page reload to close the
    old connection and establish a new connection without
    shutting down the EXE.
    If no new connection appears, the browser page is considered
    closed and the packaged EXE is shut down.
    """
    time.sleep(
        LIFECYCLE_GRACE_PERIOD
    )
    with LIFECYCLE_LOCK:
        # A new page connection appeared during the grace period.
        if (
            connection_generation
            != LIFECYCLE_GENERATION
        ):
            return
        if LIFECYCLE_CONNECTED:
            return
    print(
        "Browser lifecycle connection closed. "
        "Downloader tab appears to be closed."
    )
    # Automatic shutdown only applies to the packaged EXE.
    #
    # During normal development:
    #
    #     python app.py
    #
    # the server will NOT automatically shut down.
    if not getattr(
        sys,
        "frozen",
        False,
    ):
        return
    # ---------------------------------------------------------
    # Cancel Active Download Before Shutdown
    # ---------------------------------------------------------
    try:
        current_status = (
            get_progress().get(
                "status"
            )
        )
        active_states = {
            "starting",
            "downloading",
            "processing",
            "cancelling",
        }
        if (
            current_status
            in active_states
        ):
            print(
                "Active download detected. "
                "Requesting cancellation..."
            )
            cancel_download()
            wait_for_download_to_stop(
                timeout=10
            )
    except Exception:
        app.logger.exception(
            "Error while cancelling download during shutdown"
        )
    # ---------------------------------------------------------
    # Shutdown EXE
    # ---------------------------------------------------------
    print(
        "Shutting down application..."
    )
    # Intentional for the packaged local application.
    os._exit(0)
@app.route(
    "/api/lifecycle",
    methods=["GET"],
)
def lifecycle():
    """
    Keep a persistent SSE connection between the downloader
    browser tab and the backend.
    The browser remains connected even when its tab is in the
    background.
    When the tab is actually closed or reloaded, the connection
    is terminated and the generator's finally block schedules
    the shutdown check.
    """
    connection_generation = (
        mark_lifecycle_connected()
    )
    def event_stream():
        try:
            # -------------------------------------------------
            # Initial SSE Event
            # -------------------------------------------------
            yield (
                "event: connected\n"
                "data: {\"status\":\"connected\"}\n\n"
            )
            # -------------------------------------------------
            # Keep Connection Alive
            # -------------------------------------------------
            while True:
                time.sleep(10)
                with LIFECYCLE_LOCK:
                    # A newer browser connection replaced this one.
                    if (
                        connection_generation
                        != LIFECYCLE_GENERATION
                    ):
                        return
                    if not LIFECYCLE_CONNECTED:
                        return
                # Valid SSE comment used as keep-alive.
                yield (
                    ": keep-alive\n\n"
                )
        except GeneratorExit:
            # Browser closed/reloaded the connection.
            raise
        except Exception:
            app.logger.exception(
                "Browser lifecycle connection ended unexpectedly"
            )
        finally:
            disconnected = (
                mark_lifecycle_disconnected(
                    connection_generation
                )
            )
            if disconnected:
                shutdown_thread = threading.Thread(
                    target=shutdown_after_disconnect,
                    args=(
                        connection_generation,
                    ),
                    daemon=True,
                )
                shutdown_thread.start()
    return Response(
        stream_with_context(
            event_stream()
        ),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
# =========================================================
# Home
# =========================================================
@app.route("/")
def index():
    return render_template(
        "index.html"
    )
# =========================================================
# Favicon
# =========================================================
@app.route("/favicon.png")
def favicon():
    return send_from_directory(
        STATIC_DIR,
        "favicon.png",
        mimetype="image/png",
    )
# =========================================================
# Health Check
# =========================================================
@app.route("/api/health")
def health():
    return jsonify({
        "success": True,
        "message": "Video Downloader API is running",
        "ffmpeg_installed": (
            is_ffmpeg_installed()
        ),
    })
# =========================================================
# Analyze Video
# =========================================================
@app.route(
    "/api/analyze",
    methods=["POST"],
)
def analyze():
    data = request.get_json(
        silent=True
    ) or {}
    url = data.get(
        "url",
        "",
    ).strip()
    # -----------------------------------------------------
    # Validate URL
    # -----------------------------------------------------
    if not url:
        return jsonify({
            "success": False,
            "error": (
                "Please enter a video URL."
            ),
        }), 400
    try:
        result = analyze_url(
            url
        )
        status_code = (
            200
            if result.get("success")
            else 400
        )
        return jsonify(
            result
        ), status_code
    except Exception:
        app.logger.exception(
            "Unexpected error during video analysis"
        )
        return jsonify({
            "success": False,
            "error": (
                "An unexpected server error "
                "occurred while analyzing the video."
            ),
        }), 500
# =========================================================
# Start Download
# =========================================================
@app.route(
    "/api/download",
    methods=["POST"],
)
def download():
    data = request.get_json(
        silent=True
    ) or {}
    # -----------------------------------------------------
    # URL
    # -----------------------------------------------------
    url = data.get(
        "url",
        "",
    ).strip()
    # -----------------------------------------------------
    # Format
    # -----------------------------------------------------
    format_ext = (
        data.get(
            "format",
            "mp4",
        )
        .lower()
        .strip()
    )
    # -----------------------------------------------------
    # Quality
    # -----------------------------------------------------
    quality = (
        data.get(
            "quality",
            "1080p",
        )
        .strip()
    )
    # -----------------------------------------------------
    # Audio Language
    # -----------------------------------------------------
    language = (
        data.get(
            "language",
            "",
        )
        .strip()
        .lower()
    )
    # -----------------------------------------------------
    # Validate URL
    # -----------------------------------------------------
    if not url:
        return jsonify({
            "success": False,
            "error": "No URL provided.",
        }), 400
    # -----------------------------------------------------
    # Validate Format
    # -----------------------------------------------------
    allowed_formats = {
        "mp4",
        "mkv",
        "mp3",
    }
    if format_ext not in allowed_formats:
        return jsonify({
            "success": False,
            "error": (
                "Unsupported format."
            ),
        }), 400
    # -----------------------------------------------------
    # Validate Quality
    # -----------------------------------------------------
    if quality.upper() == "4K":
        quality = "4K"
    else:
        quality_match = re.fullmatch(
            r"(\d{3,4})[pP]",
            quality,
        )
        if not quality_match:
            return jsonify({
                "success": False,
                "error": (
                    "Unsupported video quality."
                ),
            }), 400
        quality_height = int(
            quality_match.group(1)
        )
        if (
            quality_height < 144
            or quality_height > 4320
        ):
            return jsonify({
                "success": False,
                "error": (
                    "Unsupported video quality."
                ),
            }), 400
        quality = (
            f"{quality_height}p"
        )
    # -----------------------------------------------------
    # Validate Language
    # -----------------------------------------------------
    if language:
        language_pattern = (
            r"^[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*$"
        )
        if not re.fullmatch(
            language_pattern,
            language,
        ):
            return jsonify({
                "success": False,
                "error": (
                    "Invalid audio language."
                ),
            }), 400
    # -----------------------------------------------------
    # Start Download
    # -----------------------------------------------------
    started = start_download_thread(
        url,
        format_ext,
        quality,
        language,
    )
    # -----------------------------------------------------
    # Download Already Running
    # -----------------------------------------------------
    if not started:
        return jsonify({
            "success": False,
            "error": (
                "A download is already "
                "in progress. Please wait "
                "until it finishes."
            ),
        }), 409
    # -----------------------------------------------------
    # Success
    # -----------------------------------------------------
    return jsonify({
        "success": True,
        "message": "Download started.",
        "format": format_ext,
        "quality": quality,
        "language": language,
    })
# =========================================================
# Download Progress
# =========================================================
@app.route("/api/progress")
def progress():
    return jsonify(
        get_progress()
    )
# =========================================================
# Cancel Download
# =========================================================
@app.route(
    "/api/cancel",
    methods=["POST"],
)
def cancel():
    result = cancel_download()
    if result.get("success"):
        return jsonify(
            result
        )
    return jsonify(
        result
    ), 400
# =========================================================
# List Downloaded Files
# =========================================================
@app.route("/api/downloads")
def list_downloads():
    files = []
    for path in (
        settings.DOWNLOAD_FOLDER.glob("*")
    ):
        if path.is_file():
            files.append({
                "name": path.name,
                "size": (
                    f"{path.stat().st_size / (1024 * 1024):.2f} MB"
                ),
            })
    return jsonify(
        files
    )
# =========================================================
# Serve Downloaded Files
# =========================================================
@app.route(
    "/downloads/<path:filename>"
)
def serve_download(filename):
    return send_from_directory(
        settings.DOWNLOAD_FOLDER,
        filename,
    )
# =========================================================
# Open Browser
# =========================================================
def open_browser():
    """
    Open the local downloader in the default browser.
    """
    webbrowser.open(
        f"http://{settings.BROWSER_HOST}:{settings.PORT}"
    )
# =========================================================
# Run Flask
# =========================================================
if __name__ == "__main__":
    is_frozen = getattr(
        sys,
        "frozen",
        False,
    )
    if is_frozen:
        # Give Flask a moment to start before
        # opening the browser.
        threading.Timer(
            1.5,
            open_browser,
        ).start()
        # Never use Flask's development reloader
        # inside the packaged EXE.
        app.run(
            host=settings.HOST,
            port=settings.PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    else:
        # Normal development mode.
        app.run(
            host=settings.HOST,
            port=settings.PORT,
            debug=settings.DEBUG,
            use_reloader=False,
            threaded=True,
        )
import logging
import time
from typing import Any
from urllib.parse import urlparse
import yt_dlp
logger = logging.getLogger(__name__)
SUPPORTED_QUALITIES = {
    480: "480p",
    720: "720p",
    1080: "1080p",
    1440: "1440p",
    2160: "4K",
}
# ---------------------------------------------------------
# Language Names
# ---------------------------------------------------------
LANGUAGE_NAMES = {
    "en": "English",
    "en-us": "English (US)",
    "en-gb": "English (UK)",
    "bn": "Bengali",
    "bn-bd": "Bengali (Bangladesh)",
    "bn-in": "Bengali (India)",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-br": "Portuguese (Brazil)",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-cn": "Chinese (China)",
    "zh-tw": "Chinese (Taiwan)",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "th": "Thai",
    "pl": "Polish",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "uk": "Ukrainian",
    "cs": "Czech",
    "ro": "Romanian",
}
# ---------------------------------------------------------
# Platform Helpers
# ---------------------------------------------------------
def get_hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
def is_youtube_url(url: str) -> bool:
    hostname = get_hostname(url)
    return (
        hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
        or hostname == "youtu.be"
        or hostname.endswith(".youtu.be")
    )
def is_pinterest_url(url: str) -> bool:
    hostname = get_hostname(url)
    return (
        hostname == "pinterest.com"
        or hostname.endswith(".pinterest.com")
        or hostname == "pin.it"
        or hostname.endswith(".pin.it")
    )
def build_ydl_options(url: str) -> dict[str, Any]:
    """
    Common yt-dlp settings.
    Pinterest sometimes resets the connection while requesting its
    JSON metadata. These retry/timeout/header settings give yt-dlp
    several chances to complete a transient request.
    """
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        # Network reliability.
        "socket_timeout": 30,
        "retries": 5,
        "extractor_retries": 5,
        "fragment_retries": 5,
        # Browser-like headers.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if is_pinterest_url(url):
        options["http_headers"].update({
            "Referer": "https://www.pinterest.com/",
            "Origin": "https://www.pinterest.com",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
        })
    return options
# ---------------------------------------------------------
# Language Helper
# ---------------------------------------------------------
def get_language_name(language_code: str) -> str:
    if not language_code:
        return ""
    language_code = language_code.strip().lower()
    if language_code in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[language_code]
    base_language = language_code.split("-")[0]
    if base_language in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[base_language]
    return language_code.upper()
# ---------------------------------------------------------
# Extract Audio Languages
# ---------------------------------------------------------
def extract_audio_languages(
    formats: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """
    Extract available audio languages from yt-dlp formats.
    This feature is intentionally used for YouTube only.
    """
    languages: dict[str, dict[str, str]] = {}
    for fmt in formats:
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        language = fmt.get("language")
        # Only audio-only formats.
        if vcodec not in (None, "none"):
            continue
        if acodec in (None, "none"):
            continue
        if not language:
            continue
        language = str(language).strip().lower()
        if not language:
            continue
        if language not in languages:
            languages[language] = {
                "code": language,
                "name": get_language_name(language),
            }
    return list(languages.values())
# ---------------------------------------------------------
# Analyze URL
# ---------------------------------------------------------
def analyze_url(url: str) -> dict[str, Any]:
    """
    Analyze one video URL using yt-dlp.
    YouTube:
        - quality detection
        - audio language detection
    Other supported platforms:
        - quality detection
        - no YouTube-specific audio-language selector
    """
    if not url or not url.strip():
        return {
            "success": False,
            "error": "URL is empty.",
        }
    url = url.strip()
    ydl_opts = build_ydl_options(url)
    # -----------------------------------------------------
    # Extract with retries
    # -----------------------------------------------------
    max_attempts = 3 if is_pinterest_url(url) else 1
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )
            if not info:
                return {
                    "success": False,
                    "error": "Could not extract video information.",
                }
            # -------------------------------------------------
            # Extract Formats
            # -------------------------------------------------
            formats = info.get("formats", [])
            # -------------------------------------------------
            # Extract Video Resolutions
            # -------------------------------------------------
            available_heights: set[int] = set()
            for fmt in formats:
                height = fmt.get("height")
                if (
                    isinstance(height, int)
                    and height in SUPPORTED_QUALITIES
                ):
                    available_heights.add(height)
            sorted_heights = sorted(available_heights)
            qualities = [
                SUPPORTED_QUALITIES[height]
                for height in sorted_heights
            ]
            # If the extractor does not expose one of our exact
            # preferred heights, still expose the best available
            # height rather than showing an empty quality list.
            if not qualities:
                all_heights = sorted({
                    fmt.get("height")
                    for fmt in formats
                    if isinstance(fmt.get("height"), int)
                    and fmt.get("height") > 0
                })
                if all_heights:
                    qualities = [
                        (
                            "4K"
                            if height >= 2160
                            else f"{height}p"
                        )
                        for height in all_heights
                    ]
            # -------------------------------------------------
            # YouTube Audio Languages
            # -------------------------------------------------
            languages = []
            if is_youtube_url(url):
                languages = extract_audio_languages(formats)
            # -------------------------------------------------
            # Supported Output Formats
            # -------------------------------------------------
            supported_formats = [
                "mp4",
                "mkv",
                "mp3",
            ]
            # -------------------------------------------------
            # Final Result
            # -------------------------------------------------
            return {
                "success": True,
                "title": (
                    info.get("title")
                    or "Unknown title"
                ),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "duration_string": info.get(
                    "duration_string"
                ),
                "uploader": info.get("uploader"),
                "webpage_url": (
                    info.get("webpage_url")
                    or url
                ),
                "qualities": qualities,
                "formats": supported_formats,
                "languages": languages,
                "platform": (
                    "youtube"
                    if is_youtube_url(url)
                    else (
                        "pinterest"
                        if is_pinterest_url(url)
                        else "other"
                    )
                ),
            }
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            logger.warning(
                "yt-dlp attempt %s/%s failed for %s: %s",
                attempt,
                max_attempts,
                url,
                exc,
            )
            # Pinterest connection resets can be transient.
            if is_pinterest_url(url) and attempt < max_attempts:
                time.sleep(2 * attempt)
                continue
            error_message = str(exc)
            if is_pinterest_url(url) and (
                "ConnectionResetError" in error_message
                or "Connection aborted" in error_message
                or "10054" in error_message
                or "Unable to download JSON metadata" in error_message
            ):
                return {
                    "success": False,
                    "error": (
                        "Pinterest connection was interrupted while "
                        "reading the Pin information. Please try again."
                    ),
                }
            return {
                "success": False,
                "error": (
                    "Unable to analyze this video: "
                    f"{error_message}"
                ),
            }
        except Exception as exc:
            last_error = exc
            logger.exception(
                "Unexpected error while analyzing URL: %s",
                url,
            )
            if is_pinterest_url(url) and attempt < max_attempts:
                time.sleep(2 * attempt)
                continue
            return {
                "success": False,
                "error": (
                    "Unexpected analysis error: "
                    f"{str(exc)}"
                ),
            }
    return {
        "success": False,
        "error": (
            "Unable to analyze this URL."
            if last_error is None
            else str(last_error)
        ),
    }

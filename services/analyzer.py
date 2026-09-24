import logging
import time
from typing import Any
from urllib.parse import urlparse
import yt_dlp
logger = logging.getLogger(__name__)
# ---------------------------------------------------------
# Standard User-Facing Qualities
# ---------------------------------------------------------
#
# Different platforms expose different raw resolutions.
#
# Examples:
#   416  -> 480p
#   640  -> 720p
#   960  -> 1080p
#   1280 -> 1440p
#
# The downloader will later select the actual available
# source stream at or below the requested quality.
# ---------------------------------------------------------
SUPPORTED_QUALITIES = {
    360: "360p",
    480: "480p",
    720: "720p",
    1080: "1080p",
    1440: "1440p",
    2160: "4K",
}
QUALITY_LEVELS = [
    (360, "360p"),
    (480, "480p"),
    (720, "720p"),
    (1080, "1080p"),
    (1440, "1440p"),
    (2160, "4K"),
]
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
        return (
            urlparse(url).hostname
            or ""
        ).lower()
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
# ---------------------------------------------------------
# yt-dlp Options
# ---------------------------------------------------------
def build_ydl_options(
    url: str,
) -> dict[str, Any]:
    """
    Common yt-dlp settings.
    Pinterest sometimes resets the connection while requesting
    its JSON metadata. These retry/timeout/header settings give
    yt-dlp several chances to complete a transient request.
    """
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        # -------------------------------------------------
        # Network reliability
        # -------------------------------------------------
        "socket_timeout": 30,
        "retries": 5,
        "extractor_retries": 5,
        "fragment_retries": 5,
        # -------------------------------------------------
        # Browser-like headers
        # -------------------------------------------------
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/153.0.0.0 "
                "Safari/537.36"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
        },
    }
    # -----------------------------------------------------
    # Pinterest-specific headers
    # -----------------------------------------------------
    if is_pinterest_url(url):
        options["http_headers"].update({
            "Referer": (
                "https://www.pinterest.com/"
            ),
            "Origin": (
                "https://www.pinterest.com"
            ),
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;"
                "q=0.9,"
                "image/avif,"
                "image/webp,"
                "*/*;"
                "q=0.8"
            ),
        })
    return options
# ---------------------------------------------------------
# Language Helper
# ---------------------------------------------------------
def get_language_name(
    language_code: str,
) -> str:
    if not language_code:
        return ""
    language_code = (
        language_code
        .strip()
        .lower()
    )
    if language_code in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[
            language_code
        ]
    base_language = (
        language_code
        .split("-")[0]
    )
    if base_language in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[
            base_language
        ]
    return language_code.upper()
# ---------------------------------------------------------
# Extract Audio Languages
# ---------------------------------------------------------
def extract_audio_languages(
    formats: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Extract available audio languages from yt-dlp formats.
    This feature is intentionally used for YouTube only.
    """
    languages: dict[
        str,
        dict[str, str]
    ] = {}
    for fmt in formats:
        vcodec = fmt.get(
            "vcodec"
        )
        acodec = fmt.get(
            "acodec"
        )
        language = fmt.get(
            "language"
        )
        # -------------------------------------------------
        # Only audio-only formats
        # -------------------------------------------------
        if vcodec not in (
            None,
            "none",
        ):
            continue
        if acodec in (
            None,
            "none",
        ):
            continue
        if not language:
            continue
        language = (
            str(language)
            .strip()
            .lower()
        )
        if not language:
            continue
        if language not in languages:
            languages[language] = {
                "code": language,
                "name": get_language_name(
                    language
                ),
            }
    return list(
        languages.values()
    )
# ---------------------------------------------------------
# Quality Helpers
# ---------------------------------------------------------
def normalize_height(
    value: Any,
) -> int | None:
    """
    Convert yt-dlp height values into a valid integer.
    Examples:
        720       -> 720
        "720"     -> 720
        1080.0    -> 1080
        None      -> None
        "unknown" -> None
    """
    if value is None:
        return None
    try:
        height = int(
            float(value)
        )
    except (
        TypeError,
        ValueError,
    ):
        return None
    if height <= 0:
        return None
    return height
def quality_bucket_for_height(
    height: int,
) -> tuple[int, str] | None:
    """
    Convert an actual source height into a standard
    user-facing quality bucket.
    Examples:
        224  -> 360p
        338  -> 360p
        416  -> 480p
        450  -> 480p
        640  -> 720p
        676  -> 720p
        960  -> 1080p
        1012 -> 1080p
        1280 -> 1440p
        1350 -> 1440p
        2026 -> 4K
    Very small / invalid heights are ignored.
    """
    if height < 144:
        return None
    for target_height, label in QUALITY_LEVELS:
        if height <= target_height:
            return (
                target_height,
                label,
            )
    # Anything above 2160p is represented as 4K.
    return (
        2160,
        "4K",
    )
def get_normalized_qualities(
    formats: list[dict[str, Any]],
) -> list[str]:
    """
    Build a universal quality list from raw yt-dlp formats.
    The source platform may expose arbitrary resolutions such as:
        416
        640
        960
        1280
    The user will see:
        480p
        720p
        1080p
        1440p
    Duplicate quality buckets are removed.
    """
    quality_targets: set[int] = set()
    for fmt in formats:
        if not isinstance(
            fmt,
            dict,
        ):
            continue
        height = normalize_height(
            fmt.get("height")
        )
        if height is None:
            continue
        bucket = quality_bucket_for_height(
            height
        )
        if bucket is None:
            continue
        target_height, _ = bucket
        quality_targets.add(
            target_height
        )
    sorted_targets = sorted(
        quality_targets
    )
    return [
        SUPPORTED_QUALITIES[
            target_height
        ]
        for target_height in sorted_targets
    ]
# ---------------------------------------------------------
# Analyze URL
# ---------------------------------------------------------
def analyze_url(
    url: str,
) -> dict[str, Any]:
    """
    Analyze one video URL using yt-dlp.
    YouTube:
        - quality detection
        - audio language detection
    Other supported platforms:
        - universal quality detection
        - no YouTube-specific audio-language selector
    """
    if not url or not url.strip():
        return {
            "success": False,
            "error": "URL is empty.",
        }
    url = url.strip()
    ydl_opts = build_ydl_options(
        url
    )
    # -----------------------------------------------------
    # Extract with retries
    # -----------------------------------------------------
    max_attempts = (
        3
        if is_pinterest_url(url)
        else 1
    )
    last_error: Exception | None = None
    for attempt in range(
        1,
        max_attempts + 1,
    ):
        try:
            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )
            if not info:
                return {
                    "success": False,
                    "error": (
                        "Could not extract "
                        "video information."
                    ),
                }
            # -------------------------------------------------
            # Extract Formats
            # -------------------------------------------------
            formats = (
                info.get("formats")
                or []
            )
            # -------------------------------------------------
            # Universal Quality Detection
            # -------------------------------------------------
            qualities = get_normalized_qualities(
                formats
            )
            # -------------------------------------------------
            # Safety fallback
            # -------------------------------------------------
            #
            # Normally get_normalized_qualities()
            # should return the available quality
            # buckets.
            #
            # If a platform exposes no usable height,
            # we don't invent a quality.
            #
            if not qualities:
                logger.warning(
                    "No usable video heights found "
                    "for URL: %s",
                    url,
                )
            # -------------------------------------------------
            # YouTube Audio Languages
            # -------------------------------------------------
            languages = []
            if is_youtube_url(url):
                languages = extract_audio_languages(
                    formats
                )
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
                "thumbnail": (
                    info.get("thumbnail")
                ),
                "duration": (
                    info.get("duration")
                ),
                "duration_string": (
                    info.get(
                        "duration_string"
                    )
                ),
                "uploader": (
                    info.get("uploader")
                ),
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
        # -----------------------------------------------------
        # yt-dlp Download Error
        # -----------------------------------------------------
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            logger.warning(
                "yt-dlp attempt %s/%s failed for %s: %s",
                attempt,
                max_attempts,
                url,
                exc,
            )
            # -------------------------------------------------
            # Pinterest connection resets can be transient.
            # -------------------------------------------------
            if (
                is_pinterest_url(url)
                and attempt < max_attempts
            ):
                time.sleep(
                    2 * attempt
                )
                continue
            error_message = str(
                exc
            )
            # -------------------------------------------------
            # Pinterest-specific connection error
            # -------------------------------------------------
            if (
                is_pinterest_url(url)
                and (
                    "ConnectionResetError"
                    in error_message
                    or
                    "Connection aborted"
                    in error_message
                    or
                    "10054"
                    in error_message
                    or
                    "Unable to download JSON metadata"
                    in error_message
                )
            ):
                return {
                    "success": False,
                    "error": (
                        "Pinterest connection was "
                        "interrupted while reading "
                        "the Pin information. "
                        "Please try again."
                    ),
                }
            return {
                "success": False,
                "error": (
                    "Unable to analyze this video: "
                    f"{error_message}"
                ),
            }
        # -----------------------------------------------------
        # Unexpected Error
        # -----------------------------------------------------
        except Exception as exc:
            last_error = exc
            logger.exception(
                "Unexpected error while "
                "analyzing URL: %s",
                url,
            )
            if (
                is_pinterest_url(url)
                and attempt < max_attempts
            ):
                time.sleep(
                    2 * attempt
                )
                continue
            return {
                "success": False,
                "error": (
                    "Unexpected analysis error: "
                    f"{str(exc)}"
                ),
            }
    # ---------------------------------------------------------
    # Final Failure
    # ---------------------------------------------------------
    return {
        "success": False,
        "error": (
            "Unable to analyze this URL."
            if last_error is None
            else str(last_error)
        ),
    }
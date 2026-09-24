import json
import os
import subprocess
import threading
import time
# Prevent FFmpeg / FFprobe console windows from opening on Windows.
WINDOWS_NO_WINDOW = getattr(
    subprocess,
    "CREATE_NO_WINDOW",
    0,
)
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import yt_dlp
from config.settings import DOWNLOAD_FOLDER
from .ffmpeg_service import (
    is_ffmpeg_installed,
    get_ffmpeg_directory,
    get_ffmpeg_path,
)
# ---------------------------------------------------------
# Global download state
# ---------------------------------------------------------
progress_data = {
    "status": "idle",
    "phase": "idle",
    "percentage": 0,  # Legacy field; mirrors the active phase.
    "download_percentage": 0,
    "processing_percentage": 0,
    "speed": "0 MB/s",
    "eta": "00:00",
    "filename": "",
    "error": None,
    "downloaded_bytes": 0,
    "total_bytes": 0,
}
# Keep progress for multiple streams
stream_progress = {}
# Only one download at a time.
download_lock = threading.Lock()
# Event used to request cancellation.
cancel_event = threading.Event()
# yt-dlp updates this through postprocessor_hooks after the
# video/audio streams have actually been merged.
postprocessed_path = {"path": None}
# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def get_stream_key(data):
    """Return a stable key for each active media stream."""
    return (
        data.get("filename")
        or data.get("tmpfilename")
        or data.get("info_dict", {}).get("format_id")
        or "unknown-stream"
    )
def resolve_short_url(url):
    """
    Resolve short URLs such as Pinterest pin.it links
    before handing them to yt-dlp.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    short_hosts = {
        "pin.it",
        "www.pin.it",
    }
    if host not in short_hosts:
        return url
    try:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/153.0 Safari/537.36"
                )
            },
            method="GET",
        )
        with urlopen(
            request,
            timeout=15,
        ) as response:
            final_url = response.geturl()
        if final_url:
            return final_url
    except Exception as exc:
        print(
            f"Short URL resolution failed: {exc}"
        )
    return url
def get_site(url):
    """Return a simple platform name."""
    host = (
        urlparse(url).netloc
        or ""
    ).lower()
    if (
        "youtube.com" in host
        or "youtu.be" in host
    ):
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    if (
        "pinterest.com" in host
        or "pin.it" in host
    ):
        return "pinterest"
    if "instagram.com" in host:
        return "instagram"
    if (
        "facebook.com" in host
        or "fb.watch" in host
    ):
        return "facebook"
    if (
        "twitter.com" in host
        or "x.com" in host
    ):
        return "twitter"
    if "vimeo.com" in host:
        return "vimeo"
    if (
        "reddit.com" in host
        or "redd.it" in host
    ):
        return "reddit"
    if "dailymotion.com" in host:
        return "dailymotion"
    return "other"
# ---------------------------------------------------------
# yt-dlp Post-Processing Hook
# ---------------------------------------------------------
def postprocessor_hook(data):
    """Capture the actual file path after yt-dlp post-processing.
    This is more reliable than prepare_filename() because yt-dlp
    may change the final filename/container after merging video
    and audio.
    """
    if data.get("status") != "finished":
        return
    info = data.get("info_dict") or {}
    filepath = (
        info.get("filepath")
        or info.get("_filename")
    )
    if not filepath:
        return
    path = Path(filepath)
    if path.exists() and path.is_file():
        # Only treat this as the final media path when it
        # actually contains both video and audio. yt-dlp can
        # invoke postprocessor hooks for intermediate files.
        if media_has_video_and_audio(path):
            postprocessed_path["path"] = str(path)
            print(
                "yt-dlp post-processing finished:"
                f" {path}"
            )
        else:
            print(
                "yt-dlp post-processing produced an "
                f"intermediate/non-A/V file: {path}"
            )
# ---------------------------------------------------------
# Progress Hook
# ---------------------------------------------------------
def progress_hook(data):
    """
    Receive yt-dlp download progress updates.
    Downloading and processing are tracked separately:
        Downloading -> download_percentage: 0 -> 100
        Processing  -> processing_percentage: 0 -> 100
    The legacy "percentage" field mirrors the active phase so
    the existing frontend remains compatible until it is updated.
    """
    global progress_data
    if cancel_event.is_set():
        progress_data["status"] = "cancelling"
        progress_data["speed"] = "Cancelling..."
        progress_data["eta"] = "00:00"
        raise yt_dlp.utils.DownloadCancelled(
            "Download cancelled by user."
        )
    status = data.get("status")
    stream_key = get_stream_key(data)
    if status == "downloading":
        try:
            downloaded_bytes = int(
                data.get("downloaded_bytes") or 0
            )
            total_bytes = int(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0
            )
            stream_progress[stream_key] = {
                "downloaded": downloaded_bytes,
                "total": total_bytes,
                "finished": False,
            }
            total_downloaded = sum(
                item["downloaded"]
                for item in stream_progress.values()
            )
            total_size = sum(
                item["total"]
                for item in stream_progress.values()
                if item["total"] > 0
            )
            if total_size > 0:
                download_percentage = (
                    total_downloaded / total_size
                ) * 100
                download_percentage = min(
                    download_percentage,
                    99.9,
                )
                download_percentage = max(
                    download_percentage,
                    float(
                        progress_data.get(
                            "download_percentage",
                            0,
                        )
                    ),
                )
            else:
                download_percentage = float(
                    progress_data.get(
                        "download_percentage",
                        0,
                    )
                )
            progress_data["download_percentage"] = round(
                download_percentage,
                1,
            )
            # Legacy field for the current frontend.
            progress_data["percentage"] = round(
                download_percentage,
                1,
            )
            progress_data["downloaded_bytes"] = total_downloaded
            progress_data["total_bytes"] = total_size
            progress_data["speed"] = (
                data.get("_speed_str")
                or "0 MB/s"
            )
            progress_data["eta"] = (
                data.get("_eta_str")
                or "00:00"
            )
            progress_data["status"] = "downloading"
            progress_data["phase"] = "downloading"
            filename = data.get("filename")
            if filename:
                progress_data["filename"] = Path(
                    filename
                ).name
        except (ValueError, TypeError):
            pass
    elif status == "finished":
        current = stream_progress.get(
            stream_key,
            {},
        )
        total = int(
            data.get("total_bytes")
            or data.get("total_bytes_estimate")
            or current.get("total")
            or 0
        )
        downloaded = int(
            data.get("downloaded_bytes")
            or total
            or current.get("downloaded")
            or 0
        )
        stream_progress[stream_key] = {
            "downloaded": downloaded,
            "total": total,
            "finished": True,
        }
        total_downloaded = sum(
            item["downloaded"]
            for item in stream_progress.values()
        )
        total_size = sum(
            item["total"]
            for item in stream_progress.values()
            if item["total"] > 0
        )
        finished_streams = [
            item
            for item in stream_progress.values()
            if item.get("finished")
        ]
        all_known_streams_finished = (
            bool(stream_progress)
            and len(finished_streams) == len(stream_progress)
        )
        if total_size > 0:
            download_percentage = min(
                (
                    total_downloaded
                    / total_size
                ) * 100,
                100.0,
            )
            download_percentage = max(
                download_percentage,
                float(
                    progress_data.get(
                        "download_percentage",
                        0,
                    )
                ),
            )
            progress_data["download_percentage"] = round(
                download_percentage,
                1,
            )
            progress_data["percentage"] = round(
                download_percentage,
                1,
            )
        progress_data["downloaded_bytes"] = total_downloaded
        progress_data["total_bytes"] = total_size
        filename = data.get("filename")
        if filename:
            progress_data["filename"] = Path(
                filename
            ).name
        # Do not start the processing phase until every
        # currently tracked stream has finished downloading.
        if all_known_streams_finished:
            progress_data["download_percentage"] = 100
            progress_data["processing_percentage"] = 0
            progress_data["percentage"] = 100
            progress_data["status"] = "processing"
            progress_data["phase"] = "processing"
            progress_data["speed"] = "Preparing..."
            progress_data["eta"] = "Processing..."
# ---------------------------------------------------------
# Quality Parser
# ---------------------------------------------------------
def parse_quality(quality):
    """
    Convert:
        480p  -> 480
        720p  -> 720
        1080p -> 1080
        1440p -> 1440
        4K    -> 2160
    """
    if not quality:
        return 1080
    quality = (
        str(quality)
        .strip()
        .upper()
    )
    if quality == "4K":
        return 2160
    if quality.endswith("P"):
        quality = quality[:-1]
    try:
        return int(quality)
    except ValueError:
        return 1080
# ---------------------------------------------------------
# Reset Progress
# ---------------------------------------------------------
def reset_progress():
    cancel_event.clear()
    postprocessed_path["path"] = None
    progress_data.update({
        "status": "starting",
        "phase": "downloading",
        "percentage": 0,
        "download_percentage": 0,
        "processing_percentage": 0,
        "speed": "0 MB/s",
        "eta": "00:00",
        "filename": "",
        "error": None,
        "downloaded_bytes": 0,
        "total_bytes": 0,
    })
    stream_progress.clear()
# ---------------------------------------------------------
# Cleanup Partial Files
# ---------------------------------------------------------
def cleanup_partial_files():
    """
    Remove partial and temporary files.
    """
    try:
        for path in DOWNLOAD_FOLDER.glob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in {
                ".part",
                ".ytdl",
                ".temp",
                ".tmp",
                ".remux",
                ".converted",
            }:
                try:
                    path.unlink()
                    print(
                        f"Removed partial file: {path}"
                    )
                except Exception as exc:
                    print(
                        "Could not remove partial "
                        f"file {path}: {exc}"
                    )
    except Exception as exc:
        print(
            f"Partial file cleanup failed: {exc}"
        )
# ---------------------------------------------------------
# Cancel Download
# ---------------------------------------------------------
def cancel_download():
    global progress_data
    if not download_lock.locked():
        return {
            "success": False,
            "message": (
                "No download is currently running."
            ),
        }
    cancel_event.set()
    progress_data["status"] = "cancelling"
    progress_data["speed"] = "Cancelling..."
    progress_data["eta"] = "00:00"
    print(
        "Download cancellation requested."
    )
    return {
        "success": True,
        "message": "Download cancellation requested.",
    }
# ---------------------------------------------------------
# Find Downloaded Media
# ---------------------------------------------------------
def find_latest_media_file(
    minimum_mtime=0,
):
    """
    Return the newest media file created/updated after
    minimum_mtime.
    This is important after yt-dlp merges separate video
    and audio streams. The original video-only stream may
    exist briefly, while the final merged file is created
    afterwards.
    """
    candidates = []
    for path in DOWNLOAD_FOLDER.glob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {
            ".mp4",
            ".mkv",
            ".webm",
            ".mov",
            ".avi",
            ".m4v",
            ".m4a",
            ".mp3",
        }:
            continue
        try:
            if path.stat().st_mtime < minimum_mtime:
                continue
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: p.stat().st_mtime,
    )
def media_has_video_and_audio(path):
    """
    Return True only when the file contains both a video
    stream and an audio stream.
    This prevents yt-dlp's video-only intermediate file from
    being mistaken for the final merged media file.
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    codecs = probe_media_codecs(path)
    has_video = bool(
        codecs.get("video_codec")
    )
    has_audio = bool(
        codecs.get("audio_codec")
    )
    return has_video and has_audio
def resolve_downloaded_media_path(
    info,
    ydl,
    download_started_at,
):
    """
    Resolve the ACTUAL final media file created by yt-dlp.
    IMPORTANT:
    prepare_filename() and requested_downloads can point to
    the video-only stream. For video downloads we must prefer
    a file that contains BOTH video and audio.
    We therefore:
      1. collect all possible yt-dlp paths,
      2. inspect them with ffprobe,
      3. prefer a newly-created file with both streams,
      4. only fall back to video-only when the source itself
         genuinely has no audio.
    """
    candidates = []
    def add_candidate(value):
        if not value:
            return
        try:
            path = Path(value)
        except Exception:
            return
        if not path.exists() or not path.is_file():
            return
        try:
            if path.stat().st_size <= 0:
                return
            # Ignore old files from previous downloads.
            if path.stat().st_mtime < download_started_at - 2:
                return
        except OSError:
            return
        if path not in candidates:
            candidates.append(path)
    # -----------------------------------------------------
    # 1. Direct final filepath exposed by yt-dlp
    # -----------------------------------------------------
    for key in (
        "filepath",
        "_filename",
    ):
        add_candidate(info.get(key))
    # -----------------------------------------------------
    # 2. requested_downloads paths
    # -----------------------------------------------------
    requested_downloads = (
        info.get("requested_downloads")
        or []
    )
    for item in requested_downloads:
        if not isinstance(item, dict):
            continue
        for key in (
            "filepath",
            "_filename",
        ):
            add_candidate(item.get(key))
    # -----------------------------------------------------
    # 3. All newly-created media files
    #
    # This is the important part: yt-dlp may create:
    #
    #   video.mp4       <- video only
    #   audio.webm      <- audio only
    #   video.mkv       <- final merged file
    #
    # We need video.mkv, not video.mp4.
    # -----------------------------------------------------
    for path in DOWNLOAD_FOLDER.glob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {
            ".mp4",
            ".mkv",
            ".webm",
            ".mov",
            ".avi",
            ".m4v",
            ".m4a",
            ".mp3",
        }:
            continue
        add_candidate(path)
    if not candidates:
        return None
    # -----------------------------------------------------
    # Prefer a file containing BOTH video and audio.
    # -----------------------------------------------------
    av_candidates = []
    for path in candidates:
        try:
            if media_has_video_and_audio(path):
                av_candidates.append(path)
        except Exception as exc:
            print(
                "Could not inspect candidate "
                f"{path}: {exc}"
            )
    if av_candidates:
        selected = max(
            av_candidates,
            key=lambda p: p.stat().st_mtime,
        )
        print(
            "Selected merged media file "
            f"(video + audio): {selected}"
        )
        return selected
    # -----------------------------------------------------
    # If no A/V file exists, inspect whether the source
    # itself genuinely has no audio.
    #
    # For normal video downloads this should NOT happen.
    # We deliberately do not silently continue with a
    # video-only file because that would create the exact
    # silent-video problem we are fixing.
    # -----------------------------------------------------
    video_only_candidates = []
    for path in candidates:
        try:
            codecs = probe_media_codecs(path)
            if codecs.get("video_codec"):
                video_only_candidates.append(path)
        except Exception:
            pass
    if video_only_candidates:
        selected = max(
            video_only_candidates,
            key=lambda p: p.stat().st_mtime,
        )
        raise RuntimeError(
            "yt-dlp downloaded a video stream, but the "
            "final video+audio file could not be found. "
            f"Video-only file detected: {selected.name}"
        )
    return None
# ---------------------------------------------------------
# FFprobe Helpers
# ---------------------------------------------------------
def probe_media_codecs(source_path):
    """
    Inspect the first video/audio streams using FFmpeg itself.
    FFprobe is intentionally not required anymore.
    Returns:
        {
            "video_codec": "...",
            "audio_codec": "...",
            "pixel_format": "...",
        }
    If inspection fails, return empty values so callers can
    safely fall back to compatibility conversion.
    """
    source_path = Path(source_path)
    ffmpeg_path = get_ffmpeg_path()
    empty_result = {
        "video_codec": "",
        "audio_codec": "",
        "pixel_format": "",
    }
    if not ffmpeg_path:
        return empty_result
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-i",
        str(source_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        output = (
            (result.stderr or "")
            + "\n"
            + (result.stdout or "")
        )
        video_codec = ""
        audio_codec = ""
        pixel_format = ""
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if "Video:" in line and not video_codec:
                video_part = line.split("Video:", 1)[1].strip()
                video_codec = video_part.split(",", 1)[0].strip().lower()
                for part in video_part.split(","):
                    value = part.strip().lower()
                    if value.startswith("yuv"):
                        pixel_format = value
                        break
                    if value.startswith("yuva"):
                        pixel_format = value
                        break
            if "Audio:" in line and not audio_codec:
                audio_part = line.split("Audio:", 1)[1].strip()
                audio_codec = audio_part.split(",", 1)[0].strip().lower()
        return {
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "pixel_format": pixel_format,
        }
    except Exception as exc:
        print(f"FFmpeg media inspection failed: {exc}")
        return empty_result
def is_mp4_compatible(source_path):
    """
    Return True when the media already uses the codecs
    and pixel format targeted by our compatible MP4 output.
    Target:
        Video: H.264
        Audio: AAC (or no audio)
        Pixel format: yuv420p
    """
    codecs = probe_media_codecs(
        source_path
    )
    video_codec = codecs.get(
        "video_codec",
        "",
    )
    audio_codec = codecs.get(
        "audio_codec",
        "",
    )
    pixel_format = codecs.get(
        "pixel_format",
        "",
    )
    compatible_video = (
        video_codec == "h264"
        and pixel_format == "yuv420p"
    )
    # Audio must actually exist and be AAC.
    # A video-only file is NOT considered compatible.
    compatible_audio = (
        audio_codec == "aac"
    )
    is_compatible = (
        compatible_video
        and compatible_audio
    )
    print(
        "MP4 compatibility check:"
        f" video={video_codec or 'unknown'},"
        f" audio={audio_codec or 'none'},"
        f" pixel_format={pixel_format or 'unknown'},"
        f" compatible={is_compatible}"
    )
    return is_compatible
def remux_to_mp4(
    source_path,
):
    """
    Change the container to MP4 without re-encoding.
    This is used when the downloaded media already has
    H.264 + AAC + yuv420p. It is much faster than a full
    H.264 re-encode.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(
            "Downloaded source file was not found."
        )
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError(
            "FFmpeg executable could not be found."
        )
    final_path = source_path.with_suffix(
        ".mp4"
    )
    temp_path = source_path.with_name(
        source_path.stem
        + ".remux.mp4"
    )
    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        "-nostdin",
        str(temp_path),
    ]
    print(
        "Source is already compatible."
    )
    print(
        "Remuxing to MP4 without re-encoding:"
    )
    print(
        " ".join(command)
    )
    process = None
    try:
        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 0
        progress_data["percentage"] = 0
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        progress_data["speed"] = "Finalizing MP4..."
        progress_data["eta"] = "Processing..."
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=WINDOWS_NO_WINDOW,
        )
        while True:
            if cancel_event.is_set():
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                raise yt_dlp.utils.DownloadCancelled(
                    "MP4 finalization cancelled."
                )
            line = process.stdout.readline()
            if process.poll() is not None:
                break
        if process.returncode != 0:
            raise RuntimeError(
                "FFmpeg could not create the "
                "final MP4 container."
            )
        if not temp_path.exists():
            raise FileNotFoundError(
                "FFmpeg finished but the final "
                "MP4 file was not created."
            )
        if temp_path.stat().st_size <= 0:
            raise RuntimeError(
                "The final MP4 file is empty."
            )
        if final_path.exists():
            try:
                final_path.unlink()
            except Exception:
                pass
        os.replace(
            temp_path,
            final_path,
        )
        if source_path.resolve() != final_path.resolve():
            try:
                source_path.unlink()
            except Exception as exc:
                print(
                    "Could not remove source file "
                    f"after remux: {exc}"
                )
        progress_data["processing_percentage"] = 100
        progress_data["percentage"] = 100
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        progress_data["speed"] = "Finalizing..."
        progress_data["eta"] = "00:00"
        print(
            "Compatible MP4 finalized:"
            f" {final_path}"
        )
        return final_path
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise
    finally:
        if process is not None:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
# ---------------------------------------------------------
# Convert MP4 to Universal Compatibility Format
# ---------------------------------------------------------
def convert_to_compatible_mp4(
    source_path,
    duration=0,
):
    """
    Convert the downloaded media into a highly compatible
    MP4 format:
        Video: H.264 / AVC
        Audio: AAC
        Pixel format: yuv420p
        Container: MP4
    This is intentionally used for MP4 downloads so that
    AV1/VP9/etc. sources become broadly playable.
    """
    if cancel_event.is_set():
        raise yt_dlp.utils.DownloadCancelled(
            "Conversion cancelled."
        )
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(
            "Downloaded source file was not found."
        )
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError(
            "FFmpeg executable could not be found."
        )
    final_path = source_path.with_suffix(
        ".mp4"
    )
    temp_path = source_path.with_name(
        source_path.stem
        + ".compatible.mp4"
    )
    # Avoid accidentally using the same file.
    if temp_path == source_path:
        temp_path = source_path.with_name(
            source_path.stem
            + ".converted.mp4"
        )
    # If source itself is already the desired
    # final path, conversion still happens through
    # a temporary file.
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(source_path),
        # -------------------------------------------------
        # Video
        # -------------------------------------------------
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        # -------------------------------------------------
        # Audio
        # -------------------------------------------------
        "-map",
        "0:a:0?",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        # -------------------------------------------------
        # MP4 compatibility
        # -------------------------------------------------
        "-movflags",
        "+faststart",
        # -------------------------------------------------
        # Progress output
        # -------------------------------------------------
        "-progress",
        "pipe:1",
        "-nostats",
        "-nostdin",
        str(temp_path),
    ]
    print(
        "Starting compatibility conversion:"
    )
    print(
        " ".join(command)
    )
    process = None
    try:
        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 0
        progress_data["percentage"] = 0
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=WINDOWS_NO_WINDOW,
        )
        out_time_ms = 0
        while True:
            # ---------------------------------------------
            # Cancellation
            # ---------------------------------------------
            if cancel_event.is_set():
                progress_data["status"] = (
                    "cancelling"
                )
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                raise yt_dlp.utils.DownloadCancelled(
                    "Conversion cancelled by user."
                )
            # ---------------------------------------------
            # Read FFmpeg progress
            # ---------------------------------------------
            line = process.stdout.readline()
            if line:
                line = line.strip()
                if line.startswith(
                    "out_time_ms="
                ):
                    try:
                        out_time_ms = int(
                            line.split(
                                "=",
                                1,
                            )[1]
                        )
                    except (
                        ValueError,
                        IndexError,
                    ):
                        pass
                    if duration > 0:
                        current_seconds = (
                            out_time_ms
                            / 1_000_000
                        )
                        processing_percentage = (
                            current_seconds
                            / duration
                        ) * 100
                        processing_percentage = min(
                            processing_percentage,
                            99.0,
                        )
                        progress_data[
                            "download_percentage"
                        ] = 100
                        progress_data[
                            "processing_percentage"
                        ] = round(
                            max(
                                0.0,
                                processing_percentage,
                            ),
                            1,
                        )
                        progress_data[
                            "percentage"
                        ] = progress_data[
                            "processing_percentage"
                        ]
                        progress_data[
                            "speed"
                        ] = "Converting..."
                        progress_data[
                            "eta"
                        ] = "Processing..."
                elif line.startswith(
                    "speed="
                ):
                    speed_value = line.split(
                        "=",
                        1,
                    )[1].strip()
                    if speed_value:
                        progress_data[
                            "speed"
                        ] = (
                            "Converting "
                            f"{speed_value}"
                        )
            # ---------------------------------------------
            # Process finished
            # ---------------------------------------------
            if process.poll() is not None:
                break
        return_code = process.returncode
        if return_code != 0:
            raise RuntimeError(
                "FFmpeg could not create a "
                "compatible MP4 file."
            )
        # -------------------------------------------------
        # Verify converted file
        # -------------------------------------------------
        if not temp_path.exists():
            raise FileNotFoundError(
                "FFmpeg finished but the converted "
                "MP4 file was not created."
            )
        if temp_path.stat().st_size <= 0:
            raise RuntimeError(
                "The converted MP4 file is empty."
            )
        # -------------------------------------------------
        # Replace original with compatible MP4
        # -------------------------------------------------
        if source_path.resolve() == final_path.resolve():
            os.replace(
                temp_path,
                final_path,
            )
        else:
            if final_path.exists():
                try:
                    final_path.unlink()
                except Exception:
                    pass
            os.replace(
                temp_path,
                final_path,
            )
            try:
                source_path.unlink()
            except Exception as exc:
                print(
                    "Could not remove original "
                    f"source file: {exc}"
                )
        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 100
        progress_data["percentage"] = 100
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        progress_data["speed"] = "Finalizing..."
        progress_data["eta"] = "00:00"
        print(
            "Compatible MP4 created:"
            f" {final_path}"
        )
        return final_path
    except Exception:
        # Remove failed conversion file.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise
    finally:
        if process is not None:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
# ---------------------------------------------------------
# Download
# ---------------------------------------------------------
def choose_video_format(info, height):
    """Choose a real video stream, preferring H.264."""
    formats = info.get("formats") or []
    candidates = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        vcodec = str(fmt.get("vcodec") or "none")
        if vcodec == "none":
            continue
        fmt_height = fmt.get("height")
        if not fmt_height:
            continue
        try:
            fmt_height = int(fmt_height)
        except (TypeError, ValueError):
            continue
        if fmt_height > height:
            continue
        filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        try:
            filesize = int(filesize or 0)
        except (TypeError, ValueError):
            filesize = 0
        fps = fmt.get("fps") or 0
        try:
            fps = float(fps or 0)
        except (TypeError, ValueError):
            fps = 0
        h264 = vcodec.lower().startswith("avc1") or vcodec.lower() == "h264"
        candidates.append({
            "id": str(fmt.get("format_id")),
            "height": fmt_height,
            "fps": fps,
            "filesize": filesize,
            "h264": h264,
            "ext": str(fmt.get("ext") or ""),
            "vcodec": vcodec,
        })
    if not candidates:
        raise RuntimeError(
            f"No video stream was found at or below {height}p."
        )
    h264_candidates = [item for item in candidates if item["h264"]]
    pool = h264_candidates or candidates
    selected = max(
        pool,
        key=lambda item: (
            item["height"],
            item["fps"],
            item["filesize"],
        ),
    )
    print(
        "Selected video stream:"
        f" format={selected['id']},"
        f" height={selected['height']}p,"
        f" codec={selected['vcodec']},"
        f" ext={selected['ext']}"
    )
    return selected["id"]
def choose_combined_format(info, height, language=""):
    """
    Choose a format that already contains BOTH video and audio.

    This is the universal fallback for sources such as Pinterest where
    yt-dlp may expose a combined A/V format but no separate audio-only
    stream.

    Preference:
        1. Requested language when available.
        2. H.264 video when available.
        3. Highest resolution at or below the requested quality.
        4. FPS / audio bitrate / file size.
    """
    formats = info.get("formats") or []
    candidates = []
    language = str(language or "").lower().strip()

    for fmt in formats:
        if not isinstance(fmt, dict):
            continue

        vcodec = str(fmt.get("vcodec") or "none")
        acodec = str(fmt.get("acodec") or "none")

        # We specifically need a real combined A/V stream.
        if vcodec == "none" or acodec == "none":
            continue

        fmt_height = fmt.get("height")
        try:
            fmt_height = int(fmt_height or 0)
        except (TypeError, ValueError):
            fmt_height = 0

        if fmt_height <= 0:
            continue

        fps = fmt.get("fps") or 0
        try:
            fps = float(fps or 0)
        except (TypeError, ValueError):
            fps = 0

        abr = fmt.get("abr") or 0
        try:
            abr = float(abr or 0)
        except (TypeError, ValueError):
            abr = 0

        filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        try:
            filesize = int(filesize or 0)
        except (TypeError, ValueError):
            filesize = 0

        fmt_language = str(fmt.get("language") or "").lower()
        language_match = bool(
            language
            and (
                fmt_language == language
                or fmt_language.startswith(language + "-")
                or fmt_language.startswith(language + "_")
            )
        )

        h264 = (
            vcodec.lower().startswith("avc1")
            or vcodec.lower() == "h264"
        )

        candidates.append({
            "id": str(fmt.get("format_id")),
            "height": fmt_height,
            "fps": fps,
            "abr": abr,
            "filesize": filesize,
            "language_match": language_match,
            "h264": h264,
            "vcodec": vcodec,
            "acodec": acodec,
            "ext": str(fmt.get("ext") or ""),
        })

    if not candidates:
        raise RuntimeError(
            "No combined video+audio stream was found for this video."
        )

    # Prefer the requested audio language if the source exposes it.
    if language:
        matching = [
            item for item in candidates
            if item["language_match"]
        ]
        if matching:
            candidates = matching
            print(
                f"Using requested combined audio language: {language}"
            )
        else:
            print(
                f"Requested audio language '{language}' was not available "
                "in combined formats; using the best available combined stream."
            )

    # First try formats at or below the requested quality.
    within_quality = [
        item for item in candidates
        if item["height"] <= height
    ]

    # If the source has no format at/below the requested quality,
    # choose the smallest available format above it rather than failing.
    pool = within_quality or candidates

    if within_quality:
        selected = max(
            pool,
            key=lambda item: (
                item["h264"],
                item["height"],
                item["fps"],
                item["abr"],
                item["filesize"],
            ),
        )
    else:
        selected = min(
            pool,
            key=lambda item: (
                item["height"],
                not item["h264"],
                -item["fps"],
                -item["abr"],
            ),
        )

    print(
        "Selected combined video+audio stream:"
        f" format={selected['id']},"
        f" height={selected['height']}p,"
        f" video_codec={selected['vcodec']},"
        f" audio_codec={selected['acodec']},"
        f" ext={selected['ext']}"
    )

    return selected["id"]


def get_combined_fallback_formats(info, primary_id, height, language=""):
    """Return up to two alternative combined A/V formats."""
    formats = info.get("formats") or []
    primary_id = str(primary_id)
    language = str(language or "").lower().strip()
    candidates = []

    for fmt in formats:
        if not isinstance(fmt, dict):
            continue

        fmt_id = str(fmt.get("format_id") or "")
        if not fmt_id or fmt_id == primary_id:
            continue

        vcodec = str(fmt.get("vcodec") or "none")
        acodec = str(fmt.get("acodec") or "none")
        if vcodec == "none" or acodec == "none":
            continue

        fmt_height = fmt.get("height")
        try:
            fmt_height = int(fmt_height or 0)
        except (TypeError, ValueError):
            continue

        if fmt_height <= 0:
            continue

        fps = fmt.get("fps") or 0
        try:
            fps = float(fps or 0)
        except (TypeError, ValueError):
            fps = 0

        abr = fmt.get("abr") or 0
        try:
            abr = float(abr or 0)
        except (TypeError, ValueError):
            abr = 0

        fmt_language = str(fmt.get("language") or "").lower()
        language_match = bool(
            language
            and (
                fmt_language == language
                or fmt_language.startswith(language + "-")
                or fmt_language.startswith(language + "_")
            )
        )

        h264 = (
            vcodec.lower().startswith("avc1")
            or vcodec.lower() == "h264"
        )

        candidates.append({
            "id": fmt_id,
            "height": fmt_height,
            "fps": fps,
            "abr": abr,
            "language_match": language_match,
            "h264": h264,
        })

    if not candidates:
        return []

    within_quality = [
        item for item in candidates
        if item["height"] <= height
    ]
    pool = within_quality or candidates

    pool.sort(
        key=lambda item: (
            item["language_match"],
            item["h264"],
            item["height"] if within_quality else -item["height"],
            item["fps"],
            item["abr"],
        ),
        reverse=True,
    )

    return [item["id"] for item in pool[:2]]


def choose_audio_format(info, language=""):
    """Choose the best audio-only stream, respecting language when possible."""
    formats = info.get("formats") or []
    candidates = []
    language = str(language or "").lower().strip()
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        acodec = str(fmt.get("acodec") or "none")
        vcodec = str(fmt.get("vcodec") or "none")
        if acodec == "none" or vcodec != "none":
            continue
        bitrate = fmt.get("abr") or fmt.get("tbr") or 0
        try:
            bitrate = float(bitrate or 0)
        except (TypeError, ValueError):
            bitrate = 0
        fmt_language = str(fmt.get("language") or "").lower()
        language_match = bool(
            language
            and (
                fmt_language == language
                or fmt_language.startswith(language + "-")
                or fmt_language.startswith(language + "_")
            )
        )
        candidates.append({
            "id": str(fmt.get("format_id")),
            "abr": bitrate,
            "language_match": language_match,
            "language": fmt_language,
            "acodec": acodec,
            "ext": str(fmt.get("ext") or ""),
        })
    if not candidates:
        raise RuntimeError("No audio stream was found for this video.")
    if language:
        matching = [item for item in candidates if item["language_match"]]
        if matching:
            candidates = matching
            print(
                f"Using requested audio language: {language}"
            )
        else:
            print(
                f"Requested audio language '{language}' was not available; "
                "using the best available audio."
            )
    selected = max(
        candidates,
        key=lambda item: item["abr"],
    )
    print(
        "Selected audio stream:"
        f" format={selected['id']},"
        f" language={selected['language'] or 'default'},"
        f" bitrate={selected['abr']}k,"
        f" codec={selected['acodec']},"
        f" ext={selected['ext']}"
    )
    return selected["id"]
def is_youtube_403_error(exc):
    message = str(exc).lower()
    return (
        "403" in message
        and (
            "forbidden" in message
            or "http error 403" in message
        )
    )
def get_video_fallback_formats(info, primary_id, height):
    formats = info.get("formats") or []
    candidates = []
    primary_id = str(primary_id)
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        fmt_id = str(fmt.get("format_id") or "")
        if not fmt_id or fmt_id == primary_id:
            continue
        vcodec = str(fmt.get("vcodec") or "none")
        if vcodec == "none":
            continue
        fmt_height = fmt.get("height")
        try:
            fmt_height = int(fmt_height or 0)
        except (TypeError, ValueError):
            continue
        if fmt_height <= 0 or fmt_height > height:
            continue
        acodec = str(fmt.get("acodec") or "none")
        fps = float(fmt.get("fps") or 0)
        h264 = vcodec.lower().startswith("avc1") or vcodec.lower() == "h264"
        candidates.append({
            "id": fmt_id,
            "height": fmt_height,
            "fps": fps,
            "h264": h264,
            "audio": acodec != "none",
        })
    candidates.sort(
        key=lambda item: (
            item["h264"],
            item["height"],
            item["fps"],
            not item["audio"],
        ),
        reverse=True,
    )
    return [item["id"] for item in candidates[:2]]
def get_audio_fallback_formats(info, primary_id, language=""):
    formats = info.get("formats") or []
    candidates = []
    primary_id = str(primary_id)
    language = str(language or "").lower().strip()
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        fmt_id = str(fmt.get("format_id") or "")
        if not fmt_id or fmt_id == primary_id:
            continue
        acodec = str(fmt.get("acodec") or "none")
        vcodec = str(fmt.get("vcodec") or "none")
        if acodec == "none" or vcodec != "none":
            continue
        fmt_language = str(fmt.get("language") or "").lower()
        language_match = bool(
            language
            and (
                fmt_language == language
                or fmt_language.startswith(language + "-")
                or fmt_language.startswith(language + "_")
            )
        )
        try:
            abr = float(fmt.get("abr") or fmt.get("tbr") or 0)
        except (TypeError, ValueError):
            abr = 0
        candidates.append({
            "id": fmt_id,
            "abr": abr,
            "language_match": language_match,
        })
    candidates.sort(
        key=lambda item: (
            item["language_match"],
            item["abr"],
        ),
        reverse=True,
    )
    return [item["id"] for item in candidates[:2]]
def download_format_with_retry(
    url,
    format_id,
    outtmpl,
    progress_callback,
    fallback_format_ids=None,
    stream_label="media",
    use_youtube_fallback=False,
):
    """
    Download a stream with a small 403 retry/fallback strategy.
    Primary format:
      - up to 2 fresh yt-dlp attempts
      - 2 second delay between attempts
    YouTube fallback formats:
      - tried only after repeated 403s
      - one fresh attempt per fallback format
    A successful video/audio stream is never downloaded again
    just because the other stream later needs a retry.
    """
    format_ids = [str(format_id)]
    for fallback_id in fallback_format_ids or []:
        fallback_id = str(fallback_id)
        if fallback_id and fallback_id not in format_ids:
            format_ids.append(fallback_id)
    last_error = None
    for format_index, current_format_id in enumerate(format_ids):
        max_attempts = 2 if format_index == 0 else 1
        for attempt in range(1, max_attempts + 1):
            try:
                print(
                    f"{stream_label} download: format={current_format_id}, "
                    f"attempt={attempt}/{max_attempts}"
                )
                return _download_exact_format(
                    url,
                    current_format_id,
                    outtmpl,
                    progress_callback,
                )
            except yt_dlp.utils.DownloadCancelled:
                raise
            except Exception as exc:
                last_error = exc
                is_403 = is_youtube_403_error(exc)
                if not use_youtube_fallback or not is_403:
                    raise
                if attempt < max_attempts:
                    print(
                        f"{stream_label}: YouTube returned 403. "
                        "Refreshing the stream and retrying in 2 seconds..."
                    )
                    time.sleep(2)
                    continue
                if format_index < len(format_ids) - 1:
                    print(
                        f"{stream_label}: primary format was rejected. "
                        f"Trying fallback format {format_ids[format_index + 1]}..."
                    )
                    break
    if last_error:
        raise last_error
    raise RuntimeError(
        f"Unable to download {stream_label}."
    )
def _download_exact_format(url, format_id, outtmpl, progress_callback):
    """Download exactly one yt-dlp format without allowing a second stream."""
    opts = {
        "format": str(format_id),
        "outtmpl": str(outtmpl),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "ffmpeg_location": get_ffmpeg_directory(),
        "progress_hooks": [progress_callback],
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError(
                f"yt-dlp returned no information for format {format_id}."
            )
        path = Path(ydl.prepare_filename(info))
        if not path.exists():
            # Some post-processing or extension changes can alter the path.
            candidates = list(path.parent.glob(path.stem + ".*"))
            candidates = [item for item in candidates if item.is_file()]
            if candidates:
                path = max(candidates, key=lambda item: item.stat().st_mtime)
        if not path.exists() or path.stat().st_size <= 0:
            raise FileNotFoundError(
                f"Downloaded format {format_id} was not found."
            )
        return path
def download_combined_format_to_mp4(
    url,
    format_id,
    outtmpl,
    final_path,
    duration=0,
    fallback_format_ids=None,
    use_youtube_fallback=False,
):
    """
    Download one combined video+audio stream and convert it to a
    broadly compatible MP4.

    This path is used when a source does not expose a separate
    audio-only stream. FFmpeg converts the result to:
        Video: H.264 / AVC
        Audio: AAC 192k
        Pixel format: yuv420p
        Container: MP4
    """
    source_path = download_format_with_retry(
        url,
        format_id,
        outtmpl,
        progress_hook,
        fallback_format_ids=fallback_format_ids,
        stream_label="Combined video + audio",
        use_youtube_fallback=use_youtube_fallback,
    )

    if cancel_event.is_set():
        raise yt_dlp.utils.DownloadCancelled(
            "Download cancelled by user."
        )

    # Convert through the existing compatibility pipeline.
    converted_path = convert_to_compatible_mp4(
        source_path,
        duration=duration,
    )

    final_path = Path(final_path)
    converted_path = Path(converted_path)

    if converted_path.resolve() != final_path.resolve():
        if final_path.exists():
            try:
                final_path.unlink()
            except Exception:
                pass
        os.replace(converted_path, final_path)

    if not media_has_video_and_audio(final_path):
        raise RuntimeError(
            "The final MP4 was created, but it does not contain "
            "both video and audio streams."
        )

    return final_path


def merge_video_audio_to_mp4(video_path, audio_path, final_path, duration=0):
    """Deterministically merge separately downloaded video and audio."""
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg executable could not be found.")
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    final_path = Path(final_path)
    temp_path = final_path.with_name(
        final_path.stem + ".merging.mp4"
    )
    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass
    video_codecs = probe_media_codecs(video_path)
    copy_video = (
        video_codecs.get("video_codec") == "h264"
        and video_codecs.get("pixel_format") == "yuv420p"
    )
    command = [
        str(ffmpeg_path),
        "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]
    if copy_video:
        command.extend([
            "-c:v", "copy",
        ])
        print("Video is already H.264/yuv420p; copying video without re-encoding.")
    else:
        command.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
        ])
        print("Video needs compatibility conversion to H.264.")
    command.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        "-nostdin",
        str(temp_path),
    ])
    print("Merging video + audio with FFmpeg:")
    print(" ".join(command))
    progress_data["download_percentage"] = 100
    progress_data["processing_percentage"] = 0
    progress_data["percentage"] = 0
    progress_data["status"] = "processing"
    progress_data["phase"] = "processing"
    progress_data["speed"] = "Merging video + audio..."
    progress_data["eta"] = "Processing..."
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=WINDOWS_NO_WINDOW,
        )
        while True:
            if cancel_event.is_set():
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                raise yt_dlp.utils.DownloadCancelled(
                    "Video/audio merge cancelled by user."
                )
            line = process.stdout.readline()
            if line:
                line = line.strip()
                if line.startswith("out_time_ms=") and duration > 0:
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000
                        pct = min(99.0, max(0.0, (seconds / duration) * 100))
                        progress_data["processing_percentage"] = round(pct, 1)
                        progress_data["percentage"] = round(pct, 1)
                    except (ValueError, IndexError, ZeroDivisionError):
                        pass
                elif line.startswith("speed="):
                    speed = line.split("=", 1)[1].strip()
                    if speed:
                        progress_data["speed"] = f"Merging {speed}"
            if process.poll() is not None:
                break
        if process.returncode != 0:
            raise RuntimeError(
                "FFmpeg failed while merging the video and audio streams."
            )
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            raise RuntimeError(
                "FFmpeg finished, but the merged MP4 file was not created."
            )
        if final_path.exists():
            try:
                final_path.unlink()
            except Exception:
                pass
        os.replace(temp_path, final_path)
        if not media_has_video_and_audio(final_path):
            raise RuntimeError(
                "The merged MP4 was created, but it does not contain both video and audio streams."
            )
        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 100
        progress_data["percentage"] = 100
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        progress_data["speed"] = "Processing complete"
        progress_data["eta"] = "00:00"
        print(f"Final video + audio MP4: {final_path}")
        return final_path
    finally:
        if process is not None:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
def build_mp4_format_selector(height, language=""):
    """
    Build a universal yt-dlp format selector for MP4 downloads.

    Important:
        We intentionally let yt-dlp choose the actual source formats.
        Different extractors expose video/audio metadata differently,
        so manually inspecting vcodec/acodec is not reliable enough for
        a universal downloader.

    Order:
        1. Best video stream at/below requested quality + best audio.
        2. Best combined stream at/below requested quality.
        3. Best available combined stream as a final source fallback.

    bestvideo* is used instead of bestvideo so a source-provided format
    that already contains audio is allowed to pass through unchanged.
    """
    height = int(height or 0)

    if height <= 0:
        if language:
            return (
                "bestvideo*+bestaudio[language^="
                f"{language}]/bestvideo*+bestaudio/best"
            )
        return "bestvideo*+bestaudio/best"

    if language:
        return (
            f"bestvideo*[height<={height}]"
            f"+bestaudio[language^={language}]"
            f"/bestvideo*[height<={height}]+bestaudio"
            f"/best[height<={height}]"
            "/best"
        )

    return (
        f"bestvideo*[height<={height}]+bestaudio"
        f"/best[height<={height}]"
        "/best"
    )


def download_native_mp4(
    url,
    height,
    language="",
    duration=0,
    site="other",
):
    """
    Download MP4 using yt-dlp's native format selection.

    This replaces the old manual video/audio/combined format detection.
    yt-dlp already knows how each extractor represents its formats and
    how to merge separate streams with FFmpeg.

    The downloaded result is then passed through our compatibility
    conversion so the final file is always H.264 + AAC + yuv420p MP4.
    """
    global progress_data

    selector = build_mp4_format_selector(
        height,
        language,
    )

    print("Universal MP4 format selector:")
    print(selector)

    download_started_at = time.time()
    output_template = DOWNLOAD_FOLDER / "%(title)s.%(ext)s"

    ydl_opts = {
        "format": selector,
        "outtmpl": str(output_template),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "ffmpeg_location": get_ffmpeg_directory(),
        "progress_hooks": [progress_hook],
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 5,
        "socket_timeout": 30,
        "merge_output_format": "mp4",
        # Let yt-dlp handle source-provided formats naturally.
        "check_formats": "selected",
    }

    # Keep the existing YouTube language preference behavior.
    # For non-YouTube platforms language is normally empty.
    if language:
        ydl_opts["format_sort"] = [
            f"lang:{language}",
            "quality",
            "res",
            "fps",
        ]

    progress_data["status"] = "downloading"
    progress_data["phase"] = "downloading"
    progress_data["download_percentage"] = 0
    progress_data["processing_percentage"] = 0
    progress_data["percentage"] = 0
    progress_data["speed"] = "Downloading..."
    progress_data["eta"] = "Calculating..."

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

        if cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled(
                "Download cancelled by user."
            )

        if not info:
            raise RuntimeError(
                "Could not retrieve video information."
            )

        final_path = resolve_downloaded_media_path(
            info,
            ydl,
            download_started_at,
        )

    if final_path is None:
        raise FileNotFoundError(
            "yt-dlp finished the download, but the final media file "
            "could not be found."
        )

    final_path = Path(final_path)

    if not final_path.exists() or final_path.stat().st_size <= 0:
        raise RuntimeError(
            "The downloaded media file is empty or missing."
        )

    # The source may already be H.264/AAC MP4, or it may be WebM/MKV/
    # another source container. Convert through the same compatibility
    # pipeline in every case so the application always returns MP4.
    progress_data["download_percentage"] = 100
    progress_data["processing_percentage"] = 0
    progress_data["percentage"] = 0
    progress_data["status"] = "processing"
    progress_data["phase"] = "processing"
    progress_data["speed"] = "Preparing MP4..."
    progress_data["eta"] = "Processing..."

    converted_path = convert_to_compatible_mp4(
        final_path,
        duration=duration,
    )

    converted_path = Path(converted_path)

    if not media_has_video_and_audio(converted_path):
        raise RuntimeError(
            "The downloaded media was created, but the final file does "
            "not contain both video and audio streams."
        )

    return converted_path


def run_download(
    url,
    format_ext,
    quality,
    language="",
):
    global progress_data
    reset_progress()

    if not is_ffmpeg_installed():
        progress_data["status"] = "error"
        progress_data["error"] = (
            "FFmpeg not found. Please install FFmpeg and restart VS Code."
        )
        return

    url = str(url).strip()
    format_ext = str(format_ext).lower().strip()
    quality = str(quality).strip()
    language = str(language or "").lower().strip()

    if format_ext not in {"mp4", "mkv", "mp3"}:
        format_ext = "mp4"

    height = parse_quality(quality)
    DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

    original_url = url
    url = resolve_short_url(url)

    if url != original_url:
        print(
            f"Resolved URL: {original_url} -> {url}"
        )

    site = get_site(url)
    print(f"Detected platform: {site}")

    try:
        download_started_at = time.time()

        # =====================================================
        # MP4: universal yt-dlp native format selection
        # =====================================================
        if format_ext == "mp4":
            info_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
                "ffmpeg_location": get_ffmpeg_directory(),
                "socket_timeout": 30,
                "retries": 5,
                "extractor_retries": 5,
                "fragment_retries": 5,
            }

            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )

            if not info:
                raise RuntimeError(
                    "Could not retrieve video information."
                )

            duration = float(
                info.get("duration") or 0
            )

            final_path = download_native_mp4(
                url,
                height,
                language=language,
                duration=duration,
                site=site,
            )

            progress_data["filename"] = final_path.name
            progress_data["download_percentage"] = 100
            progress_data["processing_percentage"] = 100
            progress_data["percentage"] = 100
            progress_data["speed"] = "Completed"
            progress_data["eta"] = "00:00"
            progress_data["status"] = "completed"
            progress_data["phase"] = "completed"
            progress_data["error"] = None

            print(
                f"Download completed successfully: {final_path}"
            )
            return

        # =====================================================
        # MP3 / MKV: keep yt-dlp's normal workflow
        # =====================================================
        if language:
            audio_selector = (
                f"bestaudio[language^={language}]"
                "/bestaudio"
            )
        else:
            audio_selector = "bestaudio"

        ydl_opts = {
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "outtmpl": str(
                DOWNLOAD_FOLDER / "%(title)s.%(ext)s"
            ),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "ffmpeg_location": get_ffmpeg_directory(),
        }

        if format_ext == "mp3":
            ydl_opts.update({
                "format": audio_selector,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            video_selector = (
                f"bestvideo[height<={height}]"
            )
            ydl_opts.update({
                "format": (
                    f"{video_selector}+{audio_selector}/"
                    f"best[height<={height}]/best"
                ),
                "merge_output_format": "mkv",
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                url,
                download=True,
            )

        if cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled(
                "Download cancelled by user."
            )

        if not info:
            raise RuntimeError(
                "Could not retrieve video information."
            )

        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 0
        progress_data["percentage"] = 0
        progress_data["status"] = "processing"
        progress_data["phase"] = "processing"
        progress_data["speed"] = (
            "Finalizing audio..."
            if format_ext == "mp3"
            else "Finalizing video..."
        )
        progress_data["eta"] = "Processing..."

        if format_ext == "mp3":
            candidates = list(
                DOWNLOAD_FOLDER.glob("*.mp3")
            )
            if not candidates:
                raise FileNotFoundError(
                    "MP3 download finished, but the final file could not be found."
                )
            final_path = max(
                candidates,
                key=lambda p: p.stat().st_mtime,
            )
        else:
            final_path = resolve_downloaded_media_path(
                info,
                ydl,
                download_started_at,
            )
            if final_path is None:
                raise FileNotFoundError(
                    "Download finished, but the final merged MKV file could not be found."
                )

        if not final_path.exists() or final_path.stat().st_size <= 0:
            raise RuntimeError(
                "The final downloaded file is empty or missing."
            )

        progress_data["filename"] = final_path.name
        progress_data["download_percentage"] = 100
        progress_data["processing_percentage"] = 100
        progress_data["percentage"] = 100
        progress_data["speed"] = "Completed"
        progress_data["eta"] = "00:00"
        progress_data["status"] = "completed"
        progress_data["phase"] = "completed"
        progress_data["error"] = None

        print(
            f"Download completed successfully: {final_path}"
        )

    except yt_dlp.utils.DownloadCancelled:
        cleanup_partial_files()
        progress_data["status"] = "cancelled"
        progress_data["phase"] = "cancelled"
        progress_data["percentage"] = 0
        progress_data["download_percentage"] = 0
        progress_data["processing_percentage"] = 0
        progress_data["speed"] = "Cancelled"
        progress_data["eta"] = "00:00"
        progress_data["error"] = None
        print("Download cancelled by user.")

    except Exception as exc:
        if cancel_event.is_set():
            cleanup_partial_files()
            progress_data["status"] = "cancelled"
            progress_data["phase"] = "cancelled"
            progress_data["percentage"] = 0
            progress_data["download_percentage"] = 0
            progress_data["processing_percentage"] = 0
            progress_data["speed"] = "Cancelled"
            progress_data["eta"] = "00:00"
            progress_data["error"] = None
            print("Download cancelled.")
            return

        progress_data["status"] = "error"
        progress_data["phase"] = "error"

        if site == "youtube" and is_youtube_403_error(exc):
            progress_data["error"] = (
                "YouTube rejected this download request. "
                "Please try again in a few seconds."
            )
        else:
            progress_data["error"] = str(exc)

        print(f"Download error: {exc}")


# ---------------------------------------------------------
# Start Download Thread
# ---------------------------------------------------------
def start_download_thread(
    url,
    format_ext,
    quality,
    language="",
):
    global progress_data
    # -----------------------------------------------------
    # Prevent Multiple Downloads
    # -----------------------------------------------------
    if download_lock.locked():
        progress_data["status"] = (
            "error"
        )
        progress_data["error"] = (
            "A download is already in progress. "
            "Please wait until it finishes."
        )
        return False
    # -----------------------------------------------------
    # Worker
    # -----------------------------------------------------
    def worker():
        with download_lock:
            run_download(
                url,
                format_ext,
                quality,
                language,
            )
    # -----------------------------------------------------
    # Start Download
    # -----------------------------------------------------
    thread = threading.Thread(
        target=worker,
        daemon=True,
    )
    thread.start()
    return True
# ---------------------------------------------------------
# Get Progress
# ---------------------------------------------------------
def get_progress():
    return progress_data.copy()
import re

def sanitize_filename(filename):
    """
    Simple filename sanitizer.
    yt-dlp usually handles this, but good to have.
    """
    return re.sub(r'(?u)[^-\w.]', '', filename)

def format_seconds(seconds):
    """
    Converts seconds to HH:MM:SS
    """
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

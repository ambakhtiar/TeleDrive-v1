"""Pure, stateless helpers used by the uploader service (no self/state)."""
import os
from datetime import datetime


def original_timestamp(file_path, stats):
    """Best guess at when the file was *created*, not last touched.

    For images: reads EXIF DateTimeOriginal / DateTimeDigitized / DateTime
    (any format PIL can open, including HEIC via pillow-heif if available).
    For videos: reads QuickTime ©day metadata via mutagen if available.
    Fallback: earliest of filesystem birth/ctime/mtime.
    """
    ext = os.path.splitext(file_path)[1].lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
                  ".heic", ".heif", ".gif", ".ico"}

    if ext in image_exts:
        # Try PIL EXIF (handles jpg, png, webp, tiff, bmp, gif, ico)
        try:
            from PIL import Image, ExifTags
            with Image.open(file_path) as img:
                exif = img.getexif()
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id)
                    if tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S").timestamp()
        except Exception:
            pass
        # Try pillow-heif for HEIC/HEIF (if installed)
        if ext in (".heic", ".heif"):
            try:
                from pillow_heif import open_heif
                import piexif
                heif_file = open_heif(file_path)
                exif_bytes = heif_file.info.get("exif")
                if exif_bytes:
                    exif_dict = piexif.load(exif_bytes)
                    for tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                        tag_id = {"DateTimeOriginal": 36867, "DateTimeDigitized": 36868, "DateTime": 306}[tag]
                        val = exif_dict.get("ExifIFD", {}).get(tag_id)
                        if val:
                            raw = val.decode() if isinstance(val, bytes) else val
                            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").timestamp()
            except Exception:
                pass

    # Try video metadata via mutagen (mp4, mov, m4v, etc.)
    if ext in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
               ".ts", ".flv", ".wmv", ".mpeg", ".mpg", ".3gp", ".m2ts"):
        try:
            import mutagen
            from mutagen.mp4 import MP4
            from mutagen.quicktime import QuickTime
            for loader in (MP4, QuickTime):
                try:
                    video = loader(file_path)
                    val = video.get("\xa9day", [None])[0]
                    if val:
                        dt = datetime.strptime(str(val)[:10], "%Y-%m-%d")
                        return dt.timestamp()
                except Exception:
                    continue
        except Exception:
            pass

    # Filesystem fallback: earliest timestamp wins
    birth = getattr(stats, "st_birthtime", None)
    candidates = [t for t in (birth, stats.st_ctime, stats.st_mtime) if t]
    return min(candidates) if candidates else stats.st_mtime


def get_device_info(file_path):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp"]:
            from PIL import Image, ExifTags

            with Image.open(file_path) as img:
                exif = img.getexif()
                if not exif:
                    return None
                make, model = "", ""
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == "Make":
                        make = str(value).strip()
                    elif tag == "Model":
                        model = str(value).strip()
                if make or model:
                    if make and make.lower() in model.lower():
                        return model
                    return f"{make} {model}".strip()
        return None
    except Exception:
        return None


def format_metadata(file_name, file_path, stats, rel_path=None, original_mtime=None):
    size_mb = round(stats.st_size / (1024 * 1024), 2)
    ts = original_mtime if original_mtime else original_timestamp(file_path, stats)
    created = datetime.fromtimestamp(ts)
    dt_created = created.strftime("%d %b %Y, %I:%M %p")
    ext = os.path.splitext(file_name)[1]
    tags = [f"#{ext[1:].lower()}"] if ext else ["#unknown"]
    if rel_path:
        parts = [p.replace(" ", "_") for p in rel_path.replace("\\", "/").split("/") if p and p != "."]
        if parts:
            tags.append("#" + "_".join(parts))
    caption = f"📄 **{file_name}**\n\n💾 **Size:** {size_mb} MB\n📅 **Created:** {dt_created}"
    device = get_device_info(file_path)
    if device:
        caption += f"\n📱 **Device:** {device}"
    caption += f"\n\n🏷️ {' '.join(tags)}"
    return caption


def fmt_duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"

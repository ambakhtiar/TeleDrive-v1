"""Pure, stateless helpers used by the uploader service (no self/state)."""
import os
from datetime import datetime


def original_timestamp(file_path, stats):
    """Best guess at when the file was *created*, not last touched.

    Prefers EXIF DateTimeOriginal for photos, then filesystem creation time
    (st_ctime on Windows / st_birthtime on macOS), then modification time.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff"):
        try:
            from PIL import Image, ExifTags
            with Image.open(file_path) as img:
                exif = img.getexif()
                for tag_id, value in exif.items():
                    if ExifTags.TAGS.get(tag_id) in ("DateTimeOriginal", "DateTime"):
                        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S").timestamp()
        except Exception:
            pass
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


def format_metadata(file_name, file_path, stats):
    size_mb = round(stats.st_size / (1024 * 1024), 2)
    created = datetime.fromtimestamp(original_timestamp(file_path, stats))
    dt_created = created.strftime("%d %b %Y, %I:%M %p")
    ext = os.path.splitext(file_name)[1]
    hashtag = f"#{ext[1:].lower()}" if ext else "#unknown"
    caption = f"📄 **{file_name}**\n\n💾 **Size:** {size_mb} MB\n📅 **Created:** {dt_created}"
    device = get_device_info(file_path)
    if device:
        caption += f"\n📱 **Device:** {device}"
    caption += f"\n\n🏷️ {hashtag}"
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

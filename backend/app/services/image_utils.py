import struct
from pathlib import Path


SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def image_extension(mime_type: str, filename: str | None = None) -> str:
    return MIME_EXTENSIONS.get(mime_type, Path(filename or "").suffix.lower() or ".bin")


def read_image_dimensions(image_bytes: bytes, mime_type: str) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(image_bytes) >= 24:
        return struct.unpack(">II", image_bytes[16:24])
    if mime_type == "image/gif" and len(image_bytes) >= 10:
        return struct.unpack("<HH", image_bytes[6:10])
    if mime_type == "image/jpeg":
        i = 2
        while i + 9 < len(image_bytes):
            if image_bytes[i] != 0xFF:
                i += 1
                continue
            marker = image_bytes[i + 1]
            i += 2
            if marker in (0xD8, 0xD9):
                continue
            if i + 2 > len(image_bytes):
                break
            segment_len = int.from_bytes(image_bytes[i:i + 2], "big")
            if segment_len < 2:
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3,
                0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB,
                0xCD, 0xCE, 0xCF,
            } and i + 7 < len(image_bytes):
                height = int.from_bytes(image_bytes[i + 3:i + 5], "big")
                width = int.from_bytes(image_bytes[i + 5:i + 7], "big")
                return width, height
            i += segment_len
    if mime_type == "image/webp" and len(image_bytes) >= 30:
        chunk = image_bytes[12:16]
        if chunk == b"VP8X":
            width = int.from_bytes(image_bytes[24:27], "little") + 1
            height = int.from_bytes(image_bytes[27:30], "little") + 1
            return width, height
        if chunk == b"VP8L" and len(image_bytes) >= 25:
            bits = int.from_bytes(image_bytes[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
        if chunk == b"VP8 " and image_bytes[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(image_bytes[26:28], "little") & 0x3FFF
            height = int.from_bytes(image_bytes[28:30], "little") & 0x3FFF
            return width, height
    return None, None


def validate_image(image_bytes: bytes) -> tuple[str, int | None, int | None]:
    mime_type = detect_image_mime(image_bytes)
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError("Unsupported or invalid image file")

    width, height = read_image_dimensions(image_bytes, mime_type)
    if width is None or height is None:
        raise ValueError("Unable to read image dimensions")
    if width < 10 or height < 10:
        raise ValueError("Image must be at least 10x10 pixels")
    return mime_type, width, height

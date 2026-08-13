from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, UnidentifiedImageError


SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MIN_IMAGE_DIMENSION = 10
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_FRAMES = 120
MAX_DECODED_FRAME_PIXELS = 80_000_000


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
    """Read dimensions cheaply for diagnostics; never use this as content validation."""
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


def _has_complete_image_container(image_bytes: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return image_bytes.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82")
    if mime_type == "image/jpeg":
        return image_bytes.endswith(b"\xff\xd9")
    if mime_type == "image/gif":
        return image_bytes.endswith(b";")
    if mime_type == "image/webp":
        return len(image_bytes) >= 12 and int.from_bytes(image_bytes[4:8], "little") + 8 == len(image_bytes)
    return False


def validate_image(image_bytes: bytes) -> tuple[str, int, int]:
    """Fully verify and decode supported images before they may be stored or parsed."""
    mime_type = detect_image_mime(image_bytes)
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES or not _has_complete_image_container(
        image_bytes, mime_type
    ):
        raise ValueError("Unsupported or invalid image file")

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            actual_mime = Image.MIME.get(image.format or "")
            if actual_mime != mime_type:
                raise ValueError("Unsupported or invalid image file")
            width, height = image.size
            if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                raise ValueError("Image must be at least 10x10 pixels")
            if (
                width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ValueError("Image dimensions are too large")
            image.verify()

        # verify() validates structure but does not decode pixels, so reopen and load
        # every frame while enforcing a cumulative decompression budget.
        with Image.open(io.BytesIO(image_bytes)) as image:
            frame_count = int(getattr(image, "n_frames", 1) or 1)
            if frame_count > MAX_IMAGE_FRAMES:
                raise ValueError("Image has too many frames")
            if width * height * frame_count > MAX_DECODED_FRAME_PIXELS:
                raise ValueError("Animated image is too large")
            for frame_index in range(frame_count):
                image.seek(frame_index)
                image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Unsupported or invalid image file") from exc
    return mime_type, width, height


def _iter_iso_boxes(data: bytes, start: int, end: int):
    offset = start
    while offset + 8 <= end:
        box_size = int.from_bytes(data[offset:offset + 4], "big")
        box_type = data[offset + 4:offset + 8]
        header_size = 8
        if box_size == 1:
            if offset + 16 > end:
                raise ValueError("Unsupported or invalid video file")
            box_size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header_size = 16
        elif box_size == 0:
            box_size = end - offset
        if box_size < header_size or offset + box_size > end:
            raise ValueError("Unsupported or invalid video file")
        yield box_type, offset + header_size, offset + box_size
        offset += box_size
    if offset != end:
        raise ValueError("Unsupported or invalid video file")


def detect_video_type(video_bytes: bytes) -> tuple[str, str]:
    """Return MIME/extension only after a bounded structural container scan."""
    if not video_bytes:
        raise ValueError("Video file cannot be empty")
    if len(video_bytes) >= 24 and video_bytes[4:8] == b"ftyp":
        has_ftyp = False
        has_nonempty_mdat = False
        valid_moov = False
        for box_type, payload_start, payload_end in _iter_iso_boxes(
            video_bytes, 0, len(video_bytes)
        ):
            if box_type == b"ftyp":
                has_ftyp = True
            elif box_type == b"mdat" and payload_end > payload_start:
                has_nonempty_mdat = True
            elif box_type == b"moov":
                for child_type, child_start, child_end in _iter_iso_boxes(
                    video_bytes, payload_start, payload_end
                ):
                    if child_type != b"trak":
                        continue
                    if any(
                        grandchild_type == b"mdia"
                        for grandchild_type, _, _ in _iter_iso_boxes(
                            video_bytes, child_start, child_end
                        )
                    ):
                        valid_moov = True
        if (
            not has_ftyp
            or not has_nonempty_mdat
            or not valid_moov
        ):
            raise ValueError("Unsupported or invalid video file")
        major_brand = video_bytes[8:12]
        if major_brand == b"qt  ":
            return "video/quicktime", ".mov"
        return "video/mp4", ".mp4"
    if len(video_bytes) >= 24 and video_bytes.startswith(b"\x1aE\xdf\xa3"):
        segment = video_bytes.find(b"\x18S\x80g", 4)
        tracks = video_bytes.find(b"\x16T\xae\x6b", segment + 4)
        cluster = video_bytes.find(b"\x1fC\xb6u", tracks + 4)
        if segment >= 4 and tracks > segment and cluster > tracks and cluster + 4 < len(video_bytes):
            return "video/webm", ".webm"
    if (
        len(video_bytes) >= 16
        and video_bytes.startswith(b"RIFF")
        and video_bytes[8:12] == b"AVI "
    ):
        declared_size = int.from_bytes(video_bytes[4:8], "little") + 8
        list_position = video_bytes.find(b"LIST", 12)
        movi_position = video_bytes.find(b"movi", list_position + 4)
        if (
            declared_size != len(video_bytes)
            or list_position < 12
            or movi_position <= list_position
            or movi_position + 4 >= len(video_bytes)
        ):
            raise ValueError("Unsupported or invalid video file")
        return "video/x-msvideo", ".avi"
    raise ValueError("Unsupported or invalid video file")

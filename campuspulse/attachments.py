"""Validate a complete attachment batch before returning document text or image data."""
import base64
from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, UnidentifiedImageError

from campuspulse.documents import extract_document

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 3
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 10_000
IMAGE_FORMATS = {".png": ("PNG", "image/png"), ".jpg": ("JPEG", "image/jpeg"),
                 ".jpeg": ("JPEG", "image/jpeg"), ".webp": ("WEBP", "image/webp")}
IMAGE_MIME_TYPES = dict(IMAGE_FORMATS.values())
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def _prepare_image(name: str, data: bytes) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                # Browser captures may use a PNG filename for JPEG bytes. Trust the
                # decoded allowed format for MIME, while preserving the user's name.
                mime_type = IMAGE_MIME_TYPES.get(image.format)
                if mime_type is None:
                    raise ValueError("Формат изображения не поддерживается. Сохрани его как PNG, JPG или WEBP.")
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS or max(width, height) > MAX_IMAGE_SIDE:
                    raise ValueError("Изображение слишком большое: максимум 20 мегапикселей и 10000 пикселей по стороне.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Анимация не поддерживается. Прикрепи один кадр как обычное фото.")
                image.verify()
            # Some formats only expose truncated pixel data when decoded.
            with Image.open(BytesIO(data)) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Изображение слишком большое. Уменьши его до 20 мегапикселей.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Изображение повреждено или не распознано. Пересохрани его как PNG, JPG или WEBP.") from exc
    return {"name": Path(name).name, "mime_type": mime_type,
            "data": base64.b64encode(data).decode("ascii")}


def prepare_attachments(files: list[tuple[str, bytes]]) -> dict:
    """Return an atomic batch; no network calls, file writes, or partial results."""
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("Прикрепи не более 5 файлов за один раз.")
    total_bytes, image_count = 0, 0
    for name, data in files:
        if not isinstance(name, str) or not name or not isinstance(data, bytes):
            raise ValueError("Некорректное вложение: нужны имя файла и его байты.")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{name}: файл превышает лимит 5 МБ.")
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError(f"{name}: общий размер вложений превышает 10 МБ.")
        suffix = Path(name).suffix.lower()
        if suffix in IMAGE_FORMATS:
            image_count += 1
            if image_count > MAX_IMAGES:
                raise ValueError(f"{name}: можно прикрепить не более 3 фото за один раз.")
        elif suffix not in DOCUMENT_SUFFIXES:
            raise ValueError(f"{name}: поддерживаются PDF, DOCX, TXT, MD, PNG, JPG и WEBP.")

    result = {"documents": [], "images": []}
    for name, data in files:
        suffix = Path(name).suffix.lower()
        try:
            if suffix in IMAGE_FORMATS:
                result["images"].append(_prepare_image(name, data))
            else:
                result["documents"].append(extract_document(name, data))
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc
    return result


def merge_attachments(existing: dict, incoming: dict) -> dict:
    """Replace by filename across both kinds, then validate the complete new set."""
    by_name = {}
    for batch in (existing, incoming):
        for kind in ("documents", "images"):
            for item in batch.get(kind, []):
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("У каждого вложения должно быть имя файла.")
                by_name[name] = (kind, dict(item))
    if len(by_name) > MAX_FILES:
        raise ValueError("В сессии можно хранить не более 5 вложений. Удали ненужные файлы перед добавлением.")
    if sum(kind == "images" for kind, _ in by_name.values()) > MAX_IMAGES:
        raise ValueError("В сессии можно хранить не более 3 фото. Удали ненужные фото перед добавлением.")
    result = {"documents": [], "images": []}
    total_bytes = 0
    for name, (kind, item) in by_name.items():
        try:
            if kind == "documents":
                size = len(item["text"].encode("utf-8"))
            else:
                if len(item["data"]) > (MAX_TOTAL_BYTES + 2) // 3 * 4:
                    raise ValueError("Фото превышает общий лимит 10 МБ.")
                size = len(base64.b64decode(item["data"], validate=True))
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"{name}: некорректное содержимое вложения. Прикрепи файл заново.") from exc
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError(f"{name}: общий размер материалов и фото превышает 10 МБ.")
        result[kind].append(item)
    return result

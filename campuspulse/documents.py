from io import BytesIO
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_document(name: str, data: bytes) -> dict:
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Файл должен быть меньше 5 МБ.")
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("PDF защищён паролем. Загрузи доступную копию.")
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages[:40])]
            limited_pages = len(reader.pages) > 40
        except PdfReadError as exc:
            raise ValueError("Не удалось прочитать PDF. Проверь файл или загрузи текстовую копию.") from exc
        # Page labels are metadata, not evidence that a scanned PDF contains text.
        content = "\n".join(page_text for _, page_text in pages)
        text = "\n\n".join(f"[Страница {number}]\n{page_text}" for number, page_text in pages if page_text.strip())
    elif suffix in {".txt", ".md"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Сохрани текстовый файл в кодировке UTF-8 и загрузи снова.") from exc
        content = text
        limited_pages = False
    else:
        raise ValueError("Поддерживаются PDF, TXT и MD.")
    if len(content.strip()) < 20:
        raise ValueError("В файле нет извлекаемого текста. Для сканов нужен OCR.")
    return {"name": Path(name).name, "text": text[:12000], "truncated": len(text) > 12000 or limited_pages}

from io import BytesIO
from pathlib import Path
from pypdf import PdfReader


def extract_document(name: str, data: bytes) -> dict:
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Файл должен быть меньше 5 МБ.")
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("PDF защищён паролем. Загрузи доступную копию.")
        text = "\n\n".join(f"[Страница {i + 1}]\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages[:40]))
        limited_pages = len(reader.pages) > 40
    elif suffix in {".txt", ".md"}:
        text = data.decode("utf-8-sig", errors="replace")
        limited_pages = False
    else:
        raise ValueError("Поддерживаются PDF, TXT и MD.")
    if len(text.strip()) < 20:
        raise ValueError("В файле нет извлекаемого текста. Для сканов нужен OCR.")
    return {"name": Path(name).name, "text": text[:12000], "truncated": len(text) > 12000 or limited_pages}

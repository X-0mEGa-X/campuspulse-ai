from io import BytesIO
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_DOCX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_DOCX_XML_BYTES = 2 * 1024 * 1024
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_docx(data: bytes) -> str:
    """Read document text without extracting files or resolving external references."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > MAX_DOCX_EXPANDED_BYTES:
                raise ValueError("DOCX слишком велик после распаковки. Сохрани нужные страницы в отдельный файл.")
            if any(item.flag_bits & 1 for item in entries):
                raise ValueError("DOCX защищён паролем. Загрузи доступную копию.")
            documents = [item for item in entries if item.filename == "word/document.xml"]
            if len(documents) != 1:
                raise ValueError("DOCX не содержит корректного основного документа.")
            if documents[0].file_size > MAX_DOCX_XML_BYTES:
                raise ValueError("В DOCX слишком много текста. Сохрани нужную часть отдельным файлом.")
            # A bounded read also guards against misleading archive metadata.
            with archive.open(documents[0]) as source:
                xml = source.read(MAX_DOCX_XML_BYTES + 1)
            if len(xml) > MAX_DOCX_XML_BYTES:
                raise ValueError("В DOCX слишком много текста. Сохрани нужную часть отдельным файлом.")
        encoding = "utf-16" if xml.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        decoded = xml.decode(encoding)
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, re.I):
            raise ValueError("DOCX содержит неподдерживаемые XML-объявления. Пересохрани файл в Word.")
        root = ET.fromstring(decoded)
        if root.tag != WORD_NAMESPACE + "document":
            raise ValueError("DOCX не содержит корректного основного документа.")
        body = root.find(WORD_NAMESPACE + "body")
        if body is None:
            raise ValueError("DOCX не содержит текста документа.")
    except (BadZipFile, KeyError, UnicodeError, ET.ParseError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Не удалось прочитать DOCX. Пересохрани файл в Word или загрузи PDF/TXT.") from exc

    def paragraph(element):
        pieces = []
        for node in element.iter():
            if node.tag == WORD_NAMESPACE + "t":
                pieces.append(node.text or "")
            elif node.tag == WORD_NAMESPACE + "tab":
                pieces.append("\t")
            elif node.tag in {WORD_NAMESPACE + "br", WORD_NAMESPACE + "cr"}:
                pieces.append("\n")
        return "".join(pieces)

    blocks, pending = [], [body]
    while pending:
        element = pending.pop()
        if element.tag == WORD_NAMESPACE + "p":
            blocks.append(paragraph(element))
        elif element.tag == WORD_NAMESPACE + "tbl":
            blocks.extend("\t".join("\n".join(paragraph(p) for p in cell.iter(WORD_NAMESPACE + "p"))
                                    for cell in row.findall(WORD_NAMESPACE + "tc"))
                          for row in element.findall(WORD_NAMESPACE + "tr"))
        else:
            pending.extend(reversed(element))
    return "\n".join(blocks)


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
    elif suffix == ".docx":
        text = _extract_docx(data)
        content = text
        limited_pages = False
    else:
        raise ValueError("Поддерживаются PDF, DOCX, TXT и MD.")
    if not content.strip():
        raise ValueError("В файле нет извлекаемого текста. Для сканов нужен OCR: приложи нужные страницы как фото PNG/JPG/WEBP.")
    return {"name": Path(name).name, "text": text[:12000], "truncated": len(text) > 12000 or limited_pages}

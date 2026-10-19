from io import BytesIO

import pytest
from pypdf import PdfWriter

from campuspulse.documents import extract_document


def pdf_bytes(*, pages=2, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=400)
    if encrypted:
        writer.encrypt("private")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_blank_multi_page_pdf_is_not_mistaken_for_extracted_text():
    with pytest.raises(ValueError, match="OCR"):
        extract_document("scan.pdf", pdf_bytes())


def test_encrypted_pdf_has_clear_error():
    with pytest.raises(ValueError, match="паролем"):
        extract_document("locked.pdf", pdf_bytes(encrypted=True))


def test_corrupt_pdf_has_clear_error():
    with pytest.raises(ValueError, match="прочитать PDF"):
        extract_document("broken.pdf", b"not a PDF document")


def test_utf8_bom_and_material_limit_are_preserved():
    text = "Учебные материалы по программированию. " * 400
    result = extract_document("lecture.txt", text.encode("utf-8-sig"))
    assert result["text"] == text[:12000]
    assert result["truncated"] is True


def test_unsupported_text_encoding_is_not_silently_corrupted():
    with pytest.raises(ValueError, match="UTF-8"):
        extract_document("lecture.txt", "Учебный материал на русском языке".encode("cp1251"))

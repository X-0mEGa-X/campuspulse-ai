from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from campuspulse import documents
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


def docx_bytes(body, extra=None):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", body)
        if extra:
            archive.writestr(*extra)
    return output.getvalue()


def document_xml(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>' + body + '</w:body></w:document>')


def test_docx_extracts_paragraphs_and_table_cells_in_order():
    data = docx_bytes(document_xml('<w:p><w:r><w:t>Course notes</w:t><w:tab/><w:t>2026</w:t></w:r></w:p>'
                                  '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Topic</w:t></w:r></w:p></w:tc>'
                                  '<w:tc><w:p><w:r><w:t>Time</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                                  '<w:p><w:r><w:t>Final paragraph.</w:t></w:r></w:p>'))
    result = extract_document("course.docx", data)
    assert result["text"] == "Course notes\t2026\nTopic\tTime\nFinal paragraph."
    assert result["truncated"] is False


def test_short_text_is_valid_material():
    assert extract_document("equation.txt", b"x + 1 = 2")["text"] == "x + 1 = 2"


@pytest.mark.parametrize("xml", ["<invalid", '<!DOCTYPE x [<!ENTITY a "content">]><x/>'])
def test_docx_rejects_invalid_xml_and_entity_declarations(xml):
    with pytest.raises(ValueError, match="DOCX"):
        extract_document("bad.docx", docx_bytes(xml))


def test_docx_checks_xml_limit_before_parsing(monkeypatch):
    monkeypatch.setattr(documents, "MAX_DOCX_XML_BYTES", 64)
    with pytest.raises(ValueError, match="слишком много текста"):
        extract_document("large.docx", docx_bytes(document_xml("")))


def test_docx_checks_total_expanded_archive_size(monkeypatch):
    monkeypatch.setattr(documents, "MAX_DOCX_EXPANDED_BYTES", 1000)
    with pytest.raises(ValueError, match="после распаковки"):
        extract_document("bomb.docx", docx_bytes(document_xml(""), ("word/media/image.png", b"x" * 1200)))


def test_docx_missing_main_document_has_clear_error():
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("unrelated.txt", "This is not a Word document.")
    with pytest.raises(ValueError, match="основного документа"):
        extract_document("other.docx", output.getvalue())

import base64
from copy import deepcopy
from io import BytesIO

from PIL import Image
import pytest

from campuspulse import attachments
from campuspulse.attachments import merge_attachments, prepare_attachments


def image_bytes(format="PNG", size=(8, 8), animated=False):
    output = BytesIO()
    with Image.new("RGB", size, "red") as image:
        if animated:
            with Image.new("RGB", size, "blue") as second:
                image.save(output, format=format, save_all=True, append_images=[second], duration=100)
        else:
            image.save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("format,suffix,mime", [("PNG", ".png", "image/png"),
                                              ("JPEG", ".jpg", "image/jpeg"),
                                              ("WEBP", ".webp", "image/webp")])
def test_valid_photo_preserves_bytes_name_and_mime(format, suffix, mime):
    data = image_bytes(format)
    result = prepare_attachments([("Фото" + suffix, data), ("task.txt", b"x + 1 = 2")])
    photo = result["images"][0]
    assert photo["name"] == "Фото" + suffix
    assert photo["mime_type"] == mime
    assert base64.b64decode(photo["data"], validate=True) == data
    assert result["documents"][0]["text"] == "x + 1 = 2"


def test_corrupted_photo_error_names_the_file():
    with pytest.raises(ValueError, match="broken.png"):
        prepare_attachments([("broken.png", image_bytes()[:40])])


@pytest.mark.parametrize("name,format,mime", [("capture.png", "JPEG", "image/jpeg"),
                                            ("capture.jpg", "PNG", "image/png")])
def test_allowed_photo_uses_actual_mime_even_if_extension_differs(name, format, mime):
    data = image_bytes(format)
    image = prepare_attachments([(name, data)])["images"][0]
    assert image["name"] == name
    assert image["mime_type"] == mime
    assert base64.b64decode(image["data"], validate=True) == data


@pytest.mark.parametrize("data", [image_bytes("GIF"), b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                                  b"not an image"])
def test_unsupported_contents_cannot_be_enabled_by_png_filename(data):
    with pytest.raises(ValueError, match="unsupported.png"):
        prepare_attachments([("unsupported.png", data)])


def test_large_dimensions_and_animations_are_rejected():
    with pytest.raises(ValueError, match="wide.png.*слишком большое"):
        prepare_attachments([("wide.png", image_bytes(size=(10001, 1)))])
    with pytest.raises(ValueError, match="motion.png.*Анимация"):
        prepare_attachments([("motion.png", image_bytes(animated=True))])


def test_pixel_limit_is_checked_before_decode(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValueError, match="слишком большое"):
        prepare_attachments([("big.png", image_bytes())])


def test_attachment_limits():
    with pytest.raises(ValueError, match="не более 5"):
        prepare_attachments([(f"{i}.txt", b"hello") for i in range(6)])
    with pytest.raises(ValueError, match="large.txt.*5 МБ"):
        prepare_attachments([("large.txt", b"x" * (attachments.MAX_FILE_BYTES + 1))])
    with pytest.raises(ValueError, match="third.txt.*10 МБ"):
        prepare_attachments([("first.txt", b"x" * attachments.MAX_FILE_BYTES),
                             ("second.txt", b"x" * attachments.MAX_FILE_BYTES), ("third.txt", b"x")])
    with pytest.raises(ValueError, match="3.png.*не более 3"):
        prepare_attachments([(f"{i}.png", image_bytes()) for i in range(4)])


def test_batch_failure_does_not_mutate_input_or_return_partial_results():
    files = [("good.txt", b"Valid material."), ("bad.png", b"broken")]
    original = deepcopy(files)
    with pytest.raises(ValueError, match="bad.png"):
        prepare_attachments(files)
    assert files == original
    assert prepare_attachments([]) == {"documents": [], "images": []}


def test_unsupported_file_names_are_visible():
    with pytest.raises(ValueError, match="archive.zip.*поддерживаются"):
        prepare_attachments([("archive.zip", b"arbitrary")])


def test_merge_replaces_same_name_across_kinds_without_mutating_inputs():
    existing = {"documents": [{"name": "same", "text": "old", "truncated": False}], "images": []}
    incoming = {"documents": [], "images": [{"name": "same", "mime_type": "image/png",
                                                "data": base64.b64encode(image_bytes()).decode("ascii")} ]}
    original = deepcopy(existing), deepcopy(incoming)
    result = merge_attachments(existing, incoming)
    assert result["documents"] == []
    assert result["images"][0]["name"] == "same"
    assert (existing, incoming) == original
    result["images"][0]["name"] = "changed"
    assert incoming["images"][0]["name"] == "same"


def test_merge_checks_combined_count_and_actual_utf8_size(monkeypatch):
    existing = {"documents": [{"name": str(i), "text": "x"} for i in range(5)], "images": []}
    with pytest.raises(ValueError, match="не более 5"):
        merge_attachments(existing, {"documents": [{"name": "sixth", "text": "x"}]})
    monkeypatch.setattr(attachments, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(ValueError, match="second.txt.*10 МБ"):
        merge_attachments({"documents": [{"name": "first.txt", "text": "яяя"}]},
                          {"documents": [{"name": "second.txt", "text": "яяя"}]})


def test_merge_checks_combined_photo_count():
    first = prepare_attachments([(f"{i}.png", image_bytes()) for i in range(3)])
    second = prepare_attachments([("extra.png", image_bytes())])
    with pytest.raises(ValueError, match="не более 3"):
        merge_attachments(first, second)

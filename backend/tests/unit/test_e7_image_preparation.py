import builtins
import hashlib
import os
import struct
import tempfile
import zipfile
import zlib
from io import BytesIO

import pytest
from PIL import Image, ImageFile, PngImagePlugin, TiffImagePlugin

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.image_preparation import (
    MAX_IMAGE_BYTES,
    PREPARATION_VERSION,
    prepare_image,
)


def encoded(format="PNG", mode="RGB", size=(40, 24), color=None, **kwargs):
    image = Image.new(
        mode, size, color if color is not None else ("red" if mode in {"RGB", "RGBA"} else 128)
    )
    output = BytesIO()
    image.save(output, format=format, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_real_decoders_output_one_clean_rgb_jpeg(format):
    raw = encoded(format)
    result = prepare_image(raw)
    assert result.width == 40 and result.height == 24
    assert result.preparation_version == PREPARATION_VERSION
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    with Image.open(BytesIO(result.data)) as image:
        assert image.format == "JPEG" and image.mode == "RGB" and image.size == (40, 24)
        assert not image.getexif()
        assert set(image.info) <= {"jfif", "jfif_version", "jfif_unit", "jfif_density"}
    assert prepare_image(raw) == result


def test_exif_orientation_and_gps_are_applied_then_removed():
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private-person"
    exif[270] = "private-location"
    exif[34853] = {
        1: "N",
        2: tuple(TiffImagePlugin.IFDRational(x) for x in (52, 15, 0)),
        3: "E",
        4: tuple(TiffImagePlugin.IFDRational(x) for x in (21, 0, 0)),
    }
    raw = encoded("JPEG", exif=exif, comment=b"private-comment")
    assert b"Exif" in raw
    result = prepare_image(raw)
    assert (result.width, result.height) == (24, 40)
    for value in (b"Exif", b"private-person", b"private-location", b"private-comment", b"GPS"):
        assert value not in result.data


def test_png_text_xmp_icc_and_exif_do_not_survive():
    text = PngImagePlugin.PngInfo()
    text.add_text("Comment", "private-comment")
    text.add_itxt("XML:com.adobe.xmp", "private-xmp")
    result = prepare_image(encoded("PNG", pnginfo=text, icc_profile=b"private-icc"))
    for value in (b"private-comment", b"private-xmp", b"private-icc"):
        assert value not in result.data


@pytest.mark.parametrize(
    "format,mode,color",
    [
        ("PNG", "RGBA", (200, 0, 0, 0)),
        ("PNG", "LA", (0, 0)),
        ("WEBP", "RGBA", (200, 0, 0, 0)),
    ],
)
def test_alpha_flattens_to_explicit_white(format, mode, color):
    result = prepare_image(encoded(format, mode, color=color))
    with Image.open(BytesIO(result.data)) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)


def test_palette_transparency_and_long_side_resize():
    result = prepare_image(encoded("PNG", "P", color=0, transparency=0, size=(2000, 1000)))
    assert (result.width, result.height) == (1600, 800)
    with Image.open(BytesIO(result.data)) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)


@pytest.mark.parametrize("mode", ["1", "L"])
def test_simple_monochrome_and_gray_accepted(mode):
    assert prepare_image(encoded("PNG", mode)).width == 40


@pytest.mark.parametrize("format,mode", [("JPEG", "CMYK"), ("PNG", "I;16"), ("GIF", "P")])
def test_unsupported_color_modes_or_format(format, mode):
    with pytest.raises(DomainError) as error:
        prepare_image(encoded(format, mode))
    assert error.value.code == "invalid_image"


@pytest.mark.parametrize("format", ["PNG", "WEBP"])
def test_animation_rejected(format):
    first = Image.new("RGB", (40, 24), "red")
    output = BytesIO()
    first.save(
        output,
        format=format,
        save_all=True,
        append_images=[Image.new("RGB", (40, 24), "blue")],
        duration=100,
        loop=0,
    )
    with pytest.raises(DomainError) as error:
        prepare_image(output.getvalue())
    assert error.value.status == 422


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
@pytest.mark.parametrize(
    "change",
    [
        lambda b: b[:-1],
        lambda b: b[:-10],
        lambda b: b + b"\x00",
        lambda b: b + b"PK\x03\x04polyglot",
        lambda b: b + b,
    ],
)
def test_truncation_trailing_and_concatenated_image(format, change):
    with pytest.raises(DomainError) as error:
        prepare_image(change(encoded(format)))
    assert error.value.status == 422


def png_dimensions(width, height):
    raw = encoded()
    payload = struct.pack(">II", width, height) + raw[24:29]
    return raw[:16] + payload + struct.pack(">I", zlib.crc32(b"IHDR" + payload)) + raw[33:]


@pytest.mark.parametrize(
    "width,height", [(0, 1), (1, 0), (4097, 1), (4096, 4096), (100000, 100000)]
)
def test_dimensions_and_decompression_bomb_rejected_before_load(monkeypatch, width, height):
    raw = png_dimensions(width, height)

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized_image_reached_decoder")

    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(DomainError) as error:
        prepare_image(raw)
    assert error.value.status == 422


def test_crc_corruption_and_webp_container_size():
    png = bytearray(encoded())
    png[29] ^= 1
    webp = bytearray(encoded("WEBP"))
    webp[4] ^= 1
    for raw in (png, webp, b"not-image", b""):
        with pytest.raises(DomainError):
            prepare_image(bytes(raw))


def test_maximum_input_limit_and_unsafe_global_decoder_setting(monkeypatch):
    with pytest.raises(DomainError) as error:
        prepare_image(b"x" * (MAX_IMAGE_BYTES + 1))
    assert error.value.status == 413
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(DomainError) as error:
        prepare_image(encoded())
    assert error.value.status == 422


def test_decode_and_prepare_never_open_temp_or_original(monkeypatch):
    raw = encoded()
    Image.init()

    def forbidden(*args, **kwargs):
        raise AssertionError("codec_performed_file_io")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, forbidden)
    assert prepare_image(raw).width == 40


@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("mode", ["L", "RGB"])
@pytest.mark.parametrize("subsampling", [0, 1, 2])
def test_jpeg_entropy_with_real_progressive_and_sampling(progressive, mode, subsampling):
    image = Image.new(mode, (63, 49))
    for x in range(image.width):
        for y in range(image.height):
            image.putpixel(
                (x, y),
                (x * 13 + y * 29) % 256
                if mode == "L"
                else ((x * 13 + y * 29) % 256, (x * 31 + y * 7) % 256, (x * y) % 256),
            )
    output = BytesIO()
    image.save(output, "JPEG", progressive=progressive, subsampling=subsampling, optimize=True)
    assert prepare_image(output.getvalue()).width == 63


@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("interval", [1, 4, 1000])
def test_jpeg_restart_markers(progressive, interval):
    raw = encoded("JPEG", size=(93, 79), progressive=progressive, restart_marker_blocks=interval)
    assert prepare_image(raw).width == 93


@pytest.mark.parametrize("progressive", [False, True])
def test_jpeg_early_eoi_is_rejected_even_when_libjpeg_repairs_it(progressive):
    raw = encoded("JPEG", size=(800, 600), progressive=progressive)
    scan = raw.index(b"\xff\xda")
    start = scan + 2 + int.from_bytes(raw[scan + 2 : scan + 4], "big")
    broken = raw[: start + 10] + b"\xff\xd9"
    # This is the independent behavioral probe: Pillow tolerates early EOI.
    with Image.open(BytesIO(broken)) as decoder:
        decoder.load()
    with pytest.raises(DomainError) as error:
        prepare_image(broken)
    assert error.value.status == 422


def test_png_rejects_extra_zlib_stream_and_inexact_expansion():
    raw = encoded()
    position = raw.index(b"IDAT") - 4
    size = int.from_bytes(raw[position : position + 4], "big")
    payload = raw[position + 8 : position + 8 + size]
    for replacement in (
        payload + zlib.compress(b"polyglot"),
        zlib.compress(b"too-few-pixels"),
        zlib.compress(b"x" * 100000),
    ):
        chunk = struct.pack(">I", len(replacement)) + b"IDAT" + replacement
        chunk += struct.pack(">I", zlib.crc32(b"IDAT" + replacement))
        broken = raw[:position] + chunk + raw[position + 12 + size :]
        with pytest.raises(DomainError):
            prepare_image(broken)


@pytest.mark.parametrize("lossless", [False, True])
def test_webp_real_lossy_and_lossless_with_exif_xmp_and_alpha(lossless):
    exif = Image.Exif()
    exif[274] = 6
    raw = encoded(
        "WEBP",
        "RGBA",
        color=(255, 0, 0, 150),
        lossless=lossless,
        exif=exif,
        xmp=b"private-xmp",
        icc_profile=b"private-icc",
    )
    result = prepare_image(raw)
    assert (result.width, result.height) == (24, 40)
    assert b"private-" not in result.data


@pytest.mark.parametrize("lossless", [False, True])
def test_real_zip_polyglot_inside_webp_compressed_chunk_rejected(lossless):
    raw = encoded("WEBP", lossless=lossless)
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("foreign.txt", b"second-container")
    size = int.from_bytes(raw[16:20], "little")
    payload = raw[20 : 20 + size] + archive.getvalue()
    chunk = raw[12:16] + len(payload).to_bytes(4, "little") + payload
    chunk += b"\x00" if len(payload) & 1 else b""
    polyglot = b"RIFF" + (len(chunk) + 4).to_bytes(4, "little") + b"WEBP" + chunk
    # Independent readers confirm this is both an image and an actual archive.
    with Image.open(BytesIO(polyglot)) as image:
        image.load()
    with zipfile.ZipFile(BytesIO(polyglot)) as zipped:
        assert zipped.read("foreign.txt") == b"second-container"
    with pytest.raises(DomainError) as error:
        prepare_image(polyglot)
    assert error.value.code == "invalid_image"


def test_zip_symbols_in_real_image_metadata_are_not_signature_banned():
    text = PngImagePlugin.PngInfo()
    text.add_text("Comment", "PK\x03\x04 ordinary text, no archive directory")
    assert prepare_image(encoded("PNG", pnginfo=text)).width == 40


def test_pillow_decompression_bomb_exception_is_a_safe_rejection(monkeypatch):
    raw = encoded("WEBP", lossless=True)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(DomainError) as error:
        prepare_image(raw)
    assert error.value.code == "invalid_image"

"""Strict bounded image framing and deterministic metadata-free JPEG preparation."""

import hashlib
import struct
import warnings
import zlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from calorie_app.core.errors import DomainError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = 16_000_000
OUTPUT_SIDE = 1600
PREPARATION_VERSION = "food-photo-preparation-v1"
_MODES = {"1", "L", "LA", "P", "RGB", "RGBA"}


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    width: int
    height: int
    sha256: str
    preparation_version: str


def _dimensions(width: int, height: int) -> None:
    if not 0 < width <= MAX_SIDE or not 0 < height <= MAX_SIDE or width * height > MAX_PIXELS:
        raise ValueError


def _archive_polyglot(raw: bytes) -> bool:
    """Recognize an entire second ZIP container, never scan/ban image symbols.

    ZIP readers allow a prefix and trailing bytes, so RIFF sizes alone do not
    rule out an archive embedded in a compressed chunk or EXIF. Validate the
    EOCD, central directory and local-header locations without extraction or
    allocation driven by an archive. JPEG/PNG/WebP decoding never uses ZIP.
    """
    search = max(0, len(raw) - 65557)
    position = raw.find(b"PK\x05\x06", search)
    while position != -1:
        if position + 22 <= len(raw):
            disk, directory_disk, disk_entries, entries, size, offset, comment = struct.unpack(
                "<HHHHIIH", raw[position + 4 : position + 22]
            )
            if (
                disk == directory_disk == 0
                and disk_entries == entries
                and position + 22 + comment <= len(raw)
            ):
                start = position - size
                archive_start = start - offset
                if entries == 0 and size == offset == 0:
                    return True
                if (entries == 65535 or size == 0xFFFFFFFF or offset == 0xFFFFFFFF) and (
                    position >= 20 and raw[position - 20 : position - 16] == b"PK\x06\x07"
                ):
                    return True  # ZIP64 EOCD+locator: do not accept a second archive profile.
                if 0 <= archive_start <= start <= position and entries:
                    cursor = start
                    complete = True
                    for _ in range(entries):
                        if cursor + 46 > position or raw[cursor : cursor + 4] != b"PK\x01\x02":
                            complete = False
                            break
                        filename, extra, note = struct.unpack(
                            "<HHH", raw[cursor + 28 : cursor + 34]
                        )
                        local_offset = int.from_bytes(raw[cursor + 42 : cursor + 46], "little")
                        local = archive_start + local_offset
                        if (
                            not archive_start <= local < start
                            or raw[local : local + 4] != b"PK\x03\x04"
                        ):
                            complete = False
                            break
                        cursor += 46 + filename + extra + note
                        if cursor > position:
                            complete = False
                            break
                    if complete and cursor == position:
                        return True
        position = raw.find(b"PK\x05\x06", position + 4)
    return False


def _png(raw: bytes) -> None:
    """Check every CRC and exact IEND, including chunks Pillow otherwise ignores."""
    position, chunks = 8, set()
    idat_ended = False
    idat_started = False
    decoder = zlib.decompressobj()
    decoded_size = expected_size = 0
    count = 0
    while position < len(raw):
        if len(raw) - position < 12:
            raise ValueError
        size = int.from_bytes(raw[position : position + 4], "big")
        kind = raw[position + 4 : position + 8]
        end = position + 12 + size
        if end > len(raw) or not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
            raise ValueError
        if kind[2] & 32:  # PNG reserved bit must be zero.
            raise ValueError
        payload = raw[position + 8 : end - 4]
        expected = int.from_bytes(raw[end - 4 : end], "big")
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected:
            raise ValueError
        count += 1
        if count > 4096 or (not chunks and kind != b"IHDR"):
            raise ValueError
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError
        if not kind[0] & 32 and kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
            raise ValueError
        if kind == b"IHDR":
            if chunks or size != 13:
                raise ValueError
            width, height = struct.unpack(">II", payload[:8])
            _dimensions(width, height)
            depth, color, compression, filtering, interlace = payload[8:]
            allowed_depths = {0: {1, 2, 4, 8}, 2: {8}, 3: {1, 2, 4, 8}, 4: {8}, 6: {8}}
            if depth not in allowed_depths.get(color, set()) or compression or filtering:
                raise ValueError
            if interlace not in {0, 1}:
                raise ValueError
            bits = depth * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            passes = (
                [(0, 0, 1, 1)]
                if not interlace
                else [
                    (0, 0, 8, 8),
                    (4, 0, 8, 8),
                    (0, 4, 4, 8),
                    (2, 0, 4, 4),
                    (0, 2, 2, 4),
                    (1, 0, 2, 2),
                    (0, 1, 1, 2),
                ]
            )
            for x, y, dx, dy in passes:
                columns, rows = (
                    max(0, (width - x + dx - 1) // dx),
                    max(0, (height - y + dy - 1) // dy),
                )
                if columns and rows:
                    expected_size += rows * (1 + (columns * bits + 7) // 8)
        elif kind == b"IDAT":
            if idat_ended:
                raise ValueError
            idat_started = True
            decoded_size += len(decoder.decompress(payload, expected_size + 1 - decoded_size))
            if decoded_size > expected_size or decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError
        elif idat_started:
            idat_ended = True
        if kind in {b"PLTE", b"IEND"} and kind in chunks:
            raise ValueError
        if kind == b"PLTE" and (b"IDAT" in chunks or not size or size % 3 or size > 768):
            raise ValueError
        chunks.add(kind)
        position = end
        if kind == b"IEND":
            if (
                size
                or position != len(raw)
                or not idat_started
                or not decoder.eof
                or decoded_size != expected_size
            ):
                raise ValueError
            return
    raise ValueError


class _Bits:
    def __init__(self, data: bytes):
        self.data, self.position = data, 0

    def take(self, count: int) -> int:
        if self.position + count > len(self.data) * 8:
            raise ValueError
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.position // 8] >> (7 - self.position % 8)) & 1)
            self.position += 1
        return value

    def symbol(self, table: dict) -> int:
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.take(1)
            if (length, code) in table:
                return table[length, code]
        raise ValueError

    def padding(self):
        count = len(self.data) * 8 - self.position
        if count > 7 or self.take(count) != (1 << count) - 1:
            raise ValueError


def _huffman(payload: bytes, tables: dict) -> None:
    position = 0
    while position < len(payload):
        if len(payload) - position < 17:
            raise ValueError
        selector = payload[position]
        if selector >> 4 not in {0, 1} or selector & 15 > 3:
            raise ValueError
        counts = payload[position + 1 : position + 17]
        position += 17
        if not sum(counts) or position + sum(counts) > len(payload):
            raise ValueError
        code, table = 0, {}
        for length, count in enumerate(counts, 1):
            if code + count >= 1 << length:  # all-ones code is reserved for padding
                raise ValueError
            for _ in range(count):
                table[length, code] = payload[position]
                position, code = position + 1, code + 1
            code <<= 1
        tables[selector >> 4, selector & 15] = table


class _JpegFrame:
    """Entropy structure validator: libjpeg alone silently repairs early EOI."""

    def __init__(self, payload: bytes, progressive: bool):
        self.height, self.width = struct.unpack(">HH", payload[1:5])
        self.progressive = progressive
        self.components, self.approximation, self.coefficients = {}, {}, {}
        self.decoded = set()
        self.restart = 0
        for position in range(6, len(payload), 3):
            name, sampling, quantization = payload[position : position + 3]
            horizontal, vertical = sampling >> 4, sampling & 15
            if name in self.components or not 1 <= horizontal <= 4 or not 1 <= vertical <= 4:
                raise ValueError
            if quantization > 3:
                raise ValueError
            self.components[name] = horizontal, vertical
            self.approximation[name] = [None] * 64
        if sum(h * v for h, v in self.components.values()) > 10:
            raise ValueError
        self.max_h = max(h for h, _ in self.components.values())
        self.max_v = max(v for _, v in self.components.values())
        self.columns = (self.width + 8 * self.max_h - 1) // (8 * self.max_h)
        self.rows = (self.height + 8 * self.max_v - 1) // (8 * self.max_v)
        for name, (h, v) in self.components.items():
            self.coefficients[name] = bytearray(self.columns * h * self.rows * v * 64)

    def scan(self, header: bytes, chunks: list[bytes], restarts: list[int], tables: dict) -> None:
        count = header[0] if header else 0
        if count not in {1, 2, 3} or len(header) != 1 + count * 2 + 3:
            raise ValueError
        selected = {}
        for position in range(1, 1 + count * 2, 2):
            name, selector = header[position : position + 2]
            if (
                name not in self.components
                or name in selected
                or selector >> 4 > 3
                or selector & 15 > 3
            ):
                raise ValueError
            selected[name] = selector >> 4, selector & 15
        first, last, bits = header[-3:]
        high, low = bits >> 4, bits & 15
        if not 0 <= first <= last <= 63 or high > 13 or low > 13:
            raise ValueError
        if self.progressive:
            if (first == 0 and last != 0) or (first > 0 and count != 1):
                raise ValueError
            for name in selected:
                for coefficient in range(first, last + 1):
                    prior = self.approximation[name][coefficient]
                    if (not high and prior is not None) or (
                        high and (prior != high or low != high - 1)
                    ):
                        raise ValueError
        elif first != 0 or last != 63 or bits or self.decoded & selected.keys():
            raise ValueError

        if count == 1:
            name = next(iter(selected))
            h, v = self.components[name]
            columns = (self.width * h + 8 * self.max_h - 1) // (8 * self.max_h)
            rows = (self.height * v + 8 * self.max_v - 1) // (8 * self.max_v)
        else:
            columns, rows = self.columns, self.rows
        units = columns * rows
        groups = (units + self.restart - 1) // self.restart if self.restart else 1
        if len(chunks) != groups or len(restarts) != groups - 1:
            raise ValueError
        if any(marker != 0xD0 + index % 8 for index, marker in enumerate(restarts)):
            raise ValueError
        unit, eobrun = 0, 0
        for group, data in enumerate(chunks):
            reader = _Bits(data)
            end = min(units, (group + 1) * self.restart) if self.restart else units
            while unit < end:
                row, column = divmod(unit, columns)
                for name, selectors in selected.items():
                    h, v = self.components[name]
                    for y in range(v if count > 1 else 1):
                        for x in range(h if count > 1 else 1):
                            block = (
                                ((row * v + y) * self.columns * h + column * h + x)
                                if count > 1
                                else (row * self.columns * h + column)
                            )
                            eobrun = self._block(
                                reader,
                                tables,
                                selectors,
                                name,
                                block * 64,
                                first,
                                last,
                                high,
                                eobrun,
                            )
                unit += 1
            if eobrun:
                raise ValueError
            reader.padding()
        for name in selected:
            for coefficient in range(first, last + 1):
                self.approximation[name][coefficient] = low
        self.decoded.update(selected)

    def _block(self, reader, tables, selectors, name, offset, first, last, high, eobrun):
        coefficients = self.coefficients[name]
        if not self.progressive or first == 0:
            if high:
                reader.take(1)
            else:
                category = reader.symbol(tables[0, selectors[0]])
                if category > 11:
                    raise ValueError
                reader.take(category)
            if self.progressive:
                return 0
            first = 1
        if eobrun:
            if high:
                for coefficient in range(first, last + 1):
                    if coefficients[offset + coefficient]:
                        reader.take(1)
            return eobrun - 1
        coefficient = first
        while coefficient <= last:
            symbol = reader.symbol(tables[1, selectors[1]])
            run, size = symbol >> 4, symbol & 15
            if not size and run < 15:
                if not self.progressive:
                    if run:
                        raise ValueError
                    return 0
                eobrun = (1 << run) + reader.take(run)
                if high:
                    for cursor in range(coefficient, last + 1):
                        if coefficients[offset + cursor]:
                            reader.take(1)
                return eobrun - 1
            if high:
                if size not in {0, 1}:
                    raise ValueError
                if size:
                    reader.take(1)  # sign of the new coefficient precedes correction bits
                remaining = run if size else 16
                while coefficient <= last:
                    if coefficients[offset + coefficient]:
                        reader.take(1)
                    elif remaining:
                        remaining -= 1
                    else:
                        break
                    coefficient += 1
                    if not size and not remaining:
                        break
                if remaining or (size and coefficient > last):
                    raise ValueError
                if size:
                    coefficients[offset + coefficient] = 1
                    coefficient += 1
            else:
                if size > 10:
                    raise ValueError
                coefficient += run if size else 16
                if coefficient > last + (not size):
                    raise ValueError
                if size:
                    reader.take(size)
                    coefficients[offset + coefficient] = 1
                    coefficient += 1
        return 0


def _jpeg(raw: bytes) -> None:
    """Parse length-delimited markers and entropy escapes up to the only EOI."""
    position, frame, scans, markers, tables = 2, None, 0, 0, {}
    while position < len(raw):
        markers += 1
        if markers > 4096:
            raise ValueError
        if raw[position] != 0xFF:
            raise ValueError
        while position < len(raw) and raw[position] == 0xFF:
            position += 1
        if position == len(raw):
            raise ValueError
        marker = raw[position]
        position += 1
        if marker == 0xD9:
            if position != len(raw) or not frame or not scans:
                raise ValueError
            if frame.decoded != frame.components.keys():
                raise ValueError
            if frame.progressive and any(
                value is None for values in frame.approximation.values() for value in values
            ):
                raise ValueError
            return
        if marker not in {0xC0, 0xC1, 0xC2, 0xC4, 0xDB, 0xDD, 0xDA, 0xFE, *range(0xE0, 0xF0)}:
            raise ValueError
        if position + 2 > len(raw):
            raise ValueError
        size = int.from_bytes(raw[position : position + 2], "big")
        end = position + size
        if size < 2 or end > len(raw):
            raise ValueError
        if marker in {0xC0, 0xC1, 0xC2}:
            if frame or size < 8 or raw[position + 2] != 8:
                raise ValueError
            height, width = struct.unpack(">HH", raw[position + 3 : position + 7])
            _dimensions(width, height)
            components = raw[position + 7]
            if components not in {1, 3} or size != 8 + 3 * components:
                raise ValueError
            frame = _JpegFrame(raw[position + 2 : end], marker == 0xC2)
        elif marker == 0xC4:
            _huffman(raw[position + 2 : end], tables)
        elif marker == 0xDD:
            if size != 4 or frame is None:
                raise ValueError
            frame.restart = int.from_bytes(raw[position + 2 : end], "big")
        scan_header = raw[position + 2 : end] if marker == 0xDA else None
        position = end
        if marker == 0xDA:
            if not frame:
                raise ValueError
            scans += 1
            if scans > 1024:
                raise ValueError
            chunks, restarts, data = [], [], bytearray()
            while position < len(raw):
                next_marker = raw.find(b"\xff", position)
                if next_marker == -1 or next_marker + 1 == len(raw):
                    raise ValueError
                cursor = next_marker + 1
                while cursor < len(raw) and raw[cursor] == 0xFF:
                    cursor += 1
                if cursor == len(raw):
                    raise ValueError
                data.extend(raw[position:next_marker])
                if raw[cursor] == 0:
                    if cursor != next_marker + 1:
                        raise ValueError
                    data.append(0xFF)
                    position = cursor + 1
                elif 0xD0 <= raw[cursor] <= 0xD7:
                    chunks.append(bytes(data))
                    data.clear()
                    restarts.append(raw[cursor])
                    position = cursor + 1
                else:
                    chunks.append(bytes(data))
                    position = next_marker
                    break
            frame.scan(scan_header, chunks, restarts, tables)
    raise ValueError


def _webp(raw: bytes) -> None:
    if len(raw) < 20 or int.from_bytes(raw[4:8], "little") + 8 != len(raw):
        raise ValueError
    position, chunks = 12, []
    extended_size, actual_size, flags = None, None, 0
    while position < len(raw):
        if len(raw) - position < 8:
            raise ValueError
        kind = raw[position : position + 4]
        size = int.from_bytes(raw[position + 4 : position + 8], "little")
        end = position + 8 + size
        padded = end + (size & 1)
        if padded > len(raw) or (size & 1 and raw[end] != 0):
            raise ValueError
        if kind not in {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ICCP", b"EXIF", b"XMP "}:
            raise ValueError
        if kind in chunks:
            raise ValueError
        if kind == b"VP8X":
            if (
                chunks
                or size != 10
                or raw[position + 8] & 0xC3
                or any(raw[position + 9 : position + 12])
            ):
                raise ValueError
            # Animation flag (bit 1) is included in the rejected mask above.
            width = 1 + int.from_bytes(raw[position + 12 : position + 15], "little")
            height = 1 + int.from_bytes(raw[position + 15 : position + 18], "little")
            _dimensions(width, height)
            extended_size, flags = (width, height), raw[position + 8]
        elif kind == b"VP8 ":
            payload = raw[position + 8 : end]
            if size < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise ValueError
            tag = int.from_bytes(payload[:3], "little")
            if tag & 1 or (tag >> 1) & 7 > 3 or not tag & 16 or tag >> 5 > size - 10:
                raise ValueError
            actual_size = tuple(value & 0x3FFF for value in struct.unpack("<HH", payload[6:10]))
            _dimensions(*actual_size)
        elif kind == b"VP8L":
            payload = raw[position + 8 : end]
            if size < 5 or payload[0] != 0x2F:
                raise ValueError
            header = int.from_bytes(payload[1:5], "little")
            if header >> 29:
                raise ValueError
            actual_size = (1 + (header & 0x3FFF), 1 + ((header >> 14) & 0x3FFF))
            _dimensions(*actual_size)
        chunks.append(kind)
        position = padded
    if len(set(chunks) & {b"VP8 ", b"VP8L"}) != 1:
        raise ValueError
    if chunks[0] != b"VP8X" and len(chunks) != 1:
        raise ValueError
    if extended_size is not None:
        if actual_size != extended_size:
            raise ValueError
        for chunk, flag in ((b"ICCP", 0x20), (b"EXIF", 8), (b"XMP ", 4)):
            if bool(flags & flag) != (chunk in chunks):
                raise ValueError
        image_index = chunks.index(b"VP8 " if b"VP8 " in chunks else b"VP8L")
        if b"ICCP" in chunks and chunks.index(b"ICCP") > image_index:
            raise ValueError
        if any(
            chunk in chunks and chunks.index(chunk) < image_index for chunk in (b"EXIF", b"XMP ")
        ):
            raise ValueError
        if b"ALPH" in chunks and (
            b"VP8L" in chunks or not flags & 0x10 or chunks.index(b"ALPH") != image_index - 1
        ):
            raise ValueError


def _format(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        _png(raw)
        return "PNG"
    if raw.startswith(b"\xff\xd8"):
        _jpeg(raw)
        return "JPEG"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        _webp(raw)
        return "WEBP"
    raise ValueError


def prepare_image(raw: bytes) -> PreparedImage:
    """Caller must validate consent and replay before invoking this decoder."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise DomainError(413, "request_too_large")
    try:
        if not raw or ImageFile.LOAD_TRUNCATED_IMAGES or _archive_polyglot(raw):
            # Do not mutate this process-global Pillow flag during requests.
            raise ValueError
        expected = _format(raw)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with Image.open(BytesIO(raw), formats=[expected]) as image:
                _dimensions(*image.size)
                if image.format != expected or image.mode not in _MODES:
                    raise ValueError
                if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                    raise ValueError
                image.verify()
            # verify invalidates the decoder; load separately to reject corrupt
            # pixel data before any prepared bytes are returned.
            with Image.open(BytesIO(raw), formats=[expected]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                if "A" in oriented.getbands() or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, (255, 255, 255))
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgb = oriented.convert("RGB")
                rgb.thumbnail((OUTPUT_SIDE, OUTPUT_SIDE), Image.Resampling.LANCZOS)
                # Fresh canvas: never copy Image.info/exif/icc/xmp/comment.
                clean = Image.new("RGB", rgb.size)
                clean.paste(rgb)
                output = BytesIO()
                clean.save(
                    output,
                    format="JPEG",
                    quality=90,
                    subsampling=2,
                    optimize=False,
                    progressive=False,
                    exif=b"",
                    icc_profile=None,
                )
                data = output.getvalue()
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError
                return PreparedImage(
                    data,
                    clean.width,
                    clean.height,
                    hashlib.sha256(data).hexdigest(),
                    PREPARATION_VERSION,
                )
    except (
        ValueError,
        OSError,
        SyntaxError,
        struct.error,
        Warning,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        TypeError,
        OverflowError,
        KeyError,
        IndexError,
        zlib.error,
    ):
        raise DomainError(422, "invalid_image") from None

#!/usr/bin/env python3
"""Change the manifest application ID in Android's binary XML string pool."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def read_len8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
    return first, offset + 1


def write_len8(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    if value < 0x8000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    raise ValueError("Android UTF-8 string too long")


def read_len16(data: bytes, offset: int) -> tuple[int, int]:
    first = struct.unpack_from("<H", data, offset)[0]
    if first & 0x8000:
        second = struct.unpack_from("<H", data, offset + 2)[0]
        return ((first & 0x7FFF) << 16) | second, offset + 4
    return first, offset + 2


def write_len16(value: int) -> bytes:
    if value < 0x8000:
        return struct.pack("<H", value)
    return struct.pack("<HH", 0x8000 | (value >> 16), value & 0xFFFF)


def replace_pool(chunk: bytes, replacements: dict[str, str]) -> tuple[bytes, int]:
    kind, header_size, size, count, style_count, flags, strings_start, styles_start = struct.unpack_from("<HHIIIIII", chunk)
    if kind != 1 or header_size < 28 or size != len(chunk):
        raise ValueError("Malformed Android string pool")
    offsets_base = header_size
    string_offsets = list(struct.unpack_from(f"<{count}I", chunk, offsets_base)) if count else []
    styles_base = offsets_base + count * 4
    style_offsets = list(struct.unpack_from(f"<{style_count}I", chunk, styles_base)) if style_count else []
    utf8 = bool(flags & 0x100)
    values = []
    originals = []
    for relative in string_offsets:
        offset = strings_start + relative
        if utf8:
            utf16_len, offset = read_len8(chunk, offset)
            byte_len, offset = read_len8(chunk, offset)
            value = chunk[offset : offset + byte_len].decode("utf-8")
        else:
            utf16_len, offset = read_len16(chunk, offset)
            value = chunk[offset : offset + utf16_len * 2].decode("utf-16le")
        originals.append(value)
        values.append(replacements.get(value, value))
    encoded = bytearray()
    new_offsets = []
    for value in values:
        new_offsets.append(len(encoded))
        if utf8:
            body = value.encode("utf-8")
            encoded.extend(write_len8(len(value.encode("utf-16le")) // 2))
            encoded.extend(write_len8(len(body)))
            encoded.extend(body)
            encoded.append(0)
        else:
            body = value.encode("utf-16le")
            encoded.extend(write_len16(len(body) // 2))
            encoded.extend(body)
            encoded.extend(b"\0\0")
    header_and_offsets = bytearray(chunk[:header_size])
    header_and_offsets.extend(struct.pack(f"<{count}I", *new_offsets) if count else b"")
    header_and_offsets.extend(struct.pack(f"<{style_count}I", *style_offsets) if style_count else b"")
    new_strings_start = len(header_and_offsets)
    header_and_offsets.extend(encoded)
    new_styles_start = 0
    if style_count and styles_start:
        while len(header_and_offsets) % 4:
            header_and_offsets.append(0)
        new_styles_start = len(header_and_offsets)
        header_and_offsets.extend(chunk[styles_start:])
    else:
        while len(header_and_offsets) % 4:
            header_and_offsets.append(0)
    new_size = len(header_and_offsets)
    struct.pack_into("<I", header_and_offsets, 4, new_size)
    struct.pack_into("<I", header_and_offsets, 20, new_strings_start)
    struct.pack_into("<I", header_and_offsets, 24, new_styles_start)
    return bytes(header_and_offsets), sum(old != new for old, new in zip(originals, values))


def patch_manifest(source: Path, destination: Path, package_id: str) -> int:
    data = source.read_bytes()
    kind, header_size, total_size = struct.unpack_from("<HHI", data, 0)
    if kind != 0x0003 or total_size != len(data):
        raise ValueError("Input is not a complete Android binary XML manifest")
    cursor = header_size
    replacements = {
        "com.ascensionsandbox.game": package_id,
        "com.ascensionsandbox.game.fileprovider": package_id + ".fileprovider",
    }
    changed = 0
    output = bytearray(data[:header_size])
    while cursor < len(data):
        chunk_type, chunk_header_size, chunk_size = struct.unpack_from("<HHI", data, cursor)
        chunk = data[cursor : cursor + chunk_size]
        if chunk_type == 1:
            chunk, amount = replace_pool(chunk, replacements)
            changed += amount
        output.extend(chunk)
        cursor += chunk_size
    struct.pack_into("<I", output, 4, len(output))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--package", default="com.ascensionsandbox.game.ru")
    args = parser.parse_args()
    changed = patch_manifest(args.manifest, args.output, args.package)
    print(f"Updated {changed} binary-XML strings; output {args.output}")


if __name__ == "__main__":
    main()

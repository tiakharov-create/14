#!/usr/bin/env python3
"""Extract .NET user-string literals from the game's managed assemblies.

Usage:
  python tools/extract_dotnet_string_catalog.py \
      path/to/SandboxCultivation.dll path/to/Cultivation.Sim.dll \
      --output localization/source_strings.csv

Requires dnfile (python -m pip install dnfile). The string_token column is the
metadata token used by IL `ldstr`; retaining it makes the catalog useful for
binary patching without relying on decompiled source files.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import dnfile


def read_compressed_uint(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos]
    if first & 0x80 == 0:
        return first, pos + 1
    if first & 0xC0 == 0x80:
        return ((first & 0x3F) << 8) | data[pos + 1], pos + 2
    if first & 0xE0 == 0xC0:
        value = ((first & 0x1F) << 24) | (data[pos + 1] << 16) | (data[pos + 2] << 8) | data[pos + 3]
        return value, pos + 4
    raise ValueError(f"Invalid compressed integer at #US offset {pos}")


def read_user_strings(dll: Path):
    pe = dnfile.dnPE(str(dll))
    heap = pe.net.metadata.streams[b"#US"].__data__
    pos = 1  # offset zero is reserved by the CLI metadata format
    while pos < len(heap):
        offset = pos
        length, pos = read_compressed_uint(heap, pos)
        if length == 0 or pos + length > len(heap):
            break
        raw = heap[pos : pos + length]
        pos += length
        # The final byte is the CLI special-character flag; the rest is UTF-16LE.
        text_bytes = raw[:-1] if length % 2 else raw
        try:
            text = text_bytes.decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if text:
            yield offset, text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assemblies", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous = {}
    if args.output.is_file():
        with args.output.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    previous[(row["assembly"], int(row["string_token"], 16))] = row.get("russian", "")
                except (KeyError, ValueError):
                    continue

    rows = []
    for dll in args.assemblies:
        if not dll.is_file():
            parser.error(f"assembly not found: {dll}")
        for offset, text in read_user_strings(dll):
            rows.append((dll.name, f"0x70{offset:06X}", text, previous.get((dll.name, 0x70000000 | offset), "")))

    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("assembly", "string_token", "english", "russian"))
        writer.writerows(rows)
    print(f"Wrote {len(rows)} literals to {args.output}")


if __name__ == "__main__":
    main()

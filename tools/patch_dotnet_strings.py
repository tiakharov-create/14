#!/usr/bin/env python3
"""Apply translated #US string literals to unsigned .NET assemblies in-place-safe form.

The game exports its C# code as managed DLLs, so editing the blank source stubs
cannot affect the APK. This tool appends translated user strings to the CLI #US
heap, redirects matching IL `ldstr` tokens, and moves the rebuilt metadata into a
new read-only PE section. Strong-name-signed assemblies are intentionally refused.

Usage:
  python tools/patch_dotnet_strings.py input.dll localization/source_strings.csv output.dll

Requires: dnfile, dncil, pefile (pip install -r tools/requirements.txt).
Only rows with a non-empty `russian` column are patched.
"""

from __future__ import annotations

import argparse
import csv
import struct
from pathlib import Path

import dnfile
import pefile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBytes


def align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def compressed_uint(value: int) -> bytes:
    if value < 0x80:
        return bytes((value,))
    if value < 0x4000:
        return bytes((0x80 | (value >> 8), value & 0xFF))
    if value < 0x20000000:
        return bytes((0xC0 | (value >> 24), (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF))
    raise ValueError("CLI user string exceeds maximum encodable length")


def parse_metadata_root(data: bytes):
    if data[:4] != b"BSJB":
        raise ValueError("Invalid CLI metadata signature")
    version_length = struct.unpack_from("<I", data, 12)[0]
    cursor = align(16 + version_length, 4)
    flags, stream_count = struct.unpack_from("<HH", data, cursor)
    cursor += 4
    headers = []
    for _ in range(stream_count):
        offset, size = struct.unpack_from("<II", data, cursor)
        cursor += 8
        end = data.index(0, cursor)
        name = data[cursor:end].decode("ascii")
        cursor = align(end + 1, 4)
        headers.append((name, offset, size))
    prefix = data[: align(16 + version_length, 4)] + struct.pack("<HH", flags, stream_count)
    streams = {name: data[offset : offset + size] for name, offset, size in headers}
    return prefix, streams


def build_metadata_root(prefix: bytes, streams: dict[str, bytes]) -> bytes:
    names = list(streams)
    header_size = sum(8 + align(len(name.encode("ascii")) + 1, 4) for name in names)
    header_end = len(prefix) + header_size
    cursor = align(header_end, 4)
    entries = []
    for name in names:
        blob = streams[name]
        entries.append((name, cursor, len(blob)))
        cursor = align(cursor + len(blob), 4)
    out = bytearray(prefix)
    for name, offset, size in entries:
        out.extend(struct.pack("<II", offset, size))
        encoded = name.encode("ascii") + b"\0"
        out.extend(encoded)
        out.extend(b"\0" * (align(len(encoded), 4) - len(encoded)))
    out.extend(b"\0" * (align(len(out), 4) - len(out)))
    for name, offset, size in entries:
        if len(out) < offset:
            out.extend(b"\0" * (offset - len(out)))
        out.extend(streams[name])
        out.extend(b"\0" * (align(len(out), 4) - len(out)))
    return bytes(out)


def read_catalog(path: Path, assembly_name: str) -> dict[int, str]:
    translations = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("assembly") != assembly_name or not row.get("russian", "").strip():
                continue
            token = int(row["string_token"], 16)
            translations[token & 0x00FFFFFF] = row["russian"]
    return translations


def method_body_length(data: bytes, offset: int) -> int:
    first = data[offset]
    if first & 0x3 in (0x2,):  # tiny header
        return 1 + (first >> 2)
    if first & 0x3 != 0x3 or offset + 12 > len(data):
        raise ValueError("Unrecognized method header")
    flags_and_size = struct.unpack_from("<H", data, offset)[0]
    header_size = ((flags_and_size >> 12) & 0xF) * 4
    code_size = struct.unpack_from("<I", data, offset + 4)[0]
    length = header_size + code_size
    if flags_and_size & 0x8:  # more sections (most often exception handlers)
        section = align(offset + length, 4)
        if section + 4 <= len(data):
            kind = data[section]
            if kind & 0x40:  # fat section: 24-bit size
                extra = data[section + 1] | (data[section + 2] << 8) | (data[section + 3] << 16)
            else:
                extra = data[section + 1]
            length = section - offset + extra
    return length


def patch_assembly(
    source: Path,
    catalog: Path,
    destination: Path,
    resource_overrides: dict[str, bytes] | None = None,
) -> tuple[int, int]:
    original = source.read_bytes()
    pe = dnfile.dnPE(str(source))
    translations = read_catalog(catalog, source.name)
    if not translations and not resource_overrides:
        destination.write_bytes(original)
        return 0, 0
    if pe.net.struct.StrongNameSignatureSize:
        raise ValueError(f"Refusing to alter strong-name-signed assembly: {source.name}")

    stream_data = {name.decode("ascii"): stream.__data__ for name, stream in pe.net.metadata.streams.items()}
    if "#US" not in stream_data:
        raise ValueError(f"Assembly has no #US stream: {source.name}")
    us_heap = bytearray(stream_data["#US"])
    token_remap: dict[int, int] = {}
    translated_offsets: dict[str, int] = {}
    for old_offset, text in translations.items():
        if old_offset <= 0 or old_offset >= len(us_heap):
            continue
        new_offset = translated_offsets.get(text)
        if new_offset is None:
            encoded = text.encode("utf-16le") + b"\x01"
            new_offset = len(us_heap)
            us_heap.extend(compressed_uint(len(encoded)))
            us_heap.extend(encoded)
            translated_offsets[text] = new_offset
        token_remap[old_offset] = new_offset

    if not token_remap and not resource_overrides:
        destination.write_bytes(original)
        return 0, 0

    patched_literals = 0
    modified_methods = 0
    data = bytearray(original)
    for method in pe.net.mdtables.MethodDef.rows:
        if not method.Rva:
            continue
        method_offset = pe.get_offset_from_rva(method.Rva)
        try:
            length = method_body_length(data, method_offset)
            body = CilMethodBody(CilMethodBodyReaderBytes(bytes(data[method_offset : method_offset + length])))
        except Exception:
            continue
        method_changed = False
        for instruction in body.instructions:
            if instruction.opcode.name != "ldstr":
                continue
            value = instruction.operand.value
            old_offset = value & 0x00FFFFFF
            new_offset = token_remap.get(old_offset)
            if new_offset is None:
                continue
            new_token = 0x70000000 | new_offset
            operand_file_offset = method_offset + instruction.offset + instruction.size - 4
            struct.pack_into("<I", data, operand_file_offset, new_token)
            patched_literals += 1
            method_changed = True
        if method_changed:
            modified_methods += 1

    metadata_offset = pe.get_offset_from_rva(pe.net.struct.MetaDataRva)
    old_metadata = bytes(data[metadata_offset : metadata_offset + pe.net.struct.MetaDataSize])
    prefix, streams = parse_metadata_root(old_metadata)
    streams["#US"] = bytes(us_heap)

    resources_blob = None
    if resource_overrides:
        table_stream = bytearray(streams["#~"])
        inline_resources = {str(resource.name): resource.data for resource in (pe.net.resources or [])}
        unknown = set(resource_overrides) - set(inline_resources)
        if unknown:
            raise ValueError(f"Resources not found in {source.name}: {sorted(unknown)}")
        rebuilt_resources = bytearray()
        table_file_offset = pe.net.metadata.streams[b"#~"].file_offset
        for resource_row in pe.net.mdtables.ManifestResource.rows:
            if resource_row.Implementation is not None:
                continue
            name = str(resource_row.Name)
            content = resource_overrides.get(name, inline_resources[name])
            new_offset = len(rebuilt_resources)
            rebuilt_resources.extend(struct.pack("<I", len(content)))
            rebuilt_resources.extend(content)
            rebuilt_resources.extend(b"\0" * (align(len(rebuilt_resources), 4) - len(rebuilt_resources)))
            row_offset = resource_row.struct.__file_offset__ - table_file_offset
            struct.pack_into("<I", table_stream, row_offset, new_offset)
        streams["#~"] = bytes(table_stream)
        resources_blob = bytes(rebuilt_resources)

    metadata = build_metadata_root(prefix, streams)

    pe_image = pefile.PE(data=bytes(data), fast_load=True)
    section_alignment = pe_image.OPTIONAL_HEADER.SectionAlignment
    file_alignment = pe_image.OPTIONAL_HEADER.FileAlignment
    section_table = pe_image.DOS_HEADER.e_lfanew + 4 + 20 + pe_image.FILE_HEADER.SizeOfOptionalHeader
    section_count = pe_image.FILE_HEADER.NumberOfSections
    first_raw = min((s.PointerToRawData for s in pe_image.sections if s.PointerToRawData), default=len(data))
    table_end = section_table + section_count * 40
    if table_end + 40 > first_raw:
        # Some AOT/large managed assemblies have no spare DOS-header padding.
        # Open the section table by shifting section raw data and updating its offsets.
        shift = align(table_end + 40 - first_raw, file_alignment)
        old_sections = list(pe_image.sections)
        data[first_raw:first_raw] = b"\0" * shift
        for index, section in enumerate(old_sections):
            header_offset = section_table + index * 40
            for field_offset in (20, 24, 28):
                pointer = struct.unpack_from("<I", data, header_offset + field_offset)[0]
                if pointer >= first_raw and pointer:
                    struct.pack_into("<I", data, header_offset + field_offset, pointer + shift)
        optional_offset = pe_image.OPTIONAL_HEADER.get_file_offset()
        security_directory = pe_image.OPTIONAL_HEADER.DATA_DIRECTORY[4]
        if security_directory.VirtualAddress >= first_raw and security_directory.VirtualAddress:
            struct.pack_into("<I", data, security_directory.get_file_offset(), security_directory.VirtualAddress + shift)
        coff = pe_image.FILE_HEADER
        if coff.PointerToSymbolTable >= first_raw and coff.PointerToSymbolTable:
            struct.pack_into("<I", data, coff.get_file_offset() + 8, coff.PointerToSymbolTable + shift)
        struct.pack_into("<I", data, optional_offset + 60, align(table_end + 40, file_alignment))
        pe_image = pefile.PE(data=bytes(data), fast_load=True)
        section_count = pe_image.FILE_HEADER.NumberOfSections
        section_table = pe_image.DOS_HEADER.e_lfanew + 4 + 20 + pe_image.FILE_HEADER.SizeOfOptionalHeader
        first_raw = min((s.PointerToRawData for s in pe_image.sections if s.PointerToRawData), default=len(data))
        if section_table + (section_count + 1) * 40 > first_raw:
            raise ValueError("Could not expand PE section table")

    virtual_end = max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe_image.sections)
    new_rva = align(virtual_end, section_alignment)
    payload = bytearray(metadata)
    resource_relative_offset = None
    if resources_blob is not None:
        resource_relative_offset = align(len(payload), 4)
        payload.extend(b"\0" * (resource_relative_offset - len(payload)))
        payload.extend(resources_blob)
    raw_pointer = align(len(data), file_alignment)
    raw_size = align(len(payload), file_alignment)
    if len(data) < raw_pointer:
        data.extend(b"\0" * (raw_pointer - len(data)))
    data.extend(payload)
    data.extend(b"\0" * (raw_size - len(payload)))

    header = bytearray(40)
    header[:8] = b".loc\0\0\0\0"
    struct.pack_into("<IIIIIIHHI", header, 8, len(payload), new_rva, raw_size, raw_pointer, 0, 0, 0, 0, 0x40000040)
    data[section_table + section_count * 40 : section_table + (section_count + 1) * 40] = header
    struct.pack_into("<H", data, pe_image.FILE_HEADER.get_file_offset() + 2, section_count + 1)
    optional_offset = pe_image.OPTIONAL_HEADER.get_file_offset()
    new_image_size = align(new_rva + len(payload), section_alignment)
    struct.pack_into("<I", data, optional_offset + 56, new_image_size)

    cli_offset = pe_image.get_offset_from_rva(pe_image.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
    struct.pack_into("<II", data, cli_offset + 8, new_rva, len(metadata))
    if resources_blob is not None and resource_relative_offset is not None:
        struct.pack_into("<II", data, cli_offset + 24, new_rva + resource_relative_offset, len(resources_blob))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return patched_literals, modified_methods


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resource", action="append", default=[], metavar="NAME=FILE", help="replace an embedded resource")
    args = parser.parse_args()
    resources = {}
    for pair in args.resource:
        if "=" not in pair:
            parser.error("--resource must be NAME=FILE")
        name, filename = pair.split("=", 1)
        resources[name] = Path(filename).read_bytes()
    count, methods = patch_assembly(args.assembly, args.catalog, args.output, resources or None)
    print(f"Patched {count} IL string references in {methods} methods -> {args.output}")


if __name__ == "__main__":
    main()

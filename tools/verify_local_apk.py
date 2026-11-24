#!/usr/bin/env python3
"""Structural QA for the separately packaged Russian APK and its source catalog."""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import zipfile
from pathlib import Path

import dnfile
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from build_local_apk import V2_ID, V2_MAGIC, content_digest
from patch_android_manifest import read_len8, read_len16
from translate_catalog_with_model import PROTECTED, is_translatable


def lp(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    size = struct.unpack_from("<I", data, offset)[0]
    end = offset + 4 + size
    if end > len(data):
        raise ValueError("Truncated APK Signature Scheme record")
    return data[offset + 4 : end], end


def string_pool_values(chunk: bytes) -> list[str]:
    _, header_size, size, count, style_count, flags, strings_start, styles_start = struct.unpack_from("<HHIIIIII", chunk)
    if size != len(chunk):
        raise ValueError("Bad string-pool size")
    offsets = struct.unpack_from(f"<{count}I", chunk, header_size) if count else []
    values = []
    for relative in offsets:
        offset = strings_start + relative
        if flags & 0x100:
            _, offset = read_len8(chunk, offset)
            byte_len, offset = read_len8(chunk, offset)
            values.append(chunk[offset : offset + byte_len].decode("utf-8"))
        else:
            length, offset = read_len16(chunk, offset)
            values.append(chunk[offset : offset + length * 2].decode("utf-16le"))
    return values


def verify_v2(apk: bytes) -> None:
    eocd = apk.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", apk, eocd + 16)[0]
    size = struct.unpack_from("<Q", apk, cd - 24)[0]
    block_len = size + 8
    start = cd - block_len
    if apk[cd - 16 : cd] != V2_MAGIC:
        raise ValueError("APK Signature Scheme block is missing")
    pair_offset = start + 8
    pair_size = struct.unpack_from("<Q", apk, pair_offset)[0]
    if struct.unpack_from("<I", apk, pair_offset + 8)[0] != V2_ID:
        raise ValueError("V2 signature ID is missing")
    value = apk[pair_offset + 12 : pair_offset + 8 + pair_size]
    signer_sequence, _ = lp(value)
    signer, _ = lp(signer_sequence)
    signed_data, offset = lp(signer)
    signatures, offset = lp(signer, offset)
    public_key, offset = lp(signer, offset)
    if offset != len(signer):
        raise ValueError("Unexpected bytes after V2 signer")
    digests, offset = lp(signed_data)
    certificates, offset = lp(signed_data, offset)
    _, offset = lp(signed_data, offset)
    if offset != len(signed_data):
        raise ValueError("Malformed V2 signed data")
    digest_record, _ = lp(digests)
    algorithm = struct.unpack_from("<I", digest_record)[0]
    digest, _ = lp(digest_record, 4)
    signature_record, _ = lp(signatures)
    sig_algorithm = struct.unpack_from("<I", signature_record)[0]
    signature, _ = lp(signature_record, 4)
    certificate, _ = lp(certificates)
    cert = x509.load_der_x509_certificate(certificate)
    original = bytearray(apk[:start] + apk[cd:])
    unblocked_eocd = original.rfind(b"PK\x05\x06")
    struct.pack_into("<I", original, unblocked_eocd + 16, cd - block_len)
    expected, _, _, _ = content_digest(bytes(original), block_len)
    if expected != digest:
        raise ValueError("APK V2 content digest mismatch")
    if algorithm != 0x0103 or sig_algorithm != algorithm:
        raise ValueError(f"Unexpected V2 signature algorithm {algorithm:#x}")
    key = cert.public_key()
    key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
    if key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != public_key:
        raise ValueError("V2 public key does not match signing certificate")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("catalog", type=Path)
    args = parser.parse_args()
    with args.apk.open("rb") as handle:
        apk = handle.read()
    verify_v2(apk)
    with zipfile.ZipFile(args.apk) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"ZIP CRC failed for {corrupt}")
        names = set(archive.namelist())
        manifest = archive.read("AndroidManifest.xml")
        pool = string_pool_values(manifest[8 : 8 + struct.unpack_from("<I", manifest, 12)[0]])
        if "com.ascensionsandbox.game.ru" not in pool:
            raise ValueError("APK package ID is not the side-by-side Russian ID")
        if not {"assets/.godot/mono/publish/arm64/Cultivation.Sim.dll", "assets/.godot/mono/publish/arm64/SandboxCultivation.dll", "lib/arm64-v8a/libgodot_android.so"}.issubset(names):
            raise ValueError("APK is missing required Godot/Mono payload files")
        for filename in ("Cultivation.Sim.dll", "SandboxCultivation.dll"):
            path = f"assets/.godot/mono/publish/arm64/{filename}"
            managed = dnfile.dnPE(data=archive.read(path))
            if not managed.net or not managed.net.resources:
                raise ValueError(f"Invalid managed assembly in APK: {filename}")
        sim = dnfile.dnPE(data=archive.read("assets/.godot/mono/publish/arm64/Cultivation.Sim.dll"))
        for resource in sim.net.resources or []:
            name = str(resource.name)
            if name.endswith(".json"):
                raw = resource.data.decode("utf-8")
                data = json.loads(raw[raw.index("[") :])
                for item in data:
                    for key, value in item.items():
                        if key in {"name", "description", "attackName", "verb"} and isinstance(value, str) and re.search(r"[A-Za-z]", value):
                            raise ValueError(f"English remains in {name} {key}: {value[:120]}")
        arsc = archive.read("resources.arsc")
        _, _, table_size = struct.unpack_from("<HHI", arsc)
        position = 12
        app_names = []
        while position < table_size:
            chunk_type, _, chunk_size = struct.unpack_from("<HHI", arsc, position)
            if chunk_type == 1:
                app_names.extend(string_pool_values(arsc[position : position + chunk_size]))
            position += chunk_size
        if "Ascension Sandbox" in app_names or "Песочница Вознесения" not in app_names:
            raise ValueError("Android launcher name was not localized")

    with args.catalog.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    empty = [row for row in rows if not row["russian"].strip()]
    remaining = [row for row in empty if is_translatable(row["english"])]
    if remaining:
        raise ValueError(f"{len(remaining)} empty catalog rows still look translatable: {remaining[:3]}")
    mismatch = []
    for row in rows:
        if not row["russian"].strip():
            continue
        source_markers = [match.group(0) for match in PROTECTED.finditer(row["english"])]
        translated_markers = [match.group(0) for match in PROTECTED.finditer(row["russian"])]
        if source_markers != translated_markers:
            mismatch.append(row)
    if mismatch:
        raise ValueError(f"Formatting placeholder mismatch in {len(mismatch)} catalog rows")
    print(f"Verified {args.apk} ({len(apk):,} bytes): valid ZIP, v2 signature, separate package, managed resources, Russian data, and {len(rows)-len(empty)}/{len(rows)} translated catalog rows; {len(empty)} technical fragments excluded")


if __name__ == "__main__":
    main()

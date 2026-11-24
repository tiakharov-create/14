#!/usr/bin/env python3
"""Patch the extracted Godot/Mono APK payload and create a separately installable signed APK."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from patch_android_manifest import patch_manifest, replace_pool
from patch_dotnet_strings import patch_assembly

V2_ID = 0x7109871A
V2_MAGIC = b"APK Sig Block 42"
RSA_PKCS1_SHA256 = 0x0103


def lp(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def v2_signer_value(digest: bytes, certificate: bytes, public_key: bytes, private_key) -> bytes:
    digest_record = struct.pack("<I", RSA_PKCS1_SHA256) + lp(digest)
    signed_data = lp(lp(digest_record)) + lp(lp(certificate)) + lp(b"")
    signature = private_key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    signature_record = struct.pack("<I", RSA_PKCS1_SHA256) + lp(signature)
    signer = lp(signed_data) + lp(lp(signature_record)) + lp(public_key)
    return lp(lp(signer))


def make_signing_block(value: bytes) -> bytes:
    pair = struct.pack("<Q", len(value) + 4) + struct.pack("<I", V2_ID) + value
    size = len(pair) + 24
    return struct.pack("<Q", size) + pair + struct.pack("<Q", size) + V2_MAGIC


def content_digest(apk: bytes, block_size: int) -> tuple[bytes, int, int, int]:
    eocd = apk.rfind(b"PK\x05\x06")
    if eocd < 0 or len(apk) - eocd < 22:
        raise ValueError("Missing ZIP end-of-central-directory record")
    comment_len = struct.unpack_from("<H", apk, eocd + 20)[0]
    if eocd + 22 + comment_len != len(apk):
        raise ValueError("Unsupported trailing ZIP data")
    central_offset = struct.unpack_from("<I", apk, eocd + 16)[0]
    if central_offset >= 0xFFFFFFFF:
        raise ValueError("ZIP64 APK signing is not supported")
    patched_eocd = bytearray(apk[eocd:])
    # The digest covers the APK with the signing block omitted, so the EOCD
    # points at the original central-directory offset (the block start).
    struct.pack_into("<I", patched_eocd, 16, central_offset)
    sections = [apk[:central_offset], apk[central_offset:eocd], bytes(patched_eocd)]
    chunk_hashes = []
    for section in sections:
        for offset in range(0, len(section), 1024 * 1024):
            chunk = section[offset : offset + 1024 * 1024]
            chunk_hashes.append(hashlib.sha256(b"\xA5" + struct.pack("<I", len(chunk)) + chunk).digest())
    final = hashlib.sha256(b"\x5A" + struct.pack("<I", len(chunk_hashes)) + b"".join(chunk_hashes)).digest()
    return final, central_offset, eocd, comment_len


def sign_v2(apk: bytes, private_key, certificate: bytes, public_key: bytes) -> bytes:
    placeholder = v2_signer_value(b"\0" * 32, certificate, public_key, private_key)
    block_size = len(make_signing_block(placeholder))
    digest, central_offset, eocd, comment_len = content_digest(apk, block_size)
    value = v2_signer_value(digest, certificate, public_key, private_key)
    signing_block = make_signing_block(value)
    if len(signing_block) != block_size:
        raise ValueError("V2 block size changed after digest generation")
    updated_eocd = bytearray(apk[eocd:])
    struct.pack_into("<I", updated_eocd, 16, central_offset + len(signing_block))
    signed_apk = apk[:central_offset] + signing_block + apk[central_offset:eocd] + bytes(updated_eocd)
    return signed_apk


def patch_resource_table(source: Path, destination: Path) -> int:
    data = source.read_bytes()
    kind, header_size, total_size = struct.unpack_from("<HHI", data, 0)
    if kind != 2 or total_size != len(data):
        raise ValueError("Malformed resources.arsc table")
    output = bytearray(data[:header_size])
    cursor = header_size
    changed = 0
    while cursor < len(data):
        chunk_type, chunk_header, chunk_size = struct.unpack_from("<HHI", data, cursor)
        chunk = data[cursor : cursor + chunk_size]
        if chunk_type == 1:
            chunk, count = replace_pool(chunk, {"Ascension Sandbox": "Песочница Вознесения"})
            changed += count
        output.extend(chunk)
        cursor += chunk_size
    struct.pack_into("<I", output, 4, len(output))
    destination.write_bytes(output)
    return changed


def make_identity():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ascension Sandbox Russian personal build")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    pub_der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, cert_der, pub_der


def add_zip_tree(zf: zipfile.ZipFile, source: Path, arc_prefix: str = "") -> None:
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        name = f"{arc_prefix}{path.relative_to(source).as_posix()}"
        if name.startswith("META-INF/") and name.upper().endswith((".RSA", ".DSA", ".EC", ".SF", "MANIFEST.MF")):
            continue
        compression = zipfile.ZIP_STORED if name.endswith((".so", ".arsc")) else zipfile.ZIP_DEFLATED
        zf.write(path, name, compress_type=compression, compresslevel=6 if compression == zipfile.ZIP_DEFLATED else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_dir", type=Path, help="directory containing extracted Android APK files")
    parser.add_argument("assets_dir", type=Path, help="extracted Godot assets/ directory")
    parser.add_argument("native_dir", type=Path, help="directory containing libgodot_android.so")
    parser.add_argument("catalog", type=Path)
    parser.add_argument("translated_resources", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--package", default="com.ascensionsandbox.game.ru")
    args = parser.parse_args()

    arm64_assets = args.assets_dir / ".godot/mono/publish/arm64"
    with tempfile.TemporaryDirectory(prefix="ascension-ru-apk-") as temp:
        work = Path(temp)
        patched_assets = work / "assets"
        shutil.copytree(args.assets_dir, patched_assets)
        sim_source = arm64_assets / "Cultivation.Sim.dll"
        game_source = arm64_assets / "SandboxCultivation.dll"

        resource_overrides = {}
        for filename in ("Cultivation.Sim.Data.beasts.json", "Cultivation.Sim.Data.materials.json", "Cultivation.Sim.Data.physiques.json"):
            original = (Path("localization/source_resources/Cultivation.Sim") / filename).read_bytes()
            translated = (args.translated_resources / "Cultivation.Sim" / filename).read_bytes()
            # Restore the two explanatory comment lines preceding the beasts array.
            if filename.endswith("beasts.json"):
                prefix = original[: original.index(b"[")]
                translated = prefix + translated[translated.index(b"[") :]
            resource_overrides[filename] = translated
        sim_output = work / "Cultivation.Sim.dll"
        patch_assembly(sim_source, args.catalog, sim_output, resource_overrides)
        game_output = work / "SandboxCultivation.dll"
        patch_assembly(game_source, args.catalog, game_output, {"CHANGELOG.md": (args.translated_resources / "SandboxCultivation/CHANGELOG.md").read_bytes()})
        shutil.copy2(sim_output, patched_assets / ".godot/mono/publish/arm64/Cultivation.Sim.dll")
        shutil.copy2(game_output, patched_assets / ".godot/mono/publish/arm64/SandboxCultivation.dll")

        staging = work / "apk"
        staging.mkdir()
        for child in args.base_dir.iterdir():
            if child.name in {"assets.rar", "Сжать.rar", "localization", "tools", ".git"}:
                continue
            target = staging / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            elif child.name != "AndroidManifest.xml":
                shutil.copy2(child, target)
        patch_manifest(args.base_dir / "AndroidManifest.xml", staging / "AndroidManifest.xml", args.package)
        app_names = patch_resource_table(args.base_dir / "resources.arsc", staging / "resources.arsc")
        print(f"Localized {app_names} Android launcher-name variants")
        shutil.copytree(patched_assets, staging / "assets")
        native = args.native_dir / "libgodot_android.so"
        lib_dir = staging / "lib/arm64-v8a"
        lib_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native, lib_dir / native.name)

        raw_apk = work / "unsigned.apk"
        with zipfile.ZipFile(raw_apk, "w", allowZip64=False) as zf:
            add_zip_tree(zf, staging)
        key, certificate, public_key = make_identity()
        signed = sign_v2(raw_apk.read_bytes(), key, certificate, public_key)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(signed)
        print(f"Built {args.output} ({len(signed):,} bytes), package {args.package}, APK Signature Scheme v2")
        print("A new personal signing key was generated for this build; future updates must use that same key or reinstall after uninstalling this copy.")


if __name__ == "__main__":
    main()

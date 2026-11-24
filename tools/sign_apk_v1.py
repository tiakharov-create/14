#!/usr/bin/env python3
"""Re-sign an APK with the JAR/v1 scheme for older Android package installers.

This deliberately drops any existing APK Signing Block and stale META-INF
signatures, then produces a fresh SHA-256 JAR signature.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID


def wrap_attribute(name: str, value: str) -> bytes:
    raw = f"{name}: {value}".encode("utf-8")
    lines = []
    while len(raw) > 72:
        cut = 72
        while cut and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        if not cut:
            raise ValueError("Unable to wrap JAR manifest attribute")
        lines.append(raw[:cut] + b"\r\n")
        raw = b" " + raw[cut:]
    lines.append(raw + b"\r\n")
    return b"".join(lines)


def make_identity():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ascension Sandbox Russian personal build")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    key, cert = make_identity()
    output_entries = []
    manifest_sections = []
    with zipfile.ZipFile(args.source, "r") as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            upper = info.filename.upper()
            if upper.startswith("META-INF/") and upper.endswith((".RSA", ".DSA", ".EC", ".SF", "MANIFEST.MF")):
                continue
            content = source.read(info.filename)
            output_entries.append((info.filename, info.compress_type, content, info.date_time, info.external_attr))
            digest = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
            section = wrap_attribute("Name", info.filename) + wrap_attribute("SHA-256-Digest", digest) + b"\r\n"
            manifest_sections.append((info.filename, section))

    manifest = wrap_attribute("Manifest-Version", "1.0") + wrap_attribute("Created-By", "Arena personal APK build") + b"\r\n" + b"".join(section for _, section in manifest_sections)
    sf = wrap_attribute("Signature-Version", "1.0") + wrap_attribute("Created-By", "Arena personal APK build")
    sf += wrap_attribute("SHA-256-Digest-Manifest", base64.b64encode(hashlib.sha256(manifest).digest()).decode("ascii")) + b"\r\n"
    # Per-entry digests make verification independent of manifest main-section behavior.
    for filename, section in manifest_sections:
        sf += wrap_attribute("Name", filename) + wrap_attribute("SHA-256-Digest", base64.b64encode(hashlib.sha256(section).digest()).decode("ascii")) + b"\r\n"
    sf_signature = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(sf)
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary])
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", allowZip64=False) as output:
        for filename, method, content, date_time, external_attr in output_entries:
            info = zipfile.ZipInfo(filename, date_time=date_time)
            info.compress_type = method
            info.external_attr = external_attr
            output.writestr(info, content, compress_type=method, compresslevel=6 if method == zipfile.ZIP_DEFLATED else None)
        output.writestr("META-INF/MANIFEST.MF", manifest, compress_type=zipfile.ZIP_STORED)
        output.writestr("META-INF/RUSSIAN.SF", sf, compress_type=zipfile.ZIP_STORED)
        output.writestr("META-INF/RUSSIAN.RSA", sf_signature, compress_type=zipfile.ZIP_STORED)
    print(f"Created v1-signed APK: {args.output} ({args.output.stat().st_size:,} bytes)")
    print("A new private signing key was generated and is not stored; later updates require uninstalling this copy first.")


if __name__ == "__main__":
    main()

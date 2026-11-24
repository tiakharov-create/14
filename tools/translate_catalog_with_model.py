#!/usr/bin/env python3
"""Machine-translate player-facing .NET literals with a local Bergamot model.

Existing Russian entries are never overwritten. Rich-text tags, paths,
placeholders and line breaks are kept byte-for-byte and translated text is
split into manageable runs between them.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path


PROTECTED = re.compile(
    r"\[[^\]\r\n]*\]"          # Godot BBCode tags
    r"|\{[^{}\r\n]*\}"        # format/interpolation placeholders
    r"|\\[nrt]"                  # escaped control characters
    r"|%%|%(?:\d+\$)?[-+#0]*\d*(?:\.\d+)?[sdifFeEgGxXoc]"  # printf placeholders
    r"|(?:res|user)://[^\s\]\)]+"  # Godot paths
    r"|https?://[^\s\]\)]+"        # URLs
    r"|`[^`\r\n]+`"              # Markdown inline code
    r"|\r\n|\n|\r"             # literal paragraph breaks
)
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_./:-]*$")
CAMEL_IDENTIFIER = re.compile(r"^[a-z]+(?:[A-Z][A-Za-z0-9]*)+$")


def is_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped or not re.search(r"[A-Za-z]", stripped):
        return False
    visible_text = re.sub(r"\[[^\]]*\]", "", stripped)
    if not re.search(r"[A-Za-z]", visible_text):
        return False
    if stripped in {"(?<=[a-z])([A-Z])"}:
        return False
    if re.fullmatch(r"\[[^\]]*\]?", stripped):
        return False
    if stripped in {".NET Foundation", "Godot Engine contributors", "SIL OPEN FONT LICENSE"}:
        return False
    if stripped.startswith("--") or stripped.startswith("user://") or stripped.startswith("res://"):
        return False
    if IDENTIFIER.fullmatch(stripped) or CAMEL_IDENTIFIER.fullmatch(stripped):
        if stripped[0].isupper() and not any(c in stripped for c in "_./:-"):
            return True
        return False
    if re.fullmatch(r"[A-Z0-9_./:-]+", stripped):
        return False
    if stripped.startswith("\\") and not re.search(r"\s", stripped):
        return False
    return True


def split_long_text(text: str, limit: int = 360) -> list[str]:
    """Split only at whitespace, preferring sentence boundaries; preserve every character."""
    chunks = []
    while len(text) > limit:
        end = limit
        # Prefer the last sentence break in the first 360 characters.
        sentence_breaks = [m.end() for m in re.finditer(r"[.!?;][\"')\]]*\s+", text[:limit])]
        if sentence_breaks and sentence_breaks[-1] >= limit // 2:
            end = sentence_breaks[-1]
        else:
            candidates = [m.end() for m in re.finditer(r"\s+", text[:limit])]
            if candidates and candidates[-1] >= limit // 2:
                end = candidates[-1]
        chunks.append(text[:end])
        text = text[end:]
    if text:
        chunks.append(text)
    return chunks


def append_translatable_run(run: str, pieces: list[tuple], requests: list[dict]) -> None:
    if not run or not re.search(r"[A-Za-z]", run):
        pieces.append(("literal", run))
        return
    leading = run[: len(run) - len(run.lstrip())]
    core = run[len(leading) :]
    trailing = core[len(core.rstrip()) :]
    if trailing:
        core = core[: -len(trailing)]
    if not core:
        pieces.append(("literal", run))
        return
    if leading:
        pieces.append(("literal", leading))
    for chunk in split_long_text(core):
        left = chunk[: len(chunk) - len(chunk.lstrip())]
        inner = chunk[len(left) :]
        right = inner[len(inner.rstrip()) :]
        if right:
            inner = inner[: -len(right)]
        if inner and re.search(r"[A-Za-z]", inner):
            request_id = len(requests)
            requests.append({"id": request_id, "text": inner})
            pieces.append(("request", request_id, left, right))
        else:
            pieces.append(("literal", chunk))
    if trailing:
        pieces.append(("literal", trailing))


def make_pieces(source: str, requests: list[dict]) -> list[tuple]:
    pieces: list[tuple] = []
    cursor = 0
    for match in PROTECTED.finditer(source):
        append_translatable_run(source[cursor : match.start()], pieces, requests)
        pieces.append(("literal", match.group(0)))
        cursor = match.end()
    append_translatable_run(source[cursor:], pieces, requests)
    return pieces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--module", type=Path, required=True, help="@browsermt/bergamot-translator module directory")
    parser.add_argument("--model-dir", type=Path, required=True, help="directory with the three enru model files")
    parser.add_argument("--worker", type=Path, default=Path(__file__).with_name("bergamot_translate.mjs"))
    parser.add_argument("--limit", type=int, default=0, help="translate at most N new literals (for tests)")
    args = parser.parse_args()

    with args.catalog.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not {"english", "russian"}.issubset(fields):
        parser.error("catalog must have english and russian columns")

    cache: dict[str, str] = {row["english"]: row["russian"] for row in rows if row["russian"].strip()}
    requests: list[dict] = []
    row_plans: dict[int, list[tuple]] = {}
    for row_index, row in enumerate(rows):
        source = row["english"]
        if row["russian"].strip() or not is_translatable(source):
            continue
        if source in cache and cache[source]:
            row["russian"] = cache[source]
            continue
        pieces = make_pieces(source, requests)
        if any(piece[0] == "request" for piece in pieces):
            row_plans[row_index] = pieces
        if args.limit and len(row_plans) >= args.limit:
            break

    # Translate distinct runs once, then reuse exact duplicates across assemblies.
    text_to_request = {}
    deduped = []
    request_remap = {}
    for request in requests:
        text = request["text"]
        if text in text_to_request:
            request_remap[request["id"]] = text_to_request[text]
        else:
            new_id = len(deduped)
            text_to_request[text] = new_id
            request_remap[request["id"]] = new_id
            deduped.append({"id": new_id, "text": text})

    translations: dict[int, str] = {}
    if deduped:
        payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in deduped)
        process = subprocess.Popen(
            ["node", str(args.worker), str(args.module), str(args.model_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, encoding="utf-8",
        )
        output, _ = process.communicate(payload)
        if process.returncode:
            raise RuntimeError(f"Bergamot worker exited with code {process.returncode}")
        for line in output.splitlines():
            item = json.loads(line)
            if "error" not in item:
                translations[item["id"]] = item["text"]

    for row_index, pieces in row_plans.items():
        translated_parts = []
        complete = True
        for piece in pieces:
            if piece[0] == "literal":
                translated_parts.append(piece[1])
                continue
            _, old_id, leading, trailing = piece
            new_id = request_remap[old_id]
            if new_id not in translations:
                complete = False
                break
            translated_parts.append(leading + translations[new_id] + trailing)
        if complete:
            translated = "".join(translated_parts)
            rows[row_index]["russian"] = translated
            cache[rows[row_index]["english"]] = translated

    # Fill duplicate literals with a translation made for the first occurrence.
    for row in rows:
        if not row["russian"].strip() and row["english"] in cache and cache[row["english"]]:
            row["russian"] = cache[row["english"]]

    with args.catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    translated = sum(bool(row["russian"].strip()) for row in rows)
    print(f"Catalog translated: {translated}/{len(rows)} literals", file=sys.stderr)


if __name__ == "__main__":
    main()

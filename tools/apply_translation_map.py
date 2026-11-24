#!/usr/bin/env python3
"""Fill matching English strings in a localization catalog from a JSON map."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("translations", type=Path, help="JSON object: English string -> Russian string")
    parser.add_argument("--overwrite", action="store_true", help="replace existing Russian values")
    args = parser.parse_args()

    mapping = json.loads(args.translations.read_text(encoding="utf-8"))
    with args.catalog.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not {"english", "russian"}.issubset(fields):
        parser.error("catalog must have english and russian columns")

    changed = 0
    for row in rows:
        translation = mapping.get(row["english"])
        if translation and (args.overwrite or not row["russian"].strip()):
            row["russian"] = translation
            changed += 1
    with args.catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Filled {changed} catalog rows")


if __name__ == "__main__":
    main()

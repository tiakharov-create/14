#!/usr/bin/env python3
"""Translate player-facing embedded JSON resources and the in-game changelog.

The source files are extracted from the compiled game DLL. This script creates
Russian copies for embedding; enum IDs and simulation keys are deliberately not
translated.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
from pathlib import Path

DISPLAY_FIELDS = {"name", "description", "attackName", "verb"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--catalog", type=Path, required=True, help="existing C# string catalog for glossary reuse")
    parser.add_argument("--map", type=Path, required=True, help="manual English -> Russian JSON map")
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--worker", type=Path, default=Path(__file__).with_name("bergamot_translate.mjs"))
    parser.add_argument("--limit", type=int, default=0, help="test at most N resource strings")
    args = parser.parse_args()

    manual = json.loads(args.map.read_text(encoding="utf-8"))
    with args.catalog.open(encoding="utf-8-sig", newline="") as handle:
        prior = {row["english"]: row["russian"] for row in csv.DictReader(handle) if row["russian"].strip()}
    translation_cache = {**prior, **manual}

    json_jobs = []
    json_docs = []
    for source in sorted(args.source_dir.rglob("*.json")):
        raw = source.read_text(encoding="utf-8")
        # beasts.json has one explanatory comment before its JSON array.
        json_start = raw.find("[")
        if json_start < 0:
            raise ValueError(f"No JSON array in {source}")
        data = json.loads(raw[json_start:])
        json_docs.append((source, data))
        for obj_index, obj in enumerate(data):
            if not isinstance(obj, dict):
                continue
            for key in DISPLAY_FIELDS:
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    job_id = len(json_jobs)
                    json_jobs.append({"assembly": "embedded-resource", "string_token": f"0x{job_id:08X}", "english": value, "russian": translation_cache.get(value, "")})

    changelog_source = next(args.source_dir.rglob("CHANGELOG.md"), None)
    changelog_lines = None
    changelog_jobs = []
    if changelog_source:
        changelog_lines = changelog_source.read_text(encoding="utf-8").splitlines(keepends=True)
        for line_index, line in enumerate(changelog_lines):
            body = line.rstrip("\r\n")
            ending = line[len(body) :]
            prefix_match = re.match(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|>\s+|\d+[.)]\s+))", body)
            prefix = prefix_match.group(1) if prefix_match else ""
            content = body[len(prefix) :]
            job_id = len(json_jobs) + len(changelog_jobs)
            changelog_jobs.append({"assembly": "embedded-resource", "string_token": f"0x{job_id:08X}", "english": content, "russian": translation_cache.get(content, ""), "line": line_index, "prefix": prefix, "ending": ending})

    all_jobs = json_jobs + [{k: v for k, v in job.items() if k in {"assembly", "string_token", "english", "russian"}} for job in changelog_jobs]
    if args.limit:
        all_jobs = all_jobs[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="game-ru-catalog-") as temporary:
        catalog = Path(temporary) / "resources.csv"
        with catalog.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["assembly", "string_token", "english", "russian"])
            writer.writeheader()
            writer.writerows(all_jobs)
        subprocess.run([
            "python3", str(Path(__file__).with_name("translate_catalog_with_model.py")), str(catalog),
            "--module", str(args.module), "--model-dir", str(args.model_dir), "--worker", str(args.worker),
        ], check=True)
        with catalog.open(encoding="utf-8-sig", newline="") as handle:
            translations = {int(row["string_token"], 16): row["russian"] for row in csv.DictReader(handle)}

    cache_updates = {}
    for job in json_jobs:
        translated = translations.get(int(job["string_token"], 16), "")
        if translated:
            cache_updates[job["english"]] = translated
    if cache_updates:
        manual.update(cache_updates)
        args.map.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.limit:
        print(f"Test mode translated {sum(bool(v) for v in translations.values())}/{len(all_jobs)} embedded strings")
        return

    # Apply each JSON job against the exact resource and field traversal used above.
    job_id = 0
    for source, data in json_docs:
        for obj in data:
            if not isinstance(obj, dict):
                continue
            for key in DISPLAY_FIELDS:
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    translated = translations.get(job_id, "")
                    if translated:
                        obj[key] = translated
                    job_id += 1
        target = args.output_dir / source.relative_to(args.source_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if changelog_source and changelog_lines is not None:
        start = len(json_jobs)
        output_lines = []
        for job in changelog_jobs:
            translated = translations.get(start + job["line"], "")
            body = translated if translated else job["english"]
            output_lines.append(job["prefix"] + body + job["ending"])
        target = args.output_dir / changelog_source.relative_to(args.source_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(output_lines), encoding="utf-8")
    count = sum(bool(value) for value in translations.values())
    print(f"Translated {count} embedded strings; wrote Russian resources to {args.output_dir}")


if __name__ == "__main__":
    main()

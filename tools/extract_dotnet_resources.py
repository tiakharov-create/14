#!/usr/bin/env python3
"""Extract embedded managed resources (notably game data JSON) from .NET DLLs."""
from __future__ import annotations

import argparse
from pathlib import Path

import dnfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assemblies", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    written = 0
    for assembly in args.assemblies:
        if not assembly.is_file():
            parser.error(f"assembly not found: {assembly}")
        pe = dnfile.dnPE(str(assembly))
        for resource in pe.net.resources or []:
            name = str(resource.name)
            if not name or name in {"None", "."}:
                continue
            # Resource names in these assemblies are simple manifest names.
            filename = Path(name).name
            target = args.output_dir / assembly.stem / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resource.data)
            print(f"{assembly.name}: {name} -> {target}")
            written += 1
    print(f"Extracted {written} embedded resources to {args.output_dir}")


if __name__ == "__main__":
    main()

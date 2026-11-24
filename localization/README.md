# Russian localization and side-by-side Android build

This workspace contains a personal Russian-language APK assembled from the extracted Godot/Mono payload; no source project was available.

## Deliverables

- `source_strings.csv` — extracted .NET `#US` string catalog: 30,504 literals total; 26,211 player-facing candidates translated. The 4,293 remaining empty rows were checked and consist of markup fragments, formatting-only snippets, regexes, and technical identifiers rather than standalone prose.
- `translated_resources/` — Russian embedded game-data JSON and the in-game change log. Beast, material, and physique display fields are written back into `Cultivation.Sim.dll`.
- `ui-ru.json` — terminology map and hand-corrected high-priority terms.
- `Cultivation.Sim.ru.apk` — separate APK (`com.ascensionsandbox.game.ru`), with a Russian launcher name and v1/v2/v3 signing for Android/ColorOS compatibility. Native libraries are 4096-byte aligned.

## Build tools

Python dependencies are listed in `../tools/requirements.txt`. Building requires the original extracted Android files in the repository root, the extracted Godot `assets/` tree, and `libgodot_android.so` extracted from `Сжать.rar`. The local translation run additionally used the EN→RU Bergamot model and `@browsermt/bergamot-translator`.

```sh
python3 tools/build_local_apk.py . /path/to/extracted/assets /path/to/extracted/native \
  localization/source_strings.csv localization/translated_resources \
  localization/Cultivation.Sim.ru.apk
python3 tools/verify_local_apk.py localization/Cultivation.Sim.ru.apk localization/source_strings.csv
```

`build_local_apk.py` creates a v2-signed intermediate; the distributable is additionally aligned and signed with v1/v2/v3. Each final build uses a fresh personal signing key. Android allows it to sit beside the original because the package ID and FileProvider authority are changed. A later update must use the same key; because the private key is intentionally not stored in the repository, reinstalling a later build requires uninstalling the prior Russian copy first.

## Translation and validation notes

- BBCode, Godot paths, placeholders, and line breaks are preserved in the literal catalog. Empty technical fragments are intentionally left untouched.
- Embedded JSON resource keys and simulation IDs are preserved; player-facing labels are localized, but enum/schema values such as `element` and `kind` remain unchanged because the game parses them as identifiers.
- The APK ZIP, binary manifest, managed DLL/resource tables, side-by-side package ID, V2 signature, and native-library alignment were structurally verified. The updated embedded enum values now match the original resource data. Runtime launch is not covered by these checks and still needs testing on the target device. Russian copy is machine-translated with targeted terminology corrections and still merits in-game proofreading, especially the long change log and compact UI labels.

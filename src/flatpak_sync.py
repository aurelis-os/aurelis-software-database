#!/usr/bin/env python3
"""Merge Flathub fields and icon into existing app files.

Flat merge of Flathub fields only. Never touch curated or generated fields.
Icons go to data/icons/.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# Import shared helpers
sys.path.insert(0, str(Path(__file__).parent))
from common import (
    normalize_description,
    normalize_keywords,
    normalize_categories,
    normalize_screenshots,
    write_json,
)

# Fields owned by Flathub (flatpak_sync)
FLATHUB_FIELDS = {
    "name", "summary", "description", "developer", "license",
    "categories", "keywords", "urls", "screenshots"
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_flathub_data(data: dict) -> dict:
    """Apply normalizers to Flathub-owned fields."""
    result = data.copy()
    if "description" in result:
        result["description"] = normalize_description(result["description"])
    if "keywords" in result:
        result["keywords"] = normalize_keywords(result["keywords"])
    if "categories" in result:
        result["categories"] = normalize_categories(result["categories"])
    if "screenshots" in result:
        result["screenshots"] = normalize_screenshots(result["screenshots"])
    return result


def is_empty_value(value):
    """Check if a value is considered empty (null, [], {}, '')."""
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mine", required=True, help="folder with my JSON files (one per app id)")
    ap.add_argument("--flatpak", default="data/all", help="folder made by flatpak_xml_to_json.py")
    ap.add_argument("--icons-dir", default="data/icons", help="destination folder for icons")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mine_dir = Path(args.mine)
    fp_dir = Path(args.flatpak)
    icons_dir = Path(args.icons_dir)
    icons_dir.mkdir(parents=True, exist_ok=True)

    updated = unchanged = missing = 0

    for mine_path in sorted(mine_dir.glob("*.json")):
        app_id = mine_path.stem
        fp_path = fp_dir / f"{app_id}.json"

        if not fp_path.is_file():
            print(f"  MISSING in Flatpak export: {app_id}", file=sys.stderr)
            missing += 1
            continue

        mine = load_json(mine_path)
        fresh = load_json(fp_path)

        # Normalize fresh Flathub data before comparing
        fresh = normalize_flathub_data(fresh)

        # Build the merged data: start with mine, update only Flathub fields
        # but don't overwrite with empty values
        merged = mine.copy()
        changed_fields = []

        for field in FLATHUB_FIELDS:
            fresh_value = fresh.get(field)
            if is_empty_value(fresh_value):
                # Don't overwrite with empty Flathub value
                continue
            old_value = merged.get(field)
            if old_value != fresh_value:
                merged[field] = fresh_value
                changed_fields.append(field)

        # Handle icon
        icon_changed = False
        # Always use the local icon file copied by flatpak_xml_to_json.py
        icon_name = f"{app_id}.png"
        src_icon = fp_dir / icon_name
        dst_icon = icons_dir / icon_name
        if src_icon.is_file():
            if not dst_icon.exists() or src_icon.read_bytes() != dst_icon.read_bytes():
                if not args.dry_run:
                    shutil.copyfile(src_icon, dst_icon)
                icon_changed = True
            # Always set the icon field to the cached name
            merged["icon"] = {"type": "cached", "name": icon_name}
        else:
            # Keep existing icon if no new one
            if "icon" not in merged:
                merged["icon"] = {"type": "cached", "name": icon_name}

        if not changed_fields and not icon_changed:
            unchanged += 1
            continue

        print(f"  {app_id}: {', '.join(changed_fields)}" + (" +icon" if icon_changed else ""))
        updated += 1

        if args.dry_run:
            continue

        write_json(mine_path, merged)

    print(
        f"Done: {updated} updated, {unchanged} unchanged, {missing} missing"
        + (" (dry run)" if args.dry_run else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
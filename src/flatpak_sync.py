#!/usr/bin/env python3
"""Update the `flathub` block of my app JSONs from the fresh Flatpak Info export.

Only files in --mine are touched. The `local` block (github_repo, version, ...)
is never modified. A file is rewritten only if something really changed.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def diff_keys(old, new):
    """Return the names of top-level fields that differ between two dicts."""
    keys = set(old) | set(new)
    return sorted(k for k in keys if old.get(k) != new.get(k))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mine", required=True, help="folder with my JSON files (one per app id)")
    ap.add_argument("--flatpak", default="Flatpak Info", help="folder made by flatpak_xml_to_json.py")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mine_dir = Path(args.mine)
    fp_dir = Path(args.flatpak)

    updated = unchanged = missing = 0

    for mine_path in sorted(mine_dir.glob("*.json")):
        app_id = mine_path.stem
        fp_path = fp_dir / f"{app_id}.json"

        if not fp_path.is_file():
            print(f"  MISSING in Flatpak Info: {app_id}", file=sys.stderr)
            missing += 1
            continue

        mine = load(mine_path)
        fresh = load(fp_path).get("flathub", {})
        old = mine.get("flathub", {})

        changed = diff_keys(old, fresh)
        if not changed:
            unchanged += 1
            continue

        print(f"  {app_id}: {', '.join(changed)}")
        updated += 1
        if args.dry_run:
            continue

        mine["flathub"] = fresh
        mine_path.write_text(
            json.dumps(mine, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        # refresh the icon only if its content really differs
        src_icon = fp_dir / f"{app_id}.png"
        dst_icon = mine_dir / f"{app_id}.png"
        if src_icon.is_file() and (not dst_icon.exists() or src_icon.read_bytes() != dst_icon.read_bytes()):
            shutil.copyfile(src_icon, dst_icon)

    print(
        f"Done: {updated} updated, {unchanged} unchanged, {missing} missing"
        + (" (dry run)" if args.dry_run else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
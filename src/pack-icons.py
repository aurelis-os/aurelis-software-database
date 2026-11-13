#!/usr/bin/env python3
"""Pack all icons in data/icons to output app-icons.tar.gz"""

import argparse
import json
import sys
from pathlib import Path

from common import create_reproducible_tar_gz, get_source_date_epoch, load_json


def main():
    parser = argparse.ArgumentParser(description="Pack icons into reproducible archive")
    parser.add_argument("--icons", default="data/icons", help="Icons directory")
    parser.add_argument("--apps", default="data/apps", help="Apps directory (for reference check)")
    parser.add_argument("--out", default="data/output", help="Output directory")
    args = parser.parse_args()

    icons_dir = Path(args.icons)
    apps_dir = Path(args.apps)
    output_dir = Path(args.out)

    if not icons_dir.exists():
        print(f"Error: icons directory not found: {icons_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all icon files
    icon_files = sorted(icons_dir.glob("*.png"))

    # Check which icons are referenced by apps
    referenced_icons = set()
    if apps_dir.exists():
        for json_file in apps_dir.glob("*.json"):
            try:
                app = load_json(json_file)
                icon = app.get("icon", {})
                if icon.get("name"):
                    referenced_icons.add(icon["name"])
            except (OSError, json.JSONDecodeError):
                pass

    # Warn about unreferenced icons
    for icon_file in icon_files:
        if icon_file.name not in referenced_icons:
            print(f"Warning: icon not referenced by any app: {icon_file.name}", file=sys.stderr)

    # Create reproducible tar.gz
    tar_path = output_dir / "app-icons.tar.gz"
    epoch = get_source_date_epoch()
    mtime = epoch if epoch is not None else 0

    files = [(icon_file, icon_file.name) for icon_file in icon_files]
    create_reproducible_tar_gz(tar_path, files, mtime)

    print(f"Created archive with {len(icon_files)} icons: {tar_path}")


if __name__ == "__main__":
    main()
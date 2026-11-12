#!/usr/bin/env python3
"""
Check if app icons exist in data/icons directory.
"""

import json
import sys
from pathlib import Path

# Color codes
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def main():
    apps_dir = Path("data/apps")
    icons_dir = Path("data/icons")

    if not apps_dir.exists():
        print(f"Error: {apps_dir} does not exist")
        sys.exit(1)

    if not icons_dir.exists():
        print(f"Error: {icons_dir} does not exist")
        sys.exit(1)

    # Get all icon files in data/icons
    icon_files = {f.name for f in icons_dir.iterdir() if f.is_file()}

    json_files = sorted(apps_dir.glob("*.json"))

    if not json_files:
        print("No JSON files found in data/apps")
        sys.exit(0)

    ok_count = 0
    fail_count = 0

    for json_file in json_files:
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing {json_file.name}: {e}")
            continue

        icon_info = data.get("icon")
        if not icon_info:
            continue

        icon_name = icon_info.get("name")
        if not icon_name:
            continue

        app_id = data.get("id", json_file.stem)

        if icon_name in icon_files:
            status = f"{GREEN}[OK]{RESET}"
            ok_count += 1
        else:
            status = f"{RED}[FAIL]{RESET}"
            fail_count += 1

        print(f"{app_id} -> {icon_name} {status}")

    print()
    print(f"{BOLD}Summary:{RESET} {GREEN}{ok_count} OK{RESET}, {RED}{fail_count} FAIL{RESET}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
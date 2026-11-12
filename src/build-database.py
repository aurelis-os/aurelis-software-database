#!/usr/bin/env python3
"""Build a combined JSON database from individual app JSON files and create a tar.gz archive."""

import json
import tarfile
from pathlib import Path


def main():
    apps_dir = Path("data/apps")
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = output_dir / "apps.db"
    tar_path = output_dir / "apps.db.tar.gz"

    # Collect all app JSON files
    apps = []
    for json_file in sorted(apps_dir.glob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            app_data = json.load(f)
            apps.append(app_data)

    # Write combined database
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Created database with {len(apps)} apps: {db_path}")

    # Create tar.gz archive
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(db_path, arcname="apps.db")

    print(f"Created archive: {tar_path}")


if __name__ == "__main__":
    main()
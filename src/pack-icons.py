#!/usr/bin/env python3
"""Pack all icons in data/icons to output app-icons.tar.gz"""

import tarfile
from pathlib import Path


def main():
    icons_dir = Path("data/icons")
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    tar_path = output_dir / "app-icons.tar.gz"

    # Create compressed tar.gz archive
    with tarfile.open(tar_path, "w:gz") as tar:
        for icon_file in sorted(icons_dir.glob("*")):
            if icon_file.is_file():
                tar.add(icon_file, arcname=icon_file.name)

    print(f"Created archive with {len(list(icons_dir.glob('*')))} icons: {tar_path}")


if __name__ == "__main__":
    main()
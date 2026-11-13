#!/usr/bin/env python3
"""
Add a new app to the Aurelis software database.

Usage:
    src/add-app.py <flathub-id> --repo owner/name --suffix <asset_suffix> --version-regex '<regex>' [--title-version-regex ...]

Steps:
1. Create data/apps/<id>.json with curated fields only
2. Merge Flathub fields from data/all/<id>.json using flatpak_sync logic
3. Copy icon to data/icons/
4. Run fetch for that id only (get_latest_appimages.py)
5. Run validation for that file and print entry summary
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Import shared helpers
sys.path.insert(0, str(Path(__file__).parent))
from common import (
    normalize_categories,
    normalize_description,
    normalize_keywords,
    normalize_screenshots,
    write_json,
)

# Fields owned by Flathub (flatpak_sync)
FLATHUB_FIELDS = {
    "name", "summary", "description", "developer", "license",
    "categories", "keywords", "urls", "screenshots"
}


def load_json(path: Path) -> dict:
    """Load JSON from a file."""
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


def is_empty_value(value) -> bool:
    """Check if a value is considered empty (null, [], {}, '')."""
    if value is None:
        return True
    return isinstance(value, (list, dict, str)) and len(value) == 0


def merge_flathub_fields(mine: dict, fresh: dict) -> tuple[dict, list[str]]:
    """Merge Flathub fields into mine, returning merged dict and list of changed fields."""
    fresh = normalize_flathub_data(fresh)
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

    return merged, changed_fields


def copy_icon(app_id: str, flatpak_dir: Path, icons_dir: Path) -> bool:
    """Copy icon from flatpak export to icons directory. Returns True if copied."""
    icon_name = f"{app_id}.png"
    src_icon = flatpak_dir / icon_name
    dst_icon = icons_dir / icon_name

    if src_icon.is_file() and (not dst_icon.exists() or src_icon.read_bytes() != dst_icon.read_bytes()):
        shutil.copyfile(src_icon, dst_icon)
        return True
    return False


def run_get_latest_appimages(app_id: str, apps_dir: Path, dry_run: bool = False) -> tuple[bool, str | None]:
    """Run get_latest_appimages.py for a single app. Returns (success, error_message)."""
    cmd = [
        sys.executable,
        "src/get_latest_appimages.py",
        app_id,
        "--apps-dir", str(apps_dir),
    ]
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=Path(__file__).parent.parent)
    if result.returncode == 0:
        return True, None
    else:
        return False, result.stderr.strip() or result.stdout.strip()


def run_validation(app_id: str, apps_dir: Path, icons_dir: Path) -> tuple[bool, list[str]]:
    """Run build-database.py --check for a single app. Returns (success, errors)."""
    # We'll validate just this one app by temporarily running the validation logic
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_database", Path(__file__).parent / "build-database.py")
    build_database = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_database)
    validate_app = build_database.validate_app
    load_json = build_database.load_json
    normalize_app = build_database.normalize_app

    app_path = apps_dir / f"{app_id}.json"
    if not app_path.exists():
        return False, [f"App file not found: {app_path}"]

    try:
        app = load_json(app_path)
    except json.JSONDecodeError as e:
        return False, [f"JSON parse error: {e}"]

    # Check id matches filename stem
    expected_id = app_path.stem
    actual_id = app.get("id")
    if actual_id != expected_id:
        return False, [f"id '{actual_id}' does not match filename stem '{expected_id}'"]

    seen_ids = set()
    errors = validate_app(app, apps_dir, icons_dir, seen_ids)

    # Also normalize to check for any issues
    try:
        normalize_app(app)
    except (ValueError, TypeError, KeyError) as e:
        errors.append(f"Normalization error: {e}")

    return len(errors) == 0, errors


def print_summary(app: dict) -> None:
    """Print a summary of the app entry."""
    print("\n" + "=" * 60)
    print(f"App Summary: {app.get('id')}")
    print("=" * 60)
    print(f"  Name: {app.get('name')}")
    print(f"  Repo: {app.get('repo')}")
    print(f"  Asset suffix: {app.get('asset_suffix')}")
    print(f"  Version regex: {app.get('version_regex')}")
    if app.get("title_version_regex"):
        print(f"  Title version regex: {app.get('title_version_regex')}")

    # Generated fields
    if app.get("version"):
        print("\n  Generated fields:")
        print(f"    Version: {app.get('version')}")
        print(f"    Download URL: {app.get('download_url')}")
        print(f"    Asset name: {app.get('asset_name')}")
        print(f"    Size: {app.get('size')} bytes")
        print(f"    SHA256: {app.get('sha256')}")
        print(f"    ZSync URL: {app.get('zsync_url')}")
        print(f"    Arch: {app.get('arch')}")
        print(f"    Published at: {app.get('published_at')}")
        print(f"    Version changed at: {app.get('version_changed_at')}")

    # Flathub fields
    flathub_present = [f for f in FLATHUB_FIELDS if app.get(f)]
    if flathub_present:
        print(f"\n  Flathub fields: {', '.join(flathub_present)}")

    # Icon
    icon = app.get("icon", {})
    if icon.get("name"):
        print(f"  Icon: {icon['name']}")

    # Screenshots
    screenshots = app.get("screenshots", [])
    if screenshots:
        print(f"  Screenshots: {len(screenshots)} (default: {next((i for i, s in enumerate(screenshots) if s.get('default')), 'none')})")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Add a new app to the Aurelis software database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  src/add-app.py org.kde.kate --repo pkgforge-dev/Kate-AppImage-Enhanced \\
    --suffix "-anylinux-x86_64.AppImage" --version-regex "([0-9.]+-[0-9]+)@"

  src/add-app.py com.jetbrains.PhpStorm --repo pkgforge-dev/PhpStorm-AppImage \\
    --suffix "-anylinux-x86_64.AppImage" --version-regex "latest" \\
    --title-version-regex "PhpStorm ([0-9.]+)"
        """
    )
    parser.add_argument("flathub_id", help="Flathub app ID (e.g., org.kde.kate)")
    parser.add_argument("--repo", required=True, help="GitHub repo in format 'owner/name'")
    parser.add_argument("--suffix", required=True, help="AppImage asset suffix (e.g., '-anylinux-x86_64.AppImage')")
    parser.add_argument("--version-regex", required=True, help="Regex to extract version from release tag")
    parser.add_argument("--title-version-regex", help="Fallback regex to extract version from release title")
    parser.add_argument("--apps-dir", default="data/apps", help="Apps directory (default: data/apps)")
    parser.add_argument("--flatpak-dir", default="data/all", help="Flatpak export directory (default: data/all)")
    parser.add_argument("--icons-dir", default="data/icons", help="Icons directory (default: data/icons)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetching latest release")
    parser.add_argument("--skip-validation", action="store_true", help="Skip validation")

    args = parser.parse_args()

    app_id = args.flathub_id
    apps_dir = Path(args.apps_dir)
    flatpak_dir = Path(args.flatpak_dir)
    icons_dir = Path(args.icons_dir)

    # Validate directories
    if not apps_dir.exists():
        print(f"Error: apps directory not found: {apps_dir}", file=sys.stderr)
        sys.exit(1)

    if not flatpak_dir.exists():
        print(f"Error: flatpak directory not found: {flatpak_dir}", file=sys.stderr)
        sys.exit(1)

    icons_dir.mkdir(parents=True, exist_ok=True)

    # Check if app already exists
    app_path = apps_dir / f"{app_id}.json"
    if app_path.exists() and not args.dry_run:
        print(f"Error: App already exists: {app_path}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Create curated fields
    print(f"Creating app entry for {app_id}...")
    curated = {
        "id": app_id,
        "repo": args.repo,
        "asset_suffix": args.suffix,
        "version_regex": args.version_regex,
    }
    if args.title_version_regex:
        curated["title_version_regex"] = args.title_version_regex

    if not args.dry_run:
        write_json(app_path, curated)
        print(f"  Created {app_path} with curated fields")
    else:
        print(f"  [DRY RUN] Would create {app_path} with curated fields: {curated}")

    # Step 2: Merge Flathub fields
    fp_path = flatpak_dir / f"{app_id}.json"
    if fp_path.is_file():
        print(f"Merging Flathub fields from {fp_path}...")
        fresh = load_json(fp_path)
        if not args.dry_run:
            # Reload the file we just wrote
            mine = load_json(app_path)
            merged, changed_fields = merge_flathub_fields(mine, fresh)
            if changed_fields:
                write_json(app_path, merged)
                print(f"  Merged Flathub fields: {', '.join(changed_fields)}")
            else:
                print("  No Flathub fields to merge (or all empty)")
        else:
            mine = curated
            merged, changed_fields = merge_flathub_fields(mine, fresh)
            print(f"  [DRY RUN] Would merge Flathub fields: {changed_fields}")
    else:
        print(f"  No Flathub export found at {fp_path}, skipping Flathub merge")

    # Step 3: Copy icon
    print("Copying icon...")
    if not args.dry_run:
        icon_copied = copy_icon(app_id, flatpak_dir, icons_dir)
        if icon_copied:
            # Update the icon field in the app file
            mine = load_json(app_path)
            mine["icon"] = {"type": "cached", "name": f"{app_id}.png"}
            write_json(app_path, mine)
            print(f"  Copied icon to {icons_dir}/{app_id}.png")
        else:
            print("  No icon found in Flathub export")
    else:
        src_icon = flatpak_dir / f"{app_id}.png"
        if src_icon.is_file():
            print(f"  [DRY RUN] Would copy icon from {src_icon} to {icons_dir}/{app_id}.png")
        else:
            print("  [DRY RUN] No icon found in Flathub export")

    # Step 4: Run fetch for this app
    if not args.skip_fetch:
        print("Fetching latest release...")
        if not args.dry_run:
            success, error = run_get_latest_appimages(app_id, apps_dir, dry_run=False)
            if success:
                print("  Fetch successful")
            else:
                print(f"  Fetch failed: {error}")
                print("  (App entry created but without generated fields)")
        else:
            print("  [DRY RUN] Would run get_latest_appimages.py for this app")
    else:
        print("  Skipping fetch (--skip-fetch)")

    # Step 5: Run validation and print summary
    if not args.skip_validation:
        print("Validating...")
        if not args.dry_run:
            success, errors = run_validation(app_id, apps_dir, icons_dir)
            if success:
                print("  Validation passed")
            else:
                print("  Validation failed:")
                for err in errors:
                    print(f"    - {err}")
                sys.exit(1)

            # Print summary
            app = load_json(app_path)
            print_summary(app)
        else:
            print("  [DRY RUN] Would run validation")
    else:
        print("  Skipping validation (--skip-validation)")

    if args.dry_run:
        print("\n[DRY RUN] No changes were written.")
    else:
        print(f"\nDone! App {app_id} added successfully.")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Build a combined JSON database from individual app JSON files and create a tar.gz archive."""

import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    create_reproducible_tar_gz,
    format_generated_at,
    get_source_date_epoch,
    load_json,
    normalize_categories,
    normalize_description,
    normalize_keywords,
    normalize_screenshots,
    write_json,
)

REQUIRED_CURATED = ["id", "name", "repo", "asset_suffix", "version_regex"]
REQUIRED_GENERATED = ["version", "download_url", "asset_name", "published_at", "version_changed_at", "arch"]
# arch key must exist but value may be null
REQUIRED_GENERATED_TRUTHY = [f for f in REQUIRED_GENERATED if f != "arch"]
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d\d-\d\dT")


def validate_repo(repo: str) -> bool:
    """Validate repo format: owner/name"""
    return bool(re.match(r"^[\w.-]+/[\w.-]+$", repo))


def validate_url(url: str, field: str) -> list[str]:
    """Validate URL format."""
    errors = []
    if not url.startswith("https://"):
        errors.append(f"{field} must be https:// URL")
    return errors


def validate_sha256(sha256: str) -> list[str]:
    """Validate SHA256 format."""
    errors = []
    if not SHA256_PATTERN.match(sha256):
        errors.append("sha256 must be 64 lowercase hex characters")
    return errors


def validate_timestamp(ts: str, field: str) -> list[str]:
    """Validate timestamp format."""
    errors = []
    if not TIMESTAMP_PATTERN.match(ts):
        errors.append(f"{field} must be ISO-8601 UTC timestamp")
    return errors


def validate_app(app: dict, apps_dir: Path, icons_dir: Path, seen_ids: set) -> list[str]:
    """Validate a single app entry. Returns list of errors."""
    errors = []
    app_id = app.get("id")

    # Check id matches filename stem (will be checked by caller)
    if not app_id:
        errors.append("Missing required field: id")
        return errors

    # Check unique id
    if app_id in seen_ids:
        errors.append(f"Duplicate id: {app_id}")
    seen_ids.add(app_id)

    # Required curated fields
    for field in REQUIRED_CURATED:
        if field not in app or not app[field]:
            errors.append(f"Missing required curated field: {field}")

    # Validate repo format
    if "repo" in app and not validate_repo(app["repo"]):
        errors.append("repo must be in format 'owner/name'")

    # Validate version_regex compiles
    if app.get("version_regex"):
        try:
            re.compile(app["version_regex"])
        except re.error as e:
            errors.append(f"version_regex invalid: {e}")
    else:
        errors.append("Missing required curated field: version_regex")

    # Validate title_version_regex if present
    if app.get("title_version_regex"):
        try:
            re.compile(app["title_version_regex"])
        except re.error as e:
            errors.append(f"title_version_regex invalid: {e}")

    # Required generated fields (but allow missing for unfetched apps)
    missing_generated = [f for f in REQUIRED_GENERATED if f not in app]
    has_generated = len(missing_generated) < len(REQUIRED_GENERATED)

    if has_generated:
        # If some generated fields present, validate all truthy ones
        for field in REQUIRED_GENERATED_TRUTHY:
            if field not in app or not app[field]:
                errors.append(f"Missing required generated field: {field}")

        # arch key must exist (value may be null)
        if "arch" not in app:
            errors.append("Missing required generated field: arch")

        # Validate URLs
        errors.extend(validate_url(app.get("download_url", ""), "download_url"))
        if app.get("zsync_url"):
            errors.extend(validate_url(app["zsync_url"], "zsync_url"))
            if not app["zsync_url"].endswith(".zsync"):
                errors.append("zsync_url must end with .zsync")

        # Validate sha256
        if app.get("sha256"):
            errors.extend(validate_sha256(app["sha256"]))

        # Validate size
        if app.get("size") is not None and (not isinstance(app["size"], int) or app["size"] <= 0):
            errors.append("size must be a positive integer")

        # Validate timestamps
        for ts_field in ["published_at", "version_changed_at"]:
            if app.get(ts_field):
                errors.extend(validate_timestamp(app[ts_field], ts_field))

        # Validate icon exists
        icon = app.get("icon", {})
        if icon.get("name"):
            icon_path = icons_dir / icon["name"]
            if not icon_path.exists():
                errors.append(f"Icon file not found: {icon['name']}")
        else:
            errors.append("icon.name is required")

    # Validate screenshots if present
    if app.get("screenshots"):
        for i, shot in enumerate(app["screenshots"]):
            if "images" not in shot or not shot["images"]:
                errors.append(f"Screenshot {i}: missing images")
            else:
                for j, img in enumerate(shot["images"]):
                    if not img.get("url"):
                        errors.append(f"Screenshot {i} image {j}: missing url")
                    if not isinstance(img.get("width"), int):
                        errors.append(f"Screenshot {i} image {j}: width must be int")
                    if not isinstance(img.get("height"), int):
                        errors.append(f"Screenshot {i} image {j}: height must be int")

    return errors


def normalize_app(app: dict) -> dict:
    """Apply normalization to an app entry."""
    normalized = app.copy()

    # Normalize description
    if "description" in normalized:
        normalized["description"] = normalize_description(normalized["description"])

    # Normalize keywords
    if "keywords" in normalized:
        normalized["keywords"] = normalize_keywords(normalized["keywords"])

    # Normalize categories
    if "categories" in normalized:
        normalized["categories"] = normalize_categories(normalized["categories"])

    # Normalize screenshots
    if "screenshots" in normalized:
        normalized["screenshots"] = normalize_screenshots(normalized["screenshots"])

    return normalized


def main():
    parser = argparse.ArgumentParser(description="Build apps database")
    parser.add_argument("--apps", default="data/apps", help="Apps directory")
    parser.add_argument("--icons", default="data/icons", help="Icons directory")
    parser.add_argument("--out", default="data/output", help="Output directory")
    parser.add_argument("--check", action="store_true", help="Validate only, do not write")
    args = parser.parse_args()

    apps_dir = Path(args.apps)
    icons_dir = Path(args.icons)
    output_dir = Path(args.out)

    if not apps_dir.exists():
        print(f"Error: apps directory not found: {apps_dir}", file=sys.stderr)
        sys.exit(1)

    if not icons_dir.exists():
        print(f"Error: icons directory not found: {icons_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all apps
    apps = []
    seen_ids = set()
    all_errors = []
    warnings = []

    for json_file in sorted(apps_dir.glob("*.json")):
        try:
            app = load_json(json_file)
        except json.JSONDecodeError as e:
            all_errors.append(f"{json_file.name}: JSON parse error: {e}")
            continue

        # Check id matches filename stem
        expected_id = json_file.stem
        actual_id = app.get("id")
        if actual_id != expected_id:
            all_errors.append(f"{json_file.name}: id '{actual_id}' does not match filename stem '{expected_id}'")

        # Validate
        errors = validate_app(app, apps_dir, icons_dir, seen_ids)
        if errors:
            all_errors.extend([f"{json_file.name}: {e}" for e in errors])

        # Normalize
        app = normalize_app(app)
        apps.append(app)

    # Summary
    # arch key must exist but value may be null
    skipped = sum(1 for a in apps if not all(f in a and a[f] for f in REQUIRED_GENERATED_TRUTHY))
    valid_apps = [a for a in apps if all(f in a and a[f] for f in REQUIRED_GENERATED_TRUTHY)]

    # Warn about apps with null arch
    null_arch_ids = [a["id"] for a in valid_apps if not a.get("arch")]

    print(f"Total apps: {len(apps)}")
    print(f"Valid apps: {len(valid_apps)}")
    print(f"Skipped (no generated data): {skipped}")
    print(f"Warnings: {len(warnings)}")
    print(f"Errors: {len(all_errors)}")

    if null_arch_ids:
        print(f"WARNING: null arch for: {', '.join(null_arch_ids)}")

    if all_errors:
        print("\nErrors:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)

    if args.check:
        if all_errors:
            sys.exit(1)
        print("Validation passed")
        sys.exit(0)

    if all_errors:
        print("Validation failed, not writing output", file=sys.stderr)
        sys.exit(1)

    # Sort by id
    apps.sort(key=lambda a: a["id"])

    # Build envelope
    epoch = get_source_date_epoch()
    generated_at = format_generated_at(epoch)

    envelope = {
        "schema_version": 1,
        "generated_at": generated_at,
        "count": len(valid_apps),
        "apps": valid_apps,
    }

    # Write database
    db_path = output_dir / "apps.db"
    write_json(db_path, envelope)
    print(f"Created database with {len(valid_apps)} apps: {db_path}")

    # Create reproducible tar.gz
    tar_path = output_dir / "apps.db.tar.gz"
    mtime = epoch if epoch is not None else 0
    create_reproducible_tar_gz(tar_path, [(db_path, "apps.db")], mtime)
    print(f"Created archive: {tar_path}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Fetch latest AppImage release info from GitHub and update app JSON files.

Features:
- GitHub token auth (GITHUB_TOKEN or GH_TOKEN)
- Retries with exponential backoff
- Rate limit handling
- Parallel fetch with configurable workers
- Per-app failure threshold
- Dry-run mode
- Per-id mode
- Extracts: version, download_url, asset_name, size, sha256, zsync_url, arch, published_at, version_changed_at
- Stale/broken detection with last_ok_at tracking
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Import shared helpers
sys.path.insert(0, str(Path(__file__).parent))
from common import (
    check_stale_broken,
    compute_version_changed_at,
    detect_arch,
    extract_version,
    find_sha256,
    find_zsync_url,
    generate_ci_summary,
    load_last_ok_report,
    save_last_ok_report,
    update_last_ok,
    write_json,
)

GITHUB_API_BASE = "https://api.github.com"

# Color codes for stderr output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


class RateLimitExceeded(Exception):
    """Raised when GitHub API rate limit is exhausted."""
    def __init__(self, reset_time: int | None = None):
        self.reset_time = reset_time
        super().__init__("Rate limit exceeded")


def get_github_token() -> str | None:
    """Get GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def make_request(url: str, token: str | None, max_retries: int = 3) -> dict | None:
    """
    Make HTTP request to GitHub API with retries and rate limit handling.
    Returns parsed JSON or None on 404.
    Raises RateLimitExceeded on rate limit exhaustion.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                # Check rate limit headers
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None and int(remaining) == 0:
                    reset = response.headers.get("X-RateLimit-Reset")
                    reset_time = int(reset) if reset else None
                    raise RateLimitExceeded(reset_time)

                return json.load(response)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 403:
                # Check if it's rate limit
                reset = e.headers.get("X-RateLimit-Reset")
                reset_time = int(reset) if reset else None
                raise RateLimitExceeded(reset_time)
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                # Retryable error
                wait_time = 2 ** attempt  # exponential backoff: 1, 2, 4
                time.sleep(wait_time)
                continue
            # Non-retryable error
            raise

        except (urllib.error.URLError, TimeoutError):
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            raise

    return None


def fetch_latest_release(repo: str, token: str | None) -> dict | None:
    """Fetch latest release from GitHub API."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/releases/latest"
    return make_request(url, token)


def download_and_parse_checksum(url: str, token: str | None, asset_name: str) -> str | None:
    """
    Download a checksum file and extract SHA256 for the given asset.
    Supports both sibling checksum files and combined checksum files (SHA256SUMS format).
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError):
        return None

    # Parse checksum file - format: "sha256_hash  filename" or "sha256_hash *filename"
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            sha = parts[0].lower()
            filename = parts[1].lstrip("*")
            if filename == asset_name and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha):
                return sha
    return None


def find_appimage_asset(release: dict, asset_suffix: str) -> dict | None:
    """Find the AppImage asset matching the suffix."""
    for asset in release.get("assets", []):
        if asset["name"].endswith(asset_suffix):
            return asset
    return None


def insert_generated_fields(data: dict, updates: dict) -> dict:
    """
    Insert generated fields after title_version_regex (or version_regex),
    preserving key order: curated -> generated -> flathub.
    Prefers title_version_regex if present.
    """
    result = {}
    inserted = False
    # Keys that are generated and should not be copied from original data
    generated_keys = set(updates.keys())

    for key, value in data.items():
        # Skip old generated fields - we'll use the new values from updates
        if inserted and key in generated_keys:
            continue
        result[key] = value
        # Prefer title_version_regex over version_regex
        if key == "title_version_regex" and not inserted or key == "version_regex" and not inserted and "title_version_regex" not in data:
            for uk, uv in updates.items():
                result[uk] = uv
            inserted = True

    # If neither key was found, append at the end
    if not inserted:
        for uk, uv in updates.items():
            result[uk] = uv

    return result


def process_app(
    app_id: str,
    app_data: dict,
    apps_dir: Path,
    token: str | None,
    dry_run: bool = False,
) -> tuple[str, bool, str | None, str | None, str | None]:
    """
    Process a single app.
    Returns (app_id, success, error_message, published_at, old_version).
    """
    repo = app_data.get("repo")
    asset_suffix = app_data.get("asset_suffix")
    version_regex = app_data.get("version_regex")
    title_version_regex = app_data.get("title_version_regex")

    if not repo or not asset_suffix:
        return (app_id, False, "missing repo or asset_suffix", None, None)

    release = fetch_latest_release(repo, token)
    if not release:
        return (app_id, False, "no release found", None, None)

    asset = find_appimage_asset(release, asset_suffix)
    if not asset:
        return (app_id, False, f"no asset matching suffix '{asset_suffix}'", None, None)

    # Extract version
    tag_name = release["tag_name"]
    release_title = release.get("name") or ""
    version, _version_source = extract_version(
        tag_name, version_regex, release_title, title_version_regex
    )

    old_version = app_data.get("version")

    # Detect arch
    arch = detect_arch(asset["name"])

    # Find sha256
    sha256 = find_sha256(asset, release.get("assets", []))

    # If find_sha256 indicates a checksum file exists, download and parse it
    if sha256 == "SIBLING_CHECKSUM":
        # Find the sibling checksum file
        asset_name = asset["name"]
        for sibling in release.get("assets", []):
            sname = sibling["name"]
            if sname == f"{asset_name}.sha256" or sname == f"{asset_name}.sha256sum" or sname == f"{asset_name}.sha256.txt":
                sha256 = download_and_parse_checksum(sibling["browser_download_url"], token, asset_name)
                break
    elif sha256 == "COMBINED_CHECKSUM":
        # Find the combined checksum file
        for sibling in release.get("assets", []):
            sname = sibling["name"]
            if sname in ("SHA256SUMS", "SHA256SUMS.txt", "checksums.txt", "checksums.sha256"):
                sha256 = download_and_parse_checksum(sibling["browser_download_url"], token, asset["name"])
                break

    # Find zsync_url
    zsync_url = find_zsync_url(asset["name"], release.get("assets", []))

    # Build updates
    updates = {
        "version": version,
        "download_url": asset["browser_download_url"],
        "asset_name": asset["name"],
        "size": asset.get("size"),
        "sha256": sha256,
        "zsync_url": zsync_url,
        "arch": arch,
        "published_at": release["published_at"],
        "version_changed_at": compute_version_changed_at(
            app_data, version, sha256, release["published_at"]
        ),
    }

    # Remove None values (except we keep them to show they were checked)
    updates = {k: v for k, v in updates.items() if v is not None}

    # Insert generated fields in correct position
    updated = insert_generated_fields(app_data, updates)

    if not dry_run:
        write_json(apps_dir / f"{app_id}.json", updated)

    return (app_id, True, None, release["published_at"], old_version)


def print_warning(message: str) -> None:
    """Print warning, using GitHub Actions annotation format if in CI."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{message}")
    else:
        print(f"{YELLOW}[WARN]{RESET} {message}", file=sys.stderr)


def print_error(message: str) -> None:
    """Print error, using GitHub Actions annotation format if in CI."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::{message}")
    else:
        print(f"{RED}[ERROR]{RESET} {message}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Fetch latest AppImage releases from GitHub")
    ap.add_argument("ids", nargs="*", help="Specific app IDs to process (default: all)")
    ap.add_argument("--apps-dir", default="data/apps", help="Directory with app JSON files")
    ap.add_argument("--dry-run", action="store_true", help="Don't write changes")
    ap.add_argument("--workers", type=int, default=6, help="Parallel workers (default: 6)")
    ap.add_argument("--max-failure-rate", type=float, default=0.25, help="Max failure rate (default: 0.25)")
    ap.add_argument("--last-ok-report", default="data/last_ok_report.json", help="Path to last_ok_at report file")
    ap.add_argument("--ci-summary", help="Path to write CI summary markdown")
    args = ap.parse_args()

    apps_dir = Path(args.apps_dir)
    if not apps_dir.exists():
        print(f"Apps directory '{apps_dir}' not found", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(f for f in apps_dir.glob("*.json"))
    if not json_files:
        print("No JSON files found in apps/", file=sys.stderr)
        sys.exit(1)

    # Filter by IDs if provided
    if args.ids:
        id_set = set(args.ids)
        json_files = [f for f in json_files if f.stem in id_set]
        if not json_files:
            print(f"No matching apps for IDs: {args.ids}", file=sys.stderr)
            sys.exit(1)

    token = get_github_token()
    if not token:
        print_warning("No GITHUB_TOKEN or GH_TOKEN set; unauthenticated requests limited to 60/hour")

    # Load last_ok report
    report_path = Path(args.last_ok_report)
    last_ok_report = load_last_ok_report(report_path)

    total = len(json_files)
    success_count = 0
    failure_count = 0
    rate_limited = False

    updated_apps = []
    failed_apps = []
    version_changes = []

    print(f"Processing {total} app(s) with {args.workers} worker(s)...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for json_file in json_files:
            app_id = json_file.stem
            with open(json_file, "r") as f:
                app_data = json.load(f)
            future = executor.submit(process_app, app_id, app_data, apps_dir, token, args.dry_run)
            futures[future] = app_id

        for future in as_completed(futures):
            app_id = futures[future]
            try:
                _, success, error, published_at, old_version = future.result()
                if success:
                    success_count += 1
                    updated_apps.append(app_id)
                    print(f"  {app_id}: {GREEN}[OK]{RESET}", file=sys.stderr)
                    # Update last_ok_at
                    if not args.dry_run:
                        update_last_ok(last_ok_report, app_id, True, published_at)
                    # Track version changes
                    if old_version:
                        # Get the new version from the updated file
                        app_path = apps_dir / f"{app_id}.json"
                        try:
                            with open(app_path, "r") as f:
                                updated_data = json.load(f)
                            new_version = updated_data.get("version")
                            if new_version and new_version != old_version:
                                version_changes.append((app_id, old_version, new_version))
                        except (OSError, json.JSONDecodeError):
                            pass
                else:
                    failure_count += 1
                    failed_apps.append((app_id, error))
                    print(f"  {app_id}: {RED}[FAIL]{RESET} - {error}", file=sys.stderr)
                    # Don't update last_ok_at on failure
            except RateLimitExceeded as e:
                rate_limited = True
                failure_count += 1
                failed_apps.append((app_id, "rate limit exceeded"))
                reset_msg = f" (resets at {time.ctime(e.reset_time)})" if e.reset_time else ""
                print(f"  {app_id}: {RED}[RATE LIMIT]{RESET}{reset_msg}", file=sys.stderr)
                # Cancel remaining futures
                for f in futures:
                    f.cancel()
                break
            except Exception as e:  # noqa: BLE001
                failure_count += 1
                failed_apps.append((app_id, str(e)))
                print(f"  {app_id}: {RED}[ERROR]{RESET} - {e}", file=sys.stderr)

    # Save last_ok report
    if not args.dry_run:
        save_last_ok_report(report_path, last_ok_report)

    # Check stale/broken
    stale_broken = check_stale_broken(last_ok_report, apps_dir)

    # Generate CI summary
    if args.ci_summary:
        summary = generate_ci_summary(
            updated_apps=updated_apps,
            failed_apps=failed_apps,
            warnings=[],  # Could collect warnings during processing
            version_changes=version_changes,
            stale_broken=stale_broken
        )
        Path(args.ci_summary).write_text(summary, encoding="utf-8")

    # Summary
    print(file=sys.stderr)
    print(f"{BOLD}Summary:{RESET} {GREEN}{success_count} OK{RESET}, {RED}{failure_count} FAIL{RESET}", file=sys.stderr)

    if rate_limited:
        print_error("GitHub API rate limit exceeded")
        sys.exit(2)

    if total > 0 and (failure_count / total) > args.max_failure_rate:
        print_error(f"Failure rate {failure_count}/{total} exceeds threshold {args.max_failure_rate}")
        sys.exit(1)

    # Exit with error only if failure rate exceeds threshold
    # If failures are within threshold, exit successfully
    sys.exit(0)


if __name__ == "__main__":
    main()

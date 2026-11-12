#!/usr/bin/env python3
"""
Script to fetch latest AppImage release links and versions from GitHub repos.
Updates version, download_url, asset_name, published_at in each apps/*.json file.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

GITHUB_API_BASE = "https://api.github.com"

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def fetch_latest_release(repo: str) -> dict | None:
    url = f"{GITHUB_API_BASE}/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        print(f"  {'No releases found' if e.code == 404 else f'Error fetching {repo}: {e}'} for {repo}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  Error fetching {repo}: {e}", file=sys.stderr)
        return None


def find_appimage_asset(release: dict, asset_suffix: str) -> dict | None:
    for asset in release.get("assets", []):
        if asset["name"].endswith(asset_suffix):
            return asset
    return None


def extract_version(tag_name: str, version_regex: str | None = None) -> str:
    if version_regex:
        match = re.search(version_regex, tag_name)
        if match:
            return match.group(1)
    return tag_name.lstrip("v")


def insert_after_version_regex(data: dict, updates: dict) -> dict:
    """Return new dict with update keys placed after 'version_regex', preserving order."""
    result = {}
    for key, value in data.items():
        if key in updates:
            continue  # will be inserted after version_regex
        result[key] = value
        if key == "version_regex":
            for uk, uv in updates.items():
                result[uk] = uv
    # If version_regex wasn't found, just append
    for uk, uv in updates.items():
        if uk not in result:
            result[uk] = uv
    return result


def main():
    apps_dir = "data/apps"

    if not os.path.exists(apps_dir):
        print(f"Apps directory '{apps_dir}' not found", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(f for f in os.listdir(apps_dir) if f.endswith(".json"))

    if not json_files:
        print("No JSON files found in apps/", file=sys.stderr)
        sys.exit(1)

    for filename in json_files:
        path = os.path.join(apps_dir, filename)
        with open(path, "r") as f:
            app = json.load(f)

        repo = app.get("repo")
        asset_suffix = app.get("asset_suffix")
        name = app.get("name", filename)

        if not repo or not asset_suffix:
            print(f"  Skipping {filename}: missing repo or asset_suffix", file=sys.stderr)
            continue

        print(f"Fetching {name} ({repo})... ", end="", file=sys.stderr, flush=True)

        release = fetch_latest_release(repo)
        if not release:
            print(f"{RED}[FAIL]{RESET} - No release found", file=sys.stderr)
            continue

        asset = find_appimage_asset(release, asset_suffix)
        if not asset:
            print(f"{RED}[FAIL]{RESET} - No asset matching suffix '{asset_suffix}'", file=sys.stderr)
            continue

        version = extract_version(release["tag_name"], app.get("version_regex"))

        updates = {
            "version": version,
            "download_url": asset["browser_download_url"],
            "asset_name": asset["name"],
            "published_at": release["published_at"],
        }

        updated = insert_after_version_regex(app, updates)

        with open(path, "w") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"{version} {GREEN}[OK]{RESET}", file=sys.stderr)


if __name__ == "__main__":
    main()

"""
Shared pure helpers for the Aurelis software database pipeline.
"""

import json
import os
import re
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any, indent: int = 2) -> bool:
    """
    Write JSON to a file only if content changed.
    Returns True if written, False if unchanged.
    """
    new_text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    if path.exists():
        old_text = path.read_text(encoding="utf-8")
        if old_text == new_text:
            return False
    path.write_text(new_text, encoding="utf-8")
    return True


def load_json(path: Path) -> Any:
    """Load JSON from a file."""
    return json.loads(path.read_text(encoding="utf-8"))


def detect_arch(asset_name: str) -> str | None:
    """
    Detect architecture from asset filename.
    Returns normalized arch string or None if not detected.
    """
    name = asset_name.lower()
    # x86_64 variants
    if re.search(r"(^|[-_])(x86_64|x86-64|amd64|x64)($|[-_.])", name):
        return "x86_64"
    # aarch64 variants
    if re.search(r"(^|[-_])(aarch64|arm64)($|[-_.])", name):
        return "aarch64"
    # armv7l variants
    if re.search(r"(^|[-_])(armv7l|armv7|armhf)($|[-_.])", name):
        return "armv7l"
    # i386/i686 variants
    if re.search(r"(^|[-_])(i386|i686)($|[-_.])", name):
        return "i686"
    return None


def normalize_description(text: str | None) -> str | None:
    """
    Normalize description: join soft-wrapped lines, collapse spaces,
    drop Flathub boilerplate paragraphs, keep \n between paragraphs.
    Idempotent: f(f(x)) == f(x).
    """
    if not text:
        return None

    # Join soft-wrapped lines (newline followed by indentation)
    text = re.sub(r"\n[ \t]+", " ", text)

    # Split into paragraphs on single newline
    paragraphs = text.split("\n")
    normalized = []

    for para in paragraphs:
        # Collapse whitespace within paragraph
        joined = " ".join(para.split())

        # Drop only "This flatpak is" boilerplate (case-insensitive)
        if joined.lower().startswith("this flatpak is"):
            continue

        if joined:
            normalized.append(joined)

    return "\n".join(normalized) if normalized else None


def normalize_keywords(keywords: list[str] | None) -> list[str]:
    """
    Normalize keywords: trim, drop empties, case-insensitive dedupe, keep order.
    """
    if not keywords:
        return []
    seen = set()
    result = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(kw)
    return result


def normalize_categories(categories: list[str] | None) -> list[str]:
    """
    Normalize categories: trim, drop empties, case-insensitive dedupe, keep order.
    """
    if not categories:
        return []
    seen = set()
    result = []
    for cat in categories:
        cat = cat.strip()
        if not cat:
            continue
        lower = cat.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(cat)
    return result


def normalize_screenshots(screenshots: list[dict] | None) -> list[dict]:
    """
    Normalize screenshots: int sizes, drop images without URL,
    drop screenshots without images, first default wins, force one default if none.
    """
    if not screenshots:
        return []

    normalized = []
    default_used = False

    for shot in screenshots:
        images = shot.get("images", [])
        norm_images = []
        for img in images:
            url = img.get("url", "").strip()
            if not url:
                continue
            try:
                width = int(img.get("width", 0))
                height = int(img.get("height", 0))
            except (ValueError, TypeError):
                width = 0
                height = 0
            norm_images.append({
                "type": img.get("type", ""),
                "width": width,
                "height": height,
                "url": url,
            })

        if not norm_images:
            continue

        is_default = shot.get("default", False)
        if is_default and default_used:
            is_default = False
        if is_default:
            default_used = True

        normalized.append({
            "default": is_default,
            "caption": shot.get("caption"),
            "images": norm_images,
        })

    # Force first as default if none
    if normalized and not default_used:
        normalized[0]["default"] = True

    return normalized


# Canonical order for generated fields
GENERATED = [
    "version",
    "version_changed_at",
    "download_url",
    "asset_name",
    "size",
    "sha256",
    "zsync_url",
    "arch",
    "published_at",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMBINED_RE = re.compile(r"(?i)^(sha256sums?|checksums?)(\.(txt|sha256))?$")


def parse_checksum(text: str, filename: str) -> str | None:
    """
    Parse a checksum file and return the SHA256 for filename, or None.
    Accepts: bare 64-hex line, or "<hash>  name" / "<hash> *name" lines.
    """
    basename = Path(filename).name
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 1:
            # Bare hash line
            candidate = parts[0].lower()
            if _SHA256_RE.match(candidate):
                return candidate
        elif len(parts) >= 2:
            candidate = parts[0].lower()
            name = parts[1].lstrip("*")
            if Path(name).name == basename and _SHA256_RE.match(candidate):
                return candidate
    return None


def find_sha256(
    asset: dict,
    all_assets: list[dict],
    fetch=None,
) -> str | None:
    """
    Find SHA256 for an asset.
    Priority: asset.digest -> sibling .sha256/.sha256sum/.sha256.txt ->
    combined checksum file matching SHA256SUMS/checksums pattern.
    fetch: callable(url) -> str | None (injected; None means no download).
    Returns lowercase 64-hex or None.
    """
    # 1. GitHub's digest field
    digest = asset.get("digest")
    if digest and digest.startswith("sha256:"):
        hex_val = digest[7:].lower()
        if _SHA256_RE.match(hex_val):
            return hex_val

    if fetch is None:
        return None

    asset_name = asset["name"]

    # 2. Sibling checksum files
    for sibling in all_assets:
        sname = sibling["name"]
        if sname in (f"{asset_name}.sha256", f"{asset_name}.sha256sum", f"{asset_name}.sha256.txt"):
            text = fetch(sibling["browser_download_url"])
            if text is not None:
                return parse_checksum(text, asset_name)

    # 3. Combined checksum files
    for sibling in all_assets:
        if _COMBINED_RE.match(sibling["name"]):
            text = fetch(sibling["browser_download_url"])
            if text is not None:
                return parse_checksum(text, asset_name)

    return None


def find_zsync_url(asset_name: str, all_assets: list[dict]) -> str | None:
    """Find zsync URL for an asset."""
    zsync_name = f"{asset_name}.zsync"
    for asset in all_assets:
        if asset["name"] == zsync_name:
            return asset["browser_download_url"]
    return None


def extract_version(tag_name: str, version_regex: str | None, title: str | None, title_version_regex: str | None) -> tuple[str, str]:
    """
    Extract version from tag or title.
    Returns (version, source) where source is 'tag', 'title', or 'fallback'.
    """
    # Try version_regex on tag
    if version_regex:
        match = re.search(version_regex, tag_name)
        if match:
            return (match.group(1) if match.groups() else match.group(0), "tag")

    # Try title_version_regex on title
    if title_version_regex and title:
        match = re.search(title_version_regex, title)
        if match:
            return (match.group(1) if match.groups() else match.group(0), "title")

    # Fallback: strip leading 'v' from tag
    version = tag_name.lstrip("v")
    return (version, "fallback")


def compute_version_changed_at(
    existing: dict | None,
    new_version: str,
    new_sha256: str | None,
    new_published_at: str,
) -> str:
    """
    Compute version_changed_at based on spec rules.
    """
    if not existing:
        return new_published_at

    old_version = existing.get("version")
    old_sha256 = existing.get("sha256")
    old_changed_at = existing.get("version_changed_at")

    # Version changed
    if old_version != new_version:
        return new_published_at

    # Same version but sha256 changed
    if old_sha256 and new_sha256 and old_sha256 != new_sha256:
        return new_published_at

    # Version is "latest" and published_at changed
    if new_version == "latest" and old_version == "latest":
        old_published = existing.get("published_at")
        if old_published and old_published != new_published_at:
            return new_published_at

    # Otherwise keep existing
    return old_changed_at or new_published_at


def reproducible_tar_add(tar: tarfile.TarFile, path: Path, arcname: str, mtime: int = 0) -> None:
    """Add a file to tar with reproducible metadata."""
    tarinfo = tar.gettarinfo(path, arcname)
    tarinfo.mtime = mtime
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = ""
    tarinfo.gname = ""
    tarinfo.mode = 0o644
    with open(path, "rb") as f:
        tar.addfile(tarinfo, f)


def create_reproducible_tar_gz(output_path: Path, files: list[tuple[Path, str]], mtime: int = 0) -> None:
    """
    Create a reproducible tar.gz archive.
    files: list of (source_path, archive_name)
    """
    import gzip
    import io
    # First create a reproducible tar in memory
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        # Sort by archive name for determinism
        for src, arcname in sorted(files, key=lambda x: x[1]):
            reproducible_tar_add(tar, src, arcname, mtime)
    
    # Then gzip with fixed mtime
    tar_buffer.seek(0)
    with open(output_path, "wb") as f, gzip.GzipFile(filename="", mode="wb", mtime=mtime, fileobj=f) as gz:
        gz.write(tar_buffer.read())


def get_source_date_epoch() -> int | None:
    """Get SOURCE_DATE_EPOCH as int if set and valid."""
    val = os.environ.get("SOURCE_DATE_EPOCH")
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    return None


def format_generated_at(epoch: int | None = None) -> str:
    """Format generated_at timestamp, using SOURCE_DATE_EPOCH if available."""
    from datetime import datetime
    if epoch is None:
        epoch = get_source_date_epoch()
    if epoch is not None:
        return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# Stale/broken detection helpers

def load_last_ok_report(report_path: Path) -> dict:
    """Load the last_ok_at report file."""
    if report_path.exists():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_last_ok_report(report_path: Path, report: dict) -> bool:
    """Save the last_ok_at report file."""
    return write_json(report_path, report)


def update_last_ok(report: dict, app_id: str, success: bool, published_at: str | None = None) -> None:
    """
    Update last_ok_at for an app.
    If success, set last_ok_at to the current fetch time (not the release date).
    If failure, leave last_ok_at unchanged.
    """
    if success:
        # Use the fetch time (now) as last_ok_at, not the release's published_at
        # This ensures stale detection tracks fetch success, not release age
        report[app_id] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # On failure, don't update last_ok_at - it stays at the last successful fetch


def check_stale_broken(report: dict, apps_dir: Path, max_failure_weeks: int = 3, max_release_age_months: int = 18) -> dict:
    """
    Check for stale/broken apps.
    Returns dict with 'stale' (failed 3+ weeks) and 'old_release' (release > 18 months) lists.
    """
    now = datetime.now(UTC)
    
    stale = []  # Apps that failed 3+ weeks in a row
    old_release = []  # Apps with release older than 18 months
    
    for json_file in sorted(apps_dir.glob("*.json")):
        app_id = json_file.stem
        try:
            app = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        
        last_ok = report.get(app_id)
        published_at = app.get("published_at")
        
        # Check if app has failed for 3+ weeks (no last_ok or last_ok > 3 weeks ago)
        if last_ok:
            try:
                last_ok_dt = datetime.fromisoformat(last_ok)
                if (now - last_ok_dt) > timedelta(weeks=max_failure_weeks):
                    stale.append({
                        "id": app_id,
                        "last_ok_at": last_ok,
                        "weeks_since_ok": (now - last_ok_dt).days // 7
                    })
            except (ValueError, TypeError):
                # Invalid timestamp, treat as stale
                stale.append({
                    "id": app_id,
                    "last_ok_at": last_ok,
                    "weeks_since_ok": "unknown"
                })
        else:
            # Never succeeded
            stale.append({
                "id": app_id,
                "last_ok_at": None,
                "weeks_since_ok": "never"
            })
        
        # Check if latest release is older than 18 months
        if published_at:
            try:
                pub_dt = datetime.fromisoformat(published_at)
                if (now - pub_dt) > timedelta(days=max_release_age_months * 30):
                    old_release.append({
                        "id": app_id,
                        "published_at": published_at,
                        "months_since_release": (now - pub_dt).days // 30
                    })
            except (ValueError, TypeError):
                pass
    
    return {
        "stale": stale,
        "old_release": old_release
    }


def generate_ci_summary(
    updated_apps: list[str],
    failed_apps: list[tuple[str, str]],
    warnings: list[str],
    version_changes: list[tuple[str, str, str]],  # (app_id, old_version, new_version)
    stale_broken: dict | None = None
) -> str:
    """Generate a markdown summary for CI job summary."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    
    lines = [
        "# Aurelis Software Database - Build Summary",
        "",
        f"**Generated at:** {now}",
        "",
        f"## Updated Apps ({len(updated_apps)})",
        ""
    ]
    
    if updated_apps:
        for app_id in sorted(updated_apps):
            lines.append(f"- `{app_id}`")
    else:
        lines.append("_No apps updated_")
    
    lines.extend([
        "",
        f"## Failed Apps ({len(failed_apps)})",
        ""
    ])
    
    if failed_apps:
        for app_id, error in failed_apps:
            lines.append(f"- `{app_id}`: {error}")
    else:
        lines.append("_No failures_")
    
    lines.extend([
        "",
        f"## Version Changes ({len(version_changes)})",
        ""
    ])
    
    if version_changes:
        for app_id, old_ver, new_ver in version_changes:
            lines.append(f"- `{app_id}`: `{old_ver}` → `{new_ver}`")
    else:
        lines.append("_No version changes_")
    
    lines.extend([
        "",
        f"## Warnings ({len(warnings)})",
        ""
    ])
    
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("_No warnings_")
    
    if stale_broken:
        lines.extend([
            "",
            "## Stale/Broken Detection",
            ""
        ])
        
        stale = stale_broken.get("stale", [])
        old_release = stale_broken.get("old_release", [])
        
        lines.append(f"### Stale Apps (failed ≥ 3 weeks) ({len(stale)})")
        lines.append("")
        if stale:
            for item in stale:
                last_ok = item.get("last_ok_at") or "never"
                weeks = item.get("weeks_since_ok", "?")
                lines.append(f"- `{item['id']}`: last OK {last_ok} ({weeks} weeks ago)")
        else:
            lines.append("_None_")
        
        lines.append("")
        lines.append(f"### Old Releases (> 18 months) ({len(old_release)})")
        lines.append("")
        if old_release:
            for item in old_release:
                months = item.get("months_since_release", "?")
                lines.append(f"- `{item['id']}`: released {item['published_at']} ({months} months ago)")
        else:
            lines.append("_None_")
    
    return "\n".join(lines)
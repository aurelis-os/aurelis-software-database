#!/usr/bin/env python3
"""
Shared pure helpers for the Aurelis software database pipeline.
"""

import json
import os
import re
import tarfile
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
    """
    if not text:
        return None

    # Split into paragraphs (double newline or single newline with indentation)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    normalized = []

    for para in paragraphs:
        # Join lines within paragraph, collapse whitespace
        lines = para.split("\n")
        joined = " ".join(line.strip() for line in lines if line.strip())
        # Collapse multiple spaces
        joined = re.sub(r"\s+", " ", joined)

        # Drop Flathub boilerplate
        if joined.lower().startswith("this flatpak is"):
            continue
        if joined.lower().startswith("this application is"):
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


def find_sha256(asset: dict, all_assets: list[dict]) -> str | None:
    """
    Find SHA256 for an asset.
    Priority: asset.digest, sibling .sha256 file, combined SHA256SUMS/checksums.txt.
    """
    # 1. GitHub's digest field
    digest = asset.get("digest")
    if digest and digest.startswith("sha256:"):
        return digest[7:].lower()

    asset_name = asset["name"]

    # 2. Sibling checksum files
    for sibling in all_assets:
        sname = sibling["name"]
        if sname == f"{asset_name}.sha256" or sname == f"{asset_name}.sha256sum" or sname == f"{asset_name}.sha256.txt":
            # Fetch and parse the checksum file
            # For now, we'll need to download it - but in the actual implementation
            # this would be done by the fetch script. Here we just return None
            # and let the caller handle downloading.
            pass

    # 3. Combined checksum files
    for sibling in all_assets:
        sname = sibling["name"]
        if sname in ("SHA256SUMS", "SHA256SUMS.txt", "checksums.txt", "checksums.sha256"):
            pass

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


def reproducible_tar_add(tar: tarfile.TarInfo, path: Path, arcname: str, mtime: int = 0) -> None:
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
    with tarfile.open(output_path, "w:gz") as tar:
        # Sort by archive name for determinism
        for src, arcname in sorted(files, key=lambda x: x[1]):
            reproducible_tar_add(tar, src, arcname, mtime)


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
    from datetime import datetime, timezone
    if epoch is None:
        epoch = get_source_date_epoch()
    if epoch is not None:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
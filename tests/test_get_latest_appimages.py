"""Unit tests for get_latest_appimages.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import detect_arch, find_sha256, find_zsync_url
from get_latest_appimages import (
    find_appimage_asset,
    insert_generated_fields,
)


class TestInsertGeneratedFields(unittest.TestCase):
    def test_insert_after_title_version_regex(self):
        data = {
            "id": "test",
            "name": "Test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "version_regex": "v(.+)",
            "title_version_regex": "(.+)",
            "summary": "Test app",
        }
        updates = {"version": "1.0", "download_url": "http://example.com/app.AppImage"}
        result = insert_generated_fields(data, updates)

        # Check order: curated -> generated -> flathub
        keys = list(result.keys())
        version_idx = keys.index("version")
        title_version_regex_idx = keys.index("title_version_regex")
        self.assertEqual(version_idx, title_version_regex_idx + 1)

    def test_insert_after_version_regex(self):
        data = {
            "id": "test",
            "name": "Test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "version_regex": "v(.+)",
            "summary": "Test app",
        }
        updates = {"version": "1.0", "download_url": "http://example.com/app.AppImage"}
        result = insert_generated_fields(data, updates)

        keys = list(result.keys())
        version_idx = keys.index("version")
        version_regex_idx = keys.index("version_regex")
        self.assertEqual(version_idx, version_regex_idx + 1)

    def test_append_if_neither_key(self):
        data = {
            "id": "test",
            "name": "Test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "summary": "Test app",
        }
        updates = {"version": "1.0"}
        result = insert_generated_fields(data, updates)

        keys = list(result.keys())
        self.assertEqual(keys[-1], "version")


class TestFindAppimageAsset(unittest.TestCase):
    def test_finds_matching_suffix(self):
        release = {
            "assets": [
                {"name": "app-x86_64.AppImage", "browser_download_url": "http://example.com/app-x86_64.AppImage"},
                {"name": "app-arm64.AppImage", "browser_download_url": "http://example.com/app-arm64.AppImage"},
            ]
        }
        asset = find_appimage_asset(release, "-x86_64.AppImage")
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "app-x86_64.AppImage")

    def test_returns_none_if_no_match(self):
        release = {"assets": [{"name": "app.deb", "browser_download_url": "http://example.com/app.deb"}]}
        asset = find_appimage_asset(release, ".AppImage")
        self.assertIsNone(asset)


class TestDetectArch(unittest.TestCase):
    def test_various_archs(self):
        self.assertEqual(detect_arch("app-x86_64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app-amd64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app-aarch64.AppImage"), "aarch64")
        self.assertEqual(detect_arch("app-arm64.AppImage"), "aarch64")
        self.assertEqual(detect_arch("app-armv7l.AppImage"), "armv7l")
        self.assertEqual(detect_arch("app-i686.AppImage"), "i686")
        self.assertIsNone(detect_arch("app-universal.AppImage"))


class TestFindSha256(unittest.TestCase):
    def test_from_digest(self):
        asset = {"name": "app.AppImage", "digest": "sha256:abc123"}
        assets = [asset]
        result = find_sha256(asset, assets)
        self.assertEqual(result, "abc123")

    def test_digest_not_sha256(self):
        asset = {"name": "app.AppImage", "digest": "sha512:abc123"}
        assets = [asset]
        result = find_sha256(asset, assets)
        self.assertIsNone(result)


class TestFindZsyncUrl(unittest.TestCase):
    def test_finds_zsync(self):
        assets = [
            {"name": "app.AppImage", "browser_download_url": "http://example.com/app.AppImage"},
            {"name": "app.AppImage.zsync", "browser_download_url": "http://example.com/app.AppImage.zsync"},
        ]
        result = find_zsync_url("app.AppImage", assets)
        self.assertEqual(result, "http://example.com/app.AppImage.zsync")

    def test_not_found(self):
        assets = [{"name": "app.AppImage", "browser_download_url": "http://example.com/app.AppImage"}]
        result = find_zsync_url("app.AppImage", assets)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
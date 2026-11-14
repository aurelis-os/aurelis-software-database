"""Unit tests for get_latest_appimages.py."""

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import detect_arch, find_sha256, find_zsync_url
from get_latest_appimages import (
    download_text,
    find_appimage_asset,
    insert_generated_fields,
)


class TestInsertGeneratedFields(unittest.TestCase):
    def test_insert_after_title_version_regex(self):
        data = {
            "id": "test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "version_regex": "v(.+)",
            "title_version_regex": "(.+)",
            "summary": "Test app",
        }
        updates = {"version": "1.0", "download_url": "http://example.com/app.AppImage"}
        result = insert_generated_fields(data, updates)
        keys = list(result.keys())
        self.assertEqual(keys.index("version"), keys.index("title_version_regex") + 1)

    def test_insert_after_version_regex(self):
        data = {
            "id": "test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "version_regex": "v(.+)",
            "summary": "Test app",
        }
        updates = {"version": "1.0", "download_url": "http://example.com/app.AppImage"}
        result = insert_generated_fields(data, updates)
        keys = list(result.keys())
        self.assertEqual(keys.index("version"), keys.index("version_regex") + 1)

    def test_old_generated_keys_removed(self):
        """Old sha256/zsync_url not in new updates must be gone."""
        data = {
            "id": "test",
            "repo": "owner/repo",
            "asset_suffix": ".AppImage",
            "version_regex": "v(.+)",
            "version": "1.0",
            "sha256": "old" * 16,
            "zsync_url": "https://example.com/old.zsync",
            "arch": "x86_64",
            "published_at": "2024-01-01T00:00:00Z",
            "version_changed_at": "2024-01-01T00:00:00Z",
            "download_url": "https://example.com/old.AppImage",
            "asset_name": "old.AppImage",
        }
        updates = {"version": "2.0", "download_url": "https://example.com/new.AppImage",
                   "asset_name": "new.AppImage", "arch": "x86_64",
                   "published_at": "2025-01-01T00:00:00Z",
                   "version_changed_at": "2025-01-01T00:00:00Z"}
        result = insert_generated_fields(data, updates)
        self.assertNotIn("sha256", result)
        self.assertNotIn("zsync_url", result)
        self.assertEqual(result["version"], "2.0")

    def test_canonical_key_order(self):
        """Generated keys appear in GENERATED canonical order."""
        from common import GENERATED
        data = {"id": "x", "repo": "a/b", "asset_suffix": ".AppImage", "version_regex": "v(.+)"}
        updates = {"version": "1.0", "arch": "x86_64", "published_at": "2025-01-01T00:00:00Z",
                   "download_url": "https://x.com/a.AppImage", "asset_name": "a.AppImage",
                   "version_changed_at": "2025-01-01T00:00:00Z"}
        result = insert_generated_fields(data, updates)
        gen_keys = [k for k in result if k in set(GENERATED)]
        expected = [g for g in GENERATED if g in updates]
        self.assertEqual(gen_keys, expected)

    def test_idempotent(self):
        """Running twice produces no diff."""
        data = {"id": "x", "repo": "a/b", "asset_suffix": ".AppImage", "version_regex": "v(.+)"}
        updates = {"version": "1.0", "arch": "x86_64", "published_at": "2025-01-01T00:00:00Z",
                   "download_url": "https://x.com/a.AppImage", "asset_name": "a.AppImage",
                   "version_changed_at": "2025-01-01T00:00:00Z"}
        first = insert_generated_fields(data, updates)
        second = insert_generated_fields(first, updates)
        self.assertEqual(first, second)

    def test_append_if_neither_key(self):
        data = {"id": "test", "repo": "owner/repo", "asset_suffix": ".AppImage"}
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


class TestDownloadText(unittest.TestCase):
    def _make_response(self, content: bytes):
        import io
        resp = unittest.mock.MagicMock()
        resp.read.return_value = content
        resp.__enter__ = lambda s: s
        resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        return resp

    def test_no_auth_for_non_api_url(self):
        resp = self._make_response(b"hash  file")
        with unittest.mock.patch("urllib.request.urlopen", return_value=resp), \
             unittest.mock.patch("urllib.request.Request") as MockReq:
            MockReq.return_value = unittest.mock.MagicMock()
            download_text("https://objects.githubusercontent.com/file.sha256")
            call_headers = MockReq.call_args[1].get("headers") or MockReq.call_args[0][1]
            self.assertNotIn("Authorization", call_headers)

    def test_auth_for_api_url(self):
        resp = self._make_response(b'{"tag_name": "v1"}')
        with unittest.mock.patch("urllib.request.urlopen", return_value=resp), \
             unittest.mock.patch("urllib.request.Request") as MockReq, \
             unittest.mock.patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            MockReq.return_value = unittest.mock.MagicMock()
            download_text("https://api.github.com/repos/x/y/releases/latest")
            call_headers = MockReq.call_args[1].get("headers") or MockReq.call_args[0][1]
            self.assertIn("Authorization", call_headers)
            self.assertIn("tok", call_headers["Authorization"])


class TestFindSha256Legacy(unittest.TestCase):
    def test_from_digest(self):
        h = "a" * 64
        asset = {"name": "app.AppImage", "digest": f"sha256:{h}"}
        self.assertEqual(find_sha256(asset, [asset]), h)

    def test_digest_not_sha256(self):
        asset = {"name": "app.AppImage", "digest": "sha512:abc123"}
        self.assertIsNone(find_sha256(asset, [asset]))


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
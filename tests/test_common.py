#!/usr/bin/env python3
"""Unit tests for common.py helpers."""

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import (
    write_json,
    load_json,
    detect_arch,
    normalize_description,
    normalize_keywords,
    normalize_categories,
    normalize_screenshots,
    extract_version,
    compute_version_changed_at,
    find_zsync_url,
    reproducible_tar_add,
    create_reproducible_tar_gz,
    format_generated_at,
)


class TestWriteJson(unittest.TestCase):
    def test_write_json_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            data = {"key": "value"}
            result = write_json(path, data)
            self.assertTrue(result)
            self.assertTrue(path.exists())
            loaded = load_json(path)
            self.assertEqual(loaded, data)

    def test_write_json_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            data = {"key": "value"}
            write_json(path, data)
            result = write_json(path, data)
            self.assertFalse(result)  # Should return False when unchanged


class TestDetectArch(unittest.TestCase):
    def test_x86_64_variants(self):
        self.assertEqual(detect_arch("app-x86_64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app-x86-64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app-amd64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app-x64.AppImage"), "x86_64")
        self.assertEqual(detect_arch("x86_64-app.AppImage"), "x86_64")
        self.assertEqual(detect_arch("app_x86_64.AppImage"), "x86_64")

    def test_aarch64_variants(self):
        self.assertEqual(detect_arch("app-aarch64.AppImage"), "aarch64")
        self.assertEqual(detect_arch("app-arm64.AppImage"), "aarch64")

    def test_armv7l_variants(self):
        self.assertEqual(detect_arch("app-armv7l.AppImage"), "armv7l")
        self.assertEqual(detect_arch("app-armv7.AppImage"), "armv7l")
        self.assertEqual(detect_arch("app-armhf.AppImage"), "armv7l")

    def test_i686_variants(self):
        self.assertEqual(detect_arch("app-i386.AppImage"), "i686")
        self.assertEqual(detect_arch("app-i686.AppImage"), "i686")

    def test_no_arch(self):
        self.assertIsNone(detect_arch("app-universal.AppImage"))
        self.assertIsNone(detect_arch("app.AppImage"))

    def test_arch_embedded_in_word(self):
        # Should not match when embedded in longer word
        self.assertIsNone(detect_arch("app-x86_64foo.AppImage"))
        self.assertIsNone(detect_arch("app-foox86_64.AppImage"))


class TestNormalizeDescription(unittest.TestCase):
    def test_joins_soft_wrapped_lines(self):
        text = "Line one\n      continues here\n\nParagraph two"
        result = normalize_description(text)
        self.assertEqual(result, "Line one continues here\nParagraph two")

    def test_collapses_spaces(self):
        text = "Multiple    spaces   here"
        result = normalize_description(text)
        self.assertEqual(result, "Multiple spaces here")

    def test_drops_flatpak_boilerplate(self):
        text = "This flatpak is community maintained.\n\nReal description here."
        result = normalize_description(text)
        self.assertEqual(result, "Real description here.")

    def test_drops_this_application_boilerplate(self):
        text = "This application is a flatpak.\n\nReal description."
        result = normalize_description(text)
        self.assertEqual(result, "Real description.")

    def test_preserves_paragraphs(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        result = normalize_description(text)
        self.assertEqual(result, "Para one.\nPara two.\nPara three.")

    def test_handles_none(self):
        self.assertIsNone(normalize_description(None))
        self.assertIsNone(normalize_description(""))


class TestNormalizeKeywords(unittest.TestCase):
    def test_trims_and_dedupes(self):
        keywords = ["  email  ", "internet", "Email", "  "]
        result = normalize_keywords(keywords)
        self.assertEqual(result, ["email", "internet"])

    def test_keeps_order(self):
        keywords = ["zebra", "apple", "banana", "apple"]
        result = normalize_keywords(keywords)
        self.assertEqual(result, ["zebra", "apple", "banana"])

    def test_handles_none(self):
        self.assertEqual(normalize_keywords(None), [])
        self.assertEqual(normalize_keywords([]), [])


class TestNormalizeCategories(unittest.TestCase):
    def test_trims_and_dedupes(self):
        cats = ["  Development  ", "IDE", "development", "  "]
        result = normalize_categories(cats)
        self.assertEqual(result, ["Development", "IDE"])

    def test_handles_none(self):
        self.assertEqual(normalize_categories(None), [])


class TestNormalizeScreenshots(unittest.TestCase):
    def test_converts_width_height_to_int(self):
        shots = [{
            "default": True,
            "caption": "Test",
            "images": [{"type": "source", "width": "800", "height": "600", "url": "http://example.com/img.png"}]
        }]
        result = normalize_screenshots(shots)
        self.assertEqual(result[0]["images"][0]["width"], 800)
        self.assertEqual(result[0]["images"][0]["height"], 600)

    def test_drops_images_without_url(self):
        shots = [{
            "default": True,
            "images": [
                {"type": "source", "width": "800", "height": "600", "url": "http://example.com/img.png"},
                {"type": "thumb", "width": "400", "height": "300", "url": ""},
            ]
        }]
        result = normalize_screenshots(shots)
        self.assertEqual(len(result[0]["images"]), 1)

    def test_drops_screenshots_without_images(self):
        shots = [
            {"default": True, "images": []},
            {"default": False, "images": [{"url": "http://example.com/img.png"}]}
        ]
        result = normalize_screenshots(shots)
        self.assertEqual(len(result), 1)

    def test_first_default_wins(self):
        shots = [
            {"default": True, "images": [{"url": "http://example.com/1.png"}]},
            {"default": True, "images": [{"url": "http://example.com/2.png"}]},
        ]
        result = normalize_screenshots(shots)
        self.assertTrue(result[0]["default"])
        self.assertFalse(result[1]["default"])

    def test_forces_default_if_none(self):
        shots = [
            {"default": False, "images": [{"url": "http://example.com/1.png"}]},
            {"default": False, "images": [{"url": "http://example.com/2.png"}]},
        ]
        result = normalize_screenshots(shots)
        self.assertTrue(result[0]["default"])

    def test_handles_invalid_width_height(self):
        shots = [{
            "default": True,
            "images": [{"type": "source", "width": "abc", "height": "xyz", "url": "http://example.com/img.png"}]
        }]
        result = normalize_screenshots(shots)
        self.assertEqual(result[0]["images"][0]["width"], 0)
        self.assertEqual(result[0]["images"][0]["height"], 0)


class TestExtractVersion(unittest.TestCase):
    def test_tag_regex_hit(self):
        version, source = extract_version("v1.2.3", r"v?([0-9.]+)", "Title", None)
        self.assertEqual(version, "1.2.3")
        self.assertEqual(source, "tag")

    def test_tag_regex_no_group(self):
        version, source = extract_version("v1.2.3", r"v[0-9.]+", "Title", None)
        self.assertEqual(version, "v1.2.3")
        self.assertEqual(source, "tag")

    def test_title_fallback(self):
        version, source = extract_version("latest", None, "App 2026.3", r"([0-9.]+)")
        self.assertEqual(version, "2026.3")
        self.assertEqual(source, "title")

    def test_raw_tag_fallback(self):
        version, source = extract_version("v1.2.3", None, "Title", None)
        self.assertEqual(version, "1.2.3")
        self.assertEqual(source, "fallback")

    def test_raw_tag_no_v(self):
        version, source = extract_version("1.2.3", None, "Title", None)
        self.assertEqual(version, "1.2.3")
        self.assertEqual(source, "fallback")


class TestComputeVersionChangedAt(unittest.TestCase):
    def test_first_sight(self):
        result = compute_version_changed_at(None, "1.0", "abc", "2026-01-01T00:00:00Z")
        self.assertEqual(result, "2026-01-01T00:00:00Z")

    def test_same_version(self):
        existing = {"version": "1.0", "sha256": "abc", "version_changed_at": "2026-01-01T00:00:00Z"}
        result = compute_version_changed_at(existing, "1.0", "abc", "2026-01-02T00:00:00Z")
        self.assertEqual(result, "2026-01-01T00:00:00Z")

    def test_new_version(self):
        existing = {"version": "1.0", "sha256": "abc", "version_changed_at": "2026-01-01T00:00:00Z"}
        result = compute_version_changed_at(existing, "2.0", "def", "2026-01-02T00:00:00Z")
        self.assertEqual(result, "2026-01-02T00:00:00Z")

    def test_same_version_new_sha(self):
        existing = {"version": "1.0", "sha256": "abc", "version_changed_at": "2026-01-01T00:00:00Z"}
        result = compute_version_changed_at(existing, "1.0", "def", "2026-01-02T00:00:00Z")
        self.assertEqual(result, "2026-01-02T00:00:00Z")

    def test_latest_with_new_date(self):
        existing = {"version": "latest", "published_at": "2026-01-01T00:00:00Z", "version_changed_at": "2026-01-01T00:00:00Z"}
        result = compute_version_changed_at(existing, "latest", "abc", "2026-01-02T00:00:00Z")
        self.assertEqual(result, "2026-01-02T00:00:00Z")

    def test_latest_same_date(self):
        existing = {"version": "latest", "published_at": "2026-01-01T00:00:00Z", "version_changed_at": "2026-01-01T00:00:00Z"}
        result = compute_version_changed_at(existing, "latest", "abc", "2026-01-01T00:00:00Z")
        self.assertEqual(result, "2026-01-01T00:00:00Z")


class TestFindZsyncUrl(unittest.TestCase):
    def test_present(self):
        assets = [
            {"name": "app.AppImage", "browser_download_url": "http://example.com/app.AppImage"},
            {"name": "app.AppImage.zsync", "browser_download_url": "http://example.com/app.AppImage.zsync"},
        ]
        result = find_zsync_url("app.AppImage", assets)
        self.assertEqual(result, "http://example.com/app.AppImage.zsync")

    def test_absent(self):
        assets = [{"name": "app.AppImage", "browser_download_url": "http://example.com/app.AppImage"}]
        result = find_zsync_url("app.AppImage", assets)
        self.assertIsNone(result)

    def test_different_name_no_match(self):
        assets = [{"name": "other.zsync", "browser_download_url": "http://example.com/other.zsync"}]
        result = find_zsync_url("app.AppImage", assets)
        self.assertIsNone(result)


class TestReproducibleTar(unittest.TestCase):
    def test_create_reproducible_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create test files
            file1 = tmpdir / "file1.txt"
            file1.write_text("content1")
            file2 = tmpdir / "file2.txt"
            file2.write_text("content2")

            output = tmpdir / "archive.tar.gz"
            create_reproducible_tar_gz(output, [(file1, "file1.txt"), (file2, "file2.txt")])

            self.assertTrue(output.exists())

            # Verify contents
            import tarfile
            with tarfile.open(output, "r:gz") as tar:
                names = sorted(tar.getnames())
                self.assertEqual(names, ["file1.txt", "file2.txt"])
                # Check mtime is 0
                for member in tar.getmembers():
                    self.assertEqual(member.mtime, 0)
                    self.assertEqual(member.uid, 0)
                    self.assertEqual(member.gid, 0)


class TestFormatGeneratedAt(unittest.TestCase):
    def test_format(self):
        # Just test it returns a string in ISO format
        result = format_generated_at(1700000000)
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
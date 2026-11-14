"""Unit tests for flatpak_sync.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from flatpak_sync import FLATHUB_FIELDS, is_empty_value, normalize_flathub_data


class TestNormalizeFlathubData(unittest.TestCase):
    def test_normalizes_description(self):
        data = {"description": "Line one\n      continues\nPara two"}
        result = normalize_flathub_data(data)
        self.assertEqual(result["description"], "Line one continues\nPara two")

    def test_normalizes_keywords(self):
        data = {"keywords": ["  email  ", "internet", "Email"]}
        result = normalize_flathub_data(data)
        self.assertEqual(result["keywords"], ["email", "internet"])

    def test_normalizes_categories(self):
        data = {"categories": ["  Development  ", "IDE", "development"]}
        result = normalize_flathub_data(data)
        self.assertEqual(result["categories"], ["Development", "IDE"])

    def test_normalizes_screenshots(self):
        data = {
            "screenshots": [{
                "default": True,
                "images": [{"type": "source", "width": "800", "height": "600", "url": "http://example.com/img.png"}]
            }]
        }
        result = normalize_flathub_data(data)
        self.assertEqual(result["screenshots"][0]["images"][0]["width"], 800)
        self.assertEqual(result["screenshots"][0]["images"][0]["height"], 600)

    def test_preserves_other_fields(self):
        data = {"name": "Test", "custom_field": "value"}
        result = normalize_flathub_data(data)
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["custom_field"], "value")


class TestIsEmptyValue(unittest.TestCase):
    def test_none(self):
        self.assertTrue(is_empty_value(None))

    def test_empty_list(self):
        self.assertTrue(is_empty_value([]))

    def test_empty_dict(self):
        self.assertTrue(is_empty_value({}))

    def test_empty_string(self):
        self.assertTrue(is_empty_value(""))

    def test_non_empty(self):
        self.assertFalse(is_empty_value("value"))
        self.assertFalse(is_empty_value([1]))
        self.assertFalse(is_empty_value({"a": 1}))
        self.assertFalse(is_empty_value(0))
        self.assertFalse(is_empty_value(False))


class TestFlathubFields(unittest.TestCase):
    def test_flathub_fields_defined(self):
        expected = {"name", "summary", "description", "developer", "license",
                    "categories", "keywords", "urls", "screenshots"}
        self.assertEqual(FLATHUB_FIELDS, expected)


if __name__ == "__main__":
    unittest.main()
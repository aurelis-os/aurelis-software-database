#!/usr/bin/env python3
"""Unit tests for flatpak_xml_to_json.py."""

import gzip
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from flatpak_xml_to_json import parse_component, parse_keywords, parse_developer


# Sample AppStream XML for testing
SAMPLE_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>org.kde.kate.desktop</id>
    <name>Kate</name>
    <summary>Advanced text editor</summary>
    <description>
      <p>Kate is a fast multi-document editor.</p>
      <p>It supports syntax highlighting.</p>
    </description>
    <developer>
      <name>KDE</name>
    </developer>
    <project_license>LGPL-2.1+</project_license>
    <categories>
      <category>Development</category>
      <category>TextEditor</category>
    </categories>
    <keywords>
      <keyword>text</keyword>
      <keyword>editor</keyword>
      <keyword>programming</keyword>
    </keywords>
    <keywords xml:lang="de">
      <keyword>text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <urls>
      <url type="homepage">https://kate-editor.org/</url>
    </urls>
    <icon type="cached">org.kde.kate.png</icon>
    <screenshots>
      <screenshot type="default">
        <caption>Editing code</caption>
        <image type="source" width="800" height="600">https://example.com/img.png</image>
      </screenshot>
    </screenshots>
  </component>
</components>
'''

SAMPLE_XML_WITH_BOILERPLATE = b'''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>com.example.app.desktop</id>
    <name>Example App</name>
    <summary>Test app</summary>
    <description>
      <p>This flatpak is community maintained and not officially endorsed.</p>
      <p>Real description paragraph one.</p>
      <p>Real description paragraph two continues here.</p>
    </description>
    <developer_name>Example Developer</developer_name>
    <project_license>MIT</project_license>
    <categories>
      <category>Utility</category>
    </categories>
    <keywords>
      <keyword>test</keyword>
      <keyword>example</keyword>
    </keywords>
    <icon type="cached">com.example.app.png</icon>
  </component>
</components>
'''

SAMPLE_XML_MULTILANG_KEYWORDS = b'''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>org.kde.kate.desktop</id>
    <name>Kate</name>
    <summary>Advanced text editor</summary>
    <description>
      <p>Kate is a fast multi-document editor.</p>
    </description>
    <keywords>
      <keyword>text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <keywords xml:lang="de">
      <keyword>text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <keywords xml:lang="fr">
      <keyword>texte</keyword>
      <keyword>editeur</keyword>
    </keywords>
    <icon type="cached">org.kde.kate.png</icon>
  </component>
</components>
'''


class TestParseKeywords(unittest.TestCase):
    def test_only_untranslated_keywords(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML_MULTILANG_KEYWORDS)
        comp = root.find("component")
        from flatpak_xml_to_json import parse_keywords
        keywords = parse_keywords(comp)
        # Should only get untranslated keywords (2), not German (2) or French (2)
        self.assertEqual(keywords, ["text", "editor"])


class TestParseDeveloper(unittest.TestCase):
    def test_developer_name_tag(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML)
        comp = root.find("component")
        from flatpak_xml_to_json import parse_developer
        dev = parse_developer(comp)
        self.assertEqual(dev, "KDE")

    def test_fallback_to_developer_name(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML_WITH_BOILERPLATE)
        comp = root.find("component")
        from flatpak_xml_to_json import parse_developer
        dev = parse_developer(comp)
        self.assertEqual(dev, "Example Developer")


class TestParseComponent(unittest.TestCase):
    def test_basic_parsing(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML)
        comp = root.find("component")
        data = parse_component(comp)

        self.assertEqual(data["id"], "org.kde.kate")
        self.assertEqual(data["name"], "Kate")
        self.assertEqual(data["summary"], "Advanced text editor")
        self.assertEqual(data["developer"], "KDE")
        self.assertEqual(data["license"], "LGPL-2.1+")
        self.assertEqual(data["categories"], ["Development", "TextEditor"])
        self.assertEqual(data["keywords"], ["text", "editor", "programming"])
        self.assertEqual(data["urls"], {"homepage": "https://kate-editor.org/"})
        self.assertEqual(data["icon"], {"type": "cached", "name": "org.kde.kate.png"})

    def test_description_normalization(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML_WITH_BOILERPLATE)
        comp = root.find("component")
        data = parse_component(comp)

        # Boilerplate should be dropped, paragraphs joined
        self.assertIn("Real description paragraph one", data["description"])
        self.assertIn("Real description paragraph two continues here", data["description"])
        self.assertNotIn("This flatpak is community maintained", data["description"])
        # Should have newline between paragraphs
        self.assertIn("\n", data["description"])

    def test_screenshots_normalization(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML)
        comp = root.find("component")
        data = parse_component(comp)

        shots = data["screenshots"]
        self.assertEqual(len(shots), 1)
        self.assertTrue(shots[0]["default"])
        self.assertEqual(shots[0]["caption"], "Editing code")
        self.assertEqual(len(shots[0]["images"]), 1)
        # Width/height should be ints
        self.assertEqual(shots[0]["images"][0]["width"], 800)
        self.assertEqual(shots[0]["images"][0]["height"], 600)

    def test_keywords_deduped(self):
        import xml.etree.ElementTree as ET
        # Create XML with duplicate keywords
        xml = b'''<?xml version="1.0"?>
<components>
  <component type="desktop-application">
    <id>test.desktop</id>
    <name>Test</name>
    <keywords>
      <keyword>text</keyword>
      <keyword>Text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <icon type="cached">test.png</icon>
  </component>
</components>'''
        root = ET.fromstring(xml)
        comp = root.find("component")
        data = parse_component(comp)
        # Should be case-insensitive deduped
        self.assertEqual(data["keywords"], ["text", "editor"])


if __name__ == "__main__":
    unittest.main()
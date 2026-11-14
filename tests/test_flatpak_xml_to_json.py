"""Unit tests for flatpak_xml_to_json.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from flatpak_xml_to_json import parse_component, parse_developer, parse_keywords

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
        keywords = parse_keywords(comp)
        # Should only get untranslated keywords (2), not German (2) or French (2)
        self.assertEqual(keywords, ["text", "editor"])


class TestParseDeveloper(unittest.TestCase):
    def test_developer_name_tag(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML)
        comp = root.find("component")
        dev = parse_developer(comp)
        self.assertEqual(dev, "KDE")

    def test_fallback_to_developer_name(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(SAMPLE_XML_WITH_BOILERPLATE)
        comp = root.find("component")
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

        # Boilerplate should be dropped, paragraphs joined with single \n
        self.assertIn("Real description paragraph one", data["description"])
        self.assertIn("Real description paragraph two continues here", data["description"])
        self.assertNotIn("This flatpak is community maintained", data["description"])
        # Should have newline between paragraphs
        self.assertIn("\n", data["description"])
        # Must NOT have double newline
        self.assertNotIn("\n\n", data["description"])

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


class TestI18n(unittest.TestCase):
    def test_i18n_parsing(self):
        """Test parsing of translated fields for specified languages."""
        import xml.etree.ElementTree as ET
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>org.kde.kate.desktop</id>
    <name>Kate</name>
    <name xml:lang="el">Κάτε</name>
    <name xml:lang="de">Kate</name>
    <summary>Advanced text editor</summary>
    <summary xml:lang="el">Προηγμένος επεξεργαστής κειμένου</summary>
    <description>
      <p>Kate is a fast multi-document editor.</p>
    </description>
    <description xml:lang="el">
      <p>Το Kate είναι ένας γρήγορες πολυ-έγγραφος επεξεργαστής.</p>
    </description>
    <keywords>
      <keyword>text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <keywords xml:lang="el">
      <keyword>κείμενο</keyword>
      <keyword>επεξεργαστής</keyword>
    </keywords>
    <keywords xml:lang="de">
      <keyword>text</keyword>
      <keyword>editor</keyword>
    </keywords>
    <icon type="cached">org.kde.kate.png</icon>
  </component>
</components>'''
        root = ET.fromstring(xml)
        comp = root.find("component")
        data = parse_component(comp, langs=["el", "de"])
        
        # Base fields should be untranslated
        self.assertEqual(data["name"], "Kate")
        self.assertEqual(data["summary"], "Advanced text editor")
        self.assertEqual(data["keywords"], ["text", "editor"])
        
        # i18n should contain Greek and German translations
        self.assertIn("i18n", data)
        self.assertIn("el", data["i18n"])
        self.assertIn("de", data["i18n"])
        
        # Greek translations
        self.assertEqual(data["i18n"]["el"]["name"], "Κάτε")
        self.assertEqual(data["i18n"]["el"]["summary"], "Προηγμένος επεξεργαστής κειμένου")
        self.assertEqual(data["i18n"]["el"]["keywords"], ["κείμενο", "επεξεργαστής"])
        self.assertIn("description", data["i18n"]["el"])
        
        # German translations (name and keywords in this test)
        self.assertEqual(data["i18n"]["de"]["name"], "Kate")
        self.assertEqual(data["i18n"]["de"]["keywords"], ["text", "editor"])
        # German has no summary in the XML, so it shouldn't be in i18n
        self.assertNotIn("summary", data["i18n"]["de"])

    def test_i18n_empty_lang_not_included(self):
        """Test that languages with no translated fields are not included."""
        import xml.etree.ElementTree as ET
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>test.desktop</id>
    <name>Test</name>
    <summary>Test app</summary>
    <icon type="cached">test.png</icon>
  </component>
</components>'''
        root = ET.fromstring(xml)
        comp = root.find("component")
        data = parse_component(comp, langs=["el"])
        
        # No i18n because no Greek translations exist
        self.assertNotIn("i18n", data)

    def test_i18n_keywords_normalized(self):
        """Test that i18n keywords are normalized (deduped)."""
        import xml.etree.ElementTree as ET
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>test.desktop</id>
    <name>Test</name>
    <name xml:lang="el">Δοκιμή</name>
    <keywords>
      <keyword>text</keyword>
    </keywords>
    <keywords xml:lang="el">
      <keyword>κείμενο</keyword>
      <keyword>Κείμενο</keyword>
      <keyword>editor</keyword>
    </keywords>
    <icon type="cached">test.png</icon>
  </component>
</components>'''
        root = ET.fromstring(xml)
        comp = root.find("component")
        data = parse_component(comp, langs=["el"])
        
        # Greek keywords should be case-insensitive deduped
        self.assertEqual(data["i18n"]["el"]["keywords"], ["κείμενο", "editor"])

    def test_i18n_multiple_langs(self):
        """Test multiple languages in --langs argument."""
        import xml.etree.ElementTree as ET
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>test.desktop</id>
    <name>Test</name>
    <name xml:lang="el">Δοκιμή</name>
    <name xml:lang="fr">Test</name>
    <name xml:lang="de">Test</name>
    <summary>Test app</summary>
    <summary xml:lang="el">Εφαρμογή δοκιμής</summary>
    <icon type="cached">test.png</icon>
  </component>
</components>'''
        root = ET.fromstring(xml)
        comp = root.find("component")
        data = parse_component(comp, langs=["el", "fr", "de"])
        
        self.assertIn("i18n", data)
        self.assertIn("el", data["i18n"])
        self.assertIn("fr", data["i18n"])
        self.assertIn("de", data["i18n"])
        
        self.assertEqual(data["i18n"]["el"]["name"], "Δοκιμή")
        self.assertEqual(data["i18n"]["el"]["summary"], "Εφαρμογή δοκιμής")
        self.assertEqual(data["i18n"]["fr"]["name"], "Test")
        self.assertEqual(data["i18n"]["de"]["name"], "Test")


if __name__ == "__main__":
    unittest.main()
#!/usr/bin/env python3
"""Convert Flathub AppStream XML into one flat JSON file per app ID."""

import argparse
import gzip
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Import shared helpers
sys.path.insert(0, str(Path(__file__).parent))
from common import (
    normalize_categories,
    normalize_description,
    normalize_keywords,
    normalize_screenshots,
    write_json,
)

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def text_of(elem):
    """Return all text inside an element, flattening child tags like <p>, <li>."""
    if elem is None:
        return None
    parts = []
    for node in elem.iter():
        if node.tag in ("p", "li") and node.text or node is elem and node.text and node.text.strip():
            parts.append(node.text.strip())
    # Join paragraphs with double newline for proper paragraph separation
    return "\n\n".join(parts) if parts else None


def localized(parent, tag):
    """Return the untranslated (no xml:lang) text of a child tag."""
    for el in parent.findall(tag):
        if not el.attrib.get(XML_LANG):
            return (el.text or "").strip() or None
    return None


def localized_for_lang(parent, tag, lang):
    """Return the text of a child tag for a specific language."""
    for el in parent.findall(tag):
        if el.attrib.get(XML_LANG) == lang:
            return (el.text or "").strip() or None
    return None


def localized_description(parent):
    for el in parent.findall("description"):
        if not el.attrib.get(XML_LANG):
            return text_of(el)
    return None


def localized_description_for_lang(parent, lang):
    for el in parent.findall("description"):
        if el.attrib.get(XML_LANG) == lang:
            return text_of(el)
    return None


def parse_keywords(comp):
    """Extract keywords only from <keywords> blocks without xml:lang."""
    keywords = []
    for kw_block in comp.findall("keywords"):
        if kw_block.attrib.get(XML_LANG):
            continue
        for kw in kw_block.findall("keyword"):
            if kw.text and kw.text.strip():
                keywords.append(kw.text.strip())
    return keywords


def parse_keywords_for_lang(comp, lang):
    """Extract keywords from <keywords> blocks with specific xml:lang."""
    keywords = []
    for kw_block in comp.findall("keywords"):
        if kw_block.attrib.get(XML_LANG) != lang:
            continue
        for kw in kw_block.findall("keyword"):
            if kw.text and kw.text.strip():
                keywords.append(kw.text.strip())
    return keywords


def parse_developer(comp):
    """Extract developer from <developer><name> (untranslated) with fallback to <developer_name>."""
    # Try <developer><name> without xml:lang
    for dev in comp.findall("developer"):
        if dev.attrib.get(XML_LANG):
            continue
        name_el = dev.find("name")
        if name_el is not None and name_el.text and name_el.text.strip():
            return name_el.text.strip()
    # Fallback to developer_name
    return localized(comp, "developer_name")


def parse_component(comp, langs=None):
    app_id = (comp.findtext("id") or "").strip()
    if not app_id:
        return None
    app_id = app_id.removesuffix(".desktop")

    screenshots = []
    for shot in comp.findall("screenshots/screenshot"):
        images = []
        for img in shot.findall("image"):
            images.append({
                "type": img.attrib.get("type"),
                "width": img.attrib.get("width"),
                "height": img.attrib.get("height"),
                "url": (img.text or "").strip(),
            })
        screenshots.append({
            "default": shot.attrib.get("type") == "default",
            "caption": localized(shot, "caption"),
            "images": images,
        })

    urls = {u.attrib.get("type", "homepage"): (u.text or "").strip()
            for u in comp.findall("urls/url")}

    icon = None
    for ic in comp.findall("icon"):
        if ic.attrib.get("type") in ("cached", "remote") or icon is None:
            icon = {"type": ic.attrib.get("type"), "name": (ic.text or "").strip()}

    # Parse raw data
    raw_keywords = parse_keywords(comp)
    raw_categories = [c.text for c in comp.findall("categories/category") if c.text]
    raw_description = localized_description(comp)
    raw_screenshots = screenshots

    # Normalize using shared helpers
    norm_keywords = normalize_keywords(raw_keywords)
    norm_categories = normalize_categories(raw_categories)
    norm_description = normalize_description(raw_description)
    norm_screenshots = normalize_screenshots(raw_screenshots)

    # Build base entry
    entry = {
        "id": app_id,
        "name": localized(comp, "name"),
        "summary": localized(comp, "summary"),
        "description": norm_description,
        "developer": parse_developer(comp),
        "license": (comp.findtext("project_license") or "").strip() or None,
        "categories": norm_categories,
        "keywords": norm_keywords,
        "urls": urls,
        "icon": icon,
        "screenshots": norm_screenshots,
    }

    # Add i18n data for requested languages
    if langs:
        i18n = {}
        for lang in langs:
            name = localized_for_lang(comp, "name", lang)
            summary = localized_for_lang(comp, "summary", lang)
            keywords = parse_keywords_for_lang(comp, lang)
            description = localized_description_for_lang(comp, lang)
            
            # Only add if we have at least one translated field
            if name or summary or keywords or description:
                i18n[lang] = {}
                if name:
                    i18n[lang]["name"] = name
                if summary:
                    i18n[lang]["summary"] = summary
                if keywords:
                    i18n[lang]["keywords"] = normalize_keywords(keywords)
                if description:
                    i18n[lang]["description"] = normalize_description(description)
        
        if i18n:
            entry["i18n"] = i18n

    return entry


def load_xml(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        return ET.parse(f).getroot()


def find_icon(icons_dir, icon):
    if not icons_dir or not icon or not icon.get("name"):
        return None
    name = icon["name"]
    for candidate in (name, f"{name}.png"):
        p = Path(icons_dir) / candidate
        if p.is_file():
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True, help="appstream.xml or .xml.gz")
    ap.add_argument("--icons", help="folder with 128x128 icons")
    ap.add_argument("--out", default="Flatpak Info")
    ap.add_argument("--langs", default="el", help="Comma-separated list of language codes to include (default: el)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Parse languages
    langs = [lang.strip() for lang in args.langs.split(",") if lang.strip()]

    root = load_xml(args.xml)
    written = skipped = 0

    for comp in root.findall("component"):
        data = parse_component(comp, langs)
        if not data:
            continue
        app_id = data["id"]
        target = out / f"{app_id}.json"

        if write_json(target, data):
            written += 1
        else:
            skipped += 1

        icon_file = find_icon(args.icons, data["icon"])
        if icon_file:
            dest = out / f"{app_id}.png"
            if not dest.exists() or dest.read_bytes() != icon_file.read_bytes():
                shutil.copyfile(icon_file, dest)

    print(f"Done: {written} written, {skipped} unchanged -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
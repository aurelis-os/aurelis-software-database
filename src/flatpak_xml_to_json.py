#!/usr/bin/env python3
"""Convert Flathub AppStream XML into one flat JSON file per app ID."""

import argparse
import gzip
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def text_of(elem):
    """Return all text inside an element, flattening child tags like <p>, <li>."""
    if elem is None:
        return None
    parts = []
    for node in elem.iter():
        if node.tag in ("p", "li") and node.text or node is elem and node.text and node.text.strip():
            parts.append(node.text.strip())
    return "\n".join(parts) if parts else None


def localized(parent, tag):
    """Return the untranslated (no xml:lang) text of a child tag."""
    for el in parent.findall(tag):
        if not el.attrib.get(XML_LANG):
            return (el.text or "").strip() or None
    return None


def localized_description(parent):
    for el in parent.findall("description"):
        if not el.attrib.get(XML_LANG):
            return text_of(el)
    return None


def parse_component(comp):
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
            for u in comp.findall("url")}

    icon = None
    for ic in comp.findall("icon"):
        if ic.attrib.get("type") in ("cached", "remote") or icon is None:
            icon = {"type": ic.attrib.get("type"), "name": (ic.text or "").strip()}

    return {
        "id": app_id,
        "name": localized(comp, "name"),
        "summary": localized(comp, "summary"),
        "description": localized_description(comp),
        "developer": localized(comp, "developer_name"),
        "license": (comp.findtext("project_license") or "").strip() or None,
        "categories": [c.text for c in comp.findall("categories/category") if c.text],
        "keywords": [k.text for k in comp.findall("keywords/keyword")
                     if k.text and not k.attrib.get(XML_LANG)],
        "urls": urls,
        "icon": icon,
        "screenshots": screenshots,
    }


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
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    root = load_xml(args.xml)
    written = skipped = 0

    for comp in root.findall("component"):
        data = parse_component(comp)
        if not data:
            continue
        app_id = data["id"]
        target = out / f"{app_id}.json"

        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") == new_text:
            skipped += 1
        else:
            target.write_text(new_text, encoding="utf-8")
            written += 1

        icon_file = find_icon(args.icons, data["icon"])
        if icon_file:
            dest = out / f"{app_id}.png"
            if not dest.exists() or dest.read_bytes() != icon_file.read_bytes():
                shutil.copyfile(icon_file, dest)

    print(f"Done: {written} written, {skipped} unchanged -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
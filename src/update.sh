#!/bin/bash
set -e

# Install flatpak if not present
if ! command -v flatpak &> /dev/null; then
    sudo pacman -S flatpak
fi

# Add flathub remote if not exists
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

# Update appstream
flatpak update --appstream

# Convert flatpak XML to JSON
python3 src/flatpak_xml_to_json.py --xml /var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz --icons /var/lib/flatpak/appstream/flathub/x86_64/active/icons/128x128 --out "data/all"

# Sync flatpak apps
python3 src/flatpak_sync.py --mine data/apps --flatpak "data/all"

# Get latest AppImages
python3 src/get_latest_appimages.py
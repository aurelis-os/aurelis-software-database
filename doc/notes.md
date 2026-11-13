Install flathub
```sh
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

Download info
```sh
flatpak update --appstream
```

Split/Export ids from xml
```sh
python3 src/flatpak_xml_to_json.py --xml /var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz --icons /var/lib/flatpak/appstream/flathub/x86_64/active/icons/128x128 --out "data/all"
```

```sh
python3 src/flatpak_sync.py --mine data/apps --flatpak "data/all"
```

Find latest and update info download

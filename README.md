# Aurelis Software Database

This repository produces the software catalog for the Aurelis Software GUI and the `app` AppImage integrator.

## Pipeline Overview

```
Flathub AppStream XML          GitHub Releases API
       |                              |
flatpak_xml_to_json.py         get_latest_appimages.py
       |                              |
       v                              v
   flatpak_sync.py  --------->  data/apps/<id>.json  <---- add-app.py
    (Flathub fields +              (single source of truth,
     icon -> data/icons)             committed to git)
           |
   build-database.py
     normalize -> validate -> write
           |
   data/output/apps.db + .tar.gz
   data/output/app-icons.tar.gz  <-- pack-icons.py
           |
   GitHub release "latest"  --> Software GUI / `app`
```

## Adding a New App

Use the `add-app.py` tool to add a new app to the database:

```bash
src/add-app.py <flathub-id> --repo owner/name --suffix <asset_suffix> --version-regex '<regex>' [--title-version-regex ...]
```

### Required Arguments

- `<flathub-id>`: The Flathub app ID (e.g., `org.kde.kate`)
- `--repo`: GitHub repository in format `owner/name` (e.g., `pkgforge-dev/Kate-AppImage-Enhanced`)
- `--suffix`: AppImage asset suffix to match (e.g., `-anylinux-x86_64.AppImage`)
- `--version-regex`: Regex to extract version from release tag (group 1 or whole match)

### Optional Arguments

- `--title-version-regex`: Fallback regex to extract version from release title (for rolling tags like `latest`)
- `--apps-dir`: Apps directory (default: `data/apps`)
- `--flatpak-dir`: Flatpak export directory (default: `data/all`)
- `--icons-dir`: Icons directory (default: `data/icons`)
- `--dry-run`: Don't write changes
- `--skip-fetch`: Skip fetching latest release from GitHub
- `--skip-validation`: Skip validation

### Example

```bash
# Add Kate
src/add-app.py org.kde.kate \
  --repo pkgforge-dev/Kate-AppImage-Enhanced \
  --suffix "-anylinux-x86_64.AppImage" \
  --version-regex "([0-9.]+-[0-9]+)@"

# Add PhpStorm (rolling tag, needs title fallback)
src/add-app.py com.jetbrains.PhpStorm \
  --repo pkgforge-dev/PhpStorm-AppImage \
  --suffix "-anylinux-x86_64.AppImage" \
  --version-regex "latest" \
  --title-version-regex "PhpStorm ([0-9.]+)"
```

### What the tool does

1. Creates `data/apps/<id>.json` with curated fields only (`id`, `repo`, `asset_suffix`, `version_regex`, `title_version_regex`)
2. Merges Flathub fields from `data/all/<id>.json` (name, summary, description, developer, license, categories, keywords, urls, screenshots)
3. Copies the icon from `data/all/<id>.png` to `data/icons/<id>.png`
4. Runs `get_latest_appimages.py` for that app to fetch the latest release info
5. Validates the entry and prints a summary

## Updating the Database

Run the full update pipeline:

```bash
./update
```

This runs:
1. `flatpak update --appstream` (updates Flathub appstream)
2. `flatpak_xml_to_json.py` (exports Flathub data to `data/all/`)
3. `flatpak_sync.py` (merges Flathub fields into `data/apps/`)
4. `get_latest_appimages.py` (fetches latest GitHub releases)
5. `build-database.py --check` (validates)

## Building the Release Artifacts

```bash
src/build-database.py --apps data/apps --icons data/icons --out data/output
src/pack-icons.py --icons data/icons --out data/output
```

This creates:
- `data/output/apps.db` - JSON database with envelope
- `data/output/apps.db.tar.gz` - Reproducible archive
- `data/output/app-icons.tar.gz` - Reproducible icon archive

## Validation

```bash
./check
```

Runs:
- `ruff check src/`
- `python3 -m unittest discover -s tests`
- `src/build-database.py --check`

## Field Ownership

| Field | Owner | Description |
|-------|-------|-------------|
| `id` | Curated | Flathub app ID, must match filename |
| `name` | Flathub | Overwritten from Flathub |
| `repo` | Curated | GitHub `owner/name` |
| `asset_suffix` | Curated | AppImage asset suffix |
| `version_regex` | Curated | Regex for version from tag |
| `title_version_regex` | Curated | Fallback regex for version from title |
| `version` | Generated | Extracted version |
| `download_url` | Generated | Asset download URL |
| `asset_name` | Generated | Asset filename |
| `size` | Generated | Asset size in bytes |
| `sha256` | Generated | SHA256 checksum |
| `zsync_url` | Generated | ZSync URL if available |
| `arch` | Generated | Detected architecture |
| `published_at` | Generated | Release publish date |
| `version_changed_at` | Generated | When version last changed |
| `summary` | Flathub | Short description |
| `description` | Flathub | Full description |
| `developer` | Flathub | Developer name |
| `license` | Flathub | SPDX license |
| `categories` | Flathub | freedesktop categories |
| `keywords` | Flathub | Untranslated keywords |
| `urls` | Flathub | AppStream URLs |
| `icon` | Flathub | `{"type":"cached","name":"<id>.png"}` |
| `screenshots` | Flathub | Screenshots with int dimensions |

## CI/CD
 
 - **ci.yml**: Runs on push/PR to main - runs `./check`
 - **build-and-release.yml**: Runs Friday 05:00 UTC and manual - builds and releases artifacts, commits data refresh
 
 ## Stale/Broken Detection
 
 The pipeline includes automated detection of stale and broken apps:
 
 - **Stale apps**: Apps that have failed to fetch updates for 3+ consecutive weeks (tracked via `last_ok_at` in `data/last_ok_report.json`)
 - **Old releases**: Apps whose latest release is older than 18 months
 
 These are reported in the CI job summary markdown.
 
 ## CI Job Summary
 
 The weekly build workflow generates a markdown summary including:
 - Updated apps list
 - Failed apps with errors
 - Version changes (old → new)
 - Warnings
 - Stale/broken detection results
 
 This summary is posted to the GitHub Actions job summary.
 
 ## Testing
 
 ```bash
 python3 -m unittest discover -s tests
 ```
 
 Tests use fixtures in `tests/fixtures/` and never touch the network.
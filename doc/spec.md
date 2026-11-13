# Aurelis Software Database: Architecture, Specification and Delivery Plan

Audience: a coding agent (Zoo Code in VS Code) working inside this repository.
Owner: apapamarkou. Repo: `aurelis-software-database`.

---

## 0. Rules for the agent

1. Work phase by phase (section 8). Finish a phase, run `./check`, then stop and report. Do not start the next phase unprompted.
2. Never hand-edit or "fix" curated fields in `data/apps/*.json` (section 4.2). Only the tools may change generated and Flathub-owned fields.
3. Tests never touch the network. Mock GitHub with fixtures in `tests/fixtures/`.
4. Every script is idempotent: running it twice produces zero diff the second time.
5. Python 3.11+, standard library only for runtime code. `ruff` and `unittest` are the only dev tools.
6. Small commits, one concern each, conventional messages (`fix:`, `feat:`, `test:`, `ci:`, `docs:`).
7. If a requirement here conflicts with what you find in the code, stop and ask. Do not guess.

---

## 1. Purpose

This repository produces the **software catalog** that the Aurelis Software GUI (PyQt6) and the `app` AppImage integrator consume. Every Friday, CI publishes two files as a GitHub release tagged `latest`:

| Asset | Content |
|---|---|
| `apps.db.tar.gz` | `apps.db`: one JSON document describing every catalog app |
| `app-icons.tar.gz` | one PNG per app, named exactly as `icon.name` in the entry |

The catalog is about 22 apps today and must scale to **about 500**.

Success criteria:

- A client can install any entry with no extra lookups: download URL, size, checksum, update source, architecture and version are all in the entry.
- A broken upstream (deleted repo, renamed asset) never produces a broken release.
- Adding an app is a one-file, one-command operation.

---

## 2. Current state (verified by reading the repo)

### 2.1 Layout

```
data/apps/<flathub-id>.json     one file per app (curated + Flathub + generated fields)
data/icons/<flathub-id>.png     128x128 icons
data/all/                       gitignored scratch: raw Flathub export
data/output/                    build products (currently tracked in git, should not be)
template/*.json                 hand-typed starting points for new apps
src/flatpak_xml_to_json.py      AppStream XML -> one JSON per Flathub id
src/flatpak_sync.py             Flathub JSON -> data/apps
src/get_latest_appimages.py     GitHub releases -> data/apps
src/build-database.py           data/apps -> apps.db(.tar.gz)
src/pack-icons.py               data/icons -> app-icons.tar.gz
src/check-icons.py              icon presence check
src/update.sh, ./update, ./check
.github/workflows/{ci,build-and-release}.yml
```

### 2.2 Owner's current manual workflow

1. Create a file in `template/` with `name`, `repo`, `asset_suffix`, `version_regex`.
2. Copy the Flathub-derived JSON for the app and merge it by hand with those lines into `data/apps/<id>.json`.
3. Run the script that finds the latest release.

Phase 4 automates exactly this.

### 2.3 Defects found (to be fixed in phases 1 to 3)

| # | Defect | Effect |
|---|---|---|
| D1 | `flatpak_sync.py` writes a nested `flathub` block, but `data/apps/*.json` are flat. | In CI every file gets a duplicate nested block on the first run. The released `apps.db` can differ from the local one. |
| D2 | `flatpak_sync.py` copies refreshed icons into `data/apps/`, but `pack-icons.py` packs `data/icons/`. | CI icon refreshes are never shipped. |
| D3 | `flatpak_xml_to_json.py` reads `keywords/keyword` from every language block. | Kate has 451 keywords, mostly translations. GIMP, Kid3 and KiCad are similar. |
| D4 | The same script reads `developer_name`, which Flathub no longer fills. | `developer` is null for almost every app. |
| D5 | Descriptions keep XML soft wraps (`\n` plus indentation) and Flathub boilerplate ("This flatpak is community maintained..."). | Ugly text, and wrong for an AppImage store. |
| D6 | Screenshots have string `width` and `height`, and several entries are `default: true` (GIMP 4, Krita 3). | Awkward for clients. |
| D7 | `title_version_regex` exists in PhpStorm's file but no script reads it. | PhpStorm stays at version `latest`, which can never be compared. |
| D8 | The fetch script sends no token and has no retry or rate-limit handling. | Unauthenticated GitHub API allows 60 requests/hour, so 500 apps fail. |
| D9 | The workflow never commits refreshed data back. | `version_changed_at` would reset to "now" every week. |
| D10 | `build-database.py` does no validation, writes a bare JSON array and a non-reproducible tarball. | Bad data ships silently. Clients cannot be versioned. A new release hash changes even if nothing changed. |
| D11 | `data/output/*` is tracked in git. | Noise in every commit. |

### 2.4 Work already drafted (UNTESTED)

Two files were drafted in an earlier session and **never executed**. Treat them as a starting point, not as finished code. Review, run and test them in Phase 0.

- `src/common.py` (new): JSON I/O, `detect_arch`, description, keyword and screenshot normalizers, reproducible tar writer.
- `src/get_latest_appimages.py` (rewritten): adds `size`, `sha256`, `zsync_url`, `arch`, `version_changed_at`, token auth, retries, rate-limit abort, parallel fetch, `--dry-run`, per-id mode, `title_version_regex` support, failure threshold.

Nothing else has been changed yet.

---

## 3. Architecture

### 3.1 Data flow

```
 Flathub AppStream XML                    GitHub Releases API
          |                                       |
 flatpak_xml_to_json.py                 get_latest_appimages.py
          |  data/all/<id>.json                   |  (generated fields)
          v                                       v
     flatpak_sync.py  ------------------>  data/apps/<id>.json  <---- curated fields
   (Flathub fields +                         (single source of truth,   (human, via
    icon -> data/icons)                       committed to git)          add-app tool)
                                                  |
                                          build-database.py
                                    normalize -> validate -> write
                                                  |
                                   data/output/apps.db + .tar.gz
                                   data/output/app-icons.tar.gz  <-- pack-icons.py
                                                  |
                                   GitHub release "latest"  --> Software GUI / `app`
```

### 3.2 Design principles

- **One file per app is the source of truth.** `data/apps/*.json` is committed. `apps.db` is a derived artifact and is never edited or committed.
- **Field ownership is explicit** (section 4.2). Each tool writes only the fields it owns.
- **Fail soft per app, fail hard per release.** One failing upstream keeps its previous data and logs a warning. Malformed data aborts the build before anything is published.
- **Deterministic output.** Sorted by id, stable key order, reproducible archives. Same inputs give byte-identical outputs, apart from `generated_at`.
- **Idempotent writes.** A file is rewritten only if its content changed (`common.write_json`).
- **Open schema.** Entries may have different fields. The builder validates the fields it knows and passes unknown fields through untouched.
- **No secrets leave the API host.** The GitHub token is sent only to `api.github.com`, never to redirect targets.

### 3.3 Components

| Component | Responsibility | Writes |
|---|---|---|
| `common.py` | Shared pure helpers (I/O, normalizers, arch detection, tar) | nothing |
| `flatpak_xml_to_json.py` | Parse Flathub AppStream into one clean JSON per id | `data/all/` (scratch) |
| `flatpak_sync.py` | Merge Flathub fields and icon into existing app files | `data/apps/`, `data/icons/` |
| `get_latest_appimages.py` | Resolve latest release, asset, size, checksum, zsync, arch | `data/apps/` |
| `build-database.py` | Normalize, validate, assemble the database | `data/output/` |
| `pack-icons.py` | Reproducible icon archive | `data/output/` |
| `add-app.py` (phase 4) | Create a new app file from a template and Flathub data | `data/apps/`, `data/icons/` |

---

## 4. Data specification

### 4.1 `apps.db` envelope (schema_version 1)

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-13T05:00:00Z",
  "count": 22,
  "apps": [ { "...": "entries sorted by id" } ]
}
```

- This replaces the current bare array. It is a **breaking change** for any existing reader. No client exists yet, so make it now.
- Increase `schema_version` only for breaking changes (field removed or meaning changed). Adding fields never needs a bump.
- `SOURCE_DATE_EPOCH`, if set, overrides `generated_at` and the tar mtime (for tests).

### 4.2 App entry fields

Owner key: **C** = curated by hand, **F** = Flathub (`flatpak_sync`), **G** = generated (`get_latest_appimages`).

| Field | Type | Owner | Required | Notes |
|---|---|---|---|---|
| `id` | string | C | yes | Flathub app id. Must equal the filename stem. Unique. |
| `name` | string | F | yes | Overwritten from Flathub. |
| `repo` | string | C | yes | `owner/name` on GitHub. |
| `asset_suffix` | string | C | yes | Selects the AppImage asset (`endswith`). |
| `version_regex` | string | C | yes | Matched against the release tag. Group 1, or the whole match if there is no group. |
| `title_version_regex` | string | C | no | Fallback: matched against the release title when the tag does not match (rolling tags like `latest`). **Assumed semantics: confirm with the owner.** |
| `arch` | string or null | G | yes | See 4.3. |
| `version` | string | G | yes | Compared by inequality only, never ordered. |
| `version_changed_at` | ISO-8601 UTC | G | yes | See 4.3. |
| `download_url` | https URL | G | yes | |
| `asset_name` | string | G | yes | |
| `size` | int (bytes) | G | no | From the release asset. |
| `sha256` | 64 hex, lowercase | G | no | See 4.3. |
| `zsync_url` | https URL ending `.zsync` | G | no | Only when the asset really exists in the release. |
| `published_at` | ISO-8601 UTC | G | yes | Release publish date. Informational only. |
| `summary` | string | F | yes | |
| `description` | string | F | no | Paragraphs joined by `\n`. |
| `developer` | string or null | F | no | |
| `license` | SPDX string or null | F | no | |
| `categories` | string[] | F | no | Raw freedesktop values. |
| `keywords` | string[] | F | no | Untranslated only. |
| `urls` | object | F | no | AppStream url types to URL. |
| `icon` | `{type, name}` | F | yes | `{"type":"cached","name":"<id>.png"}`, and the file must exist in `data/icons/`. |
| `screenshots` | object[] | F | no | Exactly one `default`; `width` and `height` are ints. |

Any other key is preserved as-is and passed to the database.

### 4.3 Derived-field semantics

- **`arch`**: detected from `asset_name` tokens (`x86_64|x86-64|amd64|x64` to `x86_64`; `aarch64|arm64` to `aarch64`; `armv7l|armv7|armhf` to `armv7l`; `i386|i686` to `i686`). If nothing is detected, the existing value is kept (manual entry), else `null`. A detected value always wins.
- **`sha256`**: GitHub's asset `digest` (`sha256:...`) first. Else a sibling checksum asset (`<asset>.sha256`, `.sha256sum`, `.sha256.txt`, or a combined `SHA256SUMS`/`checksums.txt` with a line for the asset). Else omitted. A stale value is **removed** if the new release has none.
- **`zsync_url`**: URL of the asset named `<asset_name>.zsync`. Omitted when absent.
- **`version_changed_at`**: the `published_at` of the first release seen with a given version. It stays unchanged while the version stays the same. It is bumped when the version differs, when the `sha256` differs for the same version, or, for `version == "latest"`, when `published_at` differs. A first-seen app or a migrated file gets `published_at`. This replaces `published_at` as the "recently updated" signal, because pkgforge rebuilds many apps on the same day.
- **Version extraction order**: `version_regex` on tag, then `title_version_regex` on title, then the raw tag with a leading `v` stripped, with a warning.
- **Multiple matching assets**: the first one is used, with a warning.

### 4.4 Normalization (applied in the builder; also at the source)

- `description`: join soft-wrapped lines, collapse spaces, drop paragraphs starting "This flatpak is", keep `\n` between paragraphs.
- `keywords`, `categories`: trim, drop empties, case-insensitive dedupe, keep order.
- `screenshots`: int sizes, drop images without URL and screenshots without images, first default wins, and one is forced if none.
- All normalizers are idempotent (`f(f(x)) == f(x)`).

### 4.5 Validation (build aborts with exit 1, nothing written)

- JSON parses. `id` matches filename stem. Ids are unique.
- `name`, `repo` (`^[\w.-]+/[\w.-]+$`), `asset_suffix`, `version_regex` present. Regexes compile.
- `download_url` and `zsync_url` are `https://`. `zsync_url` ends with `.zsync`.
- `sha256` matches `^[0-9a-f]{64}$`. `size` is an int greater than 0.
- Timestamps match `^\d{4}-\d\d-\d\dT`.
- `icon.name` exists in `data/icons/`.
- **Not an error**: an app with no `version`/`download_url` yet (first fetch failed). It is skipped with a warning and listed in the summary.

---

## 5. Component specifications

### 5.1 `get_latest_appimages.py`

- CLI: `[ids...] [--apps-dir] [--dry-run] [--workers N=6] [--max-failure-rate 0.25]`.
- Auth: `GITHUB_TOKEN` or `GH_TOKEN`, sent only to `https://api.github.com`. Warn if absent.
- Network: 3 retries with exponential backoff on timeouts, 429 and 5xx. 404 means "no release". Rate limit exhausted means stop issuing requests, keep what was fetched, exit 2.
- Output: one line per app, GitHub Actions annotations (`::warning::`) when `GITHUB_ACTIONS` is set.
- Exit codes: `0` ok, `1` failure rate above threshold or bad arguments, `2` rate limited.
- Failed apps keep their previous data untouched.
- Key order in files: curated keys, then the generated block right after `title_version_regex` (or `version_regex`), then Flathub fields.

### 5.2 `flatpak_xml_to_json.py` (fix D3, D4, D5, D6)

- `keywords`: only `<keywords>` blocks **without** `xml:lang`.
- `developer`: `<developer><name>` (untranslated) with fallback to `<developer_name>`.
- Descriptions: per `<p>` and `<li>`, join `itertext()` and collapse whitespace.
- Run the shared normalizers before writing, so output is already clean.
- Keep `--xml --icons --out`. Add `--langs` in Phase 5 only.

### 5.3 `flatpak_sync.py` (fix D1, D2)

- Flat merge of these fields only: `name, summary, description, developer, license, categories, keywords, urls, screenshots`. Never touch curated or generated fields.
- Do not overwrite an existing value with an empty Flathub value (`null`, `[]`, `{}`, `""`). A temporary Flathub gap must not wipe data.
- Icons: copy `data/all/<id>.png` to `data/icons/<id>.png` if content differs, then set `icon = {"type":"cached","name":"<id>.png"}`.
- New option `--icons-dir` (default `data/icons`). Remove the old copy into `data/apps/`.
- Normalize before comparing so unchanged files are not rewritten. Keep `--dry-run`.
- Report ids missing from the Flathub export. Do not fail.

### 5.4 `build-database.py`

- CLI: `--apps data/apps --icons data/icons --out data/output --check`.
- Pipeline: load, normalize, validate, sort by id, write envelope, write reproducible `apps.db.tar.gz`.
- `--check` validates only and writes nothing. It is used by `./check` and CI.
- Print a summary (count, skipped, warnings, errors).

### 5.5 `pack-icons.py`

- Reproducible archive of `data/icons/*.png` (sorted, mtime 0). Correct count in the message.
- Warn about icons not referenced by any app.

### 5.6 `update.sh` and `./update`

- `set -euo pipefail`, run from repo root.
- Order: appstream update, xml to json, sync, fetch, `build-database.py --check`.
- Pass the token through if the owner has `GITHUB_TOKEN` set.

---

## 6. CI/CD specification

**`ci.yml`** (push and PR to main): install ruff, run `./check`. `./check` runs ruff, `python3 -m unittest discover -s tests`, and `src/build-database.py --check`.

**`build-and-release.yml`** (Friday 05:00 UTC and manual):

1. Checkout, Python, install flatpak, add the Flathub remote, update appstream.
2. xml to json, sync, then fetch with `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
3. `./check` (tests plus validation).
4. Build database, pack icons.
5. **Commit refreshed `data/apps` and `data/icons` back** if anything changed (`github-actions[bot]`, message `chore: weekly data refresh`). This persists `version_changed_at`. Pushes made with `GITHUB_TOKEN` do not retrigger CI.
6. Release `latest` with both archives.

Also: add `concurrency: {group: release, cancel-in-progress: false}`, pin action versions, and add `data/output/` to `.gitignore` and untrack it (D11).

Note: the fetch script may consume 1 request per app. The Actions `GITHUB_TOKEN` is limited to about 1000 requests/hour per repository, which is fine for 500 apps. Re-check this above about 800 apps.

---

## 7. Testing strategy

Location: `tests/`. Framework: `unittest`. No network.

| Area | Cases |
|---|---|
| `detect_arch` | `x86_64`, `amd64`, `x64`, `aarch64`, `arm64`, `armhf`, `i686`, no arch, arch embedded in a longer word (must not match) |
| `extract_version` | tag regex hit, title fallback (PhpStorm-like), raw tag fallback, no group in regex |
| `find_sha256` | `digest` field, sibling `.sha256`, combined `SHA256SUMS`, bare hash file, none |
| `find_zsync_url` | present, absent, different name (must not match) |
| `version_changed_at` | first sight, same version, new version, same version with new sha, `latest` with new date |
| `apply_updates` | key order, stale `sha256`/`zsync_url` removed, `arch` kept when undetectable |
| normalizers | idempotence, soft wrap, boilerplate, keyword dedupe, one default screenshot |
| `process()` | success, no release, no matching asset, rate limit, partial failures |
| build | valid DB, each validation error, skipped unfetched app, deterministic tar, envelope fields |
| sync | flat merge, no wipe on empty Flathub value, icon copy and `icon` field |
| xml to json | fixture with per-language `<keywords>` blocks, `<developer><name>` |

Fixtures: trimmed real GitHub release JSON for one pkgforge app, one without `digest`, one rolling-tag release, plus a small AppStream XML.

---

## 8. Phases

### Phase 0: Verify the draft (about 1 hour)

- Read `src/common.py` and `src/get_latest_appimages.py`. Fix anything that does not run. Run `ruff check src/`.
- Confirm against the **live** GitHub API (the earlier session could not reach it) that release assets expose `size` and `digest`, and capture one real response per repo type as test fixtures.
- Ask the owner what `title_version_regex` should match (release title assumed) and what PhpStorm's release title looks like.

Done when: both files import and run with `--dry-run` against the real repo list, and fixtures are saved.

### Phase 1: Correct the pipeline (D1 to D9 core)

- Rewrite `flatpak_sync.py` (5.3) and fix `flatpak_xml_to_json.py` (5.2).
- Unit tests for everything touched, including phase 0 code.
- Run `./update` locally once. Review the diff of `data/apps` together with the owner: keyword counts must drop sharply, `developer` should appear, `size`/`sha256`/`zsync_url`/`arch`/`version_changed_at` should be filled.

Done when: a second `./update` produces no diff, and all tests pass.

### Phase 2: Safe build (D10, D11)

- Implement the envelope, normalization, validation and reproducible archives (4.1, 4.4, 4.5, 5.4, 5.5).
- Untrack `data/output/`.

Done when: invalid fixtures fail with clear messages, and two builds with the same `SOURCE_DATE_EPOCH` are byte-identical.

### Phase 3: CI that persists state (D9)

- Update both workflows as in section 6. Run the release workflow manually on a branch and inspect the artifacts.

Done when: a manual run produces a release, commits a data refresh only when something changed, and a second run commits nothing.

### Phase 4: Add-app tool (owner workflow)

`src/add-app.py <flathub-id> --repo owner/name --suffix <asset_suffix> --version-regex '<regex>' [--title-version-regex ...]`:

1. Create `data/apps/<id>.json` with the curated fields only.
2. Merge Flathub fields from `data/all/<id>.json` (or fetch the Flathub export if missing) using the same code as `flatpak_sync`.
3. Copy the icon to `data/icons/`.
4. Run the fetch for that id only.
5. Run validation for that file and print the entry summary.

Retire `template/`. Document the command in `README.md`.

Done when: adding a new app takes one command and produces a valid file.

### Phase 5: Localization

Restore translated search without the keyword bug: add `--langs` to `flatpak_xml_to_json.py` (default `el`). Store `i18n: {"<lang>": {"name", "summary", "keywords"}}` in each entry. Measure the size impact on 500 apps and set a limit (suggested: under 3 MB uncompressed).

### Phase 6: Hardening at 500 apps

- Stale and broken detection: record `last_ok_at` outside the entry (a report file), and flag apps whose upstream failed 3 weeks in a row or whose latest release is older than 18 months.
- A CI summary (job summary markdown): updated apps, failures, warnings, new `version_changed_at` list.
- README with the pipeline, field ownership table and "how to add an app".

---

## 9. Decisions to confirm with the owner

1. **Envelope vs bare array** for `apps.db` (recommended: envelope).
2. **CI commits data back to `main`**: required for `version_changed_at` to persist. The alternative is reading the previous release's `apps.db` as state.
3. **`name` is owned by Flathub.** A hand-written name such as "KPatience (PkgForge)" is overwritten on sync. If a curated display name is wanted, add a `name_override` field.
4. **`title_version_regex` semantics** (release title fallback).
5. **Strict validation** blocks a release for one bad entry. Alternative: exclude the bad entry and publish the rest.

---

## 10. Appendix: target entry example

```json
{
  "id": "org.kde.kate",
  "name": "Kate",
  "repo": "pkgforge-dev/Kate-AppImage-Enhanced",
  "asset_suffix": "-anylinux-x86_64.AppImage",
  "version_regex": "([0-9.]+-[0-9]+)@",
  "version": "26.08.2-1",
  "version_changed_at": "2026-11-01T18:20:58Z",
  "download_url": "https://github.com/.../Kate-26.08.2-1-anylinux-x86_64.AppImage",
  "asset_name": "Kate-26.08.2-1-anylinux-x86_64.AppImage",
  "size": 123456789,
  "sha256": "<64 lowercase hex>",
  "zsync_url": "https://github.com/.../Kate-26.08.2-1-anylinux-x86_64.AppImage.zsync",
  "arch": "x86_64",
  "published_at": "2026-11-01T18:20:58Z",
  "summary": "Advanced text editor",
  "description": "Kate is a fast multi-document ...",
  "developer": "KDE",
  "license": "LGPL-2.1+",
  "categories": ["Development", "TextEditor"],
  "keywords": ["text", "editor", "programming"],
  "urls": {"homepage": "https://kate-editor.org/"},
  "icon": {"type": "cached", "name": "org.kde.kate.png"},
  "screenshots": [{"default": true, "caption": "Editing code with Kate", "images": [{"type": "thumbnail", "width": 752, "height": 408, "url": "https://dl.flathub.org/..."}]}]
}
```

Values for `size`, `sha256`, `zsync_url` and `developer` above are illustrative. Real values come from the tools.
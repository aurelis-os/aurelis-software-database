Fix five remaining defects in this repo. Work in this order, one commit per issue
(conventional messages: fix:, test:). After each fix run ./check (ruff + unit tests +
build-database --check). Tests must never use the network. Do not hand-edit
data/apps/*.json; only the tools may change them.

--- 1. normalize_description flattens paragraphs and deletes real descriptions (src/common.py)
Data convention: paragraphs are separated by a single "\n"; XML soft wraps are
"\n" followed by indentation. Current code splits only on blank lines, so every
paragraph gets merged, and the rule dropping paragraphs that start with
"This application is" wipes legitimate descriptions.
Fix:
  - text = re.sub(r"\n[ \t]+", " ", text)   # join soft wraps first
  - split on "\n"; for each paragraph collapse whitespace with " ".join(p.split())
  - drop empty paragraphs and ONLY paragraphs starting with "This flatpak is"
    (case-insensitive). Delete the "This application is" rule.
  - return "\n".join(paragraphs) or None. Must be idempotent.
Also check flatpak_xml_to_json.py emits one "\n" between <p>/<li> items with no
indentation, so source and normalizer agree.
Tests: "Para one.\nPara two." is unchanged; "This application is a fast editor.\nIt has
plugins." is unchanged; "line one\n      line two" becomes "line one line two";
a "This flatpak is community maintained..." paragraph is dropped; f(f(x)) == f(x).
Then regenerate data/all (xml step of ./update) and run src/flatpak_sync.py so the
paragraphs come back. Verify with a short script: Krita's description contains "\n",
and no app has a null description unless Flathub has none.

--- 2. Stale generated keys survive (src/get_latest_appimages.py)
insert_generated_fields keeps old generated keys that the new release no longer
provides, so an old zsync_url or sha256 can sit next to a new download_url.
Fix: define GENERATED in common.py in this canonical order:
  version, version_changed_at, download_url, asset_name, size, sha256, zsync_url,
  arch, published_at
When rebuilding an app dict, SKIP every key in GENERATED from the old dict, then
insert the new block (only keys present in `updates`, in canonical order) right
after title_version_regex (or version_regex if absent). Optional keys (size, sha256,
zsync_url) are therefore removed when not found. A one-time reorder diff in
data/apps is expected and fine.
Tests: file with old sha256 + zsync_url and a release without them -> both keys gone;
key order is canonical; running twice produces no diff.

--- 3. arch must be allowed to be null (src/get_latest_appimages.py, src/build-database.py)
Intended behaviour: arch = detect_arch(asset_name) or existing manual value or None,
and the key `arch` is ALWAYS written (null when unknown, so the owner can fill it in).
  - Do not strip arch when it is None (strip None only for the other optional keys).
  - build-database.py: remove "arch" from the "must be truthy" list; require only
    that the key exists; value is a string or null. Print a WARNING (not an error)
    listing ids whose arch is null. These apps stay in the database.
Tests: undetectable asset name -> "arch": null written; manual arch preserved when
undetectable; detected arch overrides; build passes with null arch and prints the warning.

--- 4. GitHub token leaks to redirect targets (src/get_latest_appimages.py)
download_and_parse_checksum sends Authorization to a browser_download_url, which
redirects to another host; urllib forwards the header.
Fix: send the Bearer token ONLY when the URL starts with "https://api.github.com".
Checksum downloads send no Authorization and no GitHub JSON Accept header, only a
User-Agent. Cap the response at 1 MB; any network or decode error returns None.
Test: mock urllib.request.Request/urlopen and assert no Authorization header for a
non-API URL and that it is present for the API URL.

--- 5. Replace the SIBLING_CHECKSUM / COMBINED_CHECKSUM marker strings (src/common.py)
find_sha256 must never return marker strings. New design:
  find_sha256(asset, all_assets, fetch=None) -> str | None
  - fetch is a callable fetch(url) -> str | None (injected; None means "no download").
  - Order: asset["digest"] ("sha256:<hex>") -> sibling asset
    "<name>.sha256" / ".sha256sum" / ".sha256.txt" -> combined file matching
    re.compile(r"(?i)^(sha256sums?|checksums?)(\.txt|\.sha256)?$").
  - New pure helper parse_checksum(text, filename): accepts a bare 64-hex line, or
    "<hash>  name" / "<hash> *name" lines where basename(name) == filename.
  - Return lowercase 64-hex or None. Validate with ^[0-9a-f]{64}$.
  - get_latest_appimages.py passes fetch=download_text (the function from fix 4) and
    deletes all marker branching in process_app.
Tests with a fake fetch: digest wins and fetch is NOT called; sibling with bare hash;
sibling with "hash  name"; combined file picks the right line among several; combined
file without our asset -> None; garbage content -> None; fetch=None -> None.

--- Done when
./check passes; no marker strings remain (grep -rn "_CHECKSUM" src returns nothing);
a second run of src/get_latest_appimages.py and src/flatpak_sync.py produces zero diff;
report the git diff stat and any behaviour you chose differently from this prompt.
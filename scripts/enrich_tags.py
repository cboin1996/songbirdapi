#!/usr/bin/env python3
"""
Enrich mp3/m4a files with full iTunes metadata.

For each file in the target directory:
  - If it already passes the publish bar, skip it (tags are asserted unchanged at end).
  - Otherwise search iTunes by trackName + artistName, pick an exact match,
    back up the original, and re-tag with songbirdcore.

Modes:
  default — enrich tags via iTunes
  --analyse — report tag gaps only
  --rename — strip 'NN ' and 'N-NN ' prefixes from filenames + tag title (no iTunes calls)

Usage:
    source .venv/bin/activate
    python scripts/enrich_tags.py ~/Downloads [--dry-run] [--rate-limit 0.5]
    python scripts/enrich_tags.py ~/Downloads --rename [--dry-run]
"""
import argparse
import re
import shutil
import time
import os
import sys
from pathlib import Path

import eyed3
from mutagen.mp4 import MP4

from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiSongModel
from songbirdcore.models.modes import Modes

REQUIRED_FIELDS = [
    "trackName", "artistName", "collectionName", "artworkUrl100",
    "primaryGenreName", "releaseDate", "collectionId", "trackNumber",
]

eyed3.log.setLevel("ERROR")


def _read_mp3_tags(path: str) -> dict:
    af = eyed3.load(path)
    if not af or not af.tag:
        return {}
    t = af.tag
    return {
        "trackName": t.title or "",
        "artistName": t.artist or "",
        "collectionName": t.album or "",
        "primaryGenreName": t.genre.name if t.genre else "",
        "trackNumber": t.track_num[0] or 0,
        "trackCount": t.track_num[1] or 0,
        "discNumber": t.disc_num[0] or 0,
        "discCount": t.disc_num[1] or 0,
        "releaseDate": str(t.recording_date) if t.recording_date else "",
        "collectionArtistName": t.album_artist or "",
        "artworkUrl100": "",
        "collectionId": "",
    }


def _read_m4a_tags(path: str) -> dict:
    try:
        af = MP4(path)
    except Exception:
        return {}
    def _get(key):
        v = af.get(key)
        return v[0] if v else ""
    def _get_int(key, idx=0):
        v = af.get(key)
        if v and v[0] and len(v[0]) > idx:
            return v[0][idx] or 0
        return 0
    return {
        "trackName": _get("\xa9nam"),
        "artistName": _get("\xa9ART"),
        "collectionName": _get("\xa9alb"),
        "primaryGenreName": _get("\xa9gen"),
        "trackNumber": _get_int("trkn", 0),
        "trackCount": _get_int("trkn", 1),
        "discNumber": _get_int("disk", 0),
        "discCount": _get_int("disk", 1),
        "releaseDate": _get("\xa9day"),
        "collectionArtistName": _get("aART"),
        "artworkUrl100": "",
        "collectionId": "",
    }


def passes_bar(tags: dict) -> bool:
    return all(bool(tags.get(f)) for f in REQUIRED_FIELDS)


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _year(s: str) -> str:
    return (s or "")[:4]


def find_itunes_match(tags: dict) -> ItunesApiSongModel | None:
    track_name = tags.get("trackName", "")
    artist_name = tags.get("artistName", "")
    if not track_name or not artist_name:
        return None

    query = f"{track_name} {artist_name}"
    results = None
    backoff = 2.0
    for attempt in range(5):
        results = itunes.query_api(search_variable=query, limit=10, mode=Modes.SONG)
        if results is not None:
            break
        wait = backoff * (2 ** attempt)
        print(f"    rate limited — waiting {wait:.0f}s (attempt {attempt + 1}/5)")
        time.sleep(wait)
    if results is None:
        return None

    def score(r: ItunesApiSongModel) -> int:
        s = 0
        # Title and artist are required — disqualify if they don't match
        if _norm(r.trackName) != _norm(track_name):
            return -1
        if _norm(r.artistName) != _norm(artist_name):
            return -1
        s += 2  # base score for title+artist match
        if tags.get("collectionName") and _norm(r.collectionName) == _norm(tags["collectionName"]):
            s += 3
        if tags.get("trackNumber") and r.trackNumber == tags["trackNumber"]:
            s += 2
        if tags.get("releaseDate") and _year(r.releaseDate) == _year(tags["releaseDate"]):
            s += 1
        if tags.get("primaryGenreName") and _norm(r.primaryGenreName) == _norm(tags["primaryGenreName"]):
            s += 1
        if tags.get("discNumber") and r.discNumber == tags["discNumber"]:
            s += 1
        return s

    scored = [(score(r), r) for r in results]
    scored = [(s, r) for s, r in scored if s >= 2]  # must at least match title+artist
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def backup(src: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / src.name
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest


READABLE_FIELDS = [f for f in REQUIRED_FIELDS if f not in ("artworkUrl100", "collectionId")]


def analyse(scan_dir: Path):
    files = sorted(p for p in scan_dir.iterdir() if p.suffix.lower() in (".mp3", ".m4a") and p.parent == scan_dir)
    good, bad = [], []
    for f in files:
        ext = f.suffix.lower()
        tags = _read_mp3_tags(str(f)) if ext == ".mp3" else _read_m4a_tags(str(f))
        missing = [field for field in READABLE_FIELDS if not bool(tags.get(field))]
        if missing:
            bad.append((f.name, missing))
        else:
            good.append(f.name)
    print(f"Total: {len(files)}  |  Readable tags complete: {len(good)}  |  Still gaps: {len(bad)}")
    if bad:
        print()
        for name, missing in bad:
            print(f"  MISSING {missing}  {name}")


_PREFIX_RE = re.compile(r'^(?:\d+-\d+|\d+)\s+')


def clean_filename_stem(stem: str) -> str:
    """Strip 'NN ' / 'N-NN ' prefix and convert trailing _ → ?"""
    cleaned = _PREFIX_RE.sub('', stem).strip()
    # Trailing underscore is a common substitution for '?' (filesystem-safe download names).
    if cleaned.endswith('_'):
        cleaned = cleaned[:-1] + '?'
    return cleaned


def _set_mp3_title(path: str, title: str) -> bool:
    af = eyed3.load(path)
    if not af or not af.tag:
        return False
    af.tag.title = title
    af.tag.save()
    return True


def _set_m4a_title(path: str, title: str) -> bool:
    try:
        af = MP4(path)
    except Exception:
        return False
    af["\xa9nam"] = title
    af.save()
    return True


def rename_pass(scan_dir: Path, dry_run: bool) -> None:
    files = sorted(p for p in scan_dir.iterdir() if p.suffix.lower() in (".mp3", ".m4a"))
    print(f"Scanning {len(files)} files in {scan_dir}")
    if dry_run:
        print("DRY RUN — no files will be modified\n")

    renamed = title_set = unchanged = collisions = 0
    used_targets: set[Path] = set()

    for f in files:
        ext = f.suffix.lower()
        new_stem = clean_filename_stem(f.stem)
        if not new_stem:
            print(f"  SKIP (empty after strip)  {f.name}")
            unchanged += 1
            continue

        target = scan_dir / f"{new_stem}{ext}"

        # Collision handling: if the target already exists (and isn't this same file), suffix " (2)", " (3)", ...
        if target != f and (target.exists() or target in used_targets):
            i = 2
            while True:
                candidate = scan_dir / f"{new_stem} ({i}){ext}"
                if not candidate.exists() and candidate not in used_targets:
                    target = candidate
                    collisions += 1
                    break
                i += 1

        # Decide tag-title fix BEFORE we rename (read tags from current path).
        tags = _read_mp3_tags(str(f)) if ext == ".mp3" else _read_m4a_tags(str(f))
        existing_title = (tags.get("trackName") or "").strip()
        needs_title = not existing_title
        proposed_title = new_stem

        action_bits = []
        if target != f:
            action_bits.append(f"rename → {target.name}")
        if needs_title:
            action_bits.append(f"set title → '{proposed_title}'")
        if not action_bits:
            unchanged += 1
            continue

        print(f"  {' + '.join(action_bits):<60}  {f.name}")

        if not dry_run:
            if needs_title:
                ok = _set_mp3_title(str(f), proposed_title) if ext == ".mp3" else _set_m4a_title(str(f), proposed_title)
                if not ok:
                    print(f"    ERR: could not set title")
                    continue
                title_set += 1
            if target != f:
                f.rename(target)
                renamed += 1
                used_targets.add(target)
        else:
            if target != f: renamed += 1
            if needs_title: title_set += 1
            used_targets.add(target)

    print(f"\n--- Rename summary{' (dry run)' if dry_run else ''} ---")
    print(f"Files renamed:     {renamed}")
    print(f"Titles set:        {title_set}")
    print(f"Collisions suffixed: {collisions}")
    print(f"Unchanged:         {unchanged}")


def main():
    parser = argparse.ArgumentParser(description="Enrich mp3/m4a tags via iTunes API")
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify files")
    parser.add_argument("--analyse", action="store_true", help="Report tag gaps only, no iTunes lookups")
    parser.add_argument("--rename", action="store_true", help="Strip filename prefixes; for files lacking trackName tag, set tag.title from cleaned filename. No iTunes calls.")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between iTunes API calls (default 1.0)")
    parser.add_argument("--limit", type=int, default=None, help="Max number of files to process")
    args = parser.parse_args()

    scan_dir = Path(args.directory).expanduser().resolve()
    if not scan_dir.is_dir():
        print(f"ERROR: {scan_dir} is not a directory")
        sys.exit(1)

    if args.analyse:
        analyse(scan_dir)
        return

    if args.rename:
        rename_pass(scan_dir, args.dry_run)
        return

    backup_dir = scan_dir / ".songbird_backup"
    files = sorted(
        [p for p in scan_dir.iterdir() if p.suffix.lower() in (".mp3", ".m4a")]
    )

    if args.limit:
        files = files[:args.limit]
    print(f"Scanning {len(files)} files in {scan_dir}")
    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    results = {"skipped": [], "tagged": [], "no_match": [], "failed": [], "already_good": []}
    already_good_snapshots: dict[str, dict] = {}

    for f in files:
        ext = f.suffix.lower()
        tags = _read_mp3_tags(str(f)) if ext == ".mp3" else _read_m4a_tags(str(f))

        if not tags.get("trackName"):
            print(f"  SKIP (no title)       {f.name}")
            results["skipped"].append(f.name)
            continue

        if passes_bar(tags):
            print(f"  OK (already good)     {f.name}")
            results["already_good"].append(f.name)
            already_good_snapshots[str(f)] = tags
            continue

        print(f"  SEARCHING iTunes...   {f.name}  [{tags.get('trackName')} - {tags.get('artistName')}]")
        time.sleep(args.rate_limit)

        match = find_itunes_match(tags)
        if not match:
            print(f"  NO MATCH              {f.name}")
            results["no_match"].append(f.name)
            continue

        print(f"  MATCH: {match.trackName} — {match.artistName} ({match.collectionName}, {match.releaseDate})")

        if args.dry_run:
            results["tagged"].append(f.name)
            continue

        backup(f, backup_dir)

        if ext == ".mp3":
            ok = itunes.mp3ID3Tagger(str(f), match)
        else:
            ok = itunes.m4a_tagger(str(f), match)

        if ok:
            print(f"  TAGGED                {f.name}")
            results["tagged"].append(f.name)
        else:
            print(f"  FAILED (tagger error) {f.name}")
            shutil.copy2(backup_dir / f.name, f)  # restore backup
            results["failed"].append(f.name)

    if args.dry_run:
        print(f"\n--- Dry run summary ---")
        print(f"Would tag:     {len(results['tagged'])}")
        print(f"Already good:  {len(results['already_good'])}")
        print(f"No match:      {len(results['no_match'])}")
        print(f"Skipped:       {len(results['skipped'])}")
        return

    assertion_failures = []

    # Assert already-good files are unchanged
    print("\n--- Asserting unchanged files ---")
    for path_str, before in already_good_snapshots.items():
        p = Path(path_str)
        ext = p.suffix.lower()
        after = _read_mp3_tags(path_str) if ext == ".mp3" else _read_m4a_tags(path_str)
        changed = {k: (before[k], after[k]) for k in before if before.get(k) != after.get(k)}
        if changed:
            print(f"  ASSERTION FAIL {p.name}: {changed}")
            assertion_failures.append(f"unchanged:{p.name}")
        else:
            print(f"  UNCHANGED OK   {p.name}")

    # Assert newly tagged files now pass the bar
    print("\n--- Asserting tagged files pass bar ---")
    for name in results["tagged"]:
        p = scan_dir / name
        ext = p.suffix.lower()
        after = _read_mp3_tags(str(p)) if ext == ".mp3" else _read_m4a_tags(str(p))
        # artworkUrl100 won't be readable from file tags — check other required fields
        bar_fields = [f for f in REQUIRED_FIELDS if f != "artworkUrl100" and f != "collectionId"]
        missing = [f for f in bar_fields if not bool(after.get(f))]
        if missing:
            print(f"  ASSERTION FAIL {name}: still missing {missing}")
            assertion_failures.append(f"bar:{name}")
        else:
            print(f"  BAR PASSED     {name}")

    print(f"""
--- Summary ---
Already good (skipped): {len(results['already_good'])}
No title (skipped):     {len(results['skipped'])}
Tagged:                 {len(results['tagged'])}
No iTunes match:        {len(results['no_match'])}
Tagger failed:          {len(results['failed'])}
Assertion failures:     {len(assertion_failures)}
""")
    if results["no_match"]:
        print("No match found for:")
        for name in results["no_match"]:
            print(f"  {name}")
    if assertion_failures:
        print("WARNING — assertion failures:")
        for name in assertion_failures:
            print(f"  {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()

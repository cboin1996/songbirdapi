#!/usr/bin/env python3
"""Validate a songbird backup against production.

Usage:
    python3 scripts/backup_validate.py \
        --dump ~/backups/songbird/db/songbird-TIMESTAMP.sql \
        --data-dir ~/backups/songbird/data
"""

import argparse
import subprocess
import sys
from pathlib import Path

KEEBOX_SSH = ["ssh", "-p", "223", "keenan@kee-flix.com"]
PSQL_PREFIX = "docker exec songbird-postgres psql -U songbird songbird -t -A -c"


def _ssh(cmd: str) -> str:
    result = subprocess.run(
        [*KEEBOX_SSH, cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _prod_counts() -> dict[str, int]:
    queries = {
        "songs": "SELECT count(*) FROM songs",
        "songs_with_artwork": "SELECT count(*) FROM songs WHERE artwork_thumb IS NOT NULL",
        "users": "SELECT count(*) FROM users",
        "playlists": "SELECT count(*) FROM playlists",
        "playlist_songs": "SELECT count(*) FROM playlist_songs",
    }
    return {key: int(_ssh(f"{PSQL_PREFIX} '{q}'")) for key, q in queries.items()}


def _check_dump(dump: Path) -> list[str]:
    if not dump.exists():
        return [f"ERROR: dump not found: {dump}"]
    size = dump.stat().st_size
    if size == 0:
        return [f"ERROR: dump is 0 bytes: {dump}"]
    with open(dump, "rb") as f:
        f.seek(max(0, size - 512))
        tail = f.read().decode("utf-8", errors="ignore")
    if "PostgreSQL database dump complete" not in tail:
        return ["ERROR: dump missing completion marker — likely truncated"]
    return []


def _dump_size_delta(dump: Path) -> str | None:
    dumps = sorted(
        dump.parent.glob("*.sql"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if len(dumps) < 2 or dumps[0] != dump:
        return None
    curr_sz, prev_sz = dumps[0].stat().st_size, dumps[1].stat().st_size
    if prev_sz > 0:
        pct = (curr_sz - prev_sz) / prev_sz * 100
        if pct < -20:
            return f"WARN: dump shrank {abs(pct):.1f}% vs previous ({prev_sz // 1024} KB → {curr_sz // 1024} KB)"
    return None


def _check_audio(data_dir: Path, expected: int) -> list[str]:
    downloads = data_dir / "downloads"
    if not downloads.exists():
        return [f"ERROR: downloads/ missing: {downloads}"]
    files = list(downloads.iterdir())
    issues = []
    if len(files) != expected:
        pct = abs(len(files) - expected) / max(expected, 1) * 100
        severity = "ERROR" if pct > 5 else "WARN"
        issues.append(
            f"{severity}: audio count mismatch: local={len(files)}, prod={expected} ({pct:.1f}% diff)"
        )
    zero_byte = [f for f in files if f.stat().st_size == 0]
    if zero_byte:
        sample = [f.name for f in zero_byte[:3]]
        issues.append(f"ERROR: {len(zero_byte)} zero-byte audio file(s): {sample}")
    return issues


def _check_artwork(data_dir: Path, expected: int) -> list[str]:
    artwork = data_dir / "artwork"
    if not artwork.exists():
        return [f"ERROR: artwork/ missing: {artwork}"]
    dirs = [d for d in artwork.iterdir() if d.is_dir()]
    issues = []
    if len(dirs) != expected:
        pct = abs(len(dirs) - expected) / max(expected, 1) * 100
        severity = "ERROR" if pct > 5 else "WARN"
        issues.append(
            f"{severity}: artwork count mismatch: local={len(dirs)}, prod={expected} ({pct:.1f}% diff)"
        )
    incomplete = [
        d.name
        for d in dirs[:100]
        if not (d / "full.jpg").exists() or not (d / "thumb.jpg").exists()
    ]
    if incomplete:
        issues.append(
            f"ERROR: {len(incomplete)} artwork dir(s) missing full.jpg/thumb.jpg: {incomplete[:3]}"
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate songbird backup against prod"
    )
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()

    all_issues: list[str] = []

    print("=== Songbird Backup Validation ===\n")

    print("[1/4] Dump integrity...")
    dump_issues = _check_dump(args.dump)
    all_issues.extend(dump_issues)
    for i in dump_issues:
        print(f"  {i}")
    if not dump_issues:
        print(f"  OK  {args.dump.name}  ({args.dump.stat().st_size // 1024} KB)")
    delta = _dump_size_delta(args.dump)
    if delta:
        all_issues.append(delta)
        print(f"  {delta}")

    print("\n[2/4] Prod row counts...")
    counts: dict[str, int] = {}
    try:
        counts = _prod_counts()
        for k, v in counts.items():
            print(f"  {k}: {v}")
    except Exception as e:
        msg = f"ERROR: prod query failed — {e}"
        all_issues.append(msg)
        print(f"  {msg}")

    print("\n[3/4] Audio files...")
    if counts:
        issues = _check_audio(args.data_dir, counts["songs"])
        all_issues.extend(issues)
        for i in issues:
            print(f"  {i}")
        if not issues:
            print(f"  OK  {counts['songs']} files")

    print("\n[4/4] Artwork...")
    if counts:
        issues = _check_artwork(args.data_dir, counts["songs_with_artwork"])
        all_issues.extend(issues)
        for i in issues:
            print(f"  {i}")
        if not issues:
            print(f"  OK  {counts['songs_with_artwork']} dirs")

    errors = [i for i in all_issues if i.startswith("ERROR")]
    warnings = [i for i in all_issues if i.startswith("WARN")]
    print("\n=== Result ===")
    if errors:
        print(f"  FAILED — {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    if warnings:
        print(f"  PASSED with {len(warnings)} warning(s)")
        return 0
    print("  PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

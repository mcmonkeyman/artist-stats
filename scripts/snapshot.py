#!/usr/bin/env python3
"""
Data ingestion script: converts artist-album streaming markdown into JSON
snapshots suitable for longitudinal tracking.

Usage examples:

    # Ingest a markdown file into a new artist directory
    python3 scripts/snapshot.py --from-md radiohead_spotify_streams.md \
        --artist-dir data/radiohead \
        --name "Radiohead" \
        --spotify-id 4Z8W4fKeB5YxbusRsdQVPb \
        --source-url "https://kworb.net/spotify/artist/4Z8W4fKeB5YxbusRsdQVPb_songs.html"

    # Subsequent snapshot (meta.json already exists)
    python3 scripts/snapshot.py --from-md radiohead_spotify_streams.md \
        --artist-dir data/radiohead

    # Pipe markdown via stdin
    cat radiohead_spotify_streams.md | python3 scripts/snapshot.py --from-md - \
        --artist-dir data/radiohead

    # List latest snapshots for all artists
    python3 scripts/snapshot.py --all

No external dependencies — uses only the Python standard library.
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# Allow running as a script from the project root or from scripts/
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

from parse_md import parse_albums


def _extract_date(md: str) -> str | None:
    """Try to pull a date from 'last updated YYYY-MM-DD' in the markdown."""
    m = re.search(r"last updated (\d{4}-\d{2}-\d{2})", md, re.IGNORECASE)
    return m.group(1) if m else None


def _ingest(args: argparse.Namespace) -> None:
    # Read markdown
    if args.from_md == "-":
        md = sys.stdin.read()
    else:
        md_path = Path(args.from_md)
        if not md_path.is_file():
            sys.exit(f"Error: markdown file not found: {md_path}")
        md = md_path.read_text()

    artist_dir = Path(args.artist_dir)
    meta_path = artist_dir / "meta.json"
    snapshots_dir = artist_dir / "snapshots"

    # Ensure directories exist
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Handle meta.json
    if not meta_path.exists():
        missing = []
        if not args.name:
            missing.append("--name")
        if not args.spotify_id:
            missing.append("--spotify-id")
        if not args.source_url:
            missing.append("--source-url")
        if missing:
            sys.exit(
                f"Error: meta.json does not exist; the following flags are required "
                f"for initial creation: {', '.join(missing)}"
            )
        slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-")
        meta = {
            "name": args.name,
            "slug": slug,
            "spotify_id": args.spotify_id,
            "source_url": args.source_url,
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"Created {meta_path}")

    # Determine snapshot date
    snapshot_date = args.date or _extract_date(md) or date.today().isoformat()

    # Parse albums and build snapshot
    albums = parse_albums(md)
    snapshot = {
        "date": snapshot_date,
        "albums": albums,
    }

    out_path = snapshots_dir / f"{snapshot_date}.json"
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")

    total_tracks = sum(len(a["tracks"]) for a in albums)
    total_streams = sum(
        t["streams"] for a in albums for t in a["tracks"]
    )
    print(f"Wrote {out_path}  ({len(albums)} albums, {total_tracks} tracks, {total_streams:,} total streams)")


def _list_all(args: argparse.Namespace) -> None:
    data_dir = Path("data")
    if not data_dir.is_dir():
        sys.exit("Error: data/ directory not found")

    artist_dirs = sorted(
        p for p in data_dir.iterdir() if p.is_dir() and (p / "meta.json").exists()
    )

    if not artist_dirs:
        print("No artist directories found in data/.")
        return

    for artist_dir in artist_dirs:
        meta = json.loads((artist_dir / "meta.json").read_text())
        snapshots_dir = artist_dir / "snapshots"
        snapshots = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []

        if not snapshots:
            print(f"{meta.get('name', artist_dir.name)}: no snapshots")
            continue

        latest = snapshots[-1]
        snap = json.loads(latest.read_text())
        n_albums = len(snap.get("albums", []))
        n_tracks = sum(len(a.get("tracks", [])) for a in snap.get("albums", []))
        total = sum(t["streams"] for a in snap.get("albums", []) for t in a.get("tracks", []))
        print(
            f"{meta.get('name', artist_dir.name):30s}  "
            f"latest={snap.get('date', '?'):10s}  "
            f"{n_albums} albums  {n_tracks} tracks  {total:>15,} streams  "
            f"({len(snapshots)} snapshot{'s' if len(snapshots) != 1 else ''})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest artist streaming markdown into JSON snapshots."
    )

    # Ingest mode flags
    parser.add_argument(
        "--from-md",
        metavar="FILE",
        help="Markdown file to ingest (use '-' for stdin)",
    )
    parser.add_argument(
        "--artist-dir",
        metavar="DIR",
        help="Target artist directory (e.g. data/radiohead)",
    )
    parser.add_argument("--name", help="Artist display name (for meta.json)")
    parser.add_argument("--spotify-id", help="Spotify artist ID (for meta.json)")
    parser.add_argument("--source-url", help="Data source URL (for meta.json)")
    parser.add_argument(
        "--date",
        help="Override snapshot date (YYYY-MM-DD); default: extracted from markdown or today",
    )

    # List mode
    parser.add_argument(
        "--all",
        action="store_true",
        help="List latest snapshot summary for every artist in data/",
    )

    args = parser.parse_args()

    if args.all:
        _list_all(args)
    elif args.from_md:
        if not args.artist_dir:
            parser.error("--artist-dir is required when using --from-md")
        _ingest(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

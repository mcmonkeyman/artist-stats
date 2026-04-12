#!/usr/bin/env python3
"""
Scrapes Spotify stream counts from Kworb and album/track structure from
Wikipedia to build artist snapshots.

Usage:
    # Add a brand new artist by Spotify ID
    python3 scripts/scrape.py add 4Z8W4fKeB5YxbusRsdQVPb

    # Add with explicit Wikipedia page name (if auto-detection fails)
    python3 scripts/scrape.py add 4Z8W4fKeB5YxbusRsdQVPb --wiki "Radiohead discography"

    # Refresh stream counts for an existing artist
    python3 scripts/scrape.py refresh radiohead

    # Refresh all artists
    python3 scripts/scrape.py refresh --all

    # Dry run (show what would happen, don't write)
    python3 scripts/scrape.py add 4Z8W4fKeB5YxbusRsdQVPb --dry-run
    python3 scripts/scrape.py refresh --all --dry-run

Polite by default: identifies itself in User-Agent, 2s delay between
requests, uses Wikipedia's maxlag parameter.
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

USER_AGENT = "arpression/1.0 (streaming-data tracker; github.com; polite single-page scrape)"
REQUEST_DELAY = 2  # seconds between HTTP requests


def _fetch(url: str) -> str:
    """GET a URL with our User-Agent. Returns body text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} fetching {url}")
    except urllib.error.URLError as e:
        sys.exit(f"Error fetching {url}: {e.reason}")


def _polite_pause():
    time.sleep(REQUEST_DELAY)


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# Kworb
# ---------------------------------------------------------------------------

def fetch_kworb(spotify_id: str) -> tuple[str, str, list[dict]]:
    """
    Returns (artist_name, last_updated, [{song, streams, spotify_track_id}]).
    """
    url = f"https://kworb.net/spotify/artist/{spotify_id}_songs.html"
    html = _fetch(url)

    # Artist name from <title>
    title_m = re.search(r"<title>(.+?) - Spotify", html)
    artist_name = title_m.group(1).strip() if title_m else "Unknown"

    # Last updated date
    date_m = re.search(r"Last updated:\s*(\d{4})/(\d{2})/(\d{2})", html)
    last_updated = (
        f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
        if date_m else date.today().isoformat()
    )

    songs = []
    pattern = re.compile(
        r'<tr>\s*<td class="text"><div>'
        r'<a href="https://open\.spotify\.com/track/([^"]+)"[^>]*>'
        r'([^<]+)</a></div></td>\s*'
        r'<td>([\d,]+)</td>',
        re.DOTALL,
    )
    for m in pattern.finditer(html):
        songs.append({
            "spotify_track_id": m.group(1),
            "song": m.group(2).strip(),
            "streams": int(m.group(3).replace(",", "")),
        })

    return artist_name, last_updated, songs


# ---------------------------------------------------------------------------
# Wikipedia — discography + tracklists
# ---------------------------------------------------------------------------

def _wiki_parse(page_title: str) -> str:
    """Fetch rendered HTML of a Wikipedia page via the parse API."""
    encoded = urllib.parse.quote(page_title.replace(" ", "_"))
    url = (
        f"https://en.wikipedia.org/w/api.php?action=parse&page={encoded}"
        f"&format=json&prop=text&maxlag=5"
    )
    data = json.loads(_fetch(url))
    if "error" in data:
        sys.exit(f"Wikipedia API error for '{page_title}': {data['error'].get('info', data['error'])}")
    return data["parse"]["text"]["*"]


def _wiki_search(query: str) -> str | None:
    """OpenSearch for a Wikipedia page title. Returns first match or None."""
    encoded = urllib.parse.quote(query)
    url = (
        f"https://en.wikipedia.org/w/api.php?action=opensearch"
        f"&search={encoded}&limit=3&format=json"
    )
    data = json.loads(_fetch(url))
    titles = data[1] if len(data) > 1 else []
    return titles[0] if titles else None


def fetch_studio_albums(artist_name: str, wiki_page: str | None = None) -> list[dict]:
    """
    Fetch the artist's discography page from Wikipedia and extract studio
    albums with names, years, and Wikipedia page slugs.

    Returns [{name, year, wiki_slug}] in chronological order.
    """
    # Find the discography page
    if wiki_page:
        page_title = wiki_page
    else:
        page_title = _wiki_search(f"{artist_name} discography")
        if not page_title:
            sys.exit(f"Could not find Wikipedia discography page for '{artist_name}'")

    print(f"  Wikipedia discography: {page_title}")
    html = _wiki_parse(page_title)

    # Find the Studio albums section. We look for the heading, then parse
    # the first wikitable after it.
    studio_idx = html.find('id="Studio_albums"')
    if studio_idx == -1:
        # Some pages use "Studio_album" (singular) or different casing
        studio_idx = html.lower().find('id="studio_albums"')
    if studio_idx == -1:
        sys.exit(
            f"Could not find 'Studio albums' section in '{page_title}'. "
            f"Try --wiki with the exact page name."
        )

    # Extract the table after the heading
    table_start = html.find("<table", studio_idx)
    if table_start == -1:
        sys.exit("Could not find studio albums table")

    # Find the end of this table (handle nested tables)
    depth = 0
    i = table_start
    table_end = len(html)
    while i < len(html):
        if html[i:i+6] == "<table":
            depth += 1
        elif html[i:i+8] == "</table>":
            depth -= 1
            if depth == 0:
                table_end = i + 8
                break
        i += 1

    table_html = html[table_start:table_end]

    # Parse album rows. Pattern: <th scope="row"><i><a href="/wiki/SLUG">Name</a></i></th>
    # followed by a cell with "Released: DATE"
    albums = []
    row_pattern = re.compile(
        r'<th\s+scope="row"[^>]*>\s*<i>\s*<a\s+href="/wiki/([^"]+)"[^>]*>([^<]+)</a>\s*</i>\s*</th>'
        r'.*?Released:\s*(\d{1,2}\s+\w+\s+)?(\d{4})',
        re.DOTALL,
    )
    for m in row_pattern.finditer(table_html):
        wiki_slug = m.group(1)
        name = m.group(2).strip()
        year = int(m.group(4))
        albums.append({"name": name, "year": year, "wiki_slug": wiki_slug})

    # Sort by year (should already be, but just in case)
    albums.sort(key=lambda a: a["year"])
    return albums


def _strip_html(s: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", s)


def _extract_title_from_cell(cell_html: str) -> str:
    """
    Extract a track title from a table cell or list item.
    Handles: "Title", "<a>Title</a>", quoted with inner links, etc.
    """
    text = _strip_html(cell_html)
    # Try to extract quoted title
    m = re.search(r'"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    # Fall back to text before duration-like patterns
    text = re.split(r"\s*[\u2013\u2014]\s*\d", text)[0]  # split on – or — followed by digit
    return text.strip(' "')


def fetch_tracklist(wiki_slug: str, album_name: str) -> list[str]:
    """
    Fetch an album's Wikipedia page and extract the tracklist.
    Returns a list of track names in order.
    Handles both formats: <table class="tracklist"> and simple <ol>.
    """
    page_title = urllib.parse.unquote(wiki_slug).replace("_", " ")
    html = _wiki_parse(page_title)

    tracks = []

    # Try Format B first: <table class="tracklist">
    tracklist_tables = list(re.finditer(r'<table\s+class="tracklist"', html))
    if tracklist_tables:
        for table_match in tracklist_tables:
            start = table_match.start()
            # Find end of this table
            depth = 0
            i = start
            end = len(html)
            while i < len(html):
                if html[i:i+6] == "<table":
                    depth += 1
                elif html[i:i+8] == "</table>":
                    depth -= 1
                    if depth == 0:
                        end = i + 8
                        break
                i += 1
            table_html = html[start:end]

            # Find each track row: <th scope="row">N.</th> followed by <td>...title...</td>
            # We grab everything between the track-number <th> and the next </td>
            row_pattern = re.compile(
                r'<th[^>]*scope="row"[^>]*>\s*\d+\.\s*</th>\s*<td>(.*?)</td>',
                re.DOTALL,
            )
            for rm in row_pattern.finditer(table_html):
                title = _extract_title_from_cell(rm.group(1))
                if title:
                    tracks.append(title)

        if tracks:
            return tracks

    # Try Format A: find Track listing section, then <ol>
    tl_idx = html.find('id="Track_listing"')
    if tl_idx == -1:
        tl_idx = html.lower().find('id="track_listing"')

    if tl_idx != -1:
        ol_start = html.find("<ol>", tl_idx)
        if ol_start != -1:
            ol_end = html.find("</ol>", ol_start)
            if ol_end != -1:
                ol_html = html[ol_start:ol_end]
                for li_m in re.finditer(r"<li>(.*?)</li>", ol_html, re.DOTALL):
                    title = _extract_title_from_cell(li_m.group(1))
                    if title:
                        tracks.append(title)

    if not tracks:
        print(f"    Warning: could not parse tracklist for '{album_name}' ({page_title})")

    return tracks


# ---------------------------------------------------------------------------
# Add a new artist
# ---------------------------------------------------------------------------

def add_artist(spotify_id: str, wiki_page: str | None, dry_run: bool, data_dir: Path = DATA_DIR):
    print(f"Fetching Kworb for Spotify ID {spotify_id}...")
    artist_name, last_updated, kworb_songs = fetch_kworb(spotify_id)
    print(f"  Artist: {artist_name}")
    print(f"  Kworb: {len(kworb_songs)} songs (updated {last_updated})")

    slug = _slug(artist_name)
    source_url = f"https://kworb.net/spotify/artist/{spotify_id}_songs.html"

    # Build stream lookup from Kworb
    stream_lookup: dict[str, int] = {}
    for s in kworb_songs:
        key = _normalize(s["song"])
        if key not in stream_lookup:
            stream_lookup[key] = s["streams"]

    # Fetch discography from Wikipedia
    _polite_pause()
    print(f"  Fetching Wikipedia discography...")
    studio_albums = fetch_studio_albums(artist_name, wiki_page)
    print(f"  Found {len(studio_albums)} studio albums")

    # Fetch tracklist for each album
    albums = []
    for i, album_info in enumerate(studio_albums):
        if i > 0:
            _polite_pause()
        print(f"  Fetching tracklist: {album_info['name']} ({album_info['year']})...", end=" ", flush=True)
        track_names = fetch_tracklist(album_info["wiki_slug"], album_info["name"])
        print(f"{len(track_names)} tracks")

        # Match tracks to Kworb stream counts
        tracks = []
        matched = 0
        for num, track_name in enumerate(track_names, 1):
            key = _normalize(track_name)
            streams = stream_lookup.get(key, 0)
            if streams > 0:
                matched += 1
            tracks.append({
                "num": num,
                "song": track_name,
                "streams": streams,
            })

        if track_names:
            print(f"    Matched {matched}/{len(track_names)} to Kworb streams")

        albums.append({
            "name": album_info["name"],
            "year": album_info["year"],
            "tracks": tracks,
        })

    # Summary
    total_tracks = sum(len(a["tracks"]) for a in albums)
    total_streams = sum(t["streams"] for a in albums for t in a["tracks"])
    print(f"\n  Summary: {len(albums)} albums, {total_tracks} tracks, {total_streams:,} streams")

    if dry_run:
        print("  Dry run — not writing")
        for a in albums:
            print(f"    {a['name']} ({a['year']}): {len(a['tracks'])} tracks")
            for t in a["tracks"]:
                marker = "+" if t["streams"] > 0 else "?"
                print(f"      [{marker}] {t['num']:2d}. {t['song']} — {t['streams']:,}")
        return

    # Write meta.json
    artist_dir = data_dir / slug
    snapshots_dir = artist_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "name": artist_name,
        "slug": slug,
        "spotify_id": spotify_id,
        "source_url": source_url,
    }
    meta_path = artist_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"  Wrote {meta_path}")

    # Write snapshot
    snapshot = {
        "date": last_updated,
        "albums": albums,
    }
    snap_path = snapshots_dir / f"{last_updated}.json"
    snap_path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"  Wrote {snap_path}")
    print(f"\n  Done! View with: make serve")


# ---------------------------------------------------------------------------
# Refresh existing artists
# ---------------------------------------------------------------------------

def refresh_artist(slug: str, dry_run: bool = False, data_dir: Path = DATA_DIR) -> bool:
    artist_dir = data_dir / slug
    meta_path = artist_dir / "meta.json"
    snapshots_dir = artist_dir / "snapshots"

    if not meta_path.exists():
        print(f"  [{slug}] No meta.json — use 'add' to create this artist")
        return False

    meta = json.loads(meta_path.read_text())
    name = meta["name"]
    spotify_id = meta.get("spotify_id")
    if not spotify_id:
        print(f"  [{slug}] No spotify_id in meta.json")
        return False

    snapshot_files = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []
    if not snapshot_files:
        print(f"  [{slug}] No snapshots — use 'add' to bootstrap")
        return False

    prev = json.loads(snapshot_files[-1].read_text())
    prev_date = prev.get("date", "?")

    print(f"  [{name}] Fetching kworb.net...", end=" ", flush=True)
    _, last_updated, scraped = fetch_kworb(spotify_id)
    print(f"{len(scraped)} songs (kworb updated {last_updated})")

    # Build lookup
    scraped_lookup: dict[str, int] = {}
    for s in scraped:
        key = _normalize(s["song"])
        if key not in scraped_lookup:
            scraped_lookup[key] = s["streams"]

    # Update counts
    matched = 0
    unmatched = []
    new_albums = []

    for album in prev["albums"]:
        new_tracks = []
        for track in album["tracks"]:
            key = _normalize(track["song"])
            if key in scraped_lookup:
                new_tracks.append({
                    "num": track["num"],
                    "song": track["song"],
                    "streams": scraped_lookup[key],
                })
                matched += 1
            else:
                new_tracks.append(track.copy())
                unmatched.append(f"{album['name']}: {track['song']}")
        new_albums.append({
            "name": album["name"],
            "year": album["year"],
            "tracks": new_tracks,
        })

    total_tracks = sum(len(a["tracks"]) for a in new_albums)
    print(f"  [{name}] Matched {matched}/{total_tracks} tracks")
    if unmatched:
        print(f"  [{name}] Unmatched (keeping old counts):")
        for u in unmatched:
            print(f"    {u}")

    old_total = sum(t["streams"] for a in prev["albums"] for t in a["tracks"])
    new_total = sum(t["streams"] for a in new_albums for t in a["tracks"])
    delta = new_total - old_total
    sign = "+" if delta >= 0 else ""
    print(f"  [{name}] {old_total:,} -> {new_total:,} ({sign}{delta:,}) prev={prev_date}")

    if dry_run:
        print(f"  [{name}] Dry run — not writing")
        return True

    new_snapshot = {"date": date.today().isoformat(), "albums": new_albums}
    out_path = snapshots_dir / f"{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(new_snapshot, indent=2) + "\n")
    print(f"  [{name}] Wrote {out_path}")
    return True


# ---------------------------------------------------------------------------
# Sync from config
# ---------------------------------------------------------------------------

def sync_from_config(config_path: Path, data_dir: Path, dry_run: bool):
    """
    Read artists.json, add any new artists, then refresh all.
    Config format: [{"spotify_id": "...", "wiki": "..."}, ...]
    """
    if not config_path.is_file():
        sys.exit(f"Config not found: {config_path}")

    artists = json.loads(config_path.read_text())
    print(f"Config: {len(artists)} artist(s) in {config_path.name}\n")

    # Pass 1: add any artists that don't have data yet
    added = 0
    for i, entry in enumerate(artists):
        sid = entry["spotify_id"]
        wiki = entry.get("wiki")

        # Check if already exists by scanning meta.json files for this spotify_id
        exists = False
        if data_dir.is_dir():
            for meta_path in data_dir.glob("*/meta.json"):
                meta = json.loads(meta_path.read_text())
                if meta.get("spotify_id") == sid:
                    exists = True
                    break

        if exists:
            continue

        if added > 0 or i > 0:
            _polite_pause()
        print(f"--- Adding new artist (spotify: {sid}) ---")
        add_artist(sid, wiki, dry_run, data_dir=data_dir)
        added += 1
        print()

    if added:
        print(f"Added {added} new artist(s).\n")

    # Pass 2: refresh all existing artists
    if not data_dir.is_dir():
        return

    slugs = sorted(
        p.name for p in data_dir.iterdir()
        if p.is_dir() and (p / "meta.json").exists()
    )
    if slugs:
        print(f"--- Refreshing {len(slugs)} artist(s) ---\n")
        for i, s in enumerate(slugs):
            if i > 0:
                _polite_pause()
            refresh_artist(s, dry_run=dry_run, data_dir=data_dir)
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape streaming data from Kworb + Wikipedia."
    )
    sub = parser.add_subparsers(dest="command")

    # --- add ---
    add_p = sub.add_parser("add", help="Add a new artist by Spotify ID")
    add_p.add_argument("spotify_id", help="Spotify artist ID")
    add_p.add_argument("--wiki", help="Wikipedia discography page title (if auto-detect fails)")
    add_p.add_argument("--dry-run", action="store_true")
    add_p.add_argument("--data-dir", type=Path, default=DATA_DIR)

    # --- refresh ---
    ref_p = sub.add_parser("refresh", help="Refresh stream counts for existing artist(s)")
    ref_p.add_argument("artist", nargs="?", help="Artist slug (directory name under data/)")
    ref_p.add_argument("--all", action="store_true", help="Refresh all artists")
    ref_p.add_argument("--dry-run", action="store_true")
    ref_p.add_argument("--data-dir", type=Path, default=DATA_DIR)

    # --- sync ---
    sync_p = sub.add_parser("sync", help="Add missing + refresh all artists from artists.json")
    sync_p.add_argument("--config", type=Path, default=ROOT / "artists.json",
                        help="Config file (default: artists.json)")
    sync_p.add_argument("--dry-run", action="store_true")
    sync_p.add_argument("--data-dir", type=Path, default=DATA_DIR)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    data_dir = args.data_dir.resolve()

    if args.command == "add":
        add_artist(args.spotify_id, args.wiki, args.dry_run, data_dir=data_dir)

    elif args.command == "refresh":
        if args.all:
            slugs = sorted(
                p.name for p in data_dir.iterdir()
                if p.is_dir() and (p / "meta.json").exists()
            )
            if not slugs:
                sys.exit("No artists found in data/")
            print(f"Refreshing {len(slugs)} artist(s)...\n")
            for i, s in enumerate(slugs):
                if i > 0:
                    _polite_pause()
                refresh_artist(s, dry_run=args.dry_run, data_dir=data_dir)
                print()
        elif args.artist:
            refresh_artist(args.artist, dry_run=args.dry_run, data_dir=data_dir)
        else:
            ref_p.print_help()
            sys.exit(1)

    elif args.command == "sync":
        sync_from_config(args.config, data_dir, args.dry_run)


if __name__ == "__main__":
    main()

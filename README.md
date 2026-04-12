# artist-stats

Track and visualize Spotify streaming data for your favorite artists.

**Live site**: https://mcmonkeyman.github.io/artist-stats/

Pulls stream counts from [Kworb](https://kworb.net) and album/track structure from Wikipedia, then renders interactive Chart.js dashboards — all songs charted chronologically by release, color-coded by album.

## Quick start

```bash
make serve          # open the dashboard at http://localhost:8787
```

## Adding artists

1. Find the artist's Spotify ID (from their Spotify URL: `open.spotify.com/artist/<ID>`)
2. Add an entry to `artists.json`:

```json
[
  {
    "spotify_id": "4Z8W4fKeB5YxbusRsdQVPb",
    "wiki": "Radiohead discography"
  }
]
```

3. Run:

```bash
make scrape         # adds new artists from artists.json + refreshes all
```

The `wiki` field is optional — it auto-detects from the artist name. Include it if the discography page has a non-standard title.

You can also add a single artist directly:

```bash
make add ID=4Z8W4fKeB5YxbusRsdQVPb
make add ID=4Z8W4fKeB5YxbusRsdQVPb WIKI="Radiohead discography"
```

## Refreshing data

```bash
make refresh        # pull latest stream counts from Kworb for all artists
```

This updates the numbers without re-scraping Wikipedia. Each run writes a new dated snapshot under `data/<artist>/snapshots/` — commit them to track changes over time.

## Building static HTML

```bash
make build          # generates index + per-artist pages into build/
```

## Deployment

The site is automatically deployed to [GitHub Pages](https://mcmonkeyman.github.io/artist-stats/) on every push to `main` via the [`.github/workflows/deploy.yml`](https://github.com/mcmonkeyman/artist-stats/blob/main/.github/workflows/deploy.yml) action. The workflow runs `make build` and publishes the `build/` directory.

## Commands

```
make help           show all commands
make serve          start local dashboard
make build          generate static HTML
make scrape         sync artists.json: add new + refresh all
make add ID=...     add a single artist by Spotify ID
make refresh        refresh stream counts for all artists
make clean          remove build output and venv
```

## Project structure

```
artists.json                    # artists to track (spotify IDs + optional wiki page)
data/
  <artist>/
    meta.json                   # name, slug, spotify_id, source_url
    snapshots/
      2026-03-22.json           # full album/track/stream data per date
scripts/
  scrape.py                     # fetch from Kworb + Wikipedia, write snapshots
  render.py                     # serve or build the dashboard from snapshots
```

## Data sources

- **Stream counts**: [Kworb](https://kworb.net) (scraped politely — one request per artist, 2s delay between requests)
- **Album/track structure**: [Wikipedia](https://en.wikipedia.org) (via the parse API with `maxlag` to avoid load during high-traffic periods)

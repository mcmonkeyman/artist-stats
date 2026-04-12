#!/usr/bin/env python3
"""
Renders artist streaming data from JSON snapshots as a local website
with interactive Chart.js charts.

Usage:
    python3 scripts/render.py [--data-dir data] [--port 8787]
    python3 scripts/render.py [--data-dir data] --build [--out build]

Reads data/{artist}/meta.json + data/{artist}/snapshots/*.json,
serves an index page and per-artist detail pages.
"""

import argparse
import html
import http.server
import json
import re
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_artists(data_dir: Path) -> list[dict]:
    """Walk data/*/, read meta.json + latest snapshot for each artist."""
    artists = []
    for meta_path in sorted(data_dir.glob("*/meta.json")):
        meta = json.loads(meta_path.read_text())
        snapshots_dir = meta_path.parent / "snapshots"
        snapshot_files = sorted(snapshots_dir.glob("*.json"))
        if not snapshot_files:
            continue
        latest = json.loads(snapshot_files[-1].read_text())
        artists.append({"meta": meta, "snapshot": latest})
    return artists


def find_artist(artists: list[dict], slug: str) -> dict | None:
    for a in artists:
        if a["meta"].get("slug", _slug(a["meta"]["name"])) == slug:
            return a
    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _smart_tick(max_val: int) -> str:
    if max_val >= 1_000_000_000:
        return "v => (v/1e9).toFixed(1) + 'B'"
    elif max_val >= 1_000_000:
        return "v => (v/1e6).toFixed(0) + 'M'"
    elif max_val >= 1_000:
        return "v => (v/1e3).toFixed(0) + 'K'"
    return "v => v.toLocaleString()"


def _album_colors(albums: list[dict]) -> dict[str, str]:
    palette = [
        "rgba(29, 185, 84, 0.8)",   # green
        "rgba(86, 156, 214, 0.8)",   # blue
        "rgba(206, 145, 52, 0.8)",   # gold
        "rgba(197, 81, 99, 0.8)",    # rose
        "rgba(127, 186, 122, 0.8)",  # sage
        "rgba(156, 120, 192, 0.8)",  # purple
        "rgba(78, 201, 176, 0.8)",   # teal
        "rgba(214, 157, 133, 0.8)",  # salmon
        "rgba(220, 220, 170, 0.8)",  # cream
        "rgba(128, 128, 128, 0.8)",  # grey
    ]
    colors = {}
    for i, a in enumerate(albums):
        colors[a["name"]] = palette[i % len(palette)]
    return colors


# ---------------------------------------------------------------------------
# Chart JS generation (preserved from original)
# ---------------------------------------------------------------------------

def build_chart_js(albums: list[dict]) -> str:
    colors = _album_colors(albums)

    # All songs in chronological order
    all_tracks = []
    for a in albums:
        for t in a["tracks"]:
            all_tracks.append({
                "song": t["song"],
                "album": a["name"],
                "streams": t["streams"],
                "color": colors[a["name"]],
            })

    ranked_labels = [t["song"] for t in all_tracks]
    ranked_streams = [t["streams"] for t in all_tracks]
    ranked_colors = [t["color"] for t in all_tracks]
    ranked_albums = [t["album"] for t in all_tracks]
    ranked_height = max(400, len(all_tracks) * 22)
    ranked_tick = _smart_tick(max(ranked_streams) if ranked_streams else 0)

    legend_items = []
    seen = set()
    for a in albums:
        if a["name"] not in seen:
            seen.add(a["name"])
            legend_items.append({"name": f"{a['name']} ({a['year']})", "color": colors[a["name"]]})

    per_album_js = []
    for a in albums:
        slug = _slug(a["name"])
        songs = [t["song"] for t in a["tracks"]]
        streams = [t["streams"] for t in a["tracks"]]
        track_tick = _smart_tick(max(streams) if streams else 0)
        height = max(120, len(songs) * 28)
        per_album_js.append(f"""
  document.getElementById('wrap-{slug}').style.height = '{height}px';
  new Chart(document.getElementById('chart-{slug}'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(songs)},
      datasets: [{{
        data: {json.dumps(streams)},
        backgroundColor: '{colors[a["name"]]}',
        borderColor: '{colors[a["name"]].replace("0.8", "1")}',
        borderWidth: 1
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: ctx => ctx.raw.toLocaleString() + ' streams'
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#888', callback: {track_tick} }},
          grid: {{ color: '#333' }}
        }},
        y: {{
          ticks: {{ color: '#d4d4d4', font: {{ size: 11 }} }},
          grid: {{ display: false }}
        }}
      }}
    }}
  }});""")

    return f"""
  var rankedAlbums = {json.dumps(ranked_albums)};
  document.getElementById('chart-overview').parentElement.style.height = '{ranked_height}px';
  new Chart(document.getElementById('chart-overview'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(ranked_labels)},
      datasets: [{{
        data: {json.dumps(ranked_streams)},
        backgroundColor: {json.dumps(ranked_colors)},
        borderWidth: 0
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            title: ctx => ctx[0].label,
            label: ctx => rankedAlbums[ctx.dataIndex] + ' \\u2014 ' + ctx.raw.toLocaleString() + ' streams'
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#888', callback: {ranked_tick} }},
          grid: {{ color: '#333' }}
        }},
        y: {{
          ticks: {{ color: '#d4d4d4', font: {{ size: 10 }} }},
          grid: {{ display: false }}
        }}
      }}
    }}
  }});

  (function() {{
    var items = {json.dumps(legend_items)};
    var el = document.getElementById('chart-legend');
    if (!el) return;
    el.innerHTML = items.map(function(it) {{
      return '<span style="display:inline-flex;align-items:center;margin-right:1rem;margin-bottom:.3rem">'
        + '<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:' + it.color + ';margin-right:.4rem"></span>'
        + '<span style="color:#d4d4d4;font-size:.85rem">' + it.name + '</span></span>';
    }}).join('');
  }})();

{"".join(per_album_js)}
"""


# ---------------------------------------------------------------------------
# HTML body builders (from JSON, no markdown parsing)
# ---------------------------------------------------------------------------

def build_artist_body(artist: dict) -> str:
    meta = artist["meta"]
    snap = artist["snapshot"]
    albums = snap["albums"]
    name = html.escape(meta["name"])
    parts = []

    parts.append(f'<p style="margin-bottom:1rem"><a href="/">&larr; All Artists</a></p>')
    parts.append(f"<h1>{name} &mdash; Spotify Streams</h1>")
    parts.append(f'<p>Snapshot: {html.escape(snap["date"])}</p>')
    if meta.get("source_url"):
        parts.append(f'<p>Source: <a href="{html.escape(meta["source_url"])}">{html.escape(meta["source_url"])}</a></p>')

    # Overview chart
    parts.append("<hr>")
    parts.append(
        '<div class="overview-section">'
        '<h2>All Songs &mdash; Chronological by Release</h2>'
        '<div id="chart-legend" style="margin:.5rem 0;display:flex;flex-wrap:wrap"></div>'
        '<div class="chart-wrap"><canvas id="chart-overview"></canvas></div>'
        '</div>'
    )

    # Per-album sections
    for album in albums:
        slug = _slug(album["name"])
        parts.append("<hr>")
        parts.append(f'<h2>{html.escape(album["name"])} ({album["year"]})</h2>')
        parts.append(f'<div class="chart-wrap" id="wrap-{slug}"><canvas id="chart-{slug}"></canvas></div>')

        parts.append('<table><thead><tr>')
        parts.append('<th style="text-align:left">#</th>')
        parts.append('<th style="text-align:left">Song</th>')
        parts.append('<th style="text-align:right">Streams</th>')
        parts.append('</tr></thead><tbody>')
        album_total = 0
        for t in album["tracks"]:
            album_total += t["streams"]
            parts.append(
                f'<tr><td>{t["num"]}</td>'
                f'<td>{html.escape(t["song"])}</td>'
                f'<td style="text-align:right">{t["streams"]:,}</td></tr>'
            )
        parts.append("</tbody></table>")
        parts.append(f"<p><strong>Album total:</strong> ~{album_total:,}</p>")

    return "\n".join(parts)


def build_index_body(artists: list[dict]) -> str:
    parts = []
    parts.append("<h1>Arpression</h1>")
    parts.append("<p>Spotify streaming data, visualized.</p>")
    parts.append("<hr>")
    parts.append('<div class="artist-grid">')

    for a in artists:
        meta = a["meta"]
        snap = a["snapshot"]
        slug = meta.get("slug", _slug(meta["name"]))
        total = sum(
            t["streams"]
            for album in snap["albums"]
            for t in album["tracks"]
        )
        n_albums = len(snap["albums"])
        n_tracks = sum(len(album["tracks"]) for album in snap["albums"])
        parts.append(
            f'<a href="/artist/{slug}" class="artist-card">'
            f'<h2>{html.escape(meta["name"])}</h2>'
            f'<p>{n_albums} albums &middot; {n_tracks} tracks</p>'
            f'<p class="total">{total:,} total streams</p>'
            f'<p class="date">Snapshot: {html.escape(snap["date"])}</p>'
            f'</a>'
        )

    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

BASE_CSS = """\
  :root { --bg: #181a1b; --fg: #d4d4d4; --accent: #1db954; --muted: #888; --border: #333; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--fg); max-width: 900px; margin: 2rem auto; padding: 0 1.5rem;
         line-height: 1.6; }
  h1 { color: var(--accent); margin-bottom: .25rem; }
  h2 { color: var(--accent); margin-top: 2rem; margin-bottom: .5rem; }
  hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
  p  { margin: .5rem 0; }
  a  { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  strong { color: #eee; }
  canvas { margin: 1rem 0; }
  .chart-wrap { position: relative; width: 100%; }
  table { width: 100%; border-collapse: collapse; margin: .75rem 0; }
  th, td { padding: .4rem .75rem; border-bottom: 1px solid var(--border); }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: .85rem; text-transform: uppercase; }
  tr:hover td { background: #222; }
  .overview-section { margin: 1.5rem 0 2.5rem; }"""

INDEX_CSS = """\
  .artist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
  .artist-card { display: block; padding: 1.25rem; border: 1px solid var(--border); border-radius: 8px;
                 transition: border-color .2s; }
  .artist-card:hover { border-color: var(--accent); text-decoration: none; }
  .artist-card h2 { margin-top: 0; font-size: 1.3rem; }
  .artist-card .total { color: var(--accent); font-weight: 600; font-size: 1.1rem; }
  .artist-card .date { color: var(--muted); font-size: .85rem; }"""


def wrap_page(title: str, body: str, chart_js: str = "", extra_css: str = "") -> str:
    script_tag = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>' if chart_js else ""
    js_block = f"""
<script>
Chart.defaults.color = '#d4d4d4';
Chart.defaults.borderColor = '#333';
{chart_js}
</script>""" if chart_js else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{script_tag}
<style>
{BASE_CSS}
{extra_css}
</style>
</head>
<body>
{body}
{js_block}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def build_index_page(artists: list[dict]) -> bytes:
    body = build_index_body(artists)
    return wrap_page("Arpression", body, extra_css=INDEX_CSS).encode()


def build_artist_page(artist: dict) -> bytes:
    body = build_artist_body(artist)
    albums = artist["snapshot"]["albums"]
    chart_js = build_chart_js(albums)
    title = f"{artist['meta']['name']} — Spotify Streams"
    return wrap_page(title, body, chart_js=chart_js).encode()


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def make_handler(data_dir: Path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            artists = load_artists(data_dir)
            path = self.path.rstrip("/") or "/"

            if path == "/" or path == "/index.html":
                content = build_index_page(artists)
            elif path.startswith("/artist/"):
                slug = path.split("/artist/", 1)[1].rstrip("/")
                artist = find_artist(artists, slug)
                if not artist:
                    self.send_error(404, f"Artist not found: {slug}")
                    return
                content = build_artist_page(artist)
            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            pass

    return Handler


# ---------------------------------------------------------------------------
# Static build
# ---------------------------------------------------------------------------

def build_static(data_dir: Path, out_dir: Path):
    artists = load_artists(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Index
    (out_dir / "index.html").write_bytes(build_index_page(artists))
    print(f"  index.html")

    # Artist pages
    for a in artists:
        slug = a["meta"].get("slug", _slug(a["meta"]["name"]))
        artist_dir = out_dir / "artist" / slug
        artist_dir.mkdir(parents=True, exist_ok=True)
        (artist_dir / "index.html").write_bytes(build_artist_page(a))
        print(f"  artist/{slug}/index.html")

    print(f"Built {len(artists)} artist page(s) into {out_dir}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Serve or build a streaming-data dashboard from JSON snapshots."
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data",
                        help="Path to data directory (default: data/)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--build", action="store_true",
                        help="Generate static HTML instead of serving")
    parser.add_argument("--out", type=Path, default=ROOT / "build",
                        help="Output directory for --build (default: build/)")
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        parser.error(f"Data directory not found: {args.data_dir}")

    if args.build:
        build_static(args.data_dir, args.out)
    else:
        url = f"http://localhost:{args.port}"
        server = http.server.HTTPServer(("127.0.0.1", args.port), make_handler(args.data_dir))
        print(f"Serving at {url}  (Ctrl-C to stop)")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()

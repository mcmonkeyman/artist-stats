#!/usr/bin/env python3
"""
Renders an artist-albums streaming markdown file as styled HTML with
interactive charts.

Usage:
    python3 scripts/render.py <markdown_file> [--port PORT]

The markdown file should follow this format:

    # Artist — Title
    ...
    ## Album Name (Year)
    | # | Song | Streams |
    |---|------|--------:|
    | 1 | Track | 123,456 |
    ...

Opens http://localhost:PORT in the default browser.
No external dependencies — uses only the Python standard library.
Charts powered by Chart.js (loaded from CDN).
"""

import argparse
import html
import http.server
import json
import re
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Parse artist & album data from any conforming markdown
# ---------------------------------------------------------------------------

def parse_title(md: str) -> str:
    """Extract the h1 title, or return a fallback."""
    m = re.search(r"^# (.+)$", md, re.MULTILINE)
    return m.group(1) if m else "Streaming Data"


def parse_albums(md: str) -> list[dict]:
    albums = []
    current = None

    for line in md.split("\n"):
        # Album heading: ## Album Name (Year)
        m = re.match(r"^## (.+?) \((\d{4})\)\s*$", line)
        if m:
            current = {"name": m.group(1), "year": int(m.group(2)), "tracks": []}
            albums.append(current)
            continue

        # Table row: | 1 | Song Name | 123,456,789 |
        if current is not None:
            m = re.match(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*([\d,]+)\s*\|", line)
            if m:
                current["tracks"].append({
                    "num": int(m.group(1)),
                    "song": m.group(2).strip(),
                    "streams": int(m.group(3).replace(",", "")),
                })

    return albums


# ---------------------------------------------------------------------------
# Minimal markdown-to-HTML converter
# ---------------------------------------------------------------------------

def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    in_table = False
    aligns: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if re.match(r"^---+\s*$", line):
            if in_table:
                out.append("</tbody></table>")
                in_table = False
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = _inline(m.group(2))
            tag = f"<h{level}>{text}</h{level}>"
            # Inject chart canvas placeholder after each album h2
            album_m = re.match(r"^## (.+?) \((\d{4})\)\s*$", lines[i])
            if album_m:
                slug = _slug(album_m.group(1))
                tag += f'\n<div class="chart-wrap" id="wrap-{slug}"><canvas id="chart-{slug}"></canvas></div>'
            out.append(tag)
            i += 1
            continue

        if line.startswith("|"):
            if not in_table:
                headers = _table_cells(line)
                i += 1
                if i < len(lines) and lines[i].startswith("|"):
                    aligns = _table_aligns(lines[i])
                    i += 1
                else:
                    aligns = ["left"] * len(headers)
                out.append('<table><thead><tr>')
                for h, a in zip(headers, aligns):
                    out.append(f'<th style="text-align:{a}">{_inline(h)}</th>')
                out.append('</tr></thead><tbody>')
                in_table = True
            while i < len(lines) and lines[i].startswith("|"):
                cells = _table_cells(lines[i])
                out.append("<tr>")
                for c, a in zip(cells, aligns):
                    out.append(f'<td style="text-align:{a}">{_inline(c)}</td>')
                out.append("</tr>")
                i += 1
            continue

        if re.match(r"^[-*]\s+", line):
            out.append("<ul>")
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                text = re.sub(r"^[-*]\s+", "", lines[i])
                out.append(f"<li>{_inline(text)}</li>")
                i += 1
            out.append("</ul>")
            continue

        if re.match(r"^\d+\.\s+", line):
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                text = re.sub(r"^\d+\.\s+", "", lines[i])
                out.append(f"<li>{_inline(text)}</li>")
                i += 1
            out.append("</ol>")
            continue

        if line.strip() == "":
            if in_table:
                out.append("</tbody></table>")
                in_table = False
            i += 1
            continue

        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    if in_table:
        out.append("</tbody></table>")

    return "\n".join(out)


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _table_cells(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [c.strip() for c in line.split("|")]


def _table_aligns(sep_line: str) -> list[str]:
    cells = _table_cells(sep_line)
    aligns = []
    for c in cells:
        c = c.strip()
        if c.endswith(":") and c.startswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# Build chart JS from parsed album data
# ---------------------------------------------------------------------------

def _smart_tick(max_val: int) -> str:
    """Return a JS callback string that picks a human-readable suffix."""
    if max_val >= 1_000_000_000:
        return "v => (v/1e9).toFixed(1) + 'B'"
    elif max_val >= 1_000_000:
        return "v => (v/1e6).toFixed(0) + 'M'"
    elif max_val >= 1_000:
        return "v => (v/1e3).toFixed(0) + 'K'"
    return "v => v.toLocaleString()"


def _album_colors(albums: list[dict]) -> dict[str, str]:
    """Assign each album a distinct color for the ranked overview chart."""
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
        "rgba(128, 128, 128, 0.8)",  # grey (fallback)
    ]
    colors = {}
    for i, a in enumerate(albums):
        colors[a["name"]] = palette[i % len(palette)]
    return colors


def build_chart_js(albums: list[dict]) -> str:
    # --- All songs in chronological order (album release date, then track #) ---
    colors = _album_colors(albums)
    all_tracks = []
    for a in albums:
        for t in a["tracks"]:
            all_tracks.append({
                "song": t["song"],
                "album": a["name"],
                "streams": t["streams"],
                "color": colors[a["name"]],
            })

    ranked_labels = [f"{t['song']}" for t in all_tracks]
    ranked_streams = [t["streams"] for t in all_tracks]
    ranked_colors = [t["color"] for t in all_tracks]
    ranked_albums = [t["album"] for t in all_tracks]
    ranked_height = max(400, len(all_tracks) * 22)
    ranked_tick = _smart_tick(max(ranked_streams) if ranked_streams else 0)

    # Build legend entries (unique albums in palette order)
    legend_items = []
    seen = set()
    for a in albums:
        if a["name"] not in seen:
            seen.add(a["name"])
            legend_items.append({"name": f"{a['name']} ({a['year']})", "color": colors[a["name"]]})

    # Per-album chart configs
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
  // --- Ranked all-songs chart ---
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
            label: ctx => rankedAlbums[ctx.dataIndex] + ' — ' + ctx.raw.toLocaleString() + ' streams'
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

  // --- Album color legend ---
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

  // --- Per-album charts ---
{"".join(per_album_js)}
"""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {{ --bg: #181a1b; --fg: #d4d4d4; --accent: #1db954; --muted: #888; --border: #333; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--fg); max-width: 900px; margin: 2rem auto; padding: 0 1.5rem;
         line-height: 1.6; }}
  h1 {{ color: var(--accent); margin-bottom: .25rem; }}
  h2 {{ color: var(--accent); margin-top: 2rem; margin-bottom: .5rem; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}
  p  {{ margin: .5rem 0; }}
  a  {{ color: var(--accent); }}
  strong {{ color: #eee; }}
  canvas {{ margin: 1rem 0; }}
  .chart-wrap {{ position: relative; width: 100%; }}
  table {{ width: 100%; border-collapse: collapse; margin: .75rem 0; }}
  th, td {{ padding: .4rem .75rem; border-bottom: 1px solid var(--border); }}
  th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: .85rem; text-transform: uppercase; }}
  tr:hover td {{ background: #222; }}
  ul, ol {{ margin: .5rem 0 .5rem 1.5rem; }}
  li {{ margin: .2rem 0; }}
  .overview-section {{ margin: 1.5rem 0 2.5rem; }}
</style>
</head>
<body>
{body}

<script>
Chart.defaults.color = '#d4d4d4';
Chart.defaults.borderColor = '#333';
{chart_js}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def build_page(md_path: Path) -> bytes:
    md = md_path.read_text()
    title = parse_title(md)
    albums = parse_albums(md)
    body_html = md_to_html(md)

    # Insert ranked all-songs chart right after the first <hr>
    overview = (
        '<div class="overview-section">'
        '<h2>All Songs — Chronological by Release</h2>'
        '<div id="chart-legend" style="margin:.5rem 0;display:flex;flex-wrap:wrap"></div>'
        '<div class="chart-wrap"><canvas id="chart-overview"></canvas></div>'
        '</div>'
    )
    body_html = body_html.replace("<hr>", f"<hr>\n{overview}", 1)

    chart_js = build_chart_js(albums)
    # Strip markdown bold markers from title for the <title> tag
    plain_title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
    page = TEMPLATE.format(title=html.escape(plain_title), body=body_html, chart_js=chart_js)
    return page.encode()


def make_handler(md_path: Path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            content = build_page(md_path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            pass  # quiet

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Render an artist-albums streaming markdown file as a local web page with charts."
    )
    parser.add_argument("file", type=Path, help="Path to the markdown file")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    md_path = args.file.resolve()
    if not md_path.is_file():
        parser.error(f"File not found: {md_path}")

    url = f"http://localhost:{args.port}"
    server = http.server.HTTPServer(("127.0.0.1", args.port), make_handler(md_path))
    print(f"Serving {md_path.name} at {url}  (Ctrl-C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

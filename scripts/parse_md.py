#!/usr/bin/env python3
"""Shared markdown parsing utilities for artist-album streaming data."""

import re


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

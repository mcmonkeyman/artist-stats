FILE ?= radiohead_spotify_streams.md
PORT ?= 8787

.PHONY: serve

serve: ## Render a streaming-data markdown file locally with charts
	@python3 scripts/render.py $(FILE) --port $(PORT)

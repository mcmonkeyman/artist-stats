DATA_DIR  ?= data
BUILD_DIR ?= build
PORT      ?= 8787

.PHONY: serve build add refresh clean

serve: ## Serve the dashboard locally
	@python3 scripts/render.py --data-dir $(DATA_DIR) --port $(PORT)

build: ## Generate static HTML into build/
	@python3 scripts/render.py --data-dir $(DATA_DIR) --build --out $(BUILD_DIR)

add: ## Add a new artist: make add ID=<spotify_id> [WIKI="Page title"]
	@python3 scripts/scrape.py add $(ID) $(if $(WIKI),--wiki "$(WIKI)",)

refresh: ## Refresh stream counts for all artists
	@python3 scripts/scrape.py refresh --all

scrape: ## Sync from artists.json: add new + refresh all
	@python3 scripts/scrape.py sync

clean: ## Remove build output
	rm -rf $(BUILD_DIR)

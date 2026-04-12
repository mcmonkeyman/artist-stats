DATA_DIR  ?= data
BUILD_DIR ?= build
PORT      ?= 8787
VENV      ?= .venv
PY        = $(VENV)/bin/python3

.PHONY: serve build add refresh scrape clean venv

venv: $(VENV)/.installed ## Create virtualenv and install dependencies

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements.txt
	@touch $@

serve: venv ## Serve the dashboard locally
	@$(PY) scripts/render.py --data-dir $(DATA_DIR) --port $(PORT)

build: venv ## Generate static HTML into build/
	@$(PY) scripts/render.py --data-dir $(DATA_DIR) --build --out $(BUILD_DIR)

add: venv ## Add a new artist: make add ID=<spotify_id> [WIKI="Page title"]
	@$(PY) scripts/scrape.py add $(ID) $(if $(WIKI),--wiki "$(WIKI)",)

refresh: venv ## Refresh stream counts for all artists
	@$(PY) scripts/scrape.py refresh --all

scrape: venv ## Sync from artists.json: add new + refresh all
	@$(PY) scripts/scrape.py sync

clean: ## Remove build output and venv
	rm -rf $(BUILD_DIR) $(VENV)

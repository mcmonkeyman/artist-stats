DATA_DIR  ?= data
BUILD_DIR ?= build
PORT      ?= 8787
VENV      ?= .venv
PY        = $(VENV)/bin/python3

.PHONY: help venv serve build scrape add refresh clean

help: ## Show this help
	@grep -E '^[a-z][a-z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk -F ':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: $(VENV)/.installed ## Create virtualenv and install deps

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements.txt
	@touch $@

# ── Viewing ──────────────────────────────────────────────────

serve: venv ## Start local dashboard (http://localhost:8787)
	@$(PY) scripts/render.py --data-dir $(DATA_DIR) --port $(PORT)

build: venv ## Generate static HTML into build/
	@$(PY) scripts/render.py --data-dir $(DATA_DIR) --build --out $(BUILD_DIR)

# ── Data ─────────────────────────────────────────────────────

scrape: venv ## Add new artists from artists.json + refresh all
	@$(PY) scripts/scrape.py sync

add: venv ## Add one artist: make add ID=<spotify_id>
	@$(PY) scripts/scrape.py add $(ID) $(if $(WIKI),--wiki "$(WIKI)",)

refresh: venv ## Refresh stream counts for all existing artists
	@$(PY) scripts/scrape.py refresh --all

# ── Housekeeping ─────────────────────────────────────────────

clean: ## Remove build output and venv
	rm -rf $(BUILD_DIR) $(VENV)

SHELL := /bin/bash
UV_BIN := $(shell command -v uv 2>/dev/null)

.PHONY: ensure-uv install dev run check test

ensure-uv:
	@if [ -z "$(UV_BIN)" ]; then \
		echo "uv not found, installing..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	else \
		echo "uv already installed: $(UV_BIN)"; \
	fi

install: ensure-uv
	uv sync

dev: install
	uv sync --dev

run:
	uv run music-monitor

check:
	uv run python -m compileall src

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q -p pytest_asyncio.plugin

PYTHON ?= python3

.PHONY: install build unit-test test lint format formatter typecheck

install:
	$(PYTHON) -m pip install -e ".[dev]"

build:
	$(PYTHON) -m build

unit-test:
	$(PYTHON) -m pytest tests

test: unit-test

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

formatter: format

typecheck:
	$(PYTHON) -m mypy src

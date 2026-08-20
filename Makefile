.PHONY: test lint run-example fmt install

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check src tests
	ruff format --check src tests

fmt:
	ruff check --fix src tests
	ruff format src tests

run-example:
	readyagents run examples/calc_pipeline.yaml
	readyagents run examples/approval_gate.yaml --approve gate
	readyagents run examples/composed_gate.yaml --approve gate

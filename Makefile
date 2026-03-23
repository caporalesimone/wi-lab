VERSION := $(shell cat VERSION)
COMPOSE := docker compose
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: help build-dev up down logs test test-verbose test-cov shell build-release run-release venv test-local test-local-quick test-local-cov clean-venv lint lint-fix type-check

# Default target: show help
help:
	@echo "Wi-Lab Development Targets"
	@echo ""
	@echo "Virtual Environment:"
	@echo "  make venv              Create local Python virtual environment"
	@echo "  make clean-venv        Remove virtual environment"
	@echo ""
	@echo "Testing (Local - uses venv):"
	@echo "  make test-local        Run all tests with verbose output"
	@echo "  make test-local-quick  Run tests with minimal output"
	@echo "  make test-local-cov    Run tests with coverage report (HTML)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint              Run ruff linter"
	@echo "  make lint-fix          Fix code style issues with ruff"
	@echo "  make type-check        Run mypy type checker"
	@echo ""
	@echo "Docker:"
	@echo "  make build-dev         Build Docker development image"
	@echo "  make up                Start containers"
	@echo "  make down              Stop containers"
	@echo "  make logs              View container logs"
	@echo "  make shell             Open shell in running container"
	@echo ""
	@echo "Release:"
	@echo "  make build-release     Build release Docker image"
	@echo "  make run-release       Run release image with host networking"

# Virtual environment setup
venv: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	@echo "Creating local virtual environment at $(VENV)..."
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements.txt
	@echo "✓ Virtual environment created. Activate with: source $(VENV)/bin/activate"

# Local test targets (use venv)
test-local: venv
	@echo "Running tests locally in venv..."
	$(PYTEST) tests/ -v --tb=short

test-local-quick: venv
	@echo "Running tests locally in venv (quick mode)..."
	$(PYTEST) tests/ -q

test-local-cov: venv
	@echo "Running tests with coverage report..."
	$(PYTEST) tests/ --cov=wilab --cov-report=html --cov-report=term
	@echo ""
	@echo "✓ Coverage report generated in htmlcov/index.html"

# Code quality targets
lint: venv
	@echo "Running ruff linter..."
	$(VENV)/bin/ruff check wilab/ tests/ --color=always
	@echo "✓ Lint check completed"

lint-fix: venv
	@echo "Running ruff formatter and fixer..."
	$(VENV)/bin/ruff check wilab/ tests/ --fix --color=always
	$(VENV)/bin/ruff format wilab/ tests/
	@echo "✓ Code formatted and issues fixed"

type-check: venv
	@echo "Running mypy type checker..."
	$(VENV)/bin/mypy wilab/ tests/ --color-output
	@echo "✓ Type check completed"

# Cleanup
clean-venv:
	@echo "Removing virtual environment..."
	rm -rf $(VENV)
	@echo "✓ Virtual environment removed"

# Docker targets
build-dev:
	$(COMPOSE) build --build-arg APP_VERSION=$(VERSION)

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f wilab

shell:
	$(COMPOSE) exec wilab bash

build-release:
	docker build -t wilab:$(VERSION) -f Dockerfile --build-arg APP_VERSION=$(VERSION) .

run-release:
	docker run --net=host --privileged --cap-add=NET_ADMIN --cap-add=NET_RAW \
	  -v $(PWD)/config.yaml:/app/config.yaml:ro \
	  wilab:$(VERSION)


build-release:
	docker build -t wilab:$(VERSION) -f Dockerfile --build-arg APP_VERSION=$(VERSION) .

run-release:
	docker run --net=host --privileged --cap-add=NET_ADMIN --cap-add=NET_RAW \
	  -v $(PWD)/config.yaml:/app/config.yaml:ro \
	  wilab:$(VERSION)


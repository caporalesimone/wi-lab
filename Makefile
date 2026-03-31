VERSION := $(shell cat VERSION)
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: help venv test-local test-local-quick test-local-cov clean-venv lint lint-fix type-check stop start restart build-frontend

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
	@echo "Frontend:"
	@echo "  make build-frontend    Build minified production frontend (via Docker)"
	@echo ""
	@echo "Service Management (requires root):"
	@echo "  make stop              Stop Wi-Lab systemd service"
	@echo "  make start             Start Wi-Lab systemd service"
	@echo "  make restart           Restart Wi-Lab systemd service"

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

# Service management targets
stop:
	@sudo bash scripts/stop-service.sh

start:
	@sudo bash scripts/start-service.sh

restart: stop
	@echo "Waiting 5 seconds before restart..."
	@sleep 5
	@sudo bash scripts/start-service.sh

# Frontend targets
build-frontend:
	@echo "Building minified production frontend (via Docker)..."
	cd frontend && bash deploy_frontend.sh
	@echo "✓ Frontend build complete"


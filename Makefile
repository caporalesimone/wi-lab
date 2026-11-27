VERSION := $(shell cat VERSION)
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: help venv lock frontend-check frontend-test test-local test-local-quick test-local-cov test-e2e test-e2e-usb clean-venv lint lint-fix type-check stop start restart build-frontend

# Default target: show help
help:
	@echo "Wi-Lab Development Targets"
	@echo ""
	@echo "Virtual Environment:"
	@echo "  make venv              Create local Python virtual environment"
	@echo "  make clean-venv        Remove virtual environment"
	@echo "  make lock              Regenerate requirements.lock (on purpose, then run the tests)"
	@echo "  make frontend-check    Compile the frontend (production build in Docker) without publishing it"
	@echo "  make frontend-test     Run the frontend specs (Node test runner in Docker, no browser)"
	@echo ""
	@echo "Testing (Local - uses venv):"
	@echo "  make test-local        Run unit tests with verbose output"
	@echo "  make test-local-quick  Run unit tests with minimal output"
	@echo "  make test-local-cov    Run unit tests with coverage report (HTML)"
	@echo ""
	@echo "Testing (E2E - on the Wi-Lab machine, against the running service):"
	@echo "  make test-e2e          API + server checks, no USB unplug"
	@echo "  make test-e2e-usb      Also simulate USB unplugs (WD-4/WD-5)"
	@echo "  Add WILAB_E2E_SLOW=1 for long tests; see docs/e2e-testing.md"
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

$(VENV)/bin/activate: requirements.lock
	@echo "Creating local virtual environment at $(VENV)..."
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements.lock
	@echo "✓ Virtual environment created. Activate with: source $(VENV)/bin/activate"

# Regenerate requirements.lock from requirements.txt in a clean venv (STAB-7).
# Only on purpose, then run the unit and e2e tests before committing it.
lock:
	rm -rf .lock-venv && python3 -m venv .lock-venv
	.lock-venv/bin/pip install -q -r requirements.txt
	{ head -3 requirements.lock; .lock-venv/bin/pip freeze | grep -viE '^(setuptools|wheel|pip)=='; } > requirements.lock.new
	mv requirements.lock.new requirements.lock && rm -rf .lock-venv
	@echo "✓ requirements.lock regenerated: review the diff, run the tests"

# Compile the frontend with its production build, in Docker, without touching
# frontend/dist (unit-test-15): a compile check before deploy_frontend.sh.
frontend-check:
	docker build -q -t wi-lab-frontend:check frontend >/dev/null
	docker rmi -f wi-lab-frontend:check >/dev/null
	@echo "✓ Frontend compiles (production build); nothing was published"

# Frontend specs (unit-test-15): compiled with the project's tsc and run with Node's
# test runner inside the build image (it has node_modules); no browser needed.
frontend-test:
	docker build -q -t wi-lab-frontend:check frontend >/dev/null
	docker run --rm wi-lab-frontend:check sh -c "npx tsc -p tsconfig.spec.json && node --test out-tsc/spec/app/services/*.spec.js"
	docker rmi -f wi-lab-frontend:check >/dev/null
	@echo "✓ Frontend specs passed"

# Local test targets (use venv)
test-local: venv
	@echo "Running tests locally in venv..."
	$(PYTEST) tests/unit-tests -v --tb=short

test-local-quick: venv
	@echo "Running tests locally in venv (quick mode)..."
	$(PYTEST) tests/unit-tests -q

test-local-cov: venv
	@echo "Running tests with coverage report..."
	$(PYTEST) tests/unit-tests --cov=wilab --cov-report=html --cov-report=term
	@echo ""
	@echo "✓ Coverage report generated in htmlcov/index.html"

# End-to-end tests: run on the Wi-Lab machine against the running service
test-e2e: venv
	WILAB_E2E=1 $(PYTEST) tests/e2e-tests -v --tb=short

test-e2e-usb: venv
	WILAB_E2E=1 WILAB_E2E_USB=1 $(PYTEST) tests/e2e-tests -v --tb=short

# Code quality targets
lint: venv
	@echo "Running ruff linter..."
	$(VENV)/bin/ruff check wilab/ tests/ --color=always
	$(VENV)/bin/ruff check wilab/ main.py --select G004 --color=always
	@echo "✓ Lint check completed"

lint-fix: venv
	@echo "Running ruff formatter and fixer..."
	$(VENV)/bin/ruff check wilab/ tests/ --fix --color=always
	$(VENV)/bin/ruff format wilab/ tests/
	@echo "✓ Code formatted and issues fixed"

type-check: venv
	@echo "Running mypy type checker..."
	$(VENV)/bin/mypy wilab/ tests/unit-tests --color-output
	$(VENV)/bin/mypy tests/e2e-tests --color-output
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


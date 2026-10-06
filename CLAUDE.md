# Wi-Lab - project rules

Rules and decisions agreed on this project, kept here so they survive across sessions.
Coding conventions also live in `.github/python.instructions.md`, `.github/angular.instructions.md`
and `.github/copilot-instructions.md`: follow those too. When something here conflicts with an
older document, this file wins; the design document
[TODOs/completed/device-capabilities.md](TODOs/completed/device-capabilities.md) records the why.

## Working with the maintainer

- Code, APIs, documentation, commit messages and everything else written into the repository must
  be **strictly in English**.
- Only when replying to a request, use the language the request was written in.
- Commit and push when the maintainer asks (or asks for pipeline results); after a push, check the
  GitHub pipeline (`gh pr checks <n>`) and report the result. Work happens on the feature branch and
  the open pull request, never directly on `main`.
- The git user is the maintainer's own (`git config user.name`).
- **GitHub token:** it lives in `.git/gh_token`. Never read it into the conversation, never print
  or echo it, never put it in a file. Only *use* it, for example
  `GH_TOKEN="$(tr -d '\r\n' < .git/gh_token)" gh ...`, and mask it in any command output.
  The token cannot read repository Actions settings (403): those are changed by the maintainer.
- Prefer a clear error to an ambiguous behaviour, and a clean breaking change to a compatibility
  layer ("rendi il cambio netto"). Do not add backward-compatibility shims.
- End a piece of work with what was fixed and what is **still to do**.

## Repository layout

- Repository root: only what tools or users expect there. `main.py` (entry point), `README.md`,
  `CHANGELOG.md`, `LICENSE`, `CLAUDE.md`, `VERSION`, `Makefile`, `requirements*.txt`, `config.example.yaml`,
  `pyproject.toml` (tool configuration), and the user-facing `install.sh` / `uninstall.sh`. Do not add
  new scripts to the root.
- `scripts/`: developer and operations scripts: `update_version.sh`, `export_api_docs.py`,
  `cleanup_pr_runs.py`, `start-service.sh`, `stop-service.sh`. New helper scripts go here.
- `install/`: the installer stages used by `install.sh`. `diagnostics/`: troubleshooting scripts for a
  real machine. `docs/`: user and developer documentation. `TODOs/`: design proposals
  (`TODOs/completed/` once released). `wilab/`: the backend. `frontend/`: the Angular UI. `tests/`: pytest.
- Tests are run with pytest (or `make test-local`); there is no separate test-runner script.

## Product rules: devices, capabilities, reservations

- A device declares its **capabilities** in `config.yaml` (`2.4ghz`, `5ghz`). The declaration is
  **authoritative**: a device declared 2.4 GHz-only provides only 2.4 GHz. The hardware is never
  probed to infer capabilities, and Wi-Lab never edits the configuration.
- `config.yaml` is **validated, never corrected**: every key is mandatory, the whole report is
  shown at once (`python3 main.py --validate-config`, `--check-hardware`), and the service refuses
  to start on an invalid file. Rules live in `wilab/config_validation.py`.
- `POST /api/v1/device-reservation` takes `duration_seconds` and `required_capabilities`, **both
  mandatory**. `required_capabilities` must list **at least one** capability: no empty list and no
  "any device". Unknown fields are rejected (`extra="forbid"`). A client cannot choose the antenna
  (the `interface` field was removed on purpose; reintroduce it only if a real need appears).
- **Allocation:** assign the free device with the **fewest capabilities beyond those requested**;
  ties go to the first declared. Never waste a dual-band device when a tighter one is free.
  Examples: a 5 GHz request gets a 5 GHz-only device first, then a dual-band one (and the response
  lists both of its capabilities); a request for a band no device has is an error.
- **Errors:** `409` = matching devices exist but are all reserved (transient, `next_available_*`
  may be `null` when every holder is unlimited, `next_available_at` is UTC); `422` = the request is
  wrong or no device will ever satisfy it (permanent); never `409` for an impossible request.
- **Bands are enforced by the server:** creating a network with a `band` the reserved device does not
  declare (`dual` needs both) is refused at once with `422`, before touching the hardware.
- TX power control did not work with the USB dongles tested so far: every place that exposes it
  (API docs, web UI, troubleshooting, CHANGELOG) carries the warning "not guaranteed". Keep it.

## API documentation (Swagger / ReDoc)

- The OpenAPI schema is the documentation. Every endpoint has a `summary`, a description, response
  examples for each status (`200/401/409/422`...) and, for request bodies, named examples. Fields
  have descriptions and examples. Tests guard the important parts (see `test_reservation_capabilities.py`).
- **Group order and text** come from `OPENAPI_TAGS` in `wilab/api/__init__.py`: `System` is always
  first, every group has a description. A new tag must be added there.
- The default request example of the reservation is the dual-band one; there is no empty example.
- Group descriptions are shown below the title (shared stylesheet `wilab/api/docs_style.py`, used by
  the live `/docs` and by the exported `swagger.html`).
- `scripts/export_api_docs.py` builds `openapi.json`, `swagger.html` and `redoc.html` (offline,
  self-contained, schema references inlined) and zips them. CI builds it on every PR; the workflow
  `release-docs.yml` attaches the zip to every GitHub release (a release asset: it never expires).

## Versioning and documentation

- Change the version only with `./scripts/update_version.sh --bump-to X.Y.Z`: it updates `VERSION`,
  `frontend/package.json` and `frontend/package-lock.json` together and refuses a version that is not
  greater than the current one. It can be run from any directory.
- Breaking changes for API clients are explained in section 19 "Migration from older versions" of the
  design document.
- Keep README, `docs/`, `config.example.yaml`, Swagger text and the design document consistent with
  the code in the same change. Do not leave a statement that is no longer true.

## Code and tests

- Layers: API routes -> managers -> system commands. **No `subprocess` outside
  `wilab/network/commands.py`.** Type hints everywhere; `logging`, never `print` in production code.
- Before committing: `ruff check wilab tests scripts`, `mypy wilab tests`, and the full test suite.
  `pyproject.toml` pins the ruff rules (E4, E7, E9, F); do not rely on ruff's defaults.
- Add tests for every new behaviour. Tests never touch real hardware (`ip`, `iw`, hostapd, dnsmasq,
  iptables are replaced) and must be **OS independent**: the suite must pass on Windows and Linux.
  Shared helpers are in `tests/helpers.py` (`device_specs()` builds dual-band devices).
- Every pytest run ends with a **coverage report** (configured in `pyproject.toml`; HTML with
  `--cov-report=html` or `make test-local-cov`). CI also posts it in the job summary. Keep coverage
  from dropping; prefer testing error paths of the API layer.
- Reservation allocation is tested on a ten-antenna pool with simultaneous reservations
  (`tests/test_reservation_pool.py`): keep it passing when touching `wilab/reservation.py`.
- Local run: `.venv/Scripts/python.exe -m pytest` (Windows) or `make test-local`. Frontend:
  `cd frontend && npm test` (set `CHROME_BIN`; headless: `--watch=false --browsers=ChromeHeadlessCI`).

## Frontend

- The web UI will be **rewritten in the future**: do not invest in new UI tests now. Keep the existing
  dialog test, and verify UI changes manually. The API contract (Swagger) is the stable interface.
- Component style budget (`anyComponentStyle` in `frontend/angular.json`) is **4 kB warning / 5 kB
  error**. This is temporary: remind the maintainer to revisit it (shrink `network-card` SCSS, which
  is near 4 kB, or drop the budget) whenever styles or `angular.json` are touched.
- Prefer existing Material components over new SCSS to stay inside the budget.

## Tool configuration (`pyproject.toml`)

- One file configures **pytest** (`[tool.pytest.ini_options]`: test paths, strict markers, coverage in
  `addopts`), **ruff** (`[tool.ruff]`, rules under `[tool.ruff.lint]`) and **mypy** (`[tool.mypy]` with
  the pydantic plugin, `[tool.pydantic-mypy]`). Change a tool's behaviour there, not on a command line.
  Registering a pytest marker means adding it to `markers` (unknown markers fail the run).
- It has **no `[project]` table on purpose**: the project is deployed from a checkout, not packaged. The
  version has a single source, the `VERSION` file, changed only by `scripts/update_version.sh`; never
  add a version to `pyproject.toml`. If packaging is ever needed, make `VERSION` and the script
  follow it deliberately instead of keeping two sources.
- Do not recreate `pytest.ini`, `ruff.toml` or `mypy.ini`: they take precedence over `pyproject.toml`
  and would silently override it.

## CI / GitHub (`.github/workflows/`)

- `ci.yml` runs on pull requests and on `main`: backend (ruff, mypy, example-config validation,
  pytest with coverage), frontend (unit tests, production build), the frontend container build, the
  API docs bundle, and a last job that cleans up old runs. All on `ubuntu-latest`. Keep the
  actions (`checkout`, `setup-python`, `setup-node`, `upload-artifact`) on a current major version,
  one that runs on a supported Node runtime.
- **Run retention:** only the **3 most recent runs of each pull request** are kept; older ones are
  deleted by the last CI job (`scripts/cleanup_pr_runs.py`), with no age rule. There is no cron: nothing
  must run while the project is idle. Runs on `main`, releases and manual runs are never deleted.
- The `wi-lab-api-docs-<version>` artifact is kept for **90 days** (the maximum GitHub allows; there is no
  "forever"). In pull requests it goes away earlier, with its run, when the cleanup job deletes it.
- Do not add scheduled workflows without asking: the project has very little maintenance and
  resources must not be wasted.

## Line endings and files

- Working-tree files use CRLF (Windows); some are LF. Preserve whatever a file already uses when editing
  (edits must not rewrite whole files). Git prints "LF will be replaced by CRLF" warnings: ignore them.
- Generated output (`api-docs/`, `htmlcov/`, `.coverage`) is gitignored; never commit it.

## Changelog (`CHANGELOG.md`)

- **Where a change goes:** until a release is made, or unless the maintainer asks otherwise, every change
  goes in the `[Unreleased]` section. If the version was already bumped during development (before the
  pull request is merged), later changes go in that version. Only closing the PR and the branch ends a
  version.
- **`[Unreleased]` must not exist** when the work on the branch is finished: its entries belong to the
  version.
- **Format of a version:** `[x.y.z] - yyyy-mm-dd`. Whenever you edit a version that already has a date,
  update the date to today.
- **Sections**, in this order: Breaking Changes, Features, Bug Fixes, Maintenance, CI/CD, Tests. Write
  only the sections that have something to say. Breaking Changes always come first.
- **CI/CD** describes what changed in the pipelines and releases (workflows, artifacts, run retention),
  as descriptive bullet points like every other section.
- **Tests** are listed only for interesting changes or additions that give significant value. Never
  list every test added: it is noise.
- **Style:** short bullet points. The purpose is to let the user of the product understand what changes
  in this release. Keep low-level, low-impact changes to the bare minimum. Do not say that a class or a
  function changed: say what the change is for. Changes and additions to the API deserve more detail.

# Frontend: new architecture, in a Docker container

**Priority:** 2 (MEDIUM)
**Status:** PROPOSED (2026-11-27), decisions below; one point TBD (accounts)

The web UI is rewritten as a separate application that runs in its own Docker
container, on the Wi-Lab machine or anywhere else. Wi-Lab becomes API only.

## Decisions (2026-11-27)

1. **The frontend runs in Docker.** One image: the compiled single-page app
   served by nginx, which also forwards the API (below). The CI of the
   repository builds the image on every tag and publishes it
   (`ghcr.io/caporalesimone/wi-lab-frontend:<version>`).
2. **The Wi-Lab installer asks whether the frontend runs on this machine.**
   - **Yes:** Docker becomes a requirement (today's `02-docker.sh` check, run
     only in this case); a dedicated script builds the frontend image and
     starts it with a Docker Compose file made for this machine.
   - **No:** Docker is not required and not checked; the installer prints how
     to run the image elsewhere (`docker run -e WILAB_API_URL=... -p 80:80 ...`
     or the same compose file).
3. **No CORS.** The browser talks to one origin only, the frontend's: nginx in
   the container serves the UI and forwards `/api/` (and the event streams) to
   Wi-Lab. `cors_origins` stays `null`; the option may be removed later.

## TBD

- **Accounts: one shared access, or users and an administrator?**
  - *A. One shared access (today):* the Bearer token of `config.yaml`, typed
    in the browser and kept there. Simplest; everyone sees and can do
    everything; a leaked token is the whole lab.
  - *B. One shared access, token kept server-side:* a login page; the
    container (a small backend next to nginx, "backend for frontend") holds
    the token and gives the browser a session cookie. The token never
    reaches the browser; still one role.
  - *C. Users and an administrator:* Wi-Lab (or the frontend backend) knows
    users. A user sees and acts on their own reservations; the administrator
    also sees the logs and other users' reservations, releases everything and
    runs the protected commands (today `protected_commands_password`).
    Needed if raw logs are shown (they contain SSIDs, MACs and other users'
    reservation IDs) and if the lab is shared by teams.
  - Decide before the API changes for events and logs: their visibility
    depends on it.

## Container

- Image: multi-stage build (Node to compile, nginx to serve), a few tens of MB.
- Runtime configuration, not build time: `WILAB_API_URL` (default
  `http://127.0.0.1:8080` with the host network). An entrypoint writes it into
  the nginx configuration; the same image works with any Wi-Lab.
- nginx:
  - `/` serves the app, with a fallback to `index.html` for its routes;
  - `/api/` is forwarded to `WILAB_API_URL`, with `proxy_buffering off` and
    long read timeouts for the event streams (Server-Sent Events);
  - `/docs`, `/redoc`, `/openapi.json` forwarded too, so the API docs stay
    reachable from the UI.
- Health check: `GET /` of nginx and `GET /api/v2/status` through the proxy.
- Runs as non-root; read-only filesystem except nginx's temporary directories.

## Installer

- `install.sh` asks: "Will the web frontend run on this machine? (Y/n)". The
  answer is saved in the install state (`FRONTEND_LOCAL=1/0`), so a
  re-install does not ask again unless `--reconfigure-frontend` is given.
- Preconditions: `02-docker.sh` runs only with `FRONTEND_LOCAL=1`.
- **Dedicated script** `install/frontend/install-frontend.sh` (also usable
  alone, to add or rebuild the frontend later):
  1. checks Docker and Docker Compose (`docker compose version`);
  2. builds the image from `frontend/` with the version of the repository
     (`wi-lab-frontend:<version>`), or pulls it from the registry when asked
     (`--pull`);
  3. writes `/etc/wilab/frontend/compose.yaml` for this machine: the image,
     `network_mode: host` (so `127.0.0.1:8080` is Wi-Lab), the port (asked,
     default 80, must differ from `api_port` and `captive_portal_port`),
     `restart: unless-stopped`, the health check;
  4. `docker compose -f /etc/wilab/frontend/compose.yaml up -d`;
  5. waits for the health check and prints the URL.
- `install/frontend/uninstall-frontend.sh`: `compose down`, removes the image
  and `/etc/wilab/frontend`; called by `uninstall.sh` when `FRONTEND_LOCAL=1`.
- `05-deploy-frontend.sh` and `frontend/deploy_frontend.sh` (the build into
  `frontend/dist` served by Wi-Lab) go away.
- With the API reachable through the frontend's proxy, the installer may
  offer to bind Wi-Lab's API to `127.0.0.1` only (a new `api_host` setting):
  clients on the network then use the frontend's port for both. Open point.

## Wi-Lab side

- Remove the frontend routes (`serve_frontend`, `serve_index`) and the
  `_candidate_frontend_paths` lookup: Wi-Lab serves only `/api/v2`, `/docs`,
  `/redoc`. This removes the whole class of SEC-1.
- APIs the new UI needs (separate work, see the Fable notes):
  - `health` in `GET /antennas/{interface}` (repair budgets used and left,
    quarantines, last USB reset);
  - events: `GET /api/v2/events` and its stream (SSE), see
    [realtime-events.md](realtime-events.md);
  - logs: a ring buffer of structured records (`wilab/log.py` already adds
    antenna and reservation) with `GET /api/v2/logs` and its stream; who may
    read them depends on the accounts decision;
  - `restart_required` of `/status` (done) for the red bar.

## Application

- Framework: React + Vite + TanStack Query (recommended for a full rewrite),
  or Angular brought up to date (less migration). To decide when the work
  starts.
- Typed API client generated from Wi-Lab's OpenAPI in the build: a contract
  change breaks the compile instead of the UI.
- Push instead of polling: one event stream for the whole UI; polling only as
  a fallback.
- Pages: antennas overview; antenna detail (capabilities, health, budget);
  reservation and network (settings, clients, restarts, Internet, QoS);
  events and logs (live, filtered by antenna and reservation); system
  (version, `restart_required`, monitoring checks).
- Keep what REV-13/REV-14 fixed in the current UI: create polling rules,
  reservation IDs kept across reloads, every `404` reason as a sentence.
- API functions the current UI does not use (Fable REV-15, moved here on
  2026-11-27; the new UI must have them):
  - **Cancel a start.** The card that launched a start disables everything
    while it polls, and Stop is disabled on the others. The backend accepts
    `DELETE .../network` (and the release) during `starting`: a "Cancel start"
    button unsubscribes the polling, calls the stop, then reads the status.
  - **`restarts`** of `GET .../network` is not shown: a line "Watchdog
    restarts: AP n, DHCP m, last <reason> at <time>" when `ap + dhcp > 0`.
  - **`error` of `start_failed`** appears only in a toast of the card that
    polled: show `error.message` and `error.stage` under the state, on every
    card and after a reload.
  - **Choose the antenna.** `interface` of `POST /reservations` is never
    sent: the reserve dialog offers the free antennas of `GET /antennas`.
  - **`health`** of `GET /antennas/{interface}` (budgets, quarantines, USB
    resets) on the antenna detail page.
  - Done already: compile check without publishing (`make frontend-check`) and
    the create specs (`make frontend-test`, unit-test-15).

## Tests and CI

- Unit tests of the app (Vitest) and end-to-end tests of the UI against a
  Wi-Lab with fake radios (Playwright) in CI.
- CI builds and publishes the image on tags; on pull requests it only builds.
- The installer's tests (`install/03-tests`) check the frontend only when
  `FRONTEND_LOCAL=1`: compose service healthy, `GET /` and
  `GET /api/v2/status` through the proxy.

## Steps

1. Decide the accounts point (TBD above).
2. Wi-Lab APIs: `health`, events, logs (independent of the UI).
3. Container and nginx configuration with today's UI, the installer question
   and `install-frontend.sh`; remove the frontend routes from Wi-Lab.
4. CI: build and publish the image.
5. The new application, page by page, replacing today's UI in the same image.

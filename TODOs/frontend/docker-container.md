# Feature: Frontend in a Docker Container

**Priority:** 2  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

Run the web UI as a separate application in its own container, on the Wi-Lab
machine or elsewhere; Wi-Lab becomes API only. Decided on 2026-11-27.

## Part 1: Container

- [ ] Multi-stage image (Node to build, nginx to serve), a few tens of MB; published by CI on tags (`ghcr.io/caporalesimone/wi-lab-frontend:<version>`)
- [ ] Runtime configuration: `WILAB_API_URL` (default `http://127.0.0.1:8080` with the host network), written into nginx by the entrypoint
- [ ] nginx serves the app (fallback to `index.html`) and forwards `/api/` (event streams with `proxy_buffering off`), `/docs`, `/redoc`, `/openapi.json`: one origin, no CORS
- [ ] Health check: `GET /` and `GET /api/v2/status` through the proxy; non-root, read-only filesystem

## Part 2: Installer

- [ ] `install.sh` asks whether the frontend runs on this machine (`FRONTEND_LOCAL=1/0`, kept in the install state)
- [ ] `02-docker.sh` runs only with `FRONTEND_LOCAL=1`
- [ ] `install/frontend/install-frontend.sh`: checks Docker Compose, builds or pulls the image, writes `/etc/wilab/frontend/compose.yaml` (host network, port, restart policy, health check), starts it, prints the URL
- [ ] `install/frontend/uninstall-frontend.sh`, called by `uninstall.sh`
- [ ] Remove `05-deploy-frontend.sh`, `frontend/deploy_frontend.sh` and Wi-Lab's frontend routes (`serve_frontend`, `serve_index`, `_candidate_frontend_paths`)
- [ ] Open point: bind Wi-Lab's API to `127.0.0.1` only (`api_host`) when the proxy is the only entry

## Testing

- [ ] CI builds the image on pull requests and publishes on tags
- [ ] Installer tests check the compose service, `GET /` and `GET /api/v2/status` through the proxy when `FRONTEND_LOCAL=1`

## Benefits

- **Separation:** Wi-Lab serves only the API; the UI can run anywhere
- **Security:** Removes the class of SEC-1 (files served by the API)

## Breaking Changes

- Yes: Wi-Lab no longer serves the UI

## Success Criteria

- ✅ The UI runs from the container and talks to Wi-Lab through nginx
- ✅ The installer sets it up when asked

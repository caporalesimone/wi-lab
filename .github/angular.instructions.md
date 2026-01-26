---
description: 'Angular-specific coding standards and best practices'
applyTo: '**/*.ts, **/*.html, **/*.scss, **/*.css'
---

# Angular Development Instructions (Wi-Lab Frontend)

Wi-Lab frontend: Angular standalone, Material Design, Bearer token authentication, environment-driven API configuration.

## Wi-Lab Specifics

- **Build output**: Docker builds to `/dist/wi-lab-frontend/browser/` (served by FastAPI).
- **API integration**: All calls to `/api/v1/*` endpoints; use Bearer token in `Authorization: Bearer <token>` header via HTTP interceptor.
- **Environment config**: API base URL from `environment.ts` (dev localhost:8000) and `environment.prod.ts` (production).
- **CORS**: Configured backend-side; frontend passes credentials in HTTP calls.
- **Features**: Network form (create AP), status display, client list, internet toggle, TX power 1-4 slider.
- **State**: Signals for reactive updates (`signal()`, `computed()`, `effect()`); prefer signals over RxJS where possible.

## Development Workflow

- **Standalone components**: Default; no NgModules except app.config.ts for root providers.
- **API service** (`wilab-api.service.ts`): Centralized HTTP client with Bearer token interceptor; typed request/response.
- **Signals**: `signal()` for mutable state (form data, network list, UI flags); `computed()` for derived state (filtered clients, enabled features).
- **Components**: Smart parent (app.component) orchestrates API calls and state; presentational (network-card, dialog) receive inputs/emit outputs.
- **Forms**: Reactive `FormBuilder`; Material input/select components; custom validators for ssid/password.
- **Styling**: SCSS with Material Design tokens; scoped per component.
- **AsyncPipe**: Pipe computed signals directly in templates; handle observables from RxJS operations (e.g., network creation).
- **Tests**: Jasmine + Karma; mock API service, test signal updates, verify HTTP calls.
- **Build**: `npm run build:prod` outputs to `dist/` (Docker uses this).

## Conventions

- **File naming**: `-component.ts` (UI), `-service.ts` (HTTP/state), `.models.ts` (interfaces), `.config.ts` (providers).
- **Interfaces**: Define request/response types in `models/`; match backend Pydantic models.
- **Constants**: Environment-based (dev vs. prod); avoid magic strings.
- **JSDoc**: Document public methods and complex logic; include param/return types.

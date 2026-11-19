# Wi-Lab Frontend

Angular frontend for Wi-Lab WiFi Access Point management system.

## Features

- ✅ Real-time network status monitoring with automatic polling (5 seconds)
- ✅ Start/Stop WiFi networks
- ✅ Enable/Disable Internet access per network
- ✅ Modern Material Design UI
- ✅ Responsive layout

## Prerequisites

- Node.js 18+ and npm
- Angular CLI (install with `npm install -g @angular/cli`)

## Recovery in the dashboard

- On a Wi-Fi start failure with `409 / 1001`, the dashboard automatically
  retries the same configuration and reservation after `Retry-After`, up to
  two retries. The card shows the wait and blocks duplicate starts.
- On `500 / 1003`, it removes the invalidated reservation from the dashboard
  and browser storage without sending a release. A generic `500` leaves the
  reservation in place.
- On `503 / 1002` from a reservation request, the dashboard enables **Retry
  Reservation** after `Retry-After`; it does not reserve anything in the
  background. `503 / 1003` does not offer a retry. Recovering and unavailable
  antennas are shown but excluded from the available count.
- During watchdog restoration, the card displays whether the AP or DHCP is
  being restored. A DHCP failure can leave the AP on but unable to issue leases.

See the [API recovery contract](../docs/network-creation-failure.md).

## Installation

1. Install dependencies:
```bash
npm install
```

2. Configure API connection in `src/environments/environment.ts`:
```typescript
export const environment = {
  apiUrl: 'http://localhost:8080/api/v1',
  authToken: 'your-token-here', // Match your backend config.yaml
  pollingInterval: 5000
};
```

3. Configure CORS in backend `config.yaml`:
```yaml
cors_origins:
  - "http://localhost:4200"
```

## Development

Run development server:
```bash
ng serve
# or
npm start
```

The app will be available at `http://localhost:4200`

## Build for Production

```bash
ng build --configuration production
```

Output will be in `dist/wi-lab-frontend/` directory.

## Deploy to Ubuntu Server

1. Build the frontend:
```bash
ng build --configuration production
```

2. Copy `dist/wi-lab-frontend/` to your Ubuntu server

3. Serve with nginx or integrate with FastAPI static file serving

## Configuration

- **API URL**: Set in `src/environments/environment.ts`
- **Auth Token**: Set in `src/environments/environment.ts` (must match backend `config.yaml`)
- **Polling Interval**: Default 5 seconds, configurable in `environment.ts`

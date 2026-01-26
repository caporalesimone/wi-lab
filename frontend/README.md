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

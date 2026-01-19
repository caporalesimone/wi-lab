# Setup Guide - Wi-Lab Frontend

## Prerequisiti

1. **Node.js 18+** e npm installati
2. **Angular CLI** installato globalmente:
   ```bash
   npm install -g @angular/cli
   ```

## Installazione

1. Naviga nella cartella frontend:
   ```bash
   cd frontend
   ```

2. Installa le dipendenze:
   ```bash
   npm install
   ```

## Configurazione

### 1. Configurare il Backend (Ubuntu)

Nel file `config.yaml` del backend, aggiungi CORS per permettere richieste dal frontend:

```yaml
cors_origins:
  - "http://localhost:4200"           # Angular dev server (Windows)
  - "http://192.168.1.XXX:4200"      # Sostituisci con l'IP della tua VM Windows se diverso
```

**Nota**: Se Windows e Ubuntu sono sulla stessa macchina (VM), usa `localhost:4200`.

### 2. Configurare il Frontend (Windows)

Modifica `src/environments/environment.ts`:

```typescript
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8080/api/v1',  // Se backend su VM, usa IP della VM
  authToken: 'secret-token-12345',           // Deve corrispondere a config.yaml
  pollingInterval: 5000                      // Polling ogni 5 secondi
};
```

**Importante**: 
- Se il backend è su una VM Ubuntu, sostituisci `localhost:8080` con l'IP della VM (es. `http://192.168.1.XXX:8080`)
- Il `authToken` deve corrispondere esattamente a quello in `config.yaml` del backend

## Avvio

### Sviluppo

```bash
ng serve
# oppure
npm start
```

Il frontend sarà disponibile su `http://localhost:4200`

### Build per Produzione

```bash
ng build --configuration production
```

I file compilati saranno in `dist/wi-lab-frontend/`

## Troubleshooting

### Errore CORS

Se vedi errori CORS nel browser:
1. Verifica che `cors_origins` sia configurato in `config.yaml`
2. Verifica che l'URL nel frontend corrisponda a quello configurato
3. Riavvia il backend dopo aver modificato `config.yaml`

### Errore 401 Unauthorized

1. Verifica che `authToken` in `environment.ts` corrisponda a `auth_token` in `config.yaml`
2. Verifica che il backend sia in esecuzione

### Frontend non si connette al backend

1. Verifica che il backend sia in esecuzione: `curl http://localhost:8080/api/v1/health`
2. Se backend su VM, verifica l'IP e la connettività di rete
3. Controlla il firewall della VM Ubuntu

# Fable Notes - revisione del backend di Wi-Lab

- **Branch analizzato:** `fix/reservation-lifecycle` al commit `94c74b5` (31 commit avanti rispetto a `main`), versione 4.0.0.
- **Ambito:** tutti i file sotto `wilab/`, `main.py`, il template dell'unit systemd e i commit del branch.
  Frontend, installer e test sono stati letti solo dove spiegano il comportamento del backend.
- **Metodo:** sola lettura statica. Non è stato eseguito nulla: le dipendenze del backend non si sono
  potute installare su questa postazione (l'indice dei pacchetti ha rifiutato il download). Nessun test
  e nessun esperimento sostiene queste note, e nessuna macchina reale è stata toccata.
- **Criterio di priorità:** il servizio ha poco carico ma deve restare acceso 24 ore su 24, e una rete
  creata deve continuare a funzionare. Riavviarla è accettabile, lasciarla rotta no.
- **Le patch** riportate nelle schede sono proposte scritte leggendo il codice, **non provate**. Sono
  pensate per essere applicate da una persona o da un modello che poi esegue `ruff`, `mypy` e i test.

<a id="file-controllati-idx"></a>
## File controllati

Tutti i 39 file tracciati da git sotto `wilab/` sono stati letti per intero.

| Cartella | File |
|---|---|
| `wilab/` | `__init__.py`, `config.py`, `config_validation.py`, `models.py`, `reservation.py`, `timestamps.py`, `version.py` |
| `wilab/api/` | `__init__.py`, `auth.py`, `dependencies.py`, `errors.py` |
| `wilab/api/routes/` | `__init__.py`, `internet.py`, `network.py`, `qos_profile.py`, `recovery_responses.py`, `reservation.py`, `status.py`, `txpower.py` |
| `wilab/network/` | `__init__.py`, `captive.py`, `commands.py`, `dhcp.py`, `isolation.py`, `nat.py`, `qos.py`, `qos_profile.py`, `safety.py`, `subnet.py`, `unmanaged.py` |
| `wilab/wifi/` | `channels.py`, `discovery.py`, `hostapd.py`, `interface.py`, `manager.py`, `recovery.py`, `watchdog.py` |
| `wilab/data/qos-profiles/` | `default.json`, `profile.schema.json` |

Nota di trasparenza: nella prima stesura i due file JSON non erano stati letti. Sono stati controllati
in questa revisione e hanno prodotto un punto nuovo (BUG-9).

<a id="come-leggere-idx"></a>
## Come leggere il documento

Ogni punto ha un identificativo, una gravità e una confidenza.

| Gravità | Significato |
|---|---|
| Critica | Esposizione di sicurezza o perdita dell'intero servizio |
| Alta | Una rete o un adattatore si perde, o resta rotto, senza che il client lo sappia |
| Media | Comportamento sbagliato in un caso realistico ma meno frequente |
| Bassa | Rumore, estetica, o un caso che richiede una configurazione insolita |

| Confidenza | Significato |
|---|---|
| Confermato | Segue direttamente dal codice letto |
| Probabile | Segue dal codice più il comportamento documentato di uno strumento esterno (hostapd, iptables, systemd, pydantic, CPython) |
| Ipotesi | Plausibile, ma serve una prova su macchina reale prima di agire |

Prefissi degli identificativi: `SEC` sicurezza, `STAB` stabilità a lungo termine, `WD` watchdog e
recovery, `HAP` avvio di hostapd, `NET` firewall / DHCP / QoS, `BUG` errori logici, `RACE` concorrenza,
`PERF` prestazioni, `API` disegno delle API, `ARCH` struttura del codice.

Il documento è ordinato per priorità: le due tabelle del capitolo 2 e le schede del capitolo 4 seguono
lo stesso ordine, da 1 (più urgente) a 87. L'indice completo è in fondo. ✅ segna i punti corretti e committati, ✅ parz. quelli corretti in parte (il dettaglio è in [fable-todo.md](fable-todo.md)).

---

<a id="cap-1"></a>
## 1. Sintesi

Il branch ha lavorato bene sul percorso di **creazione** della rete: hostapd è un processo figlio
posseduto direttamente, la sua uscita si vede entro un secondo, i guasti transitori vengono ritentati
dentro la richiesta, gli avvii parziali vengono annullati e i lock sono per dispositivo.

Il lato debole è **cosa succede dopo il primo guasto e dopo giorni di attività**. Lo stesso schema
ritorna in molti punti: un meccanismo gestisce bene il primo problema e poi smette di provare, oppure
un errore transitorio viene promosso a uno stato permanente che solo un riavvio del servizio cancella.
E il riavvio, oggi, cancella le reti di tutti.

I guasti che hanno dato origine al lavoro (segfault di hostapd, beacon rifiutato, timeout) sono eventi
del driver. Il branch li gestisce correttamente, ma in tre modi diversi secondo il momento:

| Quando hostapd fallisce | Tentativi | Se falliscono |
|---|---|---|
| Durante la prima richiesta di creazione | fino a 3 | `409 / 1001`, la reservation resta |
| Durante una richiesta successiva | 1 | `409 / 1001`, oppure un `500` generico per il guasto di beacon (HAP-3) |
| Mentre la rete è attiva (watchdog) | 1, una sola volta per vita della rete | quarantena, oppure rete spenta in silenzio (WD-1, WD-2) |

Il momento più protetto è quello in cui un client sta aspettando e può semplicemente riprovare. Il meno
protetto è quello che interessa di più: una rete che funzionava e deve continuare a funzionare.

---

<a id="cap-2"></a>
## 2. Tabelle dei punti, in ordine di priorità

### 2.1 I dieci punti più importanti

| # | Id | Gravità | In una frase |
|---|---|---|---|
| 1 | [SEC-1](#sec-1) | Critica | La route che serve il frontend può restituire qualunque file dell'host senza autenticazione (`GET //etc/shadow`, `config.yaml` con il token). |
| 2 | [BUG-1](#bug-1) ✅ | Alta | Due validatori su tre della richiesta di creazione non girano mai; `ssid` non ha regole e un newline inietta righe in `hostapd.conf`. |
| 3 | [WD-2](#wd-2) ✅ | Alta | Se l'unico riavvio del watchdog fallisce per un motivo "non classificato", la rete resta spenta per sempre, senza `runtime_state` e senza avvisi. |
| 4 | [WD-1](#wd-1) ✅ | Alta | Il watchdog riavvia un AP **una sola volta per vita della rete**; al secondo guasto, anche settimane dopo, mette l'adattatore in quarantena. |
| 5 | [WD-4](#wd-4) ✅ | Alta | La quarantena non ha uscita per adattatori non USB, per cleanup falliti e dopo 10 reset falliti: serve un riavvio del servizio. |
| 6 | [NET-1](#net-1) ✅ | Alta | `iptables` è chiamato senza `-w`: con il backend legacy due chiamate concorrenti ne fanno fallire una, e uno stop fallito diventa quarantena. |
| 7 | [HAP-1](#hap-1) ✅ | Alta | Un SSID con caratteri non ASCII, virgolette o backslash non risulta mai "pronto": un adattatore sano finisce in quarantena con reset USB. |
| 8 | [STAB-1](#stab-1) ✅ | Alta | Un comando bloccato nel kernel fa attendere `subprocess.run` per sempre con il lock del dispositivo preso; il processo resta vivo e systemd non lo riavvia. |
| 9 | [NET-2](#net-2) ✅ | Alta | La creazione risponde `200` anche se NAT o isolamento non sono stati installati, e lo stato dice `internet_enabled: true`. |
| 10 | [HAP-3](#hap-3) ✅ | Alta | Lo stesso guasto di beacon è "radio" solo se avviene in un tentativo di retry; altrove diventa un `500` generico. |

### 2.2 Tutti gli altri punti

| # | Id | Gravità | In una frase |
|---|---|---|---|
| 11 | [HAP-2](#hap-2) ✅ | Alta | Una gara di pochi millisecondi decide se un guasto è `HostapdRadioFailure` o `HostapdInitFailure`, con conseguenze opposte. |
| 12 | [WD-3](#wd-3) ✅ | Alta | Un solo riavvio di dnsmasq per vita della rete, poi `dhcp_failed` per sempre con l'AP acceso. |
| 13 | [WD-5](#wd-5) ✅ parz. | Alta | Se l'interfaccia sparisce, lo stop di hostapd fallisce sempre: il dispositivo non si pulisce e non viene mai rimosso. |
| 14 | [WD-7](#wd-7) ✅ parz. | Media | Il watchdog controlla due processi, non la rete: indirizzo del gateway, regole firewall, `ip_forward` e trasmissione reale non sono verificati. |
| 15 | [WD-9](#wd-9) ✅ | Media | I thread di background non sono supervisionati: un'eccezione non prevista li termina per sempre; un `config.yaml` malformato uccide la discovery. |
| 16 | [STAB-4](#stab-4) ✅ | Media | All'avvio si puliscono solo le regole firewall: restano `tc`, dispositivi `ifb`, indirizzi, file e PID vecchi. |
| 17 | [SEC-3](#sec-3) ✅ | Media | L'API ascolta su `0.0.0.0`, quindi anche sulle reti Wi-Fi di test. |
| 18 | [SEC-2](#sec-2) | Media | `/debug` consegna a ogni client gli ID di reservation di tutti gli altri. |
| 19 | [RACE-1](#race-1) ✅ | Media | Le richieste aspettano il lock del dispositivo senza limite e possono esaurire i 40 thread dell'API. |
| 20 | [WD-6](#wd-6) ✅ | Media | Un cleanup bloccato viene ritentato ogni 5 secondi, per sempre, riempiendo il journal. |
| 21 | [HAP-4](#hap-4) ✅ | Media | Un tentativo di retry tagliato dal budget di 15 s conta come guasto radio. |
| 22 | [STAB-6](#stab-6) ✅ | Media | L'interfaccia upstream è risolta una volta e tenuta in cache per sempre. |
| 23 | [BUG-2](#bug-2) ✅ | Media | I controlli di salute di `/status` danno risposte sbagliate (`"UP" in`, `"MASQUERADE" in`). |
| 24 | [BUG-4](#bug-4) ✅ | Media | La cache dei canali è riempita una volta e mai aggiornata, ed esiste in due copie. |
| 25 | [NET-6](#net-6) ✅ | Media | Un lancio di dnsmasq andato in timeout non può più essere ripulito. |
| 26 | [WD-8](#wd-8) | Media | Una rete ripristinata dal watchdog perde il profilo QoS senza dirlo. |
| 27 | [STAB-5](#stab-5) | Media | Le scadenze usano l'orologio di sistema: un salto di orario fa scadere o allunga tutto. |
| 28 | [BUG-3](#bug-3) ✅ | Media | La validazione offline della configurazione è più severa di quella usata all'avvio. |
| 29 | [NET-5](#net-5) ✅ | Media | Ogni avvio di rete scrive nel log condizioni normali come `ERROR`. |
| 30 | [NET-3](#net-3) ✅ | Media | L'isolamento tra reti funziona solo se le subnet iniziano per `192.168.`. |
| 31 | [STAB-2](#stab-2) | Media | I file di runtime stanno in `/tmp`: possono essere cancellati per età e il percorso è prevedibile. |
| 32 | [STAB-7](#stab-7) | Media | Le dipendenze Python non sono bloccate a versioni precise. |
| 33 | [NET-11](#net-11) | Media | QoS inline: `upload_quality` viene ignorato se è presente `download_quality`. |
| 34 | [HAP-8](#hap-8) | Media | L'output di hostapd non viene conservato: un crash non si può diagnosticare dopo. |
| 35 | [HAP-5](#hap-5) | Media | Ipotesi: nessun tempo di assestamento e nessuna serializzazione tra radio all'avvio. |
| 36 | [HAP-6](#hap-6) | Media | Ipotesi: il comando TX power subito dopo l'avvio stressa un driver già fragile. |
| 37 | [BUG-5](#bug-5) | Media | La discovery può ignorare un adattatore per sempre, loggando solo a livello debug. |
| 38 | [BUG-9](#bug-9) | Media | Un profilo QoS personalizzato che passa lo schema può impedire l'avvio del servizio. |
| 39 | [STAB-9](#stab-9) | Bassa | Il rilascio da NetworkManager è solo a runtime e si perde se NetworkManager riparte. |
| 40 | [STAB-8](#stab-8) | Bassa | L'arresto ordinato può superare `TimeoutStopSec=30s`. |
| 41 | [WD-10](#wd-10) | Bassa | Tre probe lenti consecutivi riavviano un AP forse sano. |
| 42 | [HAP-9](#hap-9) | Bassa | Canali DFS con controllo radar di 10 minuti: il timeout di 75 s non basta mai. |
| 43 | [HAP-10](#hap-10) ✅ | Bassa | La configurazione generata ha chiavi duplicate; `encryption: "wpa"` è in realtà WPA2. |
| 44 | [HAP-11](#hap-11) ✅ | Media | Ogni rete usa 20 MHz e 802.11n su entrambe le bande, anche se gli adattatori supportano 40/80 MHz, 802.11ac e 802.11ax. |
| 45 | [NET-8](#net-8) | Bassa | `dns_server` ha come default `192.168.10.21`, un indirizzo di laboratorio. |
| 46 | [NET-12](#net-12) | Bassa | QoS: gara alla fine di un profilo `once`. |
| 47 | [NET-13](#net-13) | Bassa | QoS: lo stop del profilo può far fallire lo stop della rete. |
| 48 | [BUG-7](#bug-7) | Bassa | TX power: dopo un mismatch lo stato riportato non corrisponde all'hardware. |
| 49 | [BUG-8](#bug-8) | Bassa | Il token Bearer è confrontato con `!=` invece che a tempo costante. |
| 50 | [BUG-6](#bug-6) | Bassa | `validate_interface_ap_mode` non dimostra nulla (`"AP" in` su tutto il testo). |
| 51 | [NET-9](#net-9) | Bassa | Le subnet non sono stabili tra un riavvio e l'altro. |
| 52 | [NET-7](#net-7) | Bassa | I file dei lease DHCP sopravvivono alla reservation. |
| 53 | [NET-10](#net-10) | Bassa | Captive portal: porta 80 occupata, `Content-Length` malformato, indice della regola di protezione. |
| 54 | [NET-4](#net-4) ✅ | Bassa | Riga di log falsa: `Isolation disabled for testing`. |
| 55 | [HAP-7](#hap-7) | Bassa | Ipotesi: `hostapd -d` resta attivo per tutta la vita dell'AP. |
| 56 | [RACE-2](#race-2) ✅ | Bassa | `/status` legge stato condiviso senza i lock dei dispositivi. |
| 57 | [RACE-3](#race-3) | Bassa | Lo stato di `QosManager` non ha lock. |
| 58 | [PERF-3](#perf-3) | Bassa | `/status` costa tre comandi a chiamata, due sono `iptables -S`. |
| 59 | [PERF-1](#perf-1) ✅ parz. | Bassa | L'avvio di una rete esegue circa 20 comandi oltre a hostapd. |
| 60 | [PERF-2](#perf-2) | Bassa | `GET .../network` costa due o tre comandi a chiamata, sotto lock. |
| 61 | [PERF-5](#perf-5) | Bassa | `execute_command` impone un timeout minimo di 5 s all'insaputa del chiamante. |
| 62 | [PERF-6](#perf-6) | Bassa | Il cambio di TX power blocca la richiesta per 3 s sotto lock. |
| 63 | [PERF-4](#perf-4) | Bassa | Costo fisso di background: milioni di processi creati all'anno per fare polling. |
| 64 | [PERF-7](#perf-7) | Bassa | Memoria e descrittori: nessuna crescita trovata (punto informativo). |
| 65 | [API-2](#api-2) ✅ | Media | "Rete non attiva" ha due codici diversi: `409` per QoS, `404` per Internet e TX power. |
| 66 | [API-4](#api-4) ✅ | Media | `500` usato per esiti che riguardano il client. |
| 67 | [API-9](#api-9) ✅ | Media | Gli esempi OpenAPI sono corretti a mano e non corrispondono più ai modelli. |
| 68 | [API-5](#api-5) | Bassa | Le risposte di successo contengono solo una frase. |
| 69 | [API-10](#api-10) ✅ | Bassa | I campi sconosciuti nelle richieste vengono ignorati. |
| 70 | [API-3](#api-3) ✅ | Bassa | `409` significa sette cose diverse. |
| 71 | [API-11](#api-11) | Bassa | Il contratto di retry ha tre livelli; quello lato client è ormai ridondante. |
| 72 | [API-1](#api-1) | Bassa | Lo stesso dato è esposto in più punti con nomi diversi. |
| 73 | [API-8](#api-8) ✅ | Bassa | La risposta espone dettagli interni (`pid_file`, `process_stopped`). |
| 74 | [API-6](#api-6) ✅ parz. | Bassa | Nomi incoerenti (`/interface/{reservation_id}`, `tx_power_level` contro `level`). |
| 75 | [API-7](#api-7) | Bassa | Azioni modellate come percorsi (`/internet/enable`, `/internet/disable`). |
| 76 | [ARCH-2](#arch-2) | Media | La classificazione dei guasti è sparsa in quattro posti. |
| 77 | [ARCH-1](#arch-1) | Media | `NetworkManager` fa troppe cose (970 righe). |
| 78 | [ARCH-4](#arch-4) | Media | Il registro dei dispositivi esiste in quattro copie. |
| 79 | [ARCH-3](#arch-3) ✅ parz. | Bassa | Il modello dell'API è anche lo stato interno. |
| 80 | [ARCH-5](#arch-5) | Bassa | I singleton sono collegati per effetto collaterale. |
| 81 | [ARCH-6](#arch-6) | Bassa | Tre modi diversi di gestire un processo figlio. |
| 82 | [ARCH-7](#arch-7) | Bassa | Tre implementazioni di "rilascia da NetworkManager". |
| 83 | [ARCH-10](#arch-10) | Bassa | Il logging non ha una regola: errori falsi, guasti veri a `DEBUG`. |
| 84 | [ARCH-9](#arch-9) | Bassa | Codice morto, compresa una funzione pericolosa. |
| 85 | [ARCH-8](#arch-8) | Bassa | Attributi privati usati tra classi diverse. |
| 86 | [ARCH-12](#arch-12) ✅ | Bassa | `wilab/wifi/` e `wilab/data/` non hanno `__init__.py`. |
| 87 | [ARCH-11](#arch-11) | Bassa | Il layout di questo branch diverge dalle regole dell'altro branch. |

---

<a id="cap-3"></a>
## 3. Contesto: cosa ha cambiato il branch

I commit rilevanti per i crash di hostapd, dal più vecchio:

| Commit | Cosa fa |
|---|---|
| `c7cf83b` harden Wi-Fi lifecycle | Lock per dispositivo, rollback degli avvii parziali, watchdog, quarantena e recovery USB. |
| `6803551` continuous antenna discovery | I dispositivi sono scoperti a runtime; la configurazione li nomina soltanto. |
| `6a2d0b6`, `8fcc25e`, `168ae39`, `8fc241c` | Firewall: regole vecchie rimosse all'avvio, masquerade limitato alla subnet dell'AP, la disattivazione di Internet taglia i flussi esistenti. |
| `f5dcad5`, `87c3ce1` | Tiene NetworkManager e systemd-networkd lontani dalle radio, senza ricaricare NetworkManager. |
| `3f70cf9` fail fast on startup exit | I probe `hostapd_cli` durano al massimo 1 s e il processo è controllato tra un probe e l'altro; l'uscita dopo un beacon fallito diventa `HostapdInitFailure`. |
| `94c74b5` retry inside the create request | Fino a 3 avvii, a 1 s di distanza, entro 15 s. |

Sintomi documentati: `SIGSEGV` di hostapd all'avvio, "Failed to set beacon parameters" seguito da
"Interface initialization failed", timeout di readiness, e un adattatore `mt7921u` in una macchina KVM
che non si poteva più attivare (`RTNETLINK answers: Connection timed out`) fino a un reset USB.

**Cosa è solido nell'avvio.**

- hostapd gira in primo piano come figlio (`start_foreground`): codice di uscita e segnale sono noti
  subito e nessun file PID può mentire.
- Ogni istanza ha una cartella di controllo privata creata con `mkdtemp` (permessi 0700).
- "Pronto" significa "stato ENABLED sull'interfaccia giusta", non "il processo è partito".
- L'ordine è AP, poi indirizzo del gateway, poi DHCP; ogni guasto passa da `release_device`.
- L'ordine dei lock è corretto e non ho trovato deadlock: il lock del dispositivo viene sempre preso
  prima di quello dello store delle reservation, il lock del firewall è una foglia, watchdog e ciclo di
  scadenza non si bloccano mai su un lock di dispositivo.

**Cosa manca.** Il branch non ha cercato cosa fa fallire il driver più del necessario (schede HAP-5,
HAP-6, HAP-7) e ha applicato la strategia di retry solo alla richiesta di creazione, non al watchdog.

---

<a id="cap-4"></a>
## 4. Schede di dettaglio, in ordine di priorità

Ogni scheda ha la stessa struttura: **Problema**, **Come si riproduce**, **Come correggerlo**. Dove è
utile c'è codice o una patch. I percorsi dei file sono relativi alla radice del repository.

<a id="sec-1"></a>
### 1. SEC-1 - Lettura di file senza autenticazione dalla route del frontend

**Gravità:** Critica · **Confidenza:** Probabile · **File:** [wilab/api/__init__.py:195-214](wilab/api/__init__.py#L195-L214)

**Problema.** Quando esiste la cartella del frontend compilato (l'installer la crea), `create_app`
registra `GET /{full_path:path}` e serve `frontend_path / full_path` se è un file. Non c'è alcun
controllo che il risultato resti dentro la cartella del frontend:

- se `full_path` inizia con `/` (richiesta `GET //etc/shadow`), unire un percorso assoluto a un `Path`
  scarta la parte sinistra: il file servito è `/etc/shadow`;
- i segmenti `..` inviati così come sono (`curl --path-as-is`) escono dalla cartella.

Il servizio gira come root e questa route non richiede il token. Si possono leggere `config.yaml`
(token dell'API e password dei comandi protetti), i file `hostapd.conf` con le passphrase WPA, e
qualunque altro file dell'host. Lo stesso handler restituisce `None`, cioè `200` con corpo `null`, per
i percorsi `/api/...` diversi da `/api/v1` e per `/docs/...`.

**Come si riproduce.** Su una macchina di test con il frontend compilato e il servizio avviato:

```bash
curl -s --path-as-is http://<host>:8080//etc/hostname
curl -s --path-as-is http://<host>:8080/../../../../config.yaml
```

Se la risposta è il contenuto del file, il difetto è confermato. Senza server: chiamare direttamente
la funzione `serve_frontend` con `full_path="/etc/hostname"` (vedi test T-01).

**Come correggerlo.** Risolvere il percorso e servirlo solo se resta dentro la cartella del frontend.

```diff
--- a/wilab/api/__init__.py
+++ b/wilab/api/__init__.py
@@ def create_app() -> FastAPI:
     if frontend_path:
+        frontend_root = frontend_path.resolve()
+
         @app.get("/", include_in_schema=False)
         async def serve_index():
-            index_path = frontend_path / "index.html"
+            index_path = frontend_root / "index.html"
             if index_path.is_file():
                 return FileResponse(index_path)
             return {"error": "Frontend index.html not found"}

         @app.get("/{full_path:path}", include_in_schema=False)
         async def serve_frontend(full_path: str):
-            if full_path == "api/v1" or full_path.startswith("api/v1/"):
+            # Paths owned by the API and its documentation are never the frontend.
+            if full_path.split("/", 1)[0] in {"api", "docs", "redoc", "openapi.json"}:
                 raise StarletteHTTPException(status_code=404)
-            if (
-                full_path.startswith("api/")
-                or full_path == "docs"
-                or full_path.startswith("docs/")
-                or full_path == "openapi.json"
-            ):
-                return None
-
-            file_path = frontend_path / full_path
-            if file_path.is_file():
-                return FileResponse(file_path)
+
+            # Never serve anything outside the frontend directory: an absolute
+            # path or ".." segments must not escape it.
+            candidate = (frontend_root / full_path.lstrip("/")).resolve()
+            if candidate.is_relative_to(frontend_root) and candidate.is_file():
+                return FileResponse(candidate)

-            index_path = frontend_path / "index.html"
+            index_path = frontend_root / "index.html"
             if index_path.is_file():
                 return FileResponse(index_path)
             return {"error": "Frontend not found"}
```

In alternativa si può montare `StaticFiles` di Starlette, che fa già questo controllo, e tenere solo
il fallback su `index.html`. Dopo la correzione conviene ruotare `auth_token` e
`protected_commands_password` sulle macchine già esposte.

---

<a id="bug-1"></a>
### 2. BUG-1 - Validazione mancante nella richiesta di creazione (iniezione in `hostapd.conf`) ✅

**Gravità:** Alta · **Confidenza:** Probabile · **File:** [wilab/models.py:8-81](wilab/models.py#L8-L81), [wilab/wifi/hostapd.py:131-184](wilab/wifi/hostapd.py#L131-L184)

**Problema.** Pydantic valida i campi nell'ordine in cui sono dichiarati, e a un `field_validator`
passa in `info.data` solo i campi dichiarati **prima**. `NetworkCreateRequest` dichiara
`ssid, channel, password, encryption, band`:

- `validate_channel_for_band` (su `channel`) cerca `band`, dichiarato dopo: esce sempre subito. La
  route valida comunque il canale contro l'hardware, quindi l'unico effetto è che il messaggio
  documentato non compare mai.
- `validate_password_length` (su `password`) cerca `encryption`, dichiarato dopo: esce sempre subito.
  Una passphrase di 3 o di 100 caratteri viene accettata, hostapd rifiuta la propria configurazione ed
  esce con codice 1, e il client riceve un `500` generico invece di `422`.
- `ssid` è un semplice `str`: può essere vuoto, più lungo di 32 byte, o contenere un newline.

Il caso del newline è quello serio. SSID e passphrase sono scritti in `hostapd.conf` con una f-string
(`f"ssid={ssid}"`, `f"wpa_passphrase={password}"`). Un valore come `"x\ninterface=eth0"` aggiunge una
riga a un file letto da un processo root, e in hostapd vince l'ultima riga. Un client autenticato può
quindi puntare hostapd su un'altra interfaccia o cambiare qualunque opzione.

**Come si riproduce.** Senza hardware, in un test:

```python
from wilab.models import NetworkCreateRequest

# Oggi tutte e tre le righe NON sollevano errore; dopo la correzione devono sollevarlo.
NetworkCreateRequest(ssid="a", channel=6, password="abc", encryption="wpa2", band="2.4ghz", tx_power_level=4)
NetworkCreateRequest(ssid="x\ninterface=eth0", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
NetworkCreateRequest(ssid="a", channel=99, encryption="open", band="5ghz", tx_power_level=4)
```

Con il servizio: una `POST .../network` con `"password": "abc"` risponde `500` con
"hostapd exited with code 1".

**Come correggerlo.** Due livelli: validare nel modello, e difendersi anche nel generatore.

```diff
--- a/wilab/models.py
+++ b/wilab/models.py
@@
+import re
 from enum import Enum
@@
+_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
+
+
 class NetworkCreateRequest(BaseModel):
-    ssid: str
+    ssid: str = Field(description="Network name: 1 to 32 bytes in UTF-8, no control characters")
     channel: int
@@
-    @field_validator('channel')
-    @classmethod
-    def validate_channel_for_band(cls, v: int, info) -> int:
-        ...
-    @field_validator('password')
-    @classmethod
-    def validate_password_length(cls, v: str | None, info) -> str | None:
-        ...
-    @field_validator('encryption')
-    @classmethod
-    def validate_password_required(cls, v: str, info) -> str:
-        ...
+    @field_validator("ssid")
+    @classmethod
+    def validate_ssid(cls, v: str) -> str:
+        if _CONTROL_CHARS.search(v):
+            raise ValueError("ssid must not contain control characters")
+        if not 1 <= len(v.encode("utf-8")) <= 32:
+            raise ValueError("ssid must be 1 to 32 bytes long in UTF-8")
+        return v
+
+    @model_validator(mode="after")
+    def validate_cross_fields(self) -> "NetworkCreateRequest":
+        # Cross-field rules live here: a field validator only sees the fields
+        # declared before it, so it cannot compare with a later one.
+        if not is_valid_channel_for_band(self.channel, self.band):
+            raise ValueError(f"Channel {self.channel} is not a valid WiFi channel for band {self.band}")
+        if self.encryption == "open":
+            return self
+        if self.password is None:
+            raise ValueError(f"Password required for {self.encryption} encryption")
+        if _CONTROL_CHARS.search(self.password):
+            raise ValueError("password must not contain control characters")
+        if not 8 <= len(self.password.encode("utf-8")) <= 63:
+            raise ValueError(f"{self.encryption} requires a password of 8 to 63 bytes")
+        return self
```

Difesa nel generatore: scrivere l'SSID in esadecimale con la chiave `ssid2`, che hostapd accetta, così
nessun carattere dell'SSID può essere interpretato; e rifiutare comunque i newline.

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
@@ def _generate_config(
+        for name, value in (("ssid", ssid), ("password", password or ""), ("country_code", country_code)):
+            if "\n" in value or "\r" in value:
+                raise HostapdError(f"Invalid {name}: line breaks are not allowed")
         config_lines = [
             f"# Wi-Lab hostapd config for {interface}",
             f"interface={interface}",
             "driver=nl80211",
-            f"ssid={ssid}",
+            f"ssid2={ssid.encode('utf-8').hex()}",
             f"channel={channel}",
         ]
```

Attenzione: i test esistenti che cercano `ssid=` nella configurazione generata vanno aggiornati.

---

<a id="wd-2"></a>
### 3. WD-2 - Un riavvio fallito del watchdog lascia la rete spenta in silenzio ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:95-150](wilab/wifi/watchdog.py#L95-L150)

**Problema.** Quando il watchdog trova hostapd morto chiama `_restore_ap`, che ferma tutto e riavvia la
rete con **un solo tentativo** (`allow_internal_retry=False`). Se l'avvio fallisce con un guasto che non
è "radio" e il cui cleanup è riuscito, il codice scrive un warning ed esce (righe 133-142). Da quel
momento:

- `manager.active` non contiene più il dispositivo, quindi a ogni giro successivo il ciclo prende il
  ramo `status is None` e non fa nulla;
- `runtime_state` viene cancellato nel `finally`;
- la reservation resta valida.

Il client che interroga `GET .../network` vede `active: false` senza spiegazione; chi non interroga non
lo saprà mai. Per via di HAP-3, il guasto transitorio di beacon (quello che "quasi sempre riesce al
tentativo successivo") prende esattamente questa strada. La richiesta di creazione ritenta tre volte;
il watchdog, che è il componente che deve tenere vive le reti, prova una volta sola.

**Come si riproduce.** Test con hostapd simulato:

1. creare una rete (hostapd finto che risulta `ENABLED`);
2. far risultare il processo terminato (`poll()` restituisce 1);
3. al riavvio far fallire `hostapd_manager.start` una volta con `HostapdInitFailure`;
4. eseguire due giri del watchdog.

Risultato attuale: la rete non è più in `manager.active`, `watchdog.state(reservation)` è `None`, e i
giri successivi non riprovano mai.

**Come correggerlo.** Il watchdog deve ricordare la rete che deve alla reservation e riprovare con un
ritardo crescente finché la reservation è valida. Schema da adattare (insieme a WD-1 e HAP-3):

```python
# wilab/wifi/watchdog.py
RESTORE_LIMIT = 3            # restarts allowed ...
RESTORE_WINDOW = 3600.0      # ... per hour (see WD-1)
RETRY_BACKOFF = (15.0, 30.0, 60.0, 120.0, 300.0)

@dataclass
class _Pending:
    """A network the watchdog still owes to its reservation."""
    reservation: Reservation
    request: NetworkCreateRequest
    failures: int = 0
    next_try: float = 0.0
```

Nel ciclo `_watch`, prima del ramo `status is None`:

```python
if pending is not None and (
    status is not None                              # the client created a network itself
    or reservation is not pending.reservation       # released, expired or quarantined
    or self._cancelled(pending.reservation)
):
    pending = None
    self.states.pop(device, None)
if status is None and pending is not None:
    if time.monotonic() >= pending.next_try:
        pending = self._retry_pending(reservations, pending)   # None on success
    continue
```

In `_restore_ap`:

- usare `allow_internal_retry=True`, così il riavvio ha gli stessi 3 tentativi della creazione;
- nel ramo `except StartupFailure` che oggi fa solo `return`, restituire un `_Pending` con
  `failures=1`, `next_try = time.monotonic() + RETRY_BACKOFF[0]` e impostare
  `self.states[device] = (reservation, "restore_failed")`;
- `_retry_pending` richiama `manager.start_network(...)`; se fallisce di nuovo aumenta `failures` e
  sposta `next_try` (ultimo valore di `RETRY_BACKOFF` come tetto); se il guasto è `cleanup_failed`
  passa alla quarantena come oggi.

Aggiungere `restore_failed` alla descrizione di `runtime_state` in [wilab/models.py](wilab/models.py)
e a `DELETE .../network` un richiamo `manager.watchdog.forget(device)` che azzera `pending`, così il
client può rinunciare alla rete senza rilasciare la reservation.

---

<a id="wd-1"></a>
### 4. WD-1 - Un solo riavvio dell'AP per tutta la vita della rete ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:44-86](wilab/wifi/watchdog.py#L44-L86), [wilab/wifi/watchdog.py:116-120](wilab/wifi/watchdog.py#L116-L120)

**Problema.** La variabile `attempted_ap` diventa `True` dopo il primo ripristino e torna `False` solo
quando cambia l'oggetto di stato, cioè quando il client cancella e ricrea la rete.
`_restore_ap(..., already_attempted=True)` mette subito in quarantena. Per una reservation illimitata:
hostapd può cadere una volta e venire ripristinato; quando cade di nuovo un mese dopo, l'adattatore va
in quarantena, la reservation viene invalidata e la porta USB viene resettata.

**Come si riproduce.** Test: creare una rete, simulare la morte di hostapd, lasciare che il watchdog la
ripristini con successo, simulare una seconda morte (anche dopo aver fatto avanzare un orologio finto di
24 ore). Risultato attuale: `reservations.recovery_snapshot()` contiene il dispositivo e
`reservations.get(id)` è `None`.

**Come correggerlo.** Sostituire il booleano con un budget a finestra temporale.

```diff
--- a/wilab/wifi/watchdog.py
+++ b/wilab/wifi/watchdog.py
@@ def _watch(self, reservations: ReservationManager, device: str) -> None:
         current = None
         misses = 0
-        attempted_ap = False
+        restores: deque[float] = deque()   # monotonic times of recent AP restores
         attempted_dhcp = False
@@
                 if status is not current:
                     self.states.pop(device, None)
                     current, misses = status, 0
-                    attempted_ap = attempted_dhcp = False
+                    attempted_dhcp = False
@@
                 if not alive or misses >= 3:
                     self.states[device] = (reservation, "restoring_ap")
+                    now = time.monotonic()
+                    while restores and now - restores[0] > RESTORE_WINDOW:
+                        restores.popleft()
                     try:
-                        self._restore_ap(reservations, reservation, status, attempted_ap)
+                        self._restore_ap(
+                            reservations, reservation, status, len(restores) >= RESTORE_LIMIT,
+                        )
                         current = self.manager.active.get(device)
-                        attempted_ap = True
+                        restores.append(now)
                         misses = 0
```

`restores` non va azzerato quando cambia l'oggetto di stato: il budget è dell'adattatore, non della
rete. Servono `import time` e `from collections import deque`. Valori proposti: 3 ripristini all'ora.

---

<a id="wd-4"></a>
### 5. WD-4 - La quarantena non ha uscita ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:174-188](wilab/wifi/manager.py#L174-L188), [wilab/reservation.py:127-140](wilab/reservation.py#L127-L140), [wilab/wifi/recovery.py:85-123](wilab/wifi/recovery.py#L85-L123)

**Problema.** `quarantine_radio` avvia il recovery solo per un guasto radio su un adattatore USB che
non è l'interfaccia upstream. In tutti gli altri casi chiama
`reservations.quarantine(..., recovering=False)`: il dispositivo viene bloccato e nessun codice lo
sblocca più. L'unico punto che toglie un dispositivo da `_blocked` è
`finish_recovery(recovered=True)`. Restano quindi bloccati per sempre:

- un adattatore integrato o PCI;
- qualunque `cleanup_failed`, anche transitorio (vedi NET-1);
- un guasto di cleanup del DHCP (`_isolate_dhcp_failure`);
- un adattatore USB dopo 10 reset falliti (circa 10 minuti).

La documentazione dice che un riavvio del servizio cancella la quarantena. Ma il riavvio spegne le
reti di tutti gli altri client.

**Come si riproduce.** Test: far fallire una volta `nat_manager.release_network` durante lo stop
(simula NET-1) mentre il watchdog ripristina una rete. Il dispositivo entra in `recovery_snapshot()`
con valore `False`. Far tornare tutto funzionante e far passare il tempo: il dispositivo non torna mai
disponibile e `POST /device-reservation` continua a rispondere `503 / 1003`.

**Come correggerlo.** Un ciclo che riprova periodicamente i dispositivi in stato "unavailable", più un
comando per l'operatore.

```python
# wilab/wifi/recovery.py
REPROBE_INTERVAL = 900.0     # seconds between attempts on an unavailable device

class RadioRecovery:
    def reprobe_unavailable(self, reservations: "ReservationManager") -> None:
        """Give every device that is quarantined and not recovering another chance."""
        for device, recovering in reservations.recovery_snapshot().items():
            if recovering or self._stopping.is_set():
                continue
            band, channel = self._last_radio.get(device, ("2.4ghz", 6))
            with self._manager.device_lock(device):
                try:
                    self._manager.release_device(device)      # finish any pending cleanup
                    _quiesce(device)
                    _require_idle(device)
                    self._manager.probe_recovered_radio(device, band, channel)
                except (CommandError, OSError, ValueError, RuntimeError) as exc:
                    logger.info("Device %s still unavailable: %s", device, exc)
                    continue
            reservations.finish_recovery(device, recovered=True)
            logger.warning("Device %s passed the probe and is allocatable again", device)
```

- `_last_radio: dict[str, tuple[str, int]]` va riempito in `schedule()` e in
  `NetworkManager.quarantine_radio` (banda e canale dell'ultima rete).
- Chiamare `reprobe_unavailable` dal ciclo di discovery ogni `REPROBE_INTERVAL` secondi
  ([wilab/api/dependencies.py](wilab/api/dependencies.py), `discovery_loop`).
- Il dispositivo non deve avere reservation: la quarantena la rimuove già.
- Endpoint per l'operatore (non breaking, vedi N9): `POST /api/v1/maintenance/devices/{interface}/recover`,
  protetto da `require_protected_password`, che esegue lo stesso probe per un solo dispositivo.

---

<a id="net-1"></a>
### 6. NET-1 - `iptables` senza `-w` ✅

**Gravità:** Alta · **Confidenza:** Probabile (dipende dal backend) · **File:** [wilab/network/commands.py:209-211](wilab/network/commands.py#L209-L211), [wilab/network/nat.py](wilab/network/nat.py), [wilab/network/captive.py:43-46](wilab/network/captive.py#L43-L46), [wilab/network/safety.py](wilab/network/safety.py)

**Problema.** Nessuna chiamata passa `-w`. Con il backend legacy ogni invocazione di `iptables`,
comprese `-S` e `-C`, prende un lock globale e fallisce subito se un altro processo lo tiene ("Another
app is currently holding the xtables lock"). Wi-Lab serializza le proprie scritture con
`_firewall_lock`, ma:

- `/status` e `/debug` eseguono `iptables -S` due volte per chiamata **senza** quel lock
  (`NatManager.status`), e il frontend interroga `/status` di continuo;
- Docker, `ufw`, `fail2ban` e strumenti simili usano lo stesso lock.

Ogni chiamata tiene il lock per pochi millisecondi, quindi una singola collisione è improbabile; in
mesi di polling è questione di tempo. Una collisione durante un avvio dà un `500` generico o una rete
senza NAT che dichiara successo (NET-2). Una collisione durante uno stop fa fallire il cleanup, e un
cleanup fallito è `503` nel caso migliore e quarantena permanente nel peggiore (WD-4). Con il backend
nftables il lock non esiste e il problema quasi scompare.

**Come si riproduce.** Sulla macchina di laboratorio, prima controllare il backend:

```bash
iptables --version        # "(legacy)" oppure "(nf_tables)"
```

Con il backend legacy, in due terminali:

```bash
while true; do iptables -S FORWARD >/dev/null; done                 # terminale 1
for i in $(seq 1 2000); do iptables -C FORWARD -j ACCEPT 2>&1 | grep -c "xtables lock"; done | sort | uniq -c   # terminale 2
```

Ogni riga diversa da `0` è una collisione che in Wi-Lab sarebbe un errore.

**Come correggerlo.** Aggiungere `-w` in un punto solo e far passare da lì tutte le chiamate.

```diff
--- a/wilab/network/commands.py
+++ b/wilab/network/commands.py
@@
+# Seconds iptables waits for the xtables lock instead of failing at once.
+IPTABLES_LOCK_WAIT = "5"
+
+
 def execute_iptables(args: list[str]) -> str:
     """Execute iptables command."""
-    return execute_command(["iptables", *args])
+    return execute_command(["iptables", "-w", IPTABLES_LOCK_WAIT, *args])
```

Poi sostituire ogni `execute_command(["iptables", ...])` con `execute_iptables([...])`:

| File | Punti |
|---|---|
| `wilab/network/nat.py` | `remove_stale_rules` (lista della catena), `_rule_exists`, lettura della policy in `enable_nat`, `_remove_nat_rules`, i due comandi di `status` |
| `wilab/network/captive.py` | `_iptables_listing` |
| `wilab/network/safety.py` | `list_wilab_rules` (due comandi) |

Infine leggere lo stato sotto il lock del firewall, aggiungendo un metodo a `NetworkManager` e usandolo
in [wilab/api/routes/status.py](wilab/api/routes/status.py) al posto di `manager.nat_manager.status()`:

```python
def firewall_status(self) -> dict:
    """Read the firewall state without colliding with a rule change."""
    with self._firewall_lock:
        return self.nat_manager.status()
```

I test che confrontano liste di argomenti di `iptables` vanno aggiornati. Aggiungere un test che
registra tutti i comandi di un ciclo start/stop e verifica che ognuno inizi con `["iptables", "-w"]`.

---

<a id="hap-1"></a>
### 7. HAP-1 - Gli SSID che hostapd restituisce con escape non diventano mai "pronti" ✅

**Gravità:** Alta · **Confidenza:** Probabile · **File:** [wilab/wifi/hostapd.py:318-324](wilab/wifi/hostapd.py#L318-L324), [wilab/wifi/hostapd.py:412-417](wilab/wifi/hostapd.py#L412-L417)

**Problema.** La readiness confronta il campo `ssid[0]` di `hostapd_cli status` con l'SSID richiesto.
hostapd stampa quel campo con il suo codificatore di testo: virgolette, backslash, caratteri di
controllo e ogni byte fuori dall'ASCII stampabile sono scritti come sequenze di escape (`\"`, `\\`,
`\xNN`). "Caffè", un'emoji o `my"net` non risultano mai uguali. Conseguenza: l'AP è davvero acceso,
Wi-Lab aspetta 10 s, dichiara `HostapdRadioFailure`, ritenta, risponde `409 / 1001`, e alla terza
richiesta mette in quarantena l'adattatore e resetta la porta USB. Una richiesta valida toglie dal
pool un adattatore sano. Lo stesso confronto è in `is_enabled`, usato dal watchdog.

**Come si riproduce.** Test senza hardware: far restituire a `execute_command` finto, per il comando
`hostapd_cli ... status`, il testo

```
state=ENABLED
bss[0]=wlan0
ssid[0]=Caff\xc3\xa8
```

e chiamare `_wait_until_ready(process, "wlan0", "Caffè", control_dir, 2.0)`. Oggi solleva
`HostapdRadioFailure` allo scadere del timeout. Su hardware: creare una rete con SSID `Caffè`.

**Come correggerlo.** La cartella di controllo è privata per istanza (`mkdtemp`), quindi il confronto
dell'SSID non aggiunge sicurezza. Basta stato e interfaccia.

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
@@ def _wait_until_ready(
-        self, process: ForegroundProcess, interface: str, ssid: str,
-        control_dir: str, timeout: float,
+        self, process: ForegroundProcess, interface: str, control_dir: str, timeout: float,
     ) -> None:
@@
                 if (
                     time.monotonic() < deadline
                     and state == "ENABLED"
                     and fields.get("bss[0]") == interface
-                    and fields.get("ssid[0]") == ssid
                 ):
                     return
@@ def start(
-            self._wait_until_ready(process, interface, ssid, control_dir, timeout)
+            self._wait_until_ready(process, interface, control_dir, timeout)
@@ def is_enabled(self, net_id: str) -> bool:
-        return (
-            fields.get("state") == "ENABLED"
-            and fields.get("bss[0]") == interface
-            and fields.get("ssid[0]") == instance["ssid"]
-        )
+        # The control socket is private to this instance, so state and
+        # interface are enough; hostapd escapes the SSID in this output.
+        return fields.get("state") == "ENABLED" and fields.get("bss[0]") == interface
```

Aggiornare `docs/architecture.md` (sezione 5.2), che descrive il confronto dell'SSID.

---

<a id="stab-1"></a>
### 8. STAB-1 - Un comando bloccato nel kernel congela il servizio senza ucciderlo ✅

**Gravità:** Alta · **Confidenza:** meccanismo Confermato, innesco Ipotesi · **File:** [wilab/network/commands.py:160-206](wilab/network/commands.py#L160-L206), [install/systemd/wi-lab.service.template](install/systemd/wi-lab.service.template)

**Problema.** `execute_command` usa `subprocess.run(..., timeout=...)`. Quando il timeout scade,
CPython uccide il figlio e poi chiama `wait()` **senza timeout**. Un processo fermo in una chiamata di
kernel non interrompibile non muore con `SIGKILL`. È ciò che fanno `ip` e `iw` quando un driver Wi-Fi
USB si blocca tenendo il lock di rete del kernel, e il caso osservato
`RTNETLINK answers: Connection timed out` appartiene a quella famiglia. Conseguenze:

- il thread non ritorna mai e non rilascia il lock del dispositivo;
- il lock di rete del kernel è globale, quindi si bloccano anche i comandi degli altri adattatori;
- le richieste API si accumulano sui lock fino a esaurire i 40 thread, poi l'API smette di rispondere;
- il processo è vivo, quindi `Restart=always` non fa nulla, e non c'è `WatchdogSec`.

Wi-Lab non può riparare il kernel, ma deve accorgersene.

**Come si riproduce.** Test senza hardware: sostituire `subprocess.Popen` con un oggetto finto il cui
`communicate()` solleva sempre `TimeoutExpired` e il cui `wait()` non ritorna (usare un `Event`). Oggi
`execute_command` non ritorna mai. Dopo la correzione deve sollevare `CommandStuck` entro il tempo di
grazia.

**Come correggerlo.** Tre parti.

1. Runner che non aspetta mai all'infinito:

```python
# wilab/network/commands.py
KILL_GRACE = 2.0

class CommandStuck(CommandTimeout):
    """The child did not exit even after SIGKILL: it is stuck in the kernel."""

_stuck_children: list[subprocess.Popen[str]] = []     # kept referenced, reported by the health check

def stuck_commands() -> int:
    """Number of children that never exited; drops the ones that finally did."""
    _stuck_children[:] = [p for p in _stuck_children if p.poll() is None]
    return len(_stuck_children)

def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    process = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            _stuck_children.append(process)
            logger.critical("Command %s (pid %d) did not exit after SIGKILL", cmd[0], process.pid)
            raise CommandStuck(f"Command stuck in the kernel: {' '.join(cmd)}") from None
        raise CommandTimeout(f"Command timed out: {' '.join(cmd)}") from None
    return process.returncode, stdout, stderr
```

   `execute_command` chiama `_run` al posto di `subprocess.run` e mantiene il resto della logica.
   `errors="replace"` evita anche un `UnicodeDecodeError` su output non UTF-8.

2. Battito per systemd, senza dipendenze nuove:

```python
# wilab/heartbeat.py
import os
import socket

def sd_notify(state: str) -> None:
    """Send a state line to systemd; does nothing when not started by systemd."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(address)
        sock.sendall(state.encode())
```

   Ogni ciclo (scadenze, discovery, un watchdog per dispositivo) aggiorna un timestamp monotono a ogni
   giro. Un thread dedicato invia `WATCHDOG=1` ogni 20 s **solo se** tutti i timestamp sono recenti
   (per esempio meno di 180 s, per tollerare un avvio DFS) e `stuck_commands() == 0`. In `lifespan`,
   dopo l'avvio, inviare `READY=1`.

3. Unit systemd:

```diff
--- a/install/systemd/wi-lab.service.template
+++ b/install/systemd/wi-lab.service.template
@@
 [Service]
-Type=simple
+Type=notify
+NotifyAccess=main
+WatchdogSec=90s
```

Se un comando resta bloccato nel kernel, il riavvio del servizio da solo non ripara l'adattatore, ma
rende il guasto visibile.

---

<a id="net-2"></a>
### 9. NET-2 - La creazione dichiara successo anche senza NAT o isolamento ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:365-419](wilab/wifi/manager.py#L365-L419)

**Problema.** Dopo che l'AP è attivo, TX power, NAT e isolamento sono "best effort": gli errori vengono
scritti nel log e la richiesta risponde `200`. Se il NAT fallisce (nessuna route di default, collisione
NET-1, upstream giù) lo stato dice comunque `internet_enabled: true`. Il client crede di avere Internet.
Contraddice la regola del progetto "meglio un errore chiaro di un comportamento ambiguo".

**Come si riproduce.** Test: far sollevare `RuntimeError` a `nat_manager.enable_nat` e creare una rete
con `internet_enabled: true`. Oggi la risposta è `200` e `GET .../network` riporta
`internet_enabled: true`.

**Come correggerlo.** Portare NAT e isolamento dentro il blocco protetto dal rollback, come fasi
dell'avvio. Il TX power resta "best effort" perché il progetto lo dichiara non garantito.

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
@@ def _start_network(
                         # Tracked before start so a rollback removes partial rules.
                         self.captive_portals[device_id] = portal
                         portal.start()
+                    if internet_enabled:
+                        stage = "enable Internet"
+                        try:
+                            with self._firewall_lock:
+                                self.nat_manager.enable_nat(cfg_net.interface, device_id, subnet)
+                        except RuntimeError as exc:
+                            raise CommandError(str(exc)) from exc
+                    stage = "isolate network"
+                    with self._firewall_lock:
+                        self.isolation_manager.add_network(subnet)
                     if retrying and (
@@
-        # Enable NAT if internet access is enabled
-        if internet_enabled:
-            try:
-                ...
-        # Apply isolation rules to prevent inter-network traffic
-        try:
-            ...
-        logger.info(f"Isolation disabled for testing (network {device_id})")
```

Due adattamenti necessari:

- `IsolationManager._block_traffic` oggi inghiotte `CommandError`: deve rilanciarla, altrimenti la fase
  non può fallire.
- Nel rollback la subnet non è ancora in `self.active`, quindi `_stop_network` non rimuoverebbe le
  regole di isolamento. Usare la subnet assegnata:

```diff
@@ def _stop_network(self, device_id: str) -> None:
-        subnet = self.active[device_id].subnet if device_id in self.active else None
+        assigned = self._assigned_subnets.get(device_id)
+        subnet = self.active[device_id].subnet if device_id in self.active else (
+            str(assigned) if assigned is not None else None
+        )
```

  e in `IsolationManager.remove_network` non considerare un avviso il caso "subnet non presente".

Il guasto diventa un `500` con messaggio "Failed to enable Internet: ..." e la rete viene smontata.

---

<a id="hap-3"></a>
### 10. HAP-3 - `HostapdInitFailure` è un guasto radio solo durante un retry ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:74-78](wilab/wifi/hostapd.py#L74-L78), [wilab/wifi/manager.py:326-359](wilab/wifi/manager.py#L326-L359)

**Problema.** `StartupFailure.radio` è calcolato come
`isinstance(e, HostapdRadioFailure) or (retrying and stage == "start AP")`.
`HostapdInitFailure` non è una sottoclasse di `HostapdRadioFailure`, quindi lo stesso guasto di beacon
cambia natura secondo il numero del tentativo:

- prima richiesta, retry esauriti: l'ultimo tentativo ha `retrying=True`, il guasto è "radio", il
  client riceve `409 / 1001`. Corretto.
- seconda o terza richiesta (`allow_internal_retry=False`, un solo tentativo, `retrying=False`): lo
  stesso guasto è "non radio". Il client riceve un `500` generico, che la documentazione descrive come
  "non riprovare automaticamente".
- riavvio dal watchdog (un solo tentativo): come sopra, vedi WD-2.

**Come si riproduce.** Test: far fallire `hostapd_manager.start` sempre con `HostapdInitFailure`.
Prima `POST .../network`: `409 / 1001`. Attendere il `Retry-After` e ripetere: la risposta è `500` con
codice `500`, non `409 / 1001`.

**Come correggerlo.** La classificazione deve essere una proprietà dell'eccezione, non del tentativo.

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
-class HostapdInitFailure(HostapdError):
+class HostapdInitFailure(HostapdRadioFailure):
     """hostapd exited after the driver rejected the beacon during interface setup.
```

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
@@ def _start_network(
+        radio_seen = False     # a classified radio failure happened in this request
         for attempt in range(1, STARTUP_ATTEMPTS + 1):
@@
             except (HostapdError, CommandError, DhcpServerError, CaptivePortalError) as e:
                 logger.error("Failed to %s for %s: %s", stage, device_id, e)
+                radio_seen = radio_seen or isinstance(e, HostapdRadioFailure)
+                # A later attempt that fails while starting the AP keeps the
+                # classification of the failure that caused the retry.
+                radio = isinstance(e, HostapdRadioFailure) or (radio_seen and stage == "start AP")
                 try:
                     self.release_device(device_id)
                 except RuntimeError:
                     logger.exception("Startup rollback failed for %s", device_id)
                     raise StartupFailure(
-                        f"Failed to {stage}: {e}",
-                        radio=isinstance(e, HostapdRadioFailure) or (retrying and stage == "start AP"),
-                        cleanup_failed=True,
+                        f"Failed to {stage}: {e}", radio=radio, cleanup_failed=True,
                     ) from e

                 if (
                     attempt < STARTUP_ATTEMPTS
                     and allow_internal_retry
                     and stage == "start AP"
-                    and isinstance(e, (HostapdRadioFailure, HostapdInitFailure))
+                    and isinstance(e, HostapdRadioFailure)
@@
-                raise StartupFailure(
-                    f"Failed to {stage}: {e}",
-                    radio=isinstance(e, HostapdRadioFailure) or (retrying and stage == "start AP"),
-                ) from e
+                raise StartupFailure(f"Failed to {stage}: {e}", radio=radio) from e
```

Conseguenza da accettare consapevolmente: un guasto di beacon ripetuto tre volte porta alla quarantena
anziché a un `500`. Con WD-4 corretto la quarantena è temporanea, quindi è il comportamento giusto.
Aggiornare `docs/architecture.md` (sezioni 5.2 e 6), che oggi definiscono questo guasto "unclassified".

---

<a id="hap-2"></a>
### 11. HAP-2 - Lo stesso guasto è classificato in due modi secondo la tempistica ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:258-267](wilab/wifi/hostapd.py#L258-L267), [wilab/wifi/hostapd.py:325-329](wilab/wifi/hostapd.py#L325-L329)

**Problema.** Quando hostapd non riesce a impostare il beacon passa allo stato `DISABLED` e poi esce.
Se il probe vede prima `DISABLED`, il ciclo si interrompe e solleva `HostapdRadioFailure`. Se vede
prima l'uscita, `_check_process` solleva `HostapdInitFailure`. Nella richiesta di creazione la
differenza è nascosta perché entrambe vengono ritentate. Altrove è grande: la prima conta come guasto
radio (cooldown, quarantena, reset USB), la seconda no (HAP-3). Pochi millisecondi decidono tra "metti
in quarantena l'adattatore" e "riporta un errore generico".

**Come si riproduce.** Due test con hostapd finto che emette gli eventi `beacon_failed` e
`interface_init_failed`: nel primo `hostapd_cli` restituisce `state=DISABLED` mentre `poll()` è ancora
`None`; nel secondo `poll()` restituisce 1 al primo controllo. Oggi i due test ottengono due eccezioni
di tipo diverso.

**Come correggerlo.** La correzione di HAP-3 rende equivalenti le due classi per chi le riceve. Per
avere anche un messaggio coerente, dopo aver visto `DISABLED` dare a hostapd un attimo per uscire e poi
classificare dagli eventi:

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
@@ def _wait_until_ready(
                 if state == "DISABLED":
                     break
                 time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
+            if state == "DISABLED":
+                # hostapd exits right after reporting DISABLED: wait briefly so
+                # the failure is classified from its exit and its output.
+                settle = time.monotonic() + 0.5
+                while process.poll() is None and time.monotonic() < settle:
+                    time.sleep(0.05)
             check_process()
+            if _TRANSIENT_INIT_EVENTS <= set(process.output_events()):
+                raise HostapdInitFailure(f"hostapd disabled the AP on {interface}: beacon setup failed")
             raise HostapdRadioFailure(f"AP not ready on {interface} (hostapd state: {last_state})")
```

---

<a id="wd-3"></a>
### 12. WD-3 - Un solo riavvio del DHCP, poi `dhcp_failed` per sempre ✅

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:75-82](wilab/wifi/watchdog.py#L75-L82), [wilab/wifi/watchdog.py:152-181](wilab/wifi/watchdog.py#L152-L181)

**Problema.** Stesso schema di WD-1 con `attempted_dhcp`. Dopo la seconda morte di dnsmasq, o dopo un
solo riavvio fallito, l'AP continua a trasmettere e nessun client riceve un indirizzo. Lo stato viene
riportato (`dhcp_failed`), ma niente riprova. Una rete senza DHCP non è una rete funzionante.

**Come si riproduce.** Test: rete attiva, far risultare dnsmasq morto (`is_running` falso), lasciare
che il watchdog lo riavvii, farlo morire di nuovo. Risultato attuale: lo stato resta `dhcp_failed` a
ogni giro successivo e `dhcp_server.start` non viene più chiamato.

**Come correggerlo.** Budget a finestra anche per il DHCP e, se il riavvio del solo DHCP non basta,
riavvio dell'intera rete (che passa dal budget di WD-1).

```diff
--- a/wilab/wifi/watchdog.py
+++ b/wilab/wifi/watchdog.py
@@ def _watch(self, reservations: ReservationManager, device: str) -> None:
-        attempted_dhcp = False
+        dhcp_restores: deque[float] = deque()
@@
                 elif misses == 0 and not self.manager.dhcp_server.is_running(device):
-                    if not attempted_dhcp:
-                        attempted_dhcp = True
-                        self._restore_dhcp(reservations, reservation, status)
-                    else:
-                        self.states[device] = (reservation, "dhcp_failed")
+                    now = time.monotonic()
+                    while dhcp_restores and now - dhcp_restores[0] > RESTORE_WINDOW:
+                        dhcp_restores.popleft()
+                    dhcp_restores.append(now)
+                    if len(dhcp_restores) <= RESTORE_LIMIT:
+                        self._restore_dhcp(reservations, reservation, status)
+                    if self.state(reservation) == "dhcp_failed" or len(dhcp_restores) > RESTORE_LIMIT:
+                        # DHCP alone cannot be repaired: restart the whole network.
+                        misses = 3
```

Con `misses = 3` il giro successivo entra nel ramo di ripristino dell'AP. Lo stato `dhcp_failed` resta
visibile solo per i pochi secondi tra un giro e l'altro.

---

<a id="wd-5"></a>
### 13. WD-5 - Un adattatore che sparisce non si può ripulire né rimuovere ✅ parz.

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:378-389](wilab/wifi/hostapd.py#L378-L389), [wilab/wifi/manager.py:449-465](wilab/wifi/manager.py#L449-L465), [wilab/config.py:172-182](wilab/config.py#L172-L182)

**Problema.** `HostapdManager.stop` termina con `ip link set <if> down`, `iw ... set type managed`,
`ip addr flush` e considera ogni errore come "stop fallito". Se l'interfaccia non esiste più
(adattatore scollegato, nuova enumerazione USB con un altro nome, driver scaricato) quei comandi
falliscono ogni volta:

- l'istanza resta in `_instances`, quindi `release_device` fallisce per sempre;
- le regole NAT e di blocco non vengono rimosse, perché quel passo gira solo `if hostapd_stopped`;
- il dispositivo resta in `manager.active`, quindi `/status` conta una rete che non esiste;
- il dispositivo non viene mai tolto da `config.networks` (la discovery aggiunge soltanto).

Se l'adattatore torna con lo **stesso** nome mentre il recovery USB sta ancora provando (10 tentativi,
uno al minuto) il cleanup infine riesce. Dopo quei dieci minuti no (WD-4). Se torna con un altro nome,
la discovery lo aggiunge come dispositivo nuovo e la voce vecchia resta `unavailable`, tenendo lo stato
generale `degraded` fino a un riavvio.

**Come si riproduce.** Su hardware: rete attiva, scollegare l'adattatore USB, aspettare 15 minuti,
ricollegarlo. Nei test: far fallire `execute_command` per ogni comando che nomina l'interfaccia con
"Cannot find device" e chiamare `release_device`: solleva `RuntimeError` a ogni chiamata.

**Come correggerlo.** Tre cambiamenti.

1. Un'interfaccia assente non ha nulla da resettare:

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
+def interface_present(interface: str) -> bool:
+    """True while the kernel still has a network device with this name."""
+    return os.path.exists(f"/sys/class/net/{interface}")
+
@@ def stop(self, net_id: str) -> None:
-            # Leave the interface down until the next network starts.
-            execute_command(["ip", "link", "set", interface, "down"])
-            execute_command(["iw", "dev", interface, "set", "type", "managed"])
-            execute_command(["ip", "addr", "flush", "dev", interface])
-            logger.info(f"Reset interface {interface} to managed mode, down")
+            if interface_present(interface):
+                # Leave the interface down until the next network starts.
+                execute_command(["ip", "link", "set", interface, "down"])
+                execute_command(["iw", "dev", interface, "set", "type", "managed"])
+                execute_command(["ip", "addr", "flush", "dev", interface])
+                logger.info(f"Reset interface {interface} to managed mode, down")
+            else:
+                logger.warning("Interface %s is gone; nothing to reset", interface)
```

   Nei test (che non hanno `/sys`) `interface_present` va sostituita con una funzione che restituisce
   `True`, in `tests/conftest.py`.

2. Lo stesso controllo in `QosManager._teardown` e negli altri punti di `_stop_network` che eseguono
   comandi sull'interfaccia, così nessuno di essi blocca il cleanup.

3. Ritiro dei dispositivi: nella discovery, un dispositivo la cui interfaccia manca da più di N
   scansioni (per esempio 4, cioè due minuti), senza reservation e senza risorse tracciate, viene tolto
   da `config.networks`, da `ReservationManager` (nuovo metodo `remove_device`) e da `_blocked`. Se
   ricompare, viene riaggiunto come nuovo. Questo richiede il registro unico di ARCH-4, oppure quattro
   rimozioni coordinate sotto `_scan_lock`.

---

<a id="wd-7"></a>
### 14. WD-7 - Il watchdog controlla due processi, non la rete ✅ parz.

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:64-82](wilab/wifi/watchdog.py#L64-L82)

**Problema.** Il watchdog verifica che hostapd sia vivo e `ENABLED` e che dnsmasq sia vivo. Non
verifica:

- che l'interfaccia abbia ancora l'indirizzo del gateway (un gestore di rete dell'host o un
  amministratore possono toglierlo; il DHCP allora non risponde più);
- che le regole firewall di Wi-Lab esistano ancora (un riavvio di `firewalld`, `ufw` o Docker può
  riscrivere le catene: spariscono NAT, blocco di Internet e redirect del captive portal);
- che `net.ipv4.ip_forward` sia ancora 1;
- che la radio stia davvero trasmettendo (la proposta aperta `TODOs/ap-health-validation.md` descrive
  un adattatore che dichiara ENABLED e non manda beacon);
- che il thread del captive portal sia vivo.

**Come si riproduce.** Con una rete attiva e client collegati, sulla macchina di laboratorio:

```bash
ip addr flush dev <interfaccia>          # i nuovi client non ricevono più un indirizzo
iptables -t nat -F POSTROUTING           # Internet sparisce (solo su macchina di test!)
```

`/status` e `GET .../network` continuano a dire che tutto funziona e nulla viene riparato.

**Come correggerlo.** Un metodo di verifica che ripara sul posto ciò che si può riparare senza toccare
l'AP.

```python
# wilab/wifi/manager.py
def verify_network(self, device_id: str) -> list[str]:
    """Check what a running network needs and repair in place. Returns what was repaired."""
    status = self.active.get(device_id)
    if status is None or status.subnet is None:
        return []
    repaired: list[str] = []
    net = IPv4Network(status.subnet)
    gateway = f"{net[1]}/{net.prefixlen}"
    addresses = json.loads(execute_ip(["-j", "-4", "addr", "show", "dev", status.interface]))
    present = {
        f"{a['local']}/{a['prefixlen']}" for link in addresses for a in link.get("addr_info", [])
    }
    if gateway not in present:
        execute_ip(["addr", "add", gateway, "dev", status.interface])
        repaired.append("gateway address")
    if status.internet_enabled:
        with self._firewall_lock:
            # enable_nat checks each rule before adding it, so it only restores what is missing.
            self.nat_manager.enable_nat(status.interface, device_id, status.subnet)
    return repaired
```

Chiamarlo dal ciclo del watchdog una volta su sei (ogni 30 s), sotto il lock del dispositivo, e
scrivere un `WARNING` per ogni riparazione. Se `gateway address` è stato riparato, riavviare anche
dnsmasq. Per la trasmissione reale: leggere `/sys/class/net/<if>/statistics/tx_packets` a ogni giro;
se con l'AP `ENABLED` il contatore non cresce per 30 s (un AP manda circa 10 beacon al secondo),
contare un "miss" come per `is_enabled`. Verificare prima su hardware che il driver in uso conti i
beacon in quel contatore.

---

<a id="wd-9"></a>
### 15. WD-9 - I thread di background non sono supervisionati ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:83-86](wilab/wifi/watchdog.py#L83-L86), [wilab/api/dependencies.py:102-110](wilab/api/dependencies.py#L102-L110), [wilab/wifi/manager.py:939-950](wilab/wifi/manager.py#L939-L950), [wilab/config.py:189-204](wilab/config.py#L189-L204)

**Problema.** Il ciclo del watchdog cattura `OSError`, `RuntimeError` e `ValueError`; quello di
discovery solo `ValueError`; quello delle scadenze cattura tutto ma scrive a livello `DEBUG`,
invisibile con il livello `INFO` configurato. Qualunque altra eccezione termina il thread, e `_watched`
impedisce di crearne uno nuovo per quel dispositivo.

Un modo concreto di uccidere la discovery: mentre il servizio gira, salvare un `config.yaml` il cui
livello principale non è una mappa (per esempio una lista), oppure con `networks: 5`.
`_read_raw_config` solleva `AttributeError` o `TypeError`, che nessuno cattura. Da quel momento gli
adattatori collegati a caldo non vengono più aggiunti, senza alcun messaggio oltre al traceback del
thread.

**Come si riproduce.** Test: chiamare `discovery_loop` con un `scan_devices` che solleva `TypeError`
al primo giro e funziona al secondo; oggi il ciclo termina al primo. Oppure scrivere `- a\n- b\n` nel
file di configurazione e chiamare `scan_new_networks`.

**Come correggerlo.**

```diff
--- a/wilab/config.py
+++ b/wilab/config.py
@@ def _read_raw_config(cfg_path: str, *, quiet: bool = False) -> dict:
     with open(cfg_path, 'r', encoding='utf-8') as f:
         raw = yaml.safe_load(f) or {}
+    if not isinstance(raw, dict):
+        raise ValueError("Configuration must be a YAML mapping")
     if raw.get('networks') is None:
         raw['networks'] = []
+    if not isinstance(raw['networks'], list):
+        raise ValueError("networks must be a list")
```

In `load_config` aggiungere `except ValueError as e: raise SystemExit(f"Configuration error: {e}")`
(dopo il ramo `ValidationError`, che è una sottoclasse).

```diff
--- a/wilab/api/dependencies.py
+++ b/wilab/api/dependencies.py
@@ def discovery_loop(config: AppConfig, stop: threading.Event) -> None:
         try:
             scan_devices(config, quiet=not first)
-        except ValueError as exc:
+        except Exception as exc:   # this loop must survive anything
             if str(exc) != last_error:
-                logger.error("Device discovery failed: %s", exc)
+                logger.exception("Device discovery failed: %s", exc)
             last_error = str(exc)
```

```diff
--- a/wilab/wifi/watchdog.py
+++ b/wilab/wifi/watchdog.py
-            except (OSError, RuntimeError, ValueError):
+            except Exception:   # this loop must survive anything
                 logger.exception("Could not check or restore network on %s", device)
```

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
@@ def _expiry_loop(self) -> None:
-            except Exception as e:
-                logger.debug(f"[expiry-loop] Loop error: {e}")
+            except Exception:
+                logger.exception("[expiry-loop] Unexpected error")
```

Per non ripetere lo stesso traceback a ogni giro, tenere l'ultimo messaggio e riscriverlo solo se
cambia (come fa già la discovery). Esporre in `/status` se i thread sono vivi, usando i timestamp di
battito descritti in STAB-1.

---

<a id="stab-4"></a>
### 16. STAB-4 - L'avvio pulisce solo le regole firewall ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/__init__.py:96-106](wilab/api/__init__.py#L96-L106), [wilab/network/qos.py:122-127](wilab/network/qos.py#L122-L127), [wilab/network/dhcp.py:167-168](wilab/network/dhcp.py#L167-L168)

**Problema.** Dopo un arresto non pulito, l'avvio successivo rimuove le regole `iptables` e le catene
del captive portal. Non ripristina:

- le discipline di coda `tc` sulle radio. Una regola netem con il 30% di perdita dell'esecuzione
  precedente resta sull'interfaccia e degrada la rete successiva, mentre lo stato QoS dice "inattivo":
  `clear_qos` esce subito perché non ha stato per quell'interfaccia;
- i dispositivi `ifbN` rimasti;
- gli indirizzi rimasti sulle radio, che fanno saltare all'allocatore la subnet naturale (NET-9);
- i file vecchi, compreso un file PID di dnsmasq che fa fallire ogni avvio successivo su quel
  dispositivo con "Existing dnsmasq PID file";
- processi hostapd o dnsmasq orfani quando il servizio non è gestito da systemd.

**Come si riproduce.** Su macchina di test: creare una rete con un profilo QoS degradato, poi
`kill -9` del processo Python e `kill -9` di dnsmasq. Dopo il riavvio: `tc qdisc show dev <if>` mostra
ancora netem; una nuova rete sullo stesso adattatore fallisce con "Existing dnsmasq PID file".

**Come correggerlo.** Una funzione di reset completo dell'interfaccia e una pulizia della cartella di
runtime.

```python
# wilab/wifi/interface.py
def reset_interface(interface: str) -> None:
    """Bring a radio back to a known idle state: down, managed, no address, no shaping."""
    execute_command(["ip", "link", "set", interface, "down"])
    execute_iw(["dev", interface, "set", "type", "managed"])
    execute_command(["ip", "addr", "flush", "dev", interface])
    # Shaping left by a previous run would silently degrade the next network.
    execute_command(["tc", "qdisc", "del", "dev", interface, "root"], check=False)
    execute_command(["tc", "qdisc", "del", "dev", interface, "ingress"], check=False)
```

- Chiamarla in `scan_devices` per ogni dispositivo aggiunto e in `HostapdManager.start` al posto dei
  tre comandi di preparazione (mantenendo la conversione di `CommandTimeout` in `HostapdRadioFailure`).
- In `lifespan`, prima della discovery: svuotare le cartelle di runtime (`shutil.rmtree` e ricreazione)
  dopo aver terminato i processi i cui argomenti contengono quei percorsi; cancellare i dispositivi
  `ifb` creati da Wi-Lab. Per riconoscerli conviene dare loro un nome proprio (`wilab-ifb0`) invece di
  `ifb0`, che può appartenere ad altri.
- Con STAB-2 (cartella sotto `/run/wilab`) la pulizia dei file dopo un riavvio dell'host è automatica.

---

<a id="sec-3"></a>
### 17. SEC-3 - L'API ascolta anche sulle reti di test ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [main.py:38](main.py#L38)

**Problema.** uvicorn è avviato con `host="0.0.0.0"`. Ogni client Wi-Fi di ogni AP raggiunge l'API
sull'indirizzo del gateway, e attraverso SEC-1 anche il token. Nessuna regola firewall protegge l'host
stesso (catena `INPUT`) dalle subnet degli AP: le regole di Wi-Lab riguardano solo `FORWARD` e `nat`.

**Come si riproduce.** Da un dispositivo collegato a una rete creata da Wi-Lab:
`curl http://<gateway>:8080/docs` restituisce Swagger.

**Come correggerlo.** Due opzioni compatibili tra loro.

1. Indirizzo di ascolto configurabile:

```diff
--- a/wilab/config.py
+++ b/wilab/config.py
     api_port: int = 8080
+    api_bind_address: str = "0.0.0.0"   # set the management address to hide the API from AP clients
```

```diff
--- a/main.py
+++ b/main.py
-    uvicorn.run(app, host="0.0.0.0", port=config.api_port, server_header=False, headers=[("x-app-version", __version__)])
+    uvicorn.run(
+        app, host=config.api_bind_address, port=config.api_port, server_header=False,
+        headers=[("x-app-version", __version__)],
+    )
```

2. Regola per rete, che funziona anche con `0.0.0.0`: all'avvio di ogni rete inserire
   `iptables -w 5 -I INPUT 1 -i <wifi> -p tcp --dport <api_port> -j REJECT --reject-with tcp-reset -m comment --comment wilab-api-<id>`,
   rimuoverla allo stop, e aggiungere la catena `INPUT` e il prefisso `wilab-api-` a
   `NatManager.remove_stale_rules`. Il captive portal (porta 80) e il DHCP restano raggiungibili.

Documentare la nuova chiave in `config.example.yaml`.

---

<a id="sec-2"></a>
### 18. SEC-2 - `/debug` consegna a tutti gli ID di reservation

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/routes/status.py:284-294](wilab/api/routes/status.py#L284-L294), [wilab/reservation.py:19](wilab/reservation.py#L19)

**Problema.** Tutti i client condividono un solo token; l'ID di reservation è l'unica cosa che li
separa. `/debug` elenca gli ID di tutti i dispositivi, quindi qualunque client può fermare o rilasciare
la rete di un altro. L'ID è anche corto: 4 byte, 32 bit.

**Come si riproduce.** Client A crea una reservation. Client B chiama `GET /api/v1/debug`, legge
`interfaces.managed[].reservation_id` e chiama `DELETE /api/v1/device-reservation/<id>`: risponde `200`.

> **Decisione (2026-11-23):** `/debug` per ora resta com'è; in futuro verrà tolto e sostituito da un sistema diverso. La correzione qui sotto resta come riferimento.

**Come correggerlo.** Togliere l'ID e aumentare la lunghezza.

```diff
--- a/wilab/api/routes/status.py
+++ b/wilab/api/routes/status.py
                 {
                     "display_name": n.display_name,
                     "interface": n.interface,
-                    "reservation_id": (
-                        reservations[n.device_id].reservation_id
-                        if n.device_id in reservations else None
-                    ),
+                    "reserved": n.device_id in reservations,
                 }
```

```diff
--- a/wilab/reservation.py
+++ b/wilab/reservation.py
-RESERVATION_TOKEN_BYTES = 4  # 8 hex chars
+RESERVATION_TOKEN_BYTES = 16  # 32 hex chars: the ID is the only secret between clients
```

Togliere il campo da `/debug` è una modifica breaking (B10): se il frontend lo usa, va adeguato.
L'ID più lungo non rompe i client che lo trattano come stringa opaca.

---

<a id="race-1"></a>
### 19. RACE-1 - Le richieste aspettano il lock del dispositivo senza limite ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/reservation.py:239-250](wilab/reservation.py#L239-L250), [wilab/api/dependencies.py:176-183](wilab/api/dependencies.py#L176-L183)

**Problema.** Ogni endpoint per reservation, compresi quelli di sola lettura, prende il lock del
dispositivo tramite `hold_reservation`. Un avvio lo tiene fino a 15 s, o 75 s su un canale DFS; un
cambio di TX power per 3 s. Un client che interroga `GET .../network` una volta al secondo durante un
avvio lento parcheggia un thread per ogni richiesta. Il pool ha 40 thread per tutta l'API. Insieme a
STAB-1 è il modo in cui l'API smette di rispondere.

**Come si riproduce.** Test: prendere il lock di un dispositivo da un thread e tenerlo; lanciare 45
`GET .../network` concorrenti e una `GET /status`. Oggi `/status` non risponde finché il lock non viene
rilasciato.

**Come correggerlo.** Acquisire con un timeout e rispondere "occupato".

```diff
--- a/wilab/reservation.py
+++ b/wilab/reservation.py
+class DeviceBusyError(Exception):
+    """Another operation on this device is still running."""
+
@@
     @contextmanager
-    def hold(self, reservation_id: str) -> Iterator[Reservation | None]:
+    def hold(self, reservation_id: str, timeout: float = 5.0) -> Iterator[Reservation | None]:
         """Keep a reservation valid against concurrent release while in use."""
         with self._lock:
             reservation = self._reservations.get(reservation_id)
         if reservation is None:
             yield None
             return
-        with self._device_lock(reservation.device_id):
+        lock = self._device_lock(reservation.device_id)
+        if not lock.acquire(timeout=timeout):
+            raise DeviceBusyError(reservation.device_id)
+        try:
             with self._lock:
                 current = self._reservations.get(reservation_id)
             yield reservation if current is reservation and not reservation.is_expired else None
+        finally:
+            lock.release()
```

In [wilab/api/__init__.py](wilab/api/__init__.py) registrare un gestore che traduce `DeviceBusyError`
in `503` con `Retry-After: 2` e un codice proprio (per esempio `1006 device_busy`). La route di
creazione passa un timeout più lungo o nessuno. `available-channels` non ha bisogno del lock: basta
`resolve_reservation`.

---

<a id="wd-6"></a>
### 20. WD-6 - Un cleanup bloccato viene ritentato ogni 5 secondi ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:939-968](wilab/wifi/manager.py#L939-L968), [wilab/reservation.py:268-306](wilab/reservation.py#L268-L306)

**Problema.** Quando una rete che non si riesce a fermare è scaduta, il ciclo delle scadenze chiama
`stop_network` a ogni giro (più righe `ERROR` ogni volta). Finché la sua reservation esiste,
`expire_reservations` esegue il cleanup una seconda volta e lo scrive con `logger.exception`, cioè con
il traceback completo. Nella situazione di WD-5 sono fino a due cleanup falliti ogni 5 secondi: circa
35.000 al giorno. Il journal regge, ma gli errori veri vengono sepolti.

**Come si riproduce.** Test: far fallire sempre `hostapd_manager.stop`, creare una rete con scadenza
breve, far girare `_expiry_loop` per 30 secondi simulati e contare le chiamate a `stop`: oggi sono sei.

**Come correggerlo.** Ritardo crescente per dispositivo, in un punto solo.

```python
# wilab/wifi/manager.py
CLEANUP_BACKOFF = (5.0, 15.0, 60.0, 300.0)

# in __init__
self._cleanup_failures: dict[str, int] = {}
self._cleanup_retry_at: dict[str, float] = {}

def release_device(self, device_id: str) -> None:
    """Stop all tracked resources before a device can be reassigned."""
    with self.device_lock(device_id):
        ...
        try:
            self.stop_network(device_id)
        except RuntimeError:
            failures = self._cleanup_failures.get(device_id, 0)
            delay = CLEANUP_BACKOFF[min(failures, len(CLEANUP_BACKOFF) - 1)]
            self._cleanup_failures[device_id] = failures + 1
            self._cleanup_retry_at[device_id] = time.monotonic() + delay
            raise
        self._cleanup_failures.pop(device_id, None)
        self._cleanup_retry_at.pop(device_id, None)

def cleanup_due(self, device_id: str) -> bool:
    """False while a failed cleanup of this device is waiting for its next attempt."""
    return time.monotonic() >= self._cleanup_retry_at.get(device_id, 0.0)
```

`_expire_network` e `ReservationManager._cleanup_expired` (tramite un callback passato al costruttore)
saltano il dispositivo quando `cleanup_due` è falso. Le chiamate esplicite del client (`DELETE`) non
usano il ritardo: l'utente che riprova deve ottenere un tentativo vero. Usare `logger.exception` solo
al primo fallimento della serie, `logger.warning` per i successivi.

---

<a id="hap-4"></a>
### 21. HAP-4 - Un tentativo tagliato dal budget conta come guasto radio ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:48-53](wilab/wifi/manager.py#L48-L53), [wilab/wifi/manager.py:338-355](wilab/wifi/manager.py#L338-L355)

**Problema.** Il budget di 15 s parte quando parte la richiesta. Un primo tentativo che va in timeout
usa 10 s, il rollback altri secondi, poi c'è 1 s di attesa. Il tentativo successivo può partire con
appena 0,75 s (`MIN_RETRY_ATTEMPT_TIME`): l'attesa di readiness viene tagliata al tempo rimasto e
solleva "AP not ready". Quel fallimento conta come un altro guasto radio verso la quarantena, anche se
la radio non ha avuto un tentativo vero. Per i guasti di tipo timeout, "fino a 3 avvii" è in pratica 1
o 2.

**Come si riproduce.** Test con orologio controllato: primo tentativo che fallisce dopo 10 s, rollback
di 3 s. Verificare che il secondo tentativo riceva un timeout di readiness inferiore a 2 s e che il suo
fallimento produca `StartupFailure(radio=True)`.

**Come correggerlo.** Dare a ogni tentativo un tempo minimo sensato. Un avvio normale richiede circa
0,5 s e i guasti rapidi circa 1 s, quindi 4 s sono un minimo ragionevole.

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
 STARTUP_ATTEMPTS = 3
-STARTUP_RETRY_BUDGET = 15.0
+STARTUP_RETRY_BUDGET = 20.0
 STARTUP_RETRY_DELAY = 1.0
-MIN_RETRY_ATTEMPT_TIME = 0.75
+MIN_RETRY_ATTEMPT_TIME = 4.0
```

Con questi valori un tentativo parte solo se ha almeno 4 s; altrimenti la richiesta termina con il
guasto già classificato, senza aggiungerne uno artificiale. Aggiornare i tempi citati nella
documentazione dell'endpoint e in `docs/architecture.md`.

---

<a id="stab-6"></a>
### 22. STAB-6 - L'interfaccia upstream è risolta una volta sola ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/nat.py:57-100](wilab/network/nat.py#L57-L100)

**Problema.** `NatManager._resolved_upstream` non viene mai aggiornato. Se la route di default passa a
un'altra interfaccia (un cavo spostato su un'altra porta, una VPN, un failover), ogni regola NAT
successiva nomina la vecchia interfaccia e i client non hanno Internet, mentre l'API riporta
`internet_enabled: true`. Nemmeno le regole già installate vengono ricreate.

**Come si riproduce.** Con `upstream_interface: auto` e una rete attiva: cambiare la route di default
(`ip route replace default via <gw> dev <altra>`), poi creare una seconda rete. La regola
`wilab-nat-*` nomina ancora la prima interfaccia.

**Come correggerlo.** Risolvere a ogni uso e ricordare quale upstream è stato usato per ogni rete.

```diff
--- a/wilab/network/nat.py
+++ b/wilab/network/nat.py
@@ def __init__(self, upstream_interface: str = "auto"):
-        self._resolved_upstream: str | None = None
+        self._upstream_by_network: dict[str, str] = {}   # net_id -> upstream used by its rules
@@ def _discover_upstream_interface(self) -> str:
-        if self._resolved_upstream:
-            return self._resolved_upstream
-
         try:
@@
                         interface = parts[dev_idx + 1]
-                        self._resolved_upstream = interface
-                        logger.info(f"Discovered upstream interface: {interface}")
                         return interface
@@ def enable_nat(self, wifi_interface: str, net_id: str, subnet: str) -> None:
         upstream = self.get_upstream_interface()
+        if self._upstream_by_network.get(net_id) not in (None, upstream):
+            # The default route moved: rules naming the old interface are useless.
+            self._remove_nat_rules(wifi_interface, net_id)
+        self._upstream_by_network[net_id] = upstream
         self._nat_networks.add(net_id)
```

In `release_network` togliere la voce da `_upstream_by_network`. Con WD-7, che richiama `enable_nat`
periodicamente per le reti con Internet, il cambio di route viene riparato entro 30 s.

---

<a id="bug-2"></a>
### 23. BUG-2 - I controlli di salute di `/status` danno risposte sbagliate ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/routes/status.py:84-143](wilab/api/routes/status.py#L84-L143)

**Problema.**

- `is_up = "state UP" in ip_output or "UP" in ip_output`: `"UP"` compare anche in `LOWER_UP` e nel
  flag `UP` di un'interfaccia il cui stato è `DOWN`. Il controllo è vero per quasi ogni interfaccia.
- `iptables_nat.configured` è `"MASQUERADE" in <tutte le regole nat>`: vero per regole di Docker o
  libvirt che non c'entrano con Wi-Lab; falso, e quindi stato `degraded`, quando le uniche reti attive
  hanno Internet disattivato su un host senza altre regole NAT.
- hostapd non compare in `/status`; solo in `/debug`.
- dnsmasq "running" significa "esiste un file PID" (STAB-2).

Un sistema di monitoraggio che legge `status` riceve sia falsi allarmi sia false rassicurazioni.

**Come si riproduce.** Test: una rete attiva con `internet_enabled: false`, `iptables -t nat -S` finto
che restituisce solo le policy. Oggi `status` è `degraded`. Secondo test: `ip addr show` finto con
`<NO-CARRIER,BROADCAST,MULTICAST,UP> ... state DOWN`: oggi `up` è `true`.

**Come correggerlo.** Usare l'output JSON di `ip` e lo stato proprio di Wi-Lab.

```python
# wilab/api/routes/status.py
def _upstream_check(manager: NetworkManager) -> dict[str, Any]:
    name = manager.nat_manager.get_upstream_interface()
    links = json.loads(execute_command(["ip", "-j", "addr", "show", "dev", name]))
    link = links[0] if links else {}
    up = link.get("operstate") == "UP"
    has_ip = any(a.get("family") == "inet" for a in link.get("addr_info", []))
    return {"name": name, "up": up, "has_ip": has_ip, "reachable": up and has_ip}

def _nat_check(manager: NetworkManager) -> dict[str, Any]:
    rules = manager.firewall_status()                      # see NET-1
    expected = [d for d, st in manager.active.copy().items() if st.internet_enabled]
    missing = [d for d in expected if f"wilab-nat-{d}" not in (rules.get("nat") or "")]
    return {"configured": not missing, "missing": missing, "errors": rules.get("errors", [])}
```

- Il controllo dell'upstream conta per lo stato generale solo se almeno una rete ha Internet attivo.
- Aggiungere `checks.hostapd` con `manager.hostapd_manager.status()`.
- `DhcpServer.status` deve usare `is_running(net_id)` (il processo) e non l'esistenza del file PID.
- Usare le stesse funzioni in `/debug`, eliminando il codice duplicato (API-1).

`configured` resta un booleano e il campo `missing` è aggiunto: la modifica non rompe i client.

---

<a id="bug-4"></a>
### 24. BUG-4 - La cache dei canali non viene mai aggiornata ed esiste in due copie ✅

**Gravità:** Media · **Confidenza:** Confermato (il caso reale è un'Ipotesi) · **File:** [wilab/wifi/channels.py:105-126](wilab/wifi/channels.py#L105-L126), [wilab/wifi/manager.py:78](wilab/wifi/manager.py#L78), [wilab/api/dependencies.py:134-139](wilab/api/dependencies.py#L134-L139)

**Problema.** `ChannelManager.invalidate` non ha chiamanti. La cache viene riempita un attimo dopo la
scoperta di un dispositivo. Se in quel momento il dominio regolatorio non è ancora applicato
(`iw reg set` all'avvio è asincrono, e alcuni adattatori riannunciano il proprio dominio dopo il
collegamento), i canali a 5 GHz vengono memorizzati come "no IR", cioè disabilitati, e restano
rifiutati con `422` fino a un riavvio. Inoltre le cache sono **due**: il singleton usato dalle route e
un'istanza privata in `NetworkManager`, usata per il TX power.

**Come si riproduce.** Test: `execute_iw` finto che alla prima chiamata restituisce i canali 5 GHz con
`no IR` e alla seconda senza. `validate_channel(if, 36, "5ghz")` oggi solleva sempre.

**Come correggerlo.**

```diff
--- a/wilab/wifi/channels.py
+++ b/wilab/wifi/channels.py
@@ def validate_channel(self, interface: str, channel: int, band: str) -> None:
+        try:
+            self._validate(interface, channel, band)
+        except ValueError:
+            # The cached list may predate the regulatory domain: read it again
+            # once before refusing the request.
+            self.invalidate(interface)
+            self._validate(interface, channel, band)
+
+    def _validate(self, interface: str, channel: int, band: str) -> None:
         info = self.get_channels(interface)
```

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
-    def __init__(self, config: AppConfig):
+    def __init__(self, config: AppConfig, channel_manager: ChannelManager | None = None):
@@
-        self._channel_manager = ChannelManager(allow_dfs_channels=config.allow_dfs_channels)
+        self._channel_manager = channel_manager or ChannelManager(
+            allow_dfs_channels=config.allow_dfs_channels,
+        )
```

In `get_manager` passare `channel_manager=get_channel_manager()`. Chiamare `invalidate(interface)`
anche dopo un recovery USB riuscito e dopo un avvio fallito. Una rilettura costa due comandi `iw`.

---

<a id="net-6"></a>
### 25. NET-6 - Un lancio di dnsmasq andato in timeout non si può più ripulire ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/dhcp.py:203-222](wilab/network/dhcp.py#L203-L222), [wilab/network/dhcp.py:248-260](wilab/network/dhcp.py#L248-L260)

**Problema.** Se il comando che lancia dnsmasq va in timeout prima che esista il file PID, `stop`
solleva "Missing dnsmasq PID file" a ogni tentativo: il PID non è noto e il file non c'è. Il rollback
fallisce, il dispositivo va in quarantena, e ogni tentativo di recovery fallisce sulla stessa riga.

**Come si riproduce.** Test: `execute_command` finto che solleva `CommandTimeout` per il comando
`dnsmasq --conf-file=...`; poi chiamare `dhcp.stop(net_id)` due volte: solleva `DhcpServerError`
entrambe le volte.

**Come correggerlo.** Soluzione minima: quando il PID non è noto, cercare il processo dal suo
argomento `--conf-file`, che è unico per rete.

```python
# wilab/network/dhcp.py
@staticmethod
def _find_process(config_file: str) -> int | None:
    """PID of the dnsmasq started with this configuration file, if any."""
    wanted = os.fsencode(f"--conf-file={config_file}")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if args and Path(os.fsdecode(args[0])).name == "dnsmasq" and wanted in args[1:]:
            return int(entry.name)
    return None
```

In `stop`, nel ramo in cui oggi si solleva "Missing dnsmasq PID file":

```diff
-                elif not pid_file or not os.path.exists(pid_file):
-                    raise DhcpServerError(f"Missing dnsmasq PID file for {net_id}")
+                elif not pid_file or not os.path.exists(pid_file):
+                    found = self._find_process(config_file)
+                    if found is not None:
+                        stop_process(found)
```

Soluzione strutturale (ARCH-6): avviare dnsmasq in primo piano con `--keep-in-foreground` tramite
`start_foreground`, come hostapd. Spariscono file PID, cartella dei PID, `stop_process` e
`_owns_process`, e l'uscita di dnsmasq si vede subito con `poll()`.

---

<a id="wd-8"></a>
### 26. WD-8 - Una rete ripristinata perde il profilo QoS

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:121-132](wilab/wifi/watchdog.py#L121-L132), [wilab/wifi/manager.py:439-447](wilab/wifi/manager.py#L439-L447)

**Problema.** Il ripristino è stop più start. Lo stop cancella il QoS; lo start non lo rimette. Un
client che esegue un profilo "4G urbano" per un test lungo si ritrova un collegamento perfetto dopo un
ripristino, e lo stato del profilo dice "inattivo". La perdita dei sign-in del captive portal è
documentata; quella del QoS no.

**Come si riproduce.** Test: rete attiva con un profilo in esecuzione, simulare la morte di hostapd,
lasciare che il watchdog ripristini. `qos_profile_manager.is_active(interface)` è `False`.

**Come correggerlo.** Salvare il profilo prima dello stop e riavviarlo dopo un ripristino riuscito.

```diff
--- a/wilab/wifi/watchdog.py
+++ b/wilab/wifi/watchdog.py
@@ def _restore_ap(
         device = reservation.device_id
+        profiles = self.manager.qos_profile_manager
+        running = profiles.get_state(status.interface) if profiles is not None else None
+        profile_id = running.profile_id if running is not None and running.active else None
@@
             self.manager.start_network(
                 device, request, reservation.expires_at, allow_internal_retry=False,
             )
+            if profile_id is not None and profiles is not None and self.manager.qos_manager is not None:
+                profile = profiles.get_profile(profile_id)
+                if profile is not None:
+                    # The sequence restarts from its first step.
+                    profiles.start_profile(status.interface, profile, self.manager.qos_manager)
```

I profili "inline" generati (`<id>:generated_static`) non sono nel catalogo: per ripristinarli bisogna
conservare l'oggetto `QosProfile` in `_ActiveProfile` invece del solo identificativo. Documentare che
il profilo riparte dal primo passo.

---

<a id="stab-5"></a>
### 27. STAB-5 - Le scadenze usano l'orologio di sistema

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/reservation.py:48-71](wilab/reservation.py#L48-L71), [wilab/wifi/manager.py:952-955](wilab/wifi/manager.py#L952-L955), [install/systemd/wi-lab.service.template](install/systemd/wi-lab.service.template)

**Problema.** Le scadenze di reservation e reti confrontano `time.time()` con un istante memorizzato.
Un salto dell'orologio (NTP che corregge una macchina partita con l'ora sbagliata, una macchina
virtuale ripresa dopo una pausa) fa scadere tutto insieme oppure allunga tutto della dimensione del
salto. L'unit parte dopo `network-online.target`, non dopo la sincronizzazione dell'ora.

**Come si riproduce.** Test: creare una reservation di 3600 s, poi far restituire a `time.time` un
valore di due ore più avanti lasciando `time.monotonic` invariato: `is_expired` diventa `True`.

**Come correggerlo.** Tenere la scadenza in tempo monotono e derivare da essa l'istante mostrato.

```diff
--- a/wilab/reservation.py
+++ b/wilab/reservation.py
 @dataclass
 class Reservation:
@@
     expires_at: float | None  # None = unlimited (no expiry)
+    deadline: float | None = None  # monotonic time of expiry; None = unlimited
@@
     @property
     def expires_in(self) -> int | None:
-        if self.expires_at is None:
+        if self.deadline is None:
             return None
-        return max(0, int(self.expires_at - time.time()))
+        return max(0, int(self.deadline - time.monotonic()))

     @property
     def is_expired(self) -> bool:
-        if self.expires_at is None:
+        if self.deadline is None:
             return False
-        return time.time() >= self.expires_at
+        return time.monotonic() >= self.deadline
```

In `_reserve` impostare `deadline = time.monotonic() + duration_seconds`. `expires_at` resta come
valore da mostrare; per essere esatti lo si può ricalcolare a ogni lettura come
`time.time() + (deadline - time.monotonic())`. Lo stesso in `NetworkManager` per
`_expires_at_timestamp`.
Nell'unit aggiungere `After=time-sync.target` e `Wants=time-sync.target`.

---

<a id="bug-3"></a>
### 28. BUG-3 - La validazione offline è più severa di quella all'avvio

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/config_validation.py:58-71](wilab/config_validation.py#L58-L71), [wilab/config.py:26-114](wilab/config.py#L26-L114)

**Problema.** `validate_config_file` controlla che `auth_token` non sia vuoto, l'intervallo della
porta, `min_timeout <= max_timeout` e che `dns_server` sia un indirizzo IP. `load_config` non controlla
nessuna di queste cose. Il servizio parte con `dns_server: foo` e poi ogni creazione di rete fallisce
al test di configurazione di dnsmasq con un `500`. `validate_config_file` duplica anche la
normalizzazione di `_read_raw_config`.

**Come si riproduce.** Test: un file con `dns_server: foo`. `validate_config_file` restituisce un
errore, `load_config` restituisce una configurazione valida.

**Come correggerlo.** Tutte le regole in `AppConfig`; la validazione offline costruisce solo il
modello.

```diff
--- a/wilab/config.py
+++ b/wilab/config.py
 class AppConfig(BaseModel):
-    auth_token: str
-    api_port: int = 8080
+    auth_token: str = Field(min_length=1)
+    api_port: int = Field(8080, ge=1, le=65535)
@@
+    @field_validator('auth_token')
+    @classmethod
+    def validate_auth_token(cls, value: str) -> str:
+        if not value.strip():
+            raise ValueError("auth_token must not be empty")
+        return value
+
+    @field_validator('dns_server')
+    @classmethod
+    def validate_dns_server(cls, value: str) -> str:
+        return str(IPv4Address(value))
+
+    @model_validator(mode="after")
+    def validate_timeouts(self) -> "AppConfig":
+        if self.max_timeout < self.min_timeout:
+            raise ValueError("max_timeout must be at least min_timeout")
+        return self
```

Servono `from ipaddress import IPv4Address, IPv4Network` e `model_validator` tra gli import di
pydantic. In `validate_config_file` togliere i controlli duplicati (righe 58-71, tranne gli avvisi sui
valori di esempio) e riusare `_read_raw_config` per la normalizzazione. Aggiungere il test di parità
T-15.

---

<a id="net-5"></a>
### 29. NET-5 - Condizioni normali scritte nel log come errori

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/nat.py:124-143](wilab/network/nat.py#L124-L143), [wilab/network/commands.py:193-199](wilab/network/commands.py#L193-L199), [wilab/network/qos.py:208-224](wilab/network/qos.py#L208-L224)

**Problema.** `_rule_exists` esegue `iptables -C` tramite `execute_command(check=True)`, che scrive
`Command failed ...` a livello `ERROR` prima di sollevare l'eccezione. Una regola mancante è il caso
normale, quindi ogni avvio con Internet scrive tre falsi errori; i ripieghi "add, altrimenti replace"
del QoS fanno lo stesso. In un servizio che si controlla dal journal, i falsi errori nascondono quelli
veri.

**Come si riproduce.** Test con `caplog`: creare una rete con Internet e verificare che non ci siano
record di livello `ERROR`. Oggi ce ne sono tre.

**Come correggerlo.** Una funzione per le domande la cui risposta "no" è normale.

```python
# wilab/network/commands.py
def command_succeeds(cmd: list[str], timeout: float = 8.0) -> bool:
    """Run a probe whose failure is an expected answer; a failure is never logged as an error."""
    if not cmd:
        raise CommandError("Empty command")
    returncode, _, _ = _run(cmd, bounded_timeout(max(5.0, timeout)))    # _run: see STAB-1
    return returncode == 0
```

```diff
--- a/wilab/network/nat.py
+++ b/wilab/network/nat.py
     def _rule_exists(self, table: str | None, args: list) -> bool:
-        try:
-            cmd = ["iptables"]
-            if table:
-                cmd.extend(["-t", table])
-            cmd.extend(["-C"] + args)
-            execute_command(cmd)
-            return True
-        except Exception:
-            return False
+        prefix = ["-t", table] if table else []
+        return command_succeeds(["iptables", "-w", IPTABLES_LOCK_WAIT, *prefix, "-C", *args])
```

Se STAB-1 non è ancora applicato, `command_succeeds` può usare `subprocess.run` direttamente. Nel QoS,
sostituire le coppie "add, se fallisce replace" con il solo `replace` (per `qdisc`) e con
`class replace` (per le classi): `tc ... replace` crea l'oggetto se manca.

---

<a id="net-3"></a>
### 30. NET-3 - L'isolamento funziona solo per `192.168.x.x`

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/isolation.py:70-76](wilab/network/isolation.py#L70-L76)

**Problema.** `_block_traffic` salta ogni coppia in cui una subnet non inizia per `192.168.`. Con
`dhcp_base_network: 10.20.0.0/24` nessuna regola di isolamento viene installata e l'unica traccia è un
warning nel log: i client di due reti diverse possono parlarsi. Il controllo è più vecchio
dell'allocatore di subnet, che garantisce già che le subnet siano di Wi-Lab.

**Come si riproduce.** Test: `IsolationManager().add_network("10.20.0.0/24")` e poi
`add_network("10.20.1.0/24")`, registrando le chiamate a `execute_iptables`: oggi sono zero.

**Come correggerlo.**

```diff
--- a/wilab/network/isolation.py
+++ b/wilab/network/isolation.py
     def _block_traffic(self, source: str, destination: str) -> None:
-        try:
-            # SAFETY: Only block traffic BETWEEN WiFi subnets (192.168.x.0/24)
-            # Do NOT block traffic to/from host's main network
-            # Skip if either subnet is not a WiFi subnet (not 192.168.x.0/24)
-            if not (source.startswith("192.168.") and destination.startswith("192.168.")):
-                logger.warning(f"Skipping isolation rule for non-WiFi subnets: {source} -> {destination}")
-                return
-
-            execute_iptables([
-                ...
-            ])
-            logger.debug(f"Blocked traffic: {source} -> {destination}")
-        except CommandError as e:
-            logger.error(f"Failed to block traffic {source} -> {destination}: {e}")
+        # Both subnets come from the AP subnet allocator, so they are Wi-Lab's own.
+        execute_iptables([
+            "-A", "FORWARD", "-s", source, "-d", destination, "-j", "DROP",
+            "-m", "comment", "--comment", "wilab-isolation",
+        ])
+        logger.debug(f"Blocked traffic: {source} -> {destination}")
```

L'errore non viene più inghiottito: serve a NET-2, dove l'isolamento diventa una fase dell'avvio.

---

<a id="stab-2"></a>
### 31. STAB-2 - File di runtime in `/tmp`

**Gravità:** Media · **Confidenza:** Probabile · **File:** [wilab/wifi/hostapd.py:23](wilab/wifi/hostapd.py#L23), [wilab/network/dhcp.py:11-12](wilab/network/dhcp.py#L11-L12), [wilab/network/dhcp.py:317-331](wilab/network/dhcp.py#L317-L331)

**Problema.** Configurazione e socket di hostapd, configurazione, file PID e lease di dnsmasq stanno in
`/tmp/wilab-hostapd` e `/tmp/wilab-dnsmasq`. Il default di systemd rimuove da `/tmp` ciò che non viene
toccato da 10 giorni; le distribuzioni differiscono. La pulizia salta i socket ancora in uso, quindi il
socket di controllo di hostapd è al sicuro; i file normali no. Su una rete attiva da più tempo del
limite possono sparire il file PID di dnsmasq e i due file di configurazione. L'effetto visibile è che
`/status` riporta dnsmasq come non attivo e lo stato generale diventa `degraded`, perché
`DhcpServer.status` guarda il file PID e non il processo. La rete continua a funzionare.

Secondo motivo: `/tmp/wilab-dnsmasq` è un nome fisso e prevedibile in una cartella scrivibile da tutti,
e root ci scrive dentro; un utente locale può prepararla in anticipo (per esempio con un link
simbolico) e far sovrascrivere a root un file a sua scelta.

**Come si riproduce.** Controllare la politica della macchina:

```bash
systemd-tmpfiles --cat-config | grep -E '^\s*[a-zA-Z!+-]+\s+/tmp\b'
```

Per simulare l'effetto: con una rete attiva, cancellare `/tmp/wilab-dnsmasq/pids/dnsmasq-<if>.pid` e
chiamare `/status`: `checks.dnsmasq.running` diventa `false`.

**Come correggerlo.** Cartella di runtime privata, creata da systemd.

```diff
--- a/install/systemd/wi-lab.service.template
+++ b/install/systemd/wi-lab.service.template
 [Service]
+RuntimeDirectory=wilab
+RuntimeDirectoryMode=0700
```

```python
# wilab/network/commands.py (or a small wilab/paths.py)
def runtime_dir() -> Path:
    """Private directory for runtime files; systemd exports RUNTIME_DIRECTORY."""
    path = Path(os.environ.get("RUNTIME_DIRECTORY", "/run/wilab"))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path
```

Sostituire le tre costanti con `runtime_dir() / "hostapd"` e `runtime_dir() / "dnsmasq"` (calcolate
quando servono, non all'import, così i test possono cambiarle). dnsmasq cambia utente dopo l'avvio:
verificare che riesca ancora a scrivere il file dei lease nella cartella `0700` di root (lo apre prima
di cambiare utente, ma va provato). Aggiornare i riferimenti a `/tmp/wilab-*` in `docs/` e
nell'esempio OpenAPI.

---

<a id="stab-7"></a>
### 32. STAB-7 - Dipendenze non bloccate

**Gravità:** Media · **Confidenza:** Confermato · **File:** [requirements.txt](requirements.txt)

**Problema.** `requirements.txt` ha solo limiti inferiori (`fastapi>=0.110.0`, `pydantic>=2.6.0`,
`uvicorn[standard]>=0.27.0`, ...). Una reinstallazione tra sei mesi può portare una versione che cambia
comportamento, per esempio il codice che FastAPI restituisce per un header `Authorization` mancante, o
il modo in cui Starlette gestisce le route.

**Come si riproduce.** Due installazioni dello stesso commit in date diverse danno `pip freeze`
diversi.

**Come correggerlo.** Tenere `requirements.txt` come elenco delle dipendenze dirette e aggiungere un
file di blocco con le versioni esatte, usato dall'installer e dalla CI.

```bash
python -m venv /tmp/lock && /tmp/lock/bin/pip install -r requirements.txt
/tmp/lock/bin/pip freeze > requirements.lock
```

Nell'installer e nella CI: `pip install -r requirements.lock`. Il file va rigenerato di proposito,
con i test verdi, quando si decide di aggiornare.

---

<a id="net-11"></a>
### 33. NET-11 - QoS inline: `upload_quality` ignorato

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/qos_profile.py:203-228](wilab/network/qos_profile.py#L203-L228), [wilab/models.py:316-343](wilab/models.py#L316-L343)

**Problema.** `build_inline_profile` usa `download_quality` e ricorre a `upload_quality` solo se il
primo manca. Una richiesta con `download_quality: 40, upload_quality: 90` applica 40 in entrambe le
direzioni e risponde `200`. Il passo di un profilo ha un solo campo `quality`, quindi i due valori
diversi non sono rappresentabili.

**Come si riproduce.** `POST .../qos/profile` con `{"download_quality": 40, "upload_quality": 90}`,
poi `tc qdisc show dev <ifb>`: la perdita in upload è quella della qualità 40.

**Come correggerlo.** Rifiutare ciò che non si può applicare.

```diff
--- a/wilab/models.py
+++ b/wilab/models.py
@@ class QosProfileStartRequest(BaseModel):
         if not has_profile and not has_inline:
             raise ValueError("Must specify either 'profile_id' or at least one QoS parameter")
+        if (
+            self.download_quality is not None
+            and self.upload_quality is not None
+            and self.download_quality != self.upload_quality
+        ):
+            raise ValueError("download_quality and upload_quality must be equal: quality applies to both directions")
+        if self.advanced is not None and (
+            self.download_quality is not None or self.upload_quality is not None
+        ):
+            raise ValueError("'advanced' cannot be combined with a quality score")
         return self
```

Il secondo controllo copre un caso analogo: oggi con `advanced` presente la qualità viene scartata in
silenzio. In alternativa si può estendere `QosProfileStep` con qualità separate per direzione.

---

<a id="hap-8"></a>
### 34. HAP-8 - L'output di hostapd non viene conservato

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:52-83](wilab/network/commands.py#L52-L83), [wilab/wifi/hostapd.py:330-339](wilab/wifi/hostapd.py#L330-L339)

**Problema.** Dell'output di hostapd restano solo le ultime dodici etichette classificate. Quando
hostapd va in segfault, le righe subito prima del crash, cioè quelle che uno sviluppatore del driver
chiederebbe, sono perse. Il problema di origine di questo branch non si può quindi indagare a
posteriori.

**Come si riproduce.** Provocare un guasto di avvio e cercare nel journal le righe di hostapd: c'è una
sola riga riassuntiva con le etichette.

**Come correggerlo.** Tenere in memoria le ultime righe grezze e scriverle solo in caso di guasto.

```diff
--- a/wilab/network/commands.py
+++ b/wilab/network/commands.py
@@ class ForegroundProcess:
         self._events: deque[str] = deque(maxlen=12)
+        self._tail: deque[bytes] = deque(maxlen=80)   # last raw lines, reported only on failure
@@ def _drain_output(self, stream: BinaryIO, classify: Callable[[bytes], str | None]) -> None:
                 while line := stream.readline(4096):
+                    with self._events_lock:
+                        self._tail.append(line.rstrip(b"\r\n"))
                     if complete and line.endswith(b"\n") and (event := classify(line.rstrip(b"\r\n"))):
@@
+    def output_tail(self) -> list[str]:
+        """Last raw output lines of the child, for a failure report."""
+        with self._events_lock:
+            return [line.decode("utf-8", errors="replace") for line in self._tail]
```

In `_wait_until_ready`, nel ramo `except`, e nel watchdog quando trova hostapd morto, scrivere le righe
a livello `WARNING`. L'output di debug di hostapd contiene l'SSID e può contenere materiale di chiave:
prima di scrivere, scartare le righe che contengono `PSK`, `PMK`, `passphrase` o `key`. Aggiornare la
frase di `docs/architecture.md` che dichiara che l'output grezzo non viene mai registrato.

---

<a id="hap-5"></a>
### 35. HAP-5 - Ipotesi: avvii senza assestamento e senza serializzazione tra radio

**Gravità:** Media · **Confidenza:** Ipotesi · **File:** [wilab/wifi/hostapd.py:239-250](wilab/wifi/hostapd.py#L239-L250), [wilab/wifi/manager.py:81](wilab/wifi/manager.py#L81)

**Problema.** `start()` esegue `ip link set down`, `iw set type managed`, `ip addr flush` e lancia
hostapd subito. I lock sono per adattatore, quindi due adattatori possono essere attivati nello stesso
istante. Con `country_code` e `ieee80211d=1` ogni avvio di hostapd chiede al kernel un aggiornamento
regolatorio, che è globale, e adattatori USB dello stesso modello condividono bus e caricamento del
firmware. Un beacon rifiutato mentre il dominio regolatorio viene riapplicato da un altro avvio è
coerente con "fallisce una volta, riesce al tentativo immediato".

**Come si riproduce (esperimento).** Sulla macchina di laboratorio, con due adattatori:

1. 200 cicli crea/cancella su entrambi **in parallelo**; contare i guasti di avvio nel journal
   (`hostapd startup failure`).
2. Gli stessi 200 cicli **in sequenza**.
3. Ripetere il punto 1 con una pausa di 300 ms tra la preparazione dell'interfaccia e hostapd.

Se il punto 2 o 3 fallisce sensibilmente meno del punto 1, l'ipotesi è confermata.

**Come correggerlo (solo se confermata).** Un lock di processo attorno alla sola fase radio.

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
@@ class HostapdManager:
     def __init__(self) -> None:
         self._instances: dict[str, HostapdInstance] = {}
+        # Bringing up two radios at once competes for the regulatory update
+        # and for the USB bus; the load is low, so starts are serialized.
+        self._bring_up = threading.Lock()
@@ def start(
-            logger.info(f"Preparing interface {interface} for AP mode")
-            try:
-                ...
-            process = start_foreground(["hostapd", "-d", config_file], classify_output=_classify_output)
-            instance["process"] = process
-            timeout = ...
-            self._wait_until_ready(process, interface, control_dir, timeout)
+            with self._bring_up:
+                logger.info(f"Preparing interface {interface} for AP mode")
+                ...   # same statements, indented
```

Per i canali DFS (attesa fino a 75 s) rilasciare il lock quando hostapd entra nello stato `DFS`, per
non fermare gli altri adattatori.

---

<a id="hap-6"></a>
### 36. HAP-6 - Ipotesi: il TX power viene cambiato subito dopo l'avvio

**Gravità:** Media · **Confidenza:** Ipotesi · **File:** [wilab/wifi/manager.py:365-372](wilab/wifi/manager.py#L365-L372)

**Problema.** `iw dev <if> set txpower fixed` viene eseguito subito dopo la readiness, a ogni avvio. Il
progetto documenta già che il controllo del TX power non funziona sui dongle provati. Un comando che si
sa non funzionare, inviato a un driver che si sa fragile, a ogni avvio, è un rischio senza beneficio
quando il livello è 4 (il massimo, ed è il valore che il frontend manda di default).

**Come si riproduce (esperimento).** Confrontare la frequenza di guasti del watchdog e di
`Message ... timeout` in `journalctl -k` su 24 ore con il comando attivo e con il comando disattivato
per il livello 4.

**Come correggerlo.**

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
         tx_power_level = req.tx_power_level
-        try:
-            self._set_tx_power(cfg_net.interface, tx_power_level, req.channel)
-            ...
-        except Exception as e:
-            logger.warning(f"Failed to set TX power for {device_id}: {e}")
+        if tx_power_level < 4:
+            # Level 4 is the driver default: do not send a command for it.
+            try:
+                self._set_tx_power(cfg_net.interface, tx_power_level, req.channel)
+                runtime_dbm = self._read_current_txpower(cfg_net.interface)
+                logger.info(...)
+            except Exception as e:
+                logger.warning(f"Failed to set TX power for {device_id}: {e}")
```

Attenzione: se una rete precedente sullo stesso adattatore aveva abbassato la potenza, il valore può
restare. `reset_interface` (STAB-4) dovrebbe quindi includere `iw dev <if> set txpower auto`, da
eseguire a interfaccia ferma, cioè nel momento meno delicato.

---

<a id="bug-5"></a>
### 37. BUG-5 - La discovery può ignorare un adattatore per sempre

**Gravità:** Media · **Confidenza:** Probabile · **File:** [wilab/wifi/discovery.py:82-119](wilab/wifi/discovery.py#L82-L119)

**Problema.** `_ready_radio` richiede che la proprietà udev `ID_NET_NAME`, quando presente, sia uguale
al nome dell'interfaccia. Sugli host dove l'interfaccia mantiene un altro nome (regola udev
personalizzata, politica che conserva il nome del kernel) i due valori differiscono per sempre:
l'interfaccia resta "pending" e l'unico messaggio è a livello `DEBUG`. Il sintomo è "Wi-Lab non vede il
mio adattatore" con il log vuoto.

**Come si riproduce.** Test: `udevadm info` finto che restituisce `INTERFACE=wlan0`, `IFINDEX=3`,
`USEC_INITIALIZED=1`, `ID_NET_NAME=wlx00c0ca112233`. `discover_radios()` restituisce una lista vuota a
ogni chiamata.

**Come correggerlo.** Il controllo serve a non usare un'interfaccia che udev sta per rinominare. Basta
aspettare un numero limitato di scansioni, poi accettarla e dirlo.

```diff
--- a/wilab/wifi/discovery.py
+++ b/wilab/wifi/discovery.py
+# Scans an interface may stay "not yet renamed" before it is accepted as it is.
+RENAME_GRACE_SCANS = 3
+_rename_waits: dict[str, int] = {}
+
@@ def _ready_radio(phy: str, interface: str) -> DiscoveredRadio | None:
-        if (
-            not props.get("USEC_INITIALIZED")
-            or props.get("INTERFACE") != interface
-            or props.get("IFINDEX") != ifindex
-            or props.get("ID_NET_NAME", interface) != interface
-        ):
+        if (
+            not props.get("USEC_INITIALIZED")
+            or props.get("INTERFACE") != interface
+            or props.get("IFINDEX") != ifindex
+        ):
             return None
+        if props.get("ID_NET_NAME", interface) != interface:
+            waits = _rename_waits.get(interface, 0) + 1
+            _rename_waits[interface] = waits
+            if waits <= RENAME_GRACE_SCANS:
+                return None
+            if waits == RENAME_GRACE_SCANS + 1:
+                logger.warning(
+                    "Using %s although udev suggests the name %s: it was not renamed",
+                    interface, props["ID_NET_NAME"],
+                )
```

`discover_radios` fa già cinque tentativi ravvicinati per chiamata: il contatore va incrementato una
volta per chiamata di `discover_radios`, non per tentativo interno.

---

<a id="bug-9"></a>
### 38. BUG-9 - Un profilo QoS personalizzato può impedire l'avvio del servizio

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/network/qos_profile.py:63-124](wilab/network/qos_profile.py#L63-L124), [wilab/data/qos-profiles/profile.schema.json](wilab/data/qos-profiles/profile.schema.json)

**Problema.** `_load_catalogue` scarta i file con JSON non valido o che non rispettano lo schema, ma
costruisce i modelli pydantic fuori da ogni `try`. Lo schema e il modello non coincidono: lo schema
accetta un passo con `"advanced": {}` come unico contenuto (la chiave è presente, quindi `anyOf` è
soddisfatto), mentre il codice trasforma il dizionario vuoto in `None` e `QosProfileStep` rifiuta un
passo senza alcun parametro. L'eccezione risale da `QosProfileManager.__init__` a `get_manager`, che è
chiamato in `lifespan`: il servizio non parte, e con `Restart=always` riprova ogni 10 secondi. Anche un
file di schema illeggibile ha lo stesso effetto.

I dieci profili forniti in `default.json` sono corretti e non hanno questo problema.

**Come si riproduce.** Test: in una cartella temporanea copiare lo schema e scrivere `custom.json` con

```json
[{"id": "x", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "advanced": {}}]}]
```

`QosProfileManager(cartella)` solleva `pydantic.ValidationError`.

**Come correggerlo.** Un profilo sbagliato va scartato con un avviso, non deve fermare il servizio.

```diff
--- a/wilab/network/qos_profile.py
+++ b/wilab/network/qos_profile.py
+from pydantic import ValidationError
@@ def _load_catalogue(self) -> None:
-        with open(schema_path) as f:
-            schema = json.load(f)
+        try:
+            with open(schema_path) as f:
+                schema = json.load(f)
+        except (json.JSONDecodeError, OSError) as exc:
+            logger.error("Cannot read profile schema %s: %s", schema_path, exc)
+            return
@@
             for raw_profile in data:
                 pid = raw_profile["id"]
                 ...
-                steps = [
-                    QosProfileStep(...)
-                    for s in raw_profile["steps"]
-                ]
-                self._profiles[pid] = QosProfile(...)
+                try:
+                    steps = [
+                        QosProfileStep(
+                            duration_sec=s["duration_sec"],
+                            quality=s.get("quality"),
+                            dl_speed_kbit=s.get("dl_speed_kbit"),
+                            ul_speed_kbit=s.get("ul_speed_kbit"),
+                            advanced=QosQualityAdvanced(**s["advanced"]) if "advanced" in s else None,
+                        )
+                        for s in raw_profile["steps"]
+                    ]
+                    profile = QosProfile(
+                        id=pid, description=raw_profile.get("description", ""),
+                        source_file=json_file.name, mode=QosProfileMode(raw_profile["mode"]), steps=steps,
+                    )
+                except (ValidationError, ValueError) as exc:
+                    logger.warning("Skipping invalid profile '%s' in '%s': %s", pid, json_file.name, exc)
+                    continue
+                self._profiles[pid] = profile
```

Con `"advanced" in s` un oggetto vuoto diventa "netem senza parametri", coerente con lo schema.
Aggiungere allo schema `"minProperties": 1` per `advanced`, per rendere esplicita la regola.

---

<a id="stab-9"></a>
### 39. STAB-9 - Il rilascio da NetworkManager è solo a runtime

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/unmanaged.py:61-81](wilab/network/unmanaged.py#L61-L81)

**Problema.** `nmcli device set <if> managed no` viene dimenticato quando NetworkManager riparte (per
esempio per un aggiornamento di pacchetto). NetworkManager può allora riprendersi la radio di un AP
attivo. Il watchdog lo ripristina, una volta (WD-1).

**Come si riproduce.** Con una rete attiva: `systemctl restart NetworkManager`, poi
`nmcli device status`: la radio torna gestita e l'AP può cadere.

**Come correggerlo.** Scrivere un file di configurazione a runtime **senza ricaricare**
NetworkManager: si mantiene la decisione del commit `87c3ce1` (mai un reload) e si copre il caso del
riavvio, perché NetworkManager legge quella cartella quando parte.

```python
# wilab/network/unmanaged.py
NM_RUNTIME_RULES = Path("/run/NetworkManager/conf.d/00-wilab-unmanaged.conf")

# inside exclude_from_host_managers, after the nmcli loop
if NM_RUNTIME_RULES.parent.parent.is_dir():
    devices = ";".join(f"interface-name:{name}" for name in names)
    try:
        # Read only when NetworkManager starts: this file is never reloaded on purpose.
        _replace(NM_RUNTIME_RULES, f"[keyfile]\nunmanaged-devices={devices}\n")
    except OSError as exc:
        logger.warning("Cannot write NetworkManager rules for Wi-Lab radios: %s", exc)
```

Il file elenca solo i nomi delle radio di Wi-Lab, quindi non può toccare l'interfaccia di gestione.

---

<a id="stab-8"></a>
### 40. STAB-8 - L'arresto ordinato può superare `TimeoutStopSec=30s`

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:768-779](wilab/wifi/manager.py#L768-L779), [install/systemd/wi-lab.service.template](install/systemd/wi-lab.service.template)

**Problema.** L'arresto rilascia i dispositivi uno dopo l'altro; ogni rilascio può richiedere diversi
secondi (join del thread QoS fino a 5 s, terminate e kill di hostapd fino a 4 s, vari comandi). uvicorn
attende inoltre le richieste in corso, e un avvio DFS può tenerne una per 75 s. Su un pool di dieci
adattatori i 30 s possono essere superati: systemd uccide il processo e si ricade in STAB-4.

**Come si riproduce.** Con più reti attive: `time systemctl stop wi-lab` e controllare nel journal la
riga "State 'stop-sigterm' timed out. Killing."

**Come correggerlo.** Rilasciare in parallelo e dare più tempo.

```python
# wilab/wifi/manager.py, in shutdown_all
threads = [
    threading.Thread(target=self._release_quietly, args=(device_id,), name=f"shutdown-{device_id}")
    for device_id in device_ids
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=20)
```

dove `_release_quietly` contiene il `try / except` attuale. Nell'unit: `TimeoutStopSec=60s`. In
`uvicorn.run` aggiungere `timeout_graceful_shutdown=10` per non attendere all'infinito le richieste
in corso. Sostituire anche il `except Exception: pass` di `lifespan` con `logger.exception`.

---

<a id="wd-10"></a>
### 41. WD-10 - Tre probe lenti riavviano un AP forse sano

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:64-66](wilab/wifi/watchdog.py#L64-L66), [wilab/wifi/hostapd.py:399-411](wilab/wifi/hostapd.py#L399-L411)

**Problema.** `is_enabled` concede 1 s a `hostapd_cli`. Su una macchina virtuale carica, tre risposte
lente in 15 s disconnettono tutti i client, e per via di WD-1 consumano anche l'unico riavvio.

**Come si riproduce.** Test: `execute_command` finto che per `hostapd_cli` solleva `CommandTimeout` tre
volte, con il processo vivo. Il watchdog chiama `_restore_ap`.

**Come correggerlo.** Distinguere "hostapd dice che non è ENABLED" da "non ha risposto in tempo".

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
-    def is_enabled(self, net_id: str) -> bool:
+    def is_enabled(self, net_id: str) -> bool | None:
+        """True or False from hostapd; None when it did not answer in time."""
@@
-        except CommandError:
+        except CommandTimeout:
+            return None
+        except CommandError:
             return False
```

Nel watchdog: una risposta `None` conta mezzo "miss" (soglia 6 invece di 3), una risposta `False`
conta come oggi. Verificare gli altri chiamanti di `is_enabled` (`probe_recovered_radio` usa
`not ...is_enabled(...)`, che resta corretto perché `None` è falso).

---

<a id="hap-9"></a>
### 42. HAP-9 - Canali DFS con controllo radar di 10 minuti

**Gravità:** Bassa · **Confidenza:** Probabile · **File:** [wilab/wifi/hostapd.py:29](wilab/wifi/hostapd.py#L29), [wilab/wifi/hostapd.py:249](wilab/wifi/hostapd.py#L249)

**Problema.** Il timeout per i canali da 52 a 144 è 75 s. In Europa i canali dei radar meteo (120, 124,
128) richiedono 600 s di ascolto. Con `allow_dfs_channels: true` una richiesta su quei canali va sempre
in timeout e viene trattata come guasto radio, fino alla quarantena.

**Come si riproduce.** Con `allow_dfs_channels: true` e `country_code` europeo, creare una rete sul
canale 124.

**Come correggerlo.** La via semplice: rifiutare quei canali finché non sono gestiti.

```python
# wilab/wifi/channels.py
# ETSI weather-radar channels need a 10-minute radar check, longer than any request can wait.
LONG_CAC_CHANNELS = frozenset({120, 124, 128})
```

In `validate_channel`, per la banda `5ghz`: se `channel in LONG_CAC_CHANNELS` sollevare
`ValueError("Channel ... requires a 10-minute radar check and is not supported")`. La via completa:
leggere `cac_time` dalla riga `DFS-CAC-START` di hostapd e usarlo come timeout, rispondendo subito al
client con uno stato "radar check in corso".

---

<a id="hap-10"></a>
### 43. HAP-10 - Chiavi duplicate e opzione `wpa` ingannevole

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:149-182](wilab/wifi/hostapd.py#L149-L182)

**Problema.** Per `wpa3` e `wpa2-wpa3` il file contiene `wpa_key_mgmt` due o tre volte e `ieee80211w`
due volte; hostapd tiene l'ultima, quindi funziona per caso. `encryption: "wpa"` produce `wpa=2`, cioè
WPA2, identico a `wpa2`: l'API offre un'opzione che non esiste. Sui 5 GHz è abilitato solo 802.11n
(manca `ieee80211ac`), quindi le reti a 5 GHz sono più lente di quanto l'adattatore permetta.

**Come si riproduce.** `HostapdManager()._generate_config("wlan0", "x", 36, "wpa2-wpa3", "12345678", False, "5ghz")`
e contare le righe che iniziano con `wpa_key_mgmt=`: sono tre.

**Come correggerlo.** Una tabella, una riga per chiave.

```python
# wilab/wifi/hostapd.py
_SECURITY: dict[str, list[str]] = {
    "open": [],
    "wpa2": ["wpa=2", "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP"],
    "wpa3": ["wpa=2", "wpa_key_mgmt=SAE", "rsn_pairwise=CCMP", "ieee80211w=2"],
    "wpa2-wpa3": ["wpa=2", "wpa_key_mgmt=WPA-PSK SAE", "rsn_pairwise=CCMP", "ieee80211w=1"],
}
_SECURITY["wpa"] = _SECURITY["wpa2"]     # kept as an alias until the API drops it (B11)
```

In `_generate_config`: `config_lines.extend(_SECURITY[encryption])` più, se la lista non è vuota,
`wpa_passphrase=...`. Per i 5 GHz valutare `ieee80211ac=1` dopo una prova sugli adattatori in uso:
è un cambiamento del comportamento radio e va misurato, non dato per buono.

#### Decisioni e supporto a WPA1 (2026-11-24)

**`wpa` diventa un errore.** Oggi `encryption: "wpa"` produce WPA2 senza dirlo: chi vuole testare un
client WPA1 crede di averlo fatto e invece il test gira su WPA2. Si accetta la **modifica breaking**:
`wpa` risponde `422` con un messaggio che indica di usare `wpa2`, oppure `wpa1` per il vero WPA legacy.

**Le altre cifrature.** `open` e `wpa2` sono corrette. `wpa3` e `wpa2-wpa3` funzionano solo perché
hostapd tiene l'ultima chiave duplicata; con la tabella `_SECURITY` vanno anche completate:

| `encryption` | Righe hostapd |
|---|---|
| `open` | nessuna |
| `wpa1` (nuovo) | `wpa=1`, `wpa_key_mgmt=WPA-PSK`, `wpa_pairwise=TKIP`, `ieee80211n=0` |
| `wpa2` | `wpa=2`, `wpa_key_mgmt=WPA-PSK`, `rsn_pairwise=CCMP` |
| `wpa3` | `wpa=2`, `wpa_key_mgmt=SAE`, `rsn_pairwise=CCMP`, `ieee80211w=2`, `sae_pwe=2` |
| `wpa2-wpa3` | `wpa=2`, `wpa_key_mgmt=WPA-PSK SAE`, `rsn_pairwise=CCMP`, `ieee80211w=1`, `sae_require_mfp=1`, `sae_pwe=2` |

- `sae_pwe=2`: accetta sia il metodo SAE classico (*hunting-and-pecking*) sia H2E, che alcuni client
  recenti preferiscono.
- `sae_require_mfp=1`: nella modalità mista i client SAE devono usare PMF (come prevede WPA3), i client
  WPA2 no.
- `ieee80211n=0` con `wpa1`: lo standard vieta TKIP con le velocità 802.11n; lo si dichiara invece di
  lasciare che hostapd disattivi HT da solo. La rete va al massimo a 54 Mbps.

**WPA1 solo dove funziona: prima la discovery.** TKIP è deprecato e molti driver o build di hostapd non
lo supportano più in modalità AP. `wpa1` va quindi offerto solo sulle antenne in cui è verificato:

1. **Controllo statico alla discovery:** il driver dichiara il cifrario TKIP (`iw phy <phy> info`,
   riga `TKIP (00-0f-ac:2)`) e l'hostapd installato è compilato con TKIP. Sulla macchina di laboratorio
   (2026-11-24) entrambi gli mt7921u dichiarano TKIP e hostapd 2.11 di Ubuntu contiene il supporto TKIP:
   il controllo statico è positivo.
2. **Prova reale:** un e2e avvia un AP `wpa1` su un'antenna libera e verifica con
   `hostapd_cli get_config` che usi `WPA-PSK` e TKIP. Solo se questa prova passa `wpa1` entra tra i
   valori ammessi.
3. **Esposizione:** ogni antenna ricorda le cifrature che supporta. Una create con `wpa1` su
   un'antenna che non lo supporta risponde `422` ("wpa1 is not supported on this antenna"). Per far
   sapere al client cosa è disponibile, `GET /status` può elencare le cifrature per antenna in
   `networks[].encryptions` (campo aggiunto, non breaking).

**Documentazione richiesta dall'implementazione.**

- Swagger: la descrizione di `encryption` spiega ogni valore in una riga. `wpa1` è solo per testare
  client legacy: insicuro, senza 802.11n, alcuni client recenti avvisano o non si collegano, ed è
  disponibile solo sulle antenne che lo supportano. `wpa` non è più accettato: usare `wpa2`.
- CHANGELOG 4.0.0: una voce in Breaking Changes (`wpa` → `422`, migrazione a `wpa2`), una in Features
  (`wpa1`), e le stesse due righe nel capitolo API per la migrazione dei client.
- Frontend: nel menu della cifratura `wpa` è sostituito da `wpa1`, mostrato solo per le antenne che lo
  supportano.

**Test.** Unit: nessuna chiave duplicata per nessuna cifratura, righe attese per ogni valore, `wpa` →
`422`. E2E: create con ogni cifratura → `200` e `hostapd_cli get_config` coerente, `wpa` → `422`.
Tester: gli stessi codici via API. Telefono: collegamento a `wpa2-wpa3` (client WPA3 e WPA2) e a `wpa1`
(annotando avvisi o rifiuti dei client recenti).

**Separato da HAP-10:** larghezza di canale e generazione Wi-Fi (`ieee80211ac`, `ieee80211ax`, 40/80 MHz) sono il punto [HAP-11](#hap-11), da fare subito dopo e solo con una conferma umana.

---

<a id="hap-11"></a>
### 44. HAP-11 - Larghezza di canale e generazione Wi-Fi fissate a 20 MHz e 802.11n

**Gravità:** Media · **Confidenza:** Confermato (capacità lette da `iw phy` sulla macchina di laboratorio, 2026-11-24) · **File:** [wilab/wifi/hostapd.py](wilab/wifi/hostapd.py), [wilab/models.py](wilab/models.py), [wilab/wifi/channels.py](wilab/wifi/channels.py)

> **Serve una conferma umana prima di implementare.** Le scelte elencate in "Decisioni da confermare"
> cambiano il comportamento radio e l'API: vanno decise da una persona prima di scrivere codice.
> Il punto va fatto **dopo HAP-10**, che sistema la sezione di sicurezza dello stesso file di
> configurazione.

**Problema.** `hostapd.conf` contiene solo `ieee80211n=1`, senza `ht_capab`, senza `ieee80211ac` e
senza `ieee80211ax`. Ogni rete usa quindi un canale da 20 MHz con 802.11n, su entrambe le bande, anche
se gli adattatori in uso (mt7921u) supportano molto di più in modalità AP:

| Banda | Capacità dell'adattatore (AP) | Usato oggi |
|---|---|---|
| 2,4 GHz | HT20/HT40, HE (Wi-Fi 6) fino a 40 MHz | 20 MHz, 802.11n |
| 5 GHz | HT20/HT40, VHT (802.11ac) fino a 80 MHz, HE fino a 80 MHz | 20 MHz, 802.11n |

Conseguenze:

- sui 5 GHz la banda disponibile è circa un quarto di quella possibile;
- non si possono testare client nelle condizioni reali di Wi-Fi 5 (802.11ac) e Wi-Fi 6 (802.11ax);
- sui 2,4 GHz manca 802.11ax, che anche a 20 MHz porta OFDMA e 1024-QAM.

Non è un errore di correttezza: le reti funzionano. È un limite di prestazioni e di copertura dei
test.

**Come si riproduce.** Creare una rete a 5 GHz e leggere `iw dev <if> info`: `width: 20 MHz`. Il file
`hostapd.conf` dell'istanza non contiene `ht_capab`, `ieee80211ac` né `ieee80211ax`. Sullo stesso
adattatore `iw phy <phy> info` riporta `HT20/HT40`, `VHT Capabilities` e `HE Iftypes: AP` con
`HE40/HE80/5GHz`.

**Perché non basta accendere le opzioni.**

- **Gruppi di canali.** A 40 e 80 MHz i canali vanno a blocchi (5 GHz: 36–48, 52–64, 100–112, …).
  Serve la frequenza centrale (`vht_oper_centr_freq_seg0_idx`, `he_oper_centr_freq_seg0_idx`) e il
  verso del canale secondario (`[HT40+]` / `[HT40-]`). Alcune combinazioni sono impossibili (il 165
  non va a 80 MHz).
- **DFS.** Un canale da 80 MHz può includere canali DFS anche se il canale primario non lo è: va
  coordinato con HAP-9 e con `allow_dfs_channels`.
- **2,4 GHz a 40 MHz.** La banda ha solo 3 canali da 20 MHz che non si sovrappongono; un canale da
  40 MHz ne occupa due terzi e disturba le altre antenne. Lo standard obbliga hostapd a tornare a
  20 MHz se rileva reti vicine (coesistenza 20/40, OBSS): con più AP accesi accade quasi sempre.
- **802.11ac non esiste sui 2,4 GHz.**
- **Stabilità.** Gli mt7921u in VM mostrano già guasti transitori all'avvio (HAP-1…HAP-4). Canali
  più larghi e HE vanno provati sull'hardware prima di diventare comportamento normale.
- **Cifratura.** `wpa1` (HAP-10) usa TKIP, incompatibile con HT/VHT/HE: con `wpa1` larghezza e
  generazione restano 20 MHz e 802.11a/g.

**Come correggerlo (proposta).** Due campi opzionali nella richiesta di creazione, con default uguali
al comportamento di oggi, quindi nessuna modifica breaking:

```python
# wilab/models.py
class NetworkCreateRequest(BaseModel):
    ...
    channel_width: Literal[20, 40, 80] = 20           # MHz
    wifi_generation: Literal[4, 5, 6] = 4             # 4 = 802.11n, 5 = 802.11ac (5 GHz), 6 = 802.11ax
```

- Validazione (`422`): `wifi_generation: 5` solo sui 5 GHz; `channel_width: 80` solo sui 5 GHz;
  combinazioni canale/larghezza impossibili; larghezze che includono canali DFS quando non sono
  ammessi; `wpa1` con larghezza o generazione superiori al minimo.
- Una funzione pura `_width_lines(band, channel, width, generation)` restituisce le righe hostapd
  (`ht_capab`, `ieee80211ac`, `vht_oper_chwidth`, `vht_oper_centr_freq_seg0_idx`, `ieee80211ax`,
  `he_oper_chwidth`, `he_oper_centr_freq_seg0_idx`), testabile senza hardware.
- La discovery registra per ogni antenna le capacità lette da `iw phy` (HT40, VHT80, HE): una
  richiesta oltre le capacità dell'antenna risponde `422`, e `GET /status` può elencarle per antenna.
- `GET .../network` riporta larghezza e generazione effettive lette da `iw dev <if> info`, perché
  hostapd può ridurle (coesistenza 20/40, DFS).

**Decisioni da confermare (conferma umana obbligatoria).**

1. Forma dell'API: i due campi `channel_width` e `wifi_generation`, oppure una scelta automatica del
   massimo supportato dall'antenna, oppure un solo campo combinato.
2. 2,4 GHz a 40 MHz: rifiutarlo (`422`, comportamento prevedibile) oppure permetterlo con
   l'avvertenza che hostapd può tornare a 20 MHz.
3. 802.11ax: attivabile da subito o solo dopo la prova su hardware.
4. Default: restare a 20 MHz / 802.11n (nessun cambiamento per i client esistenti) oppure alzarlo
   dopo le prove.

**Decisioni prese (2026-11-25).**

1. Forma dell'API: due campi opzionali, `channel_width` (20, 40, 80) e `wifi_generation` (4, 5, 6).
2. 2,4 GHz a 40 MHz: permesso. `GET .../network` riporta in `reported_channel_width` la larghezza
   letta da `iw dev <if> info`, che può essere 20 MHz per la coesistenza 20/40.
3. 802.11ax: attivabile subito, ma solo sulle antenne in cui la discovery vede HE in modalità AP.
4. Default: 20 MHz / 802.11n, nessun cambiamento per i client esistenti.

`GET /status` elenca per antenna cifrature, larghezze e generazioni ammesse in
`networks[].capabilities`; la lista viene da `iw phy <phy> info`, letta insieme ai canali.

**Test.** Unit: righe generate per ogni combinazione banda/canale/larghezza/generazione e `422` per
quelle impossibili. E2E (con conferma, a sistema libero): create a 20/40/80 MHz e con ogni
generazione, `iw dev <if> info` mostra la larghezza attesa, nessun aumento di guasti all'avvio su una
serie di create. Telefono: collegamento e misura della velocità a 20, 40 e 80 MHz sui 5 GHz, con un
client Wi-Fi 5 e uno Wi-Fi 6.

---

<a id="net-8"></a>
### 45. NET-8 - `dns_server` ha come default un indirizzo di laboratorio

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/config.py:37](wilab/config.py#L37)

**Problema.** Il default di `dns_server` in `AppConfig` è `192.168.10.21`. Un'installazione che omette
la chiave consegna ai client un server DNS che non esiste: i dispositivi dicono "connesso, senza
Internet".

**Come si riproduce.** Configurazione senza `dns_server`, rete con Internet attivo, client collegato:
`nslookup example.com` va in timeout.

**Come correggerlo.** Rendere la chiave obbligatoria (errore chiaro all'avvio):

```diff
--- a/wilab/config.py
+++ b/wilab/config.py
-    dns_server: str = "192.168.10.21"
+    dns_server: str
```

È un cambiamento di configurazione che rompe chi ometteva la chiave: va annotato nel CHANGELOG tra le
modifiche breaking, e `config.example.yaml` deve già contenerla.

---

<a id="net-12"></a>
### 46. NET-12 - QoS: gara alla fine di un profilo `once`

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/qos_profile.py:264-274](wilab/network/qos_profile.py#L264-L274)

**Problema.** Quando un profilo `once` finisce, il thread si segna come inattivo e **poi** cancella le
regole. Un nuovo profilo avviato in quella finestra viene accettato (il precedente risulta inattivo) e
può vedersi togliere le regole dal vecchio thread: lo stato dice "profilo attivo" e `tc` è vuoto.

**Come si riproduce.** Test: `clear_qos` finto che si ferma su un `Event`; far terminare un profilo
`once`, avviarne un altro mentre `clear_qos` è fermo, poi sbloccare.

**Come correggerlo.** Cancellare prima, segnare inattivo dopo, sotto il lock del gestore.

```diff
--- a/wilab/network/qos_profile.py
+++ b/wilab/network/qos_profile.py
         finally:
-            # Mark inactive
-            ap.active = False
-            # For 'once' mode, clear QoS when the sequence finishes naturally
-            if not ap.stop_event.is_set():
-                try:
-                    qos_manager.clear_qos(interface)
-                except Exception as exc:
-                    logger.warning("Failed to clear QoS after profile end on %s: %s", interface, exc)
+            with self._lock:
+                # Clear first: a new profile is accepted only after ap.active is False.
+                if not ap.stop_event.is_set():
+                    try:
+                        qos_manager.clear_qos(interface)
+                    except Exception as exc:
+                        logger.warning("Failed to clear QoS after profile end on %s: %s", interface, exc)
+                ap.active = False
```

`start_profile` prende lo stesso lock, quindi aspetta la fine della pulizia.

---

<a id="net-13"></a>
### 47. NET-13 - QoS: lo stop del profilo può far fallire lo stop della rete

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/qos_profile.py:182-197](wilab/network/qos_profile.py#L182-L197), [wilab/wifi/manager.py:439-447](wilab/wifi/manager.py#L439-L447)

**Problema.** `stop_profile` aspetta il thread per 5 s. Un thread fermo dentro un comando `tc` lento
(ogni comando ha un timeout minimo di 5 s, e un passo ne esegue diversi) fa sollevare `RuntimeError`,
e `_stop_network` riporta uno stop fallito. Il tentativo successivo riesce, ma passando dal percorso
`503`.

**Come si riproduce.** Test: `execute_tc` finto che dorme 6 s; avviare un profilo e chiamare subito
`stop_network`.

**Come correggerlo.** Aspettare quanto può durare un passo, e non far dipendere lo stop della rete dal
thread: le regole vengono comunque cancellate da `clear_qos`.

```diff
--- a/wilab/network/qos_profile.py
+++ b/wilab/network/qos_profile.py
         ap.stop_event.set()
         if ap.thread is not None:
-            ap.thread.join(timeout=5)
+            ap.thread.join(timeout=30)
             if ap.thread.is_alive():
-                raise RuntimeError(f"QoS profile on {interface} did not stop")
+                # The thread is inside a slow tc command. It exits at its next
+                # check of stop_event; the rules are cleared below anyway.
+                logger.warning("QoS profile thread on %s is still stopping", interface)
```

`_run_profile` deve controllare `ap.stop_event` anche dopo `_apply_step`, per non applicare un passo
dopo la pulizia.

---

<a id="bug-7"></a>
### 48. BUG-7 - TX power: stato incoerente dopo un mismatch

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:824-894](wilab/wifi/manager.py#L824-L894)

**Problema.** `set_tx_power_level` invia il comando, dorme 3 s tenendo il lock del dispositivo, e in
caso di differenza solleva `TxPowerMismatchError` senza registrare nulla. L'hardware può trovarsi a un
terzo valore mentre lo stato continua a riportare il vecchio livello richiesto.

**Come si riproduce.** Test: `iw dev info` finto che riporta sempre 20 dBm; `POST .../txpower` con
livello 1 risponde `422`; `GET .../txpower` riporta ancora il livello precedente.

**Come correggerlo.** Registrare sempre il livello richiesto e riportare la differenza nella risposta,
senza attesa bloccante.

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
@@ def set_tx_power_level(self, device_id: str, level: int) -> dict:
-        info = self._set_tx_power(cfg_net.interface, level, st.channel, verify_change=True)
         st.tx_power_level = level
         self.active[device_id] = st
-        return info
+        # The requested level is recorded first: the status must say what was asked,
+        # and reported_dbm says what the hardware does.
+        return self._set_tx_power(cfg_net.interface, level, st.channel, verify_change=True)
```

Per togliere i 3 s (PERF-6): ridurre l'attesa a un controllo ripetuto ogni 0,2 s per al massimo 1 s,
uscendo appena il valore riportato corrisponde.

---

<a id="bug-8"></a>
### 49. BUG-8 - Confronto del token non a tempo costante

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/auth.py:11-19](wilab/api/auth.py#L11-L19)

**Problema.** Il token Bearer è confrontato con `!=`, mentre la password di conferma usa
`hmac.compare_digest`. Un confronto normale termina al primo carattere diverso e in teoria permette di
ricavare il token misurando i tempi.

**Come si riproduce.** Non riproducibile in modo pratico su rete; è una correzione di buona norma.

**Come correggerlo.**

```diff
--- a/wilab/api/auth.py
+++ b/wilab/api/auth.py
-    if credentials.credentials != config.auth_token:
+    if not hmac.compare_digest(credentials.credentials.encode(), config.auth_token.encode()):
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
```

---

<a id="bug-6"></a>
### 50. BUG-6 - `validate_interface_ap_mode` non dimostra nulla

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/interface.py:52-90](wilab/wifi/interface.py#L52-L90), [wilab/wifi/manager.py:254-262](wilab/wifi/manager.py#L254-L262)

**Problema.** `"AP" not in phy_output` è una ricerca di sottostringa su tutto il testo di
`iw phy info`, che contiene "AP" in molte righe non pertinenti (per esempio "Device supports AP-side
u-APSD"). La discovery ha già un parser corretto (`_supports_ap_mode`). Le tre chiamate
`validate_interface_*` prima di ogni avvio ripetono, in modo meno preciso, ciò che la discovery ha già
stabilito, al costo di quattro comandi.

**Come si riproduce.** Test: `iw phy info` finto senza la riga `* AP` tra i modi supportati ma con la
riga "Device supports AP-side u-APSD". `validate_interface_ap_mode` restituisce `True`.

**Come correggerlo.** Tenere solo il controllo di esistenza, che è l'unico che può cambiare dopo la
discovery.

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
         try:
             validate_interface_exists(cfg_net.interface)
-            validate_interface_wireless(cfg_net.interface)
-            validate_interface_ap_mode(cfg_net.interface)
         except InterfaceError as e:
```

Rimuovere `validate_interface_wireless`, `validate_interface_ap_mode` e `validate_interface` da
`interface.py` con i relativi test e le sostituzioni in `tests/conftest.py`.

---

<a id="net-9"></a>
### 51. NET-9 - Le subnet non sono stabili tra un riavvio e l'altro

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:111-141](wilab/wifi/manager.py#L111-L141)

**Problema.** L'allocatore salta ogni subnet che si sovrappone a una route dell'host. Dopo un riavvio
non pulito, una radio che ha ancora il vecchio indirizzo fa sembrare "in uso" la propria subnet
precedente: il dispositivo riceve la successiva e la tiene per tutta la vita del processo. I client che
si aspettano una subnet precisa la vedono cambiare.

**Come si riproduce.** Rete attiva sul primo adattatore (subnet base), `kill -9` del servizio, riavvio,
nuova rete sullo stesso adattatore: la subnet è la base più uno.

**Come correggerlo.** La causa sparisce con `reset_interface` alla scoperta del dispositivo (STAB-4),
che toglie l'indirizzo prima di qualunque allocazione.

---

<a id="net-7"></a>
### 52. NET-7 - I file dei lease sopravvivono alla reservation

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/dhcp.py:232-277](wilab/network/dhcp.py#L232-L277)

**Problema.** `leases-<dispositivo>.db` non viene mai cancellato: il prossimo utente dell'adattatore
eredita i lease del precedente per un massimo di 12 ore. Innocuo per l'indirizzamento, ma i dati di una
sessione di test (indirizzi MAC dei client) passano alla successiva.

**Come si riproduce.** Creare una rete, collegare un client, rilasciare; creare una nuova rete sullo
stesso adattatore e leggere il file dei lease: contiene il client precedente.

**Come correggerlo.**

```diff
--- a/wilab/network/dhcp.py
+++ b/wilab/network/dhcp.py
@@ def stop(self, net_id: str) -> None:
             if os.path.exists(config_file):
                 os.remove(config_file)
                 logger.info(f"Removed dnsmasq config {config_file}")
+            try:
+                # Leases belong to the network that ends here, not to the device.
+                os.remove(instance["lease_file"])
+            except FileNotFoundError:
+                pass
```

Attenzione: il watchdog, quando riavvia solo dnsmasq (`_restore_dhcp`), chiama `stop` e poi `start`:
in quel caso i lease vanno conservati, altrimenti i client collegati possono ricevere indirizzi già in
uso. Aggiungere a `stop` un parametro `keep_leases: bool = False` e passarlo `True` da `_restore_dhcp`.

---

<a id="net-10"></a>
### 53. NET-10 - Captive portal: tre dettagli

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/captive.py:136-137](wilab/network/captive.py#L136-L137), [wilab/network/captive.py:245-248](wilab/network/captive.py#L245-L248), [wilab/network/nat.py:219-228](wilab/network/nat.py#L219-L228)

**Problema.**

1. Il portale si mette in ascolto sull'indirizzo del gateway, porta 80. Se un servizio dell'host
   ascolta su `0.0.0.0:80`, ogni avvio del portale fallisce con un `500` generico.
2. `int(self.headers.get("Content-Length") or 0)` su un header malformato solleva `ValueError` dentro
   il gestore; il server standard stampa un traceback su stderr.
3. La regola "proteggi le connessioni esistenti" viene inserita a un indice calcolato dal solo numero
   di regole di blocco; con una regola di salto del portale presente finisce in mezzo alle regole di
   blocco di un'altra rete. Conta solo quando la policy di `FORWARD` è `DROP`.

**Come si riproduce.** (1) Avviare un server web sulla porta 80 dell'host e creare una rete con
`captive_portal: true`. (2) `curl -X POST -H "Content-Length: abc" http://<gateway>/login`.

**Come correggerlo.**

```diff
--- a/wilab/network/captive.py
+++ b/wilab/network/captive.py
     def do_POST(self) -> None:
-        length = int(self.headers.get("Content-Length") or 0)
+        try:
+            length = int(self.headers.get("Content-Length") or 0)
+        except ValueError:
+            self.send_error(400)
+            return
```

Per (1): nel messaggio di `CaptivePortalError`, quando l'errore è `EADDRINUSE`, dire esplicitamente
"porta 80 già in uso sull'host". Per (3): aggiungere la regola in coda con `-A FORWARD` invece di
calcolare un indice; con policy `DROP` basta che esista, e in coda non può scavalcare alcun blocco.

---

<a id="net-4"></a>
### 54. NET-4 - Riga di log falsa ✅

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:413-414](wilab/wifi/manager.py#L413-L414)

**Problema.** Ogni avvio scrive `Isolation disabled for testing` subito dopo
`Isolation rules applied`. È un residuo ed è falso: chi legge il log crede che l'isolamento sia spento.

**Come si riproduce.** Creare una rete e leggere il log.

**Come correggerlo.**

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
-        #     # Don't fail network creation if isolation fails
-        logger.info(f"Isolation disabled for testing (network {device_id})")
```

(La riga sparisce comunque applicando NET-2.)

---

<a id="hap-7"></a>
### 55. HAP-7 - Ipotesi: `hostapd -d` per tutta la vita dell'AP

**Gravità:** Bassa · **Confidenza:** Ipotesi · **File:** [wilab/wifi/hostapd.py:247](wilab/wifi/hostapd.py#L247)

**Problema.** L'output di debug serve solo a classificare gli eventi di avvio. Dopo, costa un risveglio
del thread lettore per ogni riga, per tutta la vita dell'AP, e modifica leggermente i tempi di hostapd.
Su un driver fragile ogni differenza di temporizzazione è un sospetto in più.

**Come si riproduce (esperimento).** Confrontare su 24 ore la stabilità di un AP avviato con `-d` e di
uno avviato senza, con lo stesso traffico.

**Come correggerlo.** Le stesse informazioni arrivano dal socket di controllo senza output di debug:
`hostapd_cli -p <dir> -i <if> -a <script>` oppure una connessione diretta al socket con il comando
`ATTACH` consegnano `AP-ENABLED`, `AP-DISABLED`, `AP-STA-CONNECTED`. È una riscrittura del modo in cui
si leggono gli eventi: da fare solo se l'esperimento mostra una differenza. Fino ad allora `-d` resta
utile, soprattutto con HAP-8.

---

<a id="race-2"></a>
### 56. RACE-2 - `/status` legge stato condiviso senza lock ✅

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/status.py:72-170](wilab/api/routes/status.py#L72-L170)

**Problema.** `len(manager.active)`, la tabella delle istanze DHCP e lo stato NAT sono letti mentre
altri thread li modificano. Con il lock dell'interprete nulla si corrompe, ma la fotografia può essere
incoerente per una chiamata: per esempio `active_networks: 1` senza istanze dnsmasq, che produce un
`degraded` passeggero.

**Come si riproduce.** Interrogare `/status` in ciclo stretto mentre una rete viene creata e cancellata
ripetutamente: ogni tanto lo stato è `degraded` senza motivo.

**Come correggerlo.** Calcolare lo stato da un'unica fotografia: copiare `manager.active` una volta
(`snapshot = manager.active.copy()`) e derivare tutti i controlli da quella. Una rete che è nella
fotografia ma il cui avvio non è ancora finito non può comparire, perché viene inserita in `active`
solo a fine avvio; resta il caso dello stop, per il quale basta non considerare `degraded` un
dispositivo il cui lock è occupato (`lock.acquire(blocking=False)` fallito: operazione in corso).

---

<a id="race-3"></a>
### 57. RACE-3 - Lo stato di `QosManager` non ha lock

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/qos.py:50-136](wilab/network/qos.py#L50-L136)

**Problema.** `_state` è scritto dal thread del profilo e dal percorso di stop. `stop_profile` aspetta
il thread prima di pulire, e questo copre il caso normale; NET-12 e NET-13 sono i due buchi.

**Come si riproduce.** Vedi NET-12 e NET-13.

**Come correggerlo.** Un lock per interfaccia in `QosManager`, preso da `apply_qos` e `clear_qos`:

```python
# wilab/network/qos.py
def _lock_for(self, interface: str) -> threading.Lock:
    with self._ifb_lock:
        return self._locks.setdefault(interface, threading.Lock())
```

con `self._locks: dict[str, threading.Lock] = {}` in `__init__` e `with self._lock_for(interface):`
attorno al corpo dei due metodi pubblici. Così due modifiche alle regole `tc` della stessa interfaccia
non si intrecciano mai.

---

<a id="perf-3"></a>
### 58. PERF-3 - `/status` costa tre comandi a chiamata

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/status.py:84-125](wilab/api/routes/status.py#L84-L125), [wilab/network/nat.py:359-376](wilab/network/nat.py#L359-L376)

**Problema.** Ogni chiamata esegue `iptables -t nat -S`, `iptables -S FORWARD` e `ip addr show`. È
l'endpoint che il frontend interroga di continuo, ed è anche la sorgente delle collisioni di NET-1.

**Come si riproduce.** Contare i processi creati: `strace -f -e trace=execve -p <pid>` durante dieci
chiamate a `/status`.

**Come correggerlo.** Una cache di pochi secondi sul risultato dei controlli.

```python
# wilab/api/routes/status.py
_HEALTH_TTL = 5.0
_health_cache: tuple[float, dict[str, Any]] | None = None
_health_lock = threading.Lock()

def _cached_health(manager: NetworkManager) -> dict[str, Any]:
    global _health_cache
    with _health_lock:
        now = time.monotonic()
        if _health_cache is None or now - _health_cache[0] > _HEALTH_TTL:
            _health_cache = (now, _compute_health(manager))
        return _health_cache[1]
```

`_compute_health` contiene i controlli di BUG-2. Il lock evita che dieci richieste simultanee lancino
dieci volte gli stessi comandi. La parte su reservation e stato dei dispositivi resta calcolata a ogni
chiamata: viene dalla memoria e non costa nulla.

---

<a id="perf-1"></a>
### 59. PERF-1 - L'avvio di una rete esegue circa 20 comandi ✅ parz.

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:94-109](wilab/wifi/manager.py#L94-L109), [wilab/wifi/manager.py:254-272](wilab/wifi/manager.py#L254-L272), [wilab/network/dhcp.py:186-200](wilab/network/dhcp.py#L186-L200), [wilab/network/nat.py:187-313](wilab/network/nat.py#L187-L313)

**Problema.** In ordine: `nmcli` tre volte più una pausa di 0,2 s, `ip link show`, `iw info` due
volte, `iw phy info`, `ip route` (controllo subnet), tre comandi di preparazione dell'interfaccia,
`hostapd_cli` una o più volte, `ip addr add`, `dnsmasq --version`, `dnsmasq --test`, `dnsmasq`,
`iw set txpower`, `iw info`, poi da sei a otto chiamate `iptables` (un controllo e un'aggiunta per ogni
regola). Ogni processo costa pochi millisecondi su un PC e decine su una scheda piccola o una macchina
virtuale carica.

**Come si riproduce.** Misurare il tempo di una `POST .../network` e contare gli `execve` con `strace`.

**Come correggerlo.** Quattro tagli semplici:

- togliere le due validazioni ridondanti dell'interfaccia (BUG-6): tre comandi in meno;
- togliere `dnsmasq --version` da `DhcpServer.start`: `--test` fallisce comunque con "Command not
  found" se manca, e l'errore è già chiaro;
- verificare la presenza di `nmcli` una volta all'avvio (`shutil.which("nmcli")`) invece di eseguire
  `nmcli --version` a ogni avvio di rete;
- installare le regole di una rete con una sola chiamata:

```python
# wilab/network/commands.py
def execute_iptables_restore(rules: str) -> None:
    """Apply several rules in one transaction, keeping every other rule."""
    process_input = rules if rules.endswith("\n") else rules + "\n"
    ...  # run ["iptables-restore", "-w", IPTABLES_LOCK_WAIT, "--noflush"] with process_input on stdin
```

  `--noflush` aggiunge senza toccare le regole esistenti, e l'operazione è atomica: o tutte le regole o
  nessuna, il che semplifica anche il rollback. Richiede che il runner accetti un input su stdin.

---

<a id="perf-2"></a>
### 60. PERF-2 - `GET .../network` costa due o tre comandi a chiamata

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:505-565](wilab/wifi/manager.py#L505-L565), [wilab/wifi/manager.py:660-713](wilab/wifi/manager.py#L660-L713)

**Problema.** Ogni lettura esegue `iw dev station dump`, `iw dev info` e legge il file dei lease,
tenendo il lock del dispositivo. Anche `enable_internet`, `disable_internet`, `set_tx_power_level` e
`_require_active_network` chiamano `get_status` solo per sapere se la rete è attiva, pagando lo stesso
costo.

**Come si riproduce.** Contare gli `execve` durante una `POST .../internet/enable`: compaiono
`iw ... station dump` e `iw ... info`, che non servono.

**Come correggerlo.** Separare "la rete è attiva?" da "dammi i dettagli".

```python
# wilab/wifi/manager.py
def active_status(self, device_id: str) -> NetworkStatus | None:
    """The stored status of an active network, without querying the radio."""
    with self.device_lock(device_id):
        return self.active.get(device_id)
```

Usarlo nei quattro punti citati al posto di `get_status`. Per i client che interrogano spesso,
conservare l'elenco dei client per 1-2 secondi in `_get_status` (timestamp monotono per dispositivo).

---

<a id="perf-5"></a>
### 61. PERF-5 - Timeout minimo di 5 s imposto in silenzio

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:160-183](wilab/network/commands.py#L160-L183), [wilab/network/subnet.py:12](wilab/network/subnet.py#L12)

**Problema.** `execute_command` porta ogni timeout ad almeno 5 s, a meno che il chiamante passi
`exact_timeout=True`. Chi scrive `timeout=2` (per esempio `host_ipv4_networks`) ottiene 5 s senza
saperlo. Due parametri per dire una cosa sola, e un valore che non significa ciò che dice.

**Come si riproduce.** Test: `execute_command(["sleep", "3"], timeout=1)` non va in timeout.

**Come correggerlo.** Il timeout passato è quello usato; il default resta 8 s.

```diff
--- a/wilab/network/commands.py
+++ b/wilab/network/commands.py
-def execute_command(
-    cmd: list[str], check: bool = True, timeout: float = 8.0, *, exact_timeout: bool = False,
-) -> str:
+def execute_command(cmd: list[str], check: bool = True, timeout: float = 8.0) -> str:
@@
-        effective_timeout = bounded_timeout(
-            timeout if exact_timeout else max(5.0, timeout)
-        )
+        effective_timeout = bounded_timeout(timeout)
```

Togliere `exact_timeout=True` dai chiamanti (`hostapd.py`, `discovery.py`) e rivedere i pochi punti che
passano un timeout inferiore a 5 s per decidere il valore voluto: `subnet.py` (2 s) e il `usbreset`
(15 s, già sopra il minimo).

---

<a id="perf-6"></a>
### 62. PERF-6 - Il cambio di TX power blocca per 3 secondi

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:849-860](wilab/wifi/manager.py#L849-L860)

**Problema.** `_set_tx_power(verify_change=True)` esegue `time.sleep(3)` dentro la richiesta e sotto il
lock del dispositivo. Per 3 s ogni altra richiesta sulla stessa reservation aspetta (RACE-1).

**Come si riproduce.** Misurare la durata di `POST .../txpower`: sempre più di 3 s.

**Come correggerlo.** Attesa attiva breve al posto della pausa fissa.

```diff
--- a/wilab/wifi/manager.py
+++ b/wilab/wifi/manager.py
         if verify_change:
-            # Wait for driver to apply change
-            time.sleep(3)
-            power_after = self._read_current_txpower(interface)
+            # Poll briefly: most drivers report the new value at once or never.
+            deadline = time.monotonic() + 1.0
+            while True:
+                power_after = self._read_current_txpower(interface)
+                if power_after is not None and abs(power_after - desired_dbm) <= 0.5:
+                    break
+                if time.monotonic() >= deadline:
+                    break
+                time.sleep(0.2)
```

Verificare su hardware che 1 s basti per gli adattatori che supportano il cambio.

---

<a id="perf-4"></a>
### 63. PERF-4 - Costo fisso del polling in background

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:49](wilab/wifi/watchdog.py#L49), [wilab/api/dependencies.py:92-123](wilab/api/dependencies.py#L92-L123), [wilab/config.py:207-235](wilab/config.py#L207-L235)

**Problema.** Per ogni AP attivo, un `hostapd_cli` ogni 5 s: circa 6,3 milioni di processi creati
all'anno per adattatore. La discovery ogni 30 s esegue due `ip route`, `iw dev`, un `iw phy info` per
radio, un `udevadm info` per interfaccia, e rilegge e rivalida tutto `config.yaml`. Il costo in CPU è
trascurabile; è un punto di eleganza e di rumore, non di necessità.

**Come si riproduce.** `perf stat -e sched:sched_process_fork -p <pid> sleep 60`.

**Come correggerlo.** In ordine di semplicità:

1. Rileggere `config.yaml` solo se la data di modifica è cambiata (`os.stat(path).st_mtime_ns`).
2. Portare l'intervallo del probe `hostapd_cli` a 15 s lasciando a 5 s il controllo `poll()` del
   processo, che non costa nulla e copre il caso del crash.
3. Soluzione a eventi: una connessione persistente al socket di controllo di hostapd (`ATTACH`) per
   `AP-DISABLED`, e `udevadm monitor --subsystem-match=net` come processo figlio in primo piano per i
   collegamenti a caldo. Il polling resta come rete di sicurezza a intervalli lunghi.

---

<a id="perf-7"></a>
### 64. PERF-7 - Memoria e descrittori: nessuna crescita trovata

**Gravità:** Bassa (informativo) · **Confidenza:** Confermato

**Problema.** Nessuno. Ho cercato strutture che crescono nel tempo: le tabelle sono indicizzate per
dispositivo e limitate; le pipe di hostapd si chiudono quando il lettore termina; le cartelle
temporanee vengono rimosse allo stop; i processi figli vengono raccolti da `poll()`. L'unico contatore
senza limite è l'indice dei dispositivi IFB (`_ifb_counter`), che allunga solo un nome.

**Come si riproduce.** Per conferma sperimentale: 10.000 cicli crea/cancella e confronto di
`/proc/<pid>/status` (`VmRSS`) e del numero di voci in `/proc/<pid>/fd` prima e dopo (test T-21).

**Come correggerlo.** Niente da correggere. Per l'indice IFB, riusare gli indici liberati:

```python
def _allocate_ifb(self) -> str:
    with self._ifb_lock:
        used = {state.ifb_device for state in self._state.values() if state.ifb_device}
        index = next(i for i in itertools.count() if f"wilab-ifb{i}" not in used)
        return f"wilab-ifb{index}"
```

---

<a id="api-2"></a>
### 65. API-2 - "Rete non attiva" ha due codici diversi ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/routes/internet.py:50-56](wilab/api/routes/internet.py#L50-L56), [wilab/api/routes/txpower.py:45-48](wilab/api/routes/txpower.py#L45-L48), [wilab/api/routes/qos_profile.py:56-66](wilab/api/routes/qos_profile.py#L56-L66)

**Problema.** Il QoS risponde `409` ("network is not active"). Internet e TX power rispondono `404` con
il messaggio "Unknown or inactive device_id". Per questi due un client non può distinguere una
reservation scaduta (`404`) da una rete semplicemente spenta, se non leggendo il messaggio, cosa che la
documentazione dice di non fare.

**Come si riproduce.** Reservation valida senza rete: `POST .../internet/enable` risponde `404`,
`POST .../qos/profile` risponde `409`.

**Come correggerlo.** Un'eccezione dedicata nel manager e una sola traduzione. **Modifica breaking**
(B2): cambia un codice di stato.

```python
# wilab/wifi/manager.py
class NetworkNotActive(ValueError):
    """The reservation is valid but it has no running network."""
```

Sollevarla in `enable_internet`, `disable_internet`, `set_tx_power_level`, `get_tx_power_info` al posto
di `ValueError("Unknown or inactive device_id")`. In [wilab/api/__init__.py](wilab/api/__init__.py):

```python
@app.exception_handler(NetworkNotActive)
async def network_not_active(request: Request, exc: NetworkNotActive) -> JSONResponse:
    return api_error_response(
        request, 409, domain_error(ApiErrorCode.NETWORK_NOT_ACTIVE, "Network is not active"),
    )
```

con `NETWORK_NOT_ACTIVE = 1007` in `ApiErrorCode`. Togliere dalle route i `except ValueError` che
traducono in `404`.

---

<a id="api-4"></a>
### 66. API-4 - `500` usato per esiti che riguardano il client ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/routes/recovery_responses.py:22-35](wilab/api/routes/recovery_responses.py#L22-L35), [wilab/api/routes/network.py:232-251](wilab/api/routes/network.py#L232-L251)

**Problema.** `500 / 1003` significa "la tua reservation non esiste più": è uno stato, non un difetto
del server. Molti client, proxy e librerie trattano `500` come "riprova", che qui è la cosa sbagliata.
Anche una passphrase di lunghezza errata è un `500` (BUG-1), e così ogni `ValueError` non riconosciuto.

**Come si riproduce.** Far fallire tre richieste di creazione con un guasto radio: la terza risponde
`500` con `reservation_invalidated: true`.

**Come correggerlo.** **Modifica breaking** (B4).

```diff
--- a/wilab/api/routes/recovery_responses.py
+++ b/wilab/api/routes/recovery_responses.py
     if code == RecoveryCode.RETRY_LATER:
         status_code = 409
-    elif code == RecoveryCode.DEVICE_UNAVAILABLE and invalidated:
-        status_code = 500
     else:
         status_code = 503
```

Il codice di dominio `1003` e `reservation_invalidated: true` restano: il client che guarda
`detail.code` non cambia. Aggiornare la tabella in `API_DESCRIPTION`, gli esempi della route e
`docs/ap-creation-procedure.md`. Gli errori di configurazione della richiesta diventano `422` con
BUG-1.

---

<a id="api-9"></a>
### 67. API-9 - Esempi OpenAPI corretti a mano e non più allineati ✅

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/api/__init__.py:221-363](wilab/api/__init__.py#L221-L363), [wilab/models.py:132-274](wilab/models.py#L132-L274)

**Problema.** `custom_openapi` modifica gli esempi a mano dentro un `try / except: pass`: se la
struttura dello schema cambia, la correzione viene saltata senza avviso. Diversi esempi mostrano un
campo `device_id` che nessun modello di risposta ha; l'esempio di `/status` dice versione `3.1.0`;
l'esempio di creazione documenta un messaggio `422` che non può essere prodotto (BUG-1). I modelli
`QosRequest`, `QosStatus` e `InterfaceStatus` descrivono endpoint che non esistono.

**Come si riproduce.** Aprire `/docs`, confrontare l'esempio `200` di `GET .../txpower` con una
risposta reale: `device_id` non c'è.

**Come correggerlo.**

1. Spostare ogni esempio accanto al modello o alla route che descrive (`json_schema_extra` nel modello,
   `openapi_examples` e `responses` nella route), come già fatto per le route più recenti.
2. Ridurre `custom_openapi` alla sola chiamata `document_errors`.
3. Cancellare i tre modelli inutilizzati e i loro test.
4. Aggiungere il test T-16, che valida ogni esempio di risposta `200` contro il proprio
   `response_model`: impedisce che gli esempi tornino a divergere.

---

<a id="api-5"></a>
### 68. API-5 - Le risposte di successo contengono solo una frase

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/network.py:229-231](wilab/api/routes/network.py#L229-L231), [wilab/api/routes/internet.py:52](wilab/api/routes/internet.py#L52)

**Problema.** `POST .../network` restituisce `{"detail": "Network wlan0 created successfully"}`. Il
client deve fare una `GET` per conoscere subnet, gateway o URL del portale, e quella `GET` costa
comandi (PERF-2). Inoltre `detail` è una stringa nei successi e un oggetto negli errori.

**Come si riproduce.** Leggere la risposta di una creazione riuscita.

**Come correggerlo.** Non breaking (N2): aggiungere lo stato accanto a `detail`.

```diff
--- a/wilab/api/routes/network.py
+++ b/wilab/api/routes/network.py
-            manager.start_network(
+            status = manager.start_network(
                 device_id, req, expires_at_timestamp=reservation.expires_at,
                 allow_internal_retry=reservation.radio_failures == 0,
             )
             reservation.radio_failures = 0
             reservation.retry_at = 0
-            return {"detail": f"Network {device_id} created successfully"}
+            return {
+                "detail": f"Network {device_id} created successfully",
+                "network": status.model_dump(exclude={"clients", "clients_connected", "tx_power"}),
+            }
```

Lo stesso per i due endpoint di Internet (`enable_internet` restituisce già lo stato). Documentare il
nuovo campo nell'esempio `200`.

---

<a id="api-10"></a>
### 69. API-10 - I campi sconosciuti vengono ignorati

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/models.py](wilab/models.py), [wilab/api/routes/reservation.py:32-45](wilab/api/routes/reservation.py#L32-L45)

**Problema.** Un errore di battitura come `captive-portal` o `internet-enabled` viene accettato e si
applica il valore di default: il client crede di aver chiesto un portale e non lo ottiene.

**Come si riproduce.** `POST .../network` con `"captive-portal": true`: risposta `200`, nessun portale.

**Come correggerlo.** **Modifica breaking** (B8) per i client che mandano campi in più.

```python
model_config = ConfigDict(extra="forbid", json_schema_extra={...})
```

su `NetworkCreateRequest`, `ReservationCreateRequest`, `TxPowerRequest`, `QosProfileStartRequest` e
`QosQualityAdvanced`. Verificare prima cosa manda il frontend.

---

<a id="api-3"></a>
### 70. API-3 - `409` significa sette cose diverse

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/errors.py:15-17](wilab/api/errors.py#L15-L17), route varie

**Problema.** `409` viene usato per: rete già attiva, rete già inattiva, ripristino in corso, riprova
più tardi (`1001`), nessun dispositivo (`1005`), profilo già attivo, rete non attiva. Solo due casi
hanno un codice proprio; gli altri hanno `code: 409` e si distinguono solo dal messaggio.

**Come si riproduce.** Confrontare `detail.code` delle risposte `409` di `POST .../network` su una rete
già attiva e durante un ripristino: entrambe `409`.

**Come correggerlo.** Un codice per caso, mantenendo lo stato HTTP. Per chi legge solo lo stato HTTP
non cambia nulla; per chi confronta `detail.code == 409` è **breaking** (B3).

```python
class ApiErrorCode(IntEnum):
    CLEANUP_FAILED = 1004
    NO_DEVICE_AVAILABLE = 1005
    DEVICE_BUSY = 1006            # RACE-1
    NETWORK_NOT_ACTIVE = 1007     # API-2
    NETWORK_ALREADY_ACTIVE = 1008
    RESTORATION_IN_PROGRESS = 1009
    QOS_PROFILE_ACTIVE = 1010
```

Sostituire nelle route `HTTPException(status_code=409, detail="...")` con
`HTTPException(status_code=409, detail=domain_error(ApiErrorCode.X, "..."))`.

---

<a id="api-11"></a>
### 71. API-11 - Tre livelli di retry

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/network.py:212-243](wilab/api/routes/network.py#L212-L243), [wilab/reservation.py:56-58](wilab/reservation.py#L56-L58)

**Problema.** Retry interno (3 avvii), retry del client con cooldown (`409 / 1001`, due volte), poi
quarantena. Il secondo livello era il disegno originale; ora che il server ritenta da solo aggiunge
soprattutto stato sulla reservation (`radio_failures`, `retry_at`) e una tabella di casi che ogni
client deve implementare. La misura fatta dal progetto stesso dice che attendere il cooldown non
migliorava il tasso di successo.

**Come si riproduce.** Leggere la tabella in `API_DESCRIPTION`: otto righe per spiegare cosa fare a
seconda della risposta.

**Come correggerlo.** **Modifica breaking** (B5), da fare dopo WD-2 e WD-4.

- La richiesta di creazione usa sempre il retry interno (`allow_internal_retry=True`).
- Se tutti i tentativi falliscono con un guasto radio: `503` con codice `1002` e `Retry-After`, la
  reservation resta, e la rete passa al watchdog come "pending" (WD-2), che continua a provare.
- Togliere `radio_failures` e `retry_at` da `Reservation`, `CREATE_RETRY_DELAYS` e il codice `1001`.
- La quarantena diventa una decisione del solo watchdog, con il budget di WD-1.

Il client si riduce a: `200` fatto, `503` riprova o interroga lo stato, `404` reservation persa.

---

<a id="api-1"></a>
### 72. API-1 - Lo stesso dato esposto in più punti

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/models.py:103-130](wilab/models.py#L103-L130), [wilab/api/routes/status.py:72-303](wilab/api/routes/status.py#L72-L303)

**Problema.** `expires_at` / `expires_in` sono nella reservation e nello stato della rete; `/status`
chiama lo stesso valore `reservation_remaining_seconds`. `clients_connected` è sempre `len(clients)`.
`tx_power` è nello stato della rete e in `GET .../txpower`. `/status` e `/debug` calcolano gli stessi
tre controlli con codice duplicato (circa 70 righe ciascuno), e il duplicato è già divergente: hostapd
compare solo in `/debug`.

**Come si riproduce.** Confrontare le due funzioni `_system_status` e `_debug_info`.

**Come correggerlo.** Parte non breaking: estrarre `_compute_health(manager)` (vedi BUG-2 e PERF-3) e
usarla in entrambe le route, cancellando la copia. Parte breaking (B7): un solo nome per il tempo
residuo (`expires_in`) anche in `/status`, e rimozione di `clients_connected`.

---

<a id="api-8"></a>
### 73. API-8 - Dettagli interni nella risposta

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/dhcp.py:279-292](wilab/network/dhcp.py#L279-L292), [wilab/models.py:128](wilab/models.py#L128)

**Problema.** Il campo `dhcp` di `GET .../network` è un dizionario non tipizzato che espone
`config_file`, `pid_file`, `lease_file` e il flag interno `process_stopped`. Sono dettagli di
implementazione (e cambieranno con STAB-2 e NET-6), e rivelano percorsi del server.

**Come si riproduce.** Leggere `dhcp` in una risposta reale.

**Come correggerlo.** Un modello tipizzato con i soli dati utili al client. **Breaking** (B7) per chi
legge i campi rimossi.

```python
# wilab/models.py
class DhcpInfo(BaseModel):
    subnet: str
    gateway: str
    range_start: str
    range_end: str
    dns_server: str
```

`NetworkStatus.dhcp: DhcpInfo | None`. `DhcpServer.get_subnet_info` resta per uso interno; un nuovo
metodo `public_info(net_id)` costruisce il modello (serve salvare `dns_server` nell'istanza).

---

<a id="api-6"></a>
### 74. API-6 - Nomi incoerenti

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/](wilab/api/routes/)

**Problema.** Il percorso dice `/interface/{reservation_id}`: il parametro è una reservation, non
un'interfaccia. La creazione usa `tx_power_level`, l'endpoint del TX power usa `level`. Gli errori
citano `device_id`, un nome che nell'API non esiste. `device-reservation` è al singolare.

**Come si riproduce.** Leggere l'elenco dei percorsi in `/docs`.

**Come correggerlo.** **Breaking** (B1), da fare una volta sola insieme alle altre.

- `/api/v1/reservations` e `/api/v1/reservations/{id}` al posto di `/device-reservation`;
- `/api/v1/reservations/{id}/network`, `/internet`, `/txpower`, `/qos/profile`, `/channels`;
- messaggi di errore con "reservation" o "network" al posto di `device_id`.

Per una transizione morbida si possono registrare gli stessi router due volte, con il vecchio prefisso
marcato `deprecated=True`, per una versione. La regola del progetto ("cambio netto, niente livelli di
compatibilità") suggerisce invece di farlo in una sola versione maggiore.

---

<a id="api-7"></a>
### 75. API-7 - Azioni modellate come percorsi

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/internet.py](wilab/api/routes/internet.py), [wilab/api/routes/txpower.py:51-87](wilab/api/routes/txpower.py#L51-L87)

**Problema.** `POST /internet/enable` e `POST /internet/disable` sono due endpoint per un booleano;
impostare il TX power è una `POST`, pur essendo un'operazione idempotente.

**Come si riproduce.** Leggere l'elenco dei percorsi.

**Come correggerlo.** Aggiungere (N7, non breaking) e poi togliere i vecchi (B6, breaking).

```python
class InternetRequest(BaseModel):
    enabled: bool

@router.put("/{reservation_id}/internet")
def set_internet(body: InternetRequest, ...):
    with hold_reservation(reservation_mgr, reservation):
        status = (manager.enable_internet if body.enabled else manager.disable_internet)(reservation.device_id)
        return {"internet_enabled": status.internet_enabled}
```

Analogamente `PUT .../txpower` con lo stesso corpo della `POST` attuale.

---

<a id="arch-2"></a>
### 76. ARCH-2 - Classificazione dei guasti sparsa in quattro posti

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:62-78](wilab/wifi/hostapd.py#L62-L78), [wilab/wifi/manager.py:60-64](wilab/wifi/manager.py#L60-L64), [wilab/api/routes/network.py:232-251](wilab/api/routes/network.py#L232-L251), [wilab/wifi/watchdog.py:133-142](wilab/wifi/watchdog.py#L133-L142)

**Problema.** Cosa sia un guasto è deciso dalla gerarchia di eccezioni in `hostapd.py`,
dall'espressione `radio=` in `manager.py`, dalla traduzione in HTTP in `routes/network.py` e dalle
decisioni in `watchdog.py`. Le route classificano anche confrontando testo
(`"already active" in error_msg_lower`). HAP-2, HAP-3 e WD-2 sono conseguenze dirette: nessuno dei
quattro posti ha una visione completa.

**Come si riproduce.** Provare a rispondere alla domanda "cosa succede se hostapd esce con codice 1
durante un riavvio del watchdog?": servono quattro file.

**Come correggerlo.** Un'enumerazione impostata dove nasce l'errore e una sola tabella enum → azione.

```python
# wilab/wifi/failures.py
class FailureKind(Enum):
    TRANSIENT_RADIO = "transient_radio"     # retry, then restart later
    CONFIGURATION = "configuration"         # the request can never work: tell the client
    CLEANUP_FAILED = "cleanup_failed"       # resources may still be up: isolate the device
    CONFLICT = "conflict"                   # already active, busy

@dataclass
class StartupFailure(Exception):
    kind: FailureKind
    stage: str
    message: str
```

`hostapd.py` solleva eccezioni che portano il proprio `kind`; `manager.py` lo propaga senza
ricalcolarlo; la route ha una tabella `kind → (status HTTP, codice)`; il watchdog una tabella
`kind → azione`. I confronti di testo spariscono.

---

<a id="arch-1"></a>
### 77. ARCH-1 - `NetworkManager` fa troppe cose

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py)

**Problema.** 970 righe: ciclo di vita, politica di retry, allocazione delle subnet, elenco dei client,
lettura dei lease, TX power, thread delle scadenze, integrazione con NetworkManager, contesto del
portale. Il ciclo di retry da solo è lungo 90 righe con cinque livelli di annidamento e due blocchi
`raise StartupFailure` quasi identici.

**Come si riproduce.** Leggere `_start_network`.

**Come correggerlo.** Estrarre, un pezzo alla volta e con i test verdi a ogni passo:

| Nuovo modulo | Contenuto | Righe tolte |
|---|---|---|
| `wilab/network/subnet_allocator.py` | `_get_subnet`, `_assigned_subnets`, `_subnet_lock` | ~40 |
| `wilab/wifi/txpower.py` | tutti i metodi `*tx_power*` e `_compute_level_dbm` | ~160 |
| `wilab/wifi/clients.py` | `list_clients`, `_leases`, `_client_mac` | ~90 |
| `wilab/wifi/startup.py` | `start_once(device, request)` (un tentativo) e `RetryPolicy` | ~150 |

`RetryPolicy` è il pezzo che conta: la usano sia la route di creazione sia il watchdog, e questo elimina
per costruzione HAP-3 e WD-2.

```python
@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    delay: float = 1.0
    budget: float = 20.0
    min_attempt_time: float = 4.0

    def run(self, start_once: Callable[[], NetworkStatus], rollback: Callable[[], None]) -> NetworkStatus:
        ...
```

---

<a id="arch-4"></a>
### 78. ARCH-4 - Il registro dei dispositivi esiste in quattro copie

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/config.py:26-39](wilab/config.py#L26-L39), [wilab/reservation.py:83-87](wilab/reservation.py#L83-L87), [wilab/wifi/watchdog.py:23](wilab/wifi/watchdog.py#L23), [wilab/wifi/manager.py:81](wilab/wifi/manager.py#L81), [wilab/api/dependencies.py:66-89](wilab/api/dependencies.py#L66-L89)

**Problema.** `config.networks`, `ReservationManager._device_ids`, `NetworkWatchdog._watched`,
`NetworkManager._device_locks`. Vengono tenuti allineati da `scan_devices`. `AppConfig`, un oggetto di
configurazione validato, viene modificato a runtime per contenere i dispositivi scoperti e la loro
porta USB. Nessuna delle quattro copie sa togliere un dispositivo: è la radice di WD-5.

**Come si riproduce.** Cercare nel codice `config.networks`: 26 punti leggono la lista dei dispositivi
dalla configurazione.

**Come correggerlo.** Un registro unico con lo stato per dispositivo.

```python
# wilab/devices.py
class DeviceState(Enum):
    FREE = "free"
    RESERVED = "reserved"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"

@dataclass
class Device:
    interface: str
    display_name: str
    usb_port: str | None
    lock: RLock = field(default_factory=threading.RLock)
    state: DeviceState = DeviceState.FREE
    missing_scans: int = 0

class DeviceRegistry:
    def add(self, device: Device) -> None: ...
    def retire(self, interface: str) -> None: ...      # only when FREE or UNAVAILABLE, with no resources
    def get(self, interface: str) -> Device: ...
    def all(self) -> list[Device]: ...
```

`AppConfig.networks` torna a contenere solo le etichette lette dal file. Reservation, watchdog e
manager ricevono il registro e non tengono copie. È un refactoring ampio: conviene farlo prima di
WD-5 punto 3 e dopo aver messo in sicurezza i punti 1-14.

---

<a id="arch-3"></a>
### 79. ARCH-3 - Il modello dell'API è anche lo stato interno

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:374-394](wilab/wifi/manager.py#L374-L394), [wilab/wifi/manager.py:516-565](wilab/wifi/manager.py#L516-L565)

**Problema.** `NetworkStatus`, il modello di risposta, è conservato in `manager.active`, modificato a
ogni lettura, e porta un attributo nascosto impostato con `object.__setattr__` e letto con `hasattr`
(`_expires_at_timestamp`). È la ragione per cui lo stato riportato è "ciò che Wi-Lab ricorda" e non
"ciò che il sistema fa" (vedi il capitolo 5, schema 4).

**Come si riproduce.** Cercare `_expires_at_timestamp`: dieci punti con `hasattr` o `getattr`.

**Come correggerlo.** Una dataclass interna e una funzione che costruisce la risposta.

```python
# wilab/wifi/manager.py
@dataclass
class ActiveNetwork:
    interface: str
    request: NetworkCreateRequest
    subnet: str
    internet_enabled: bool
    deadline: float | None            # monotonic, see STAB-5
    captive_portal_url: str | None = None
    tx_power_level: int = 4

    def to_status(self, *, clients: list[ClientInfo], dhcp: dict | None) -> NetworkStatus: ...
```

`self.active: dict[str, ActiveNetwork]`. Il watchdog non deve più ricostruire la richiesta campo per
campo (`_restore_ap` oggi lo fa a mano e rifiuta di ripartire se un campo manca): usa `network.request`.

---

<a id="arch-5"></a>
### 80. ARCH-5 - Singleton collegati per effetto collaterale

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/dependencies.py:20-56](wilab/api/dependencies.py#L20-L56), [wilab/wifi/manager.py:86-91](wilab/wifi/manager.py#L86-L91)

**Problema.** I manager sono variabili globali di modulo create al primo uso.
`get_reservation_manager` collega anche il callback delle scadenze e avvia il watchdog: l'ordine di
avvio dipende da quale richiesta o thread arriva per primo. `NetworkManager.__init__` avvia un thread.
Le funzioni con default `Depends(...)` vengono anche chiamate direttamente.

**Come si riproduce.** Leggere `lifespan`: chiama `get_manager` ma non `get_reservation_manager`; il
watchdog parte quando la discovery fa la prima scansione.

**Come correggerlo.** Un oggetto di contesto costruito in `lifespan`, con avvio e arresto espliciti.

```python
# wilab/api/context.py
@dataclass
class AppContext:
    config: AppConfig
    channels: ChannelManager
    qos: QosManager
    qos_profiles: QosProfileManager
    manager: NetworkManager
    reservations: ReservationManager

    def start(self) -> None: ...       # cleanup, expiry loop, watchdog, discovery: fixed order
    def stop(self) -> None: ...        # reverse order
```

`app.state.context = AppContext.build(config)`; le dipendenze FastAPI diventano
`def get_manager(request: Request) -> NetworkManager: return request.app.state.context.manager`.
I costruttori non avviano thread. I test costruiscono un contesto invece di azzerare sei globali.

---

<a id="arch-6"></a>
### 81. ARCH-6 - Tre modi di gestire un processo figlio

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:49-157](wilab/network/commands.py#L49-L157), [wilab/network/dhcp.py](wilab/network/dhcp.py)

**Problema.** hostapd è un figlio in primo piano posseduto direttamente; dnsmasq è un demone seguito
tramite file PID e `/proc`; i comandi singoli usano `subprocess.run`. Il modo di hostapd è quello
robusto. Quello di dnsmasq richiede file PID, `_owns_process`, `stop_process` e produce NET-6.

**Come si riproduce.** Confrontare `HostapdManager.stop` con `DhcpServer.stop`.

**Come correggerlo.** dnsmasq in primo piano.

```python
# wilab/network/dhcp.py, in start()
process = start_foreground(["dnsmasq", "--keep-in-foreground", f"--conf-file={config_file}"])
instance["process"] = process
time.sleep(0.2)                                   # a configuration or bind error exits at once
if process.poll() is not None:
    raise DhcpServerError(f"dnsmasq exited with code {process.poll()}")
```

`stop()` chiama `process.stop()`; `is_running()` è `process.poll() is None`. Si possono cancellare
`DNSMASQ_PID_DIR`, `_owns_process`, `stop_process` e il controllo "Existing dnsmasq PID file". Per
conoscere il motivo di un'uscita, passare un `classify_output` e usare `output_tail` (HAP-8).

---

<a id="arch-7"></a>
### 82. ARCH-7 - Tre implementazioni di "rilascia da NetworkManager"

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:94-109](wilab/wifi/manager.py#L94-L109), [wilab/wifi/recovery.py:45-56](wilab/wifi/recovery.py#L45-L56), [wilab/network/unmanaged.py:61-81](wilab/network/unmanaged.py#L61-L81)

**Problema.** Lo stesso `nmcli device set <if> managed no` è scritto tre volte, con gestione degli
errori diversa: una controlla `nmcli --version` e fa anche `disconnect` con una pausa, una ignora
l'errore a livello debug, una usa `check=False`.

**Come si riproduce.** Cercare `"managed", "no"` nel codice.

**Come correggerlo.** Una funzione in `unmanaged.py`, usata dagli altri due moduli.

```python
# wilab/network/unmanaged.py
def release_from_networkmanager(interface: str) -> None:
    """Ask NetworkManager to leave this interface alone; silent when nmcli is missing."""
    if shutil.which("nmcli") is None:
        return
    execute_command(["nmcli", "device", "set", interface, "managed", "no"], check=False)
    execute_command(["nmcli", "device", "disconnect", interface], check=False)
```

Togliere `_configure_networkmanager_unmanaged` da `manager.py` e le righe equivalenti da `_quiesce`.
La pausa di 0,2 s va tolta o giustificata con una misura.

---

<a id="arch-10"></a>
### 83. ARCH-10 - Il logging non ha una regola

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** tutto `wilab/`

**Problema.** f-string e `%s` mescolati; condizioni attese a livello `ERROR` (NET-5); guasti veri a
`DEBUG` (WD-9); un messaggio ripetuto ogni 5 s (WD-6); una riga falsa (NET-4). Per un servizio la cui
salute si legge dal journal, il segnale è invertito in più punti.

**Come si riproduce.** `journalctl -u wi-lab -p err --since today` su una macchina che funziona bene:
ci sono righe.

**Come correggerlo.** Tre regole, scritte in `docs/readme-dev.md` e fatte rispettare da un test:

1. `ERROR` significa che qualcuno deve intervenire. Un comando di verifica che risponde "no" non è un
   errore.
2. Nessun messaggio si ripete più di una volta al minuto per la stessa causa.
3. Sempre `logger.x("... %s", valore)`, mai f-string (la regola ruff `G004` lo controlla).

Test T-13: un ciclo completo crea/cancella su hardware simulato non deve produrre record `ERROR`.

---

<a id="arch-9"></a>
### 84. ARCH-9 - Codice morto

**Gravità:** Bassa · **Confidenza:** Confermato (ogni nome è stato cercato in `wilab/`) · **File:** vari

**Problema.** Funzioni e modelli senza chiamanti nel codice di produzione:

| Elemento | File | Nota |
|---|---|---|
| `NatManager.flush_all_rules` | `network/nat.py` | Svuoterebbe tutta la tabella NAT dell'host, Docker compreso. Non deve esistere nemmeno inutilizzata. |
| `NatManager.disable_ip_forwarding` | `network/nat.py` | |
| `IsolationManager.flush_all`, `get_active_subnets` | `network/isolation.py` | |
| `execute_pkill` | `network/commands.py` | |
| `HostapdManager.stop_all`, `DhcpServer.stop_all` | `wifi/hostapd.py`, `network/dhcp.py` | |
| `NetworkManager.get_summary` | `wifi/manager.py` | "Backward-compatible", contro la regola del progetto |
| `validate_interface` | `wifi/interface.py` | |
| `QosRequest`, `QosStatus`, `InterfaceStatus` | `models.py` | Endpoint inesistenti |
| Percorsi commentati | `api/__init__.py` (`_candidate_frontend_paths`) | |
| `"pid_file": None` | `wifi/hostapd.py` (`status`) | Campo residuo |

`safety.py` parla ancora di rete host di Docker e dice all'operatore di "eseguire lo script di cleanup"
per regole che l'avvio ormai rimuove da solo.

**Come si riproduce.** `grep -rn "<nome>" wilab/` per ogni elemento.

**Come correggerlo.** Cancellare gli elementi e i test che li esercitano (i test di codice morto
gonfiano la copertura senza proteggere nulla). In `safety.py` tenere solo `log_host_impact_warning`,
con il testo aggiornato.

---

<a id="arch-8"></a>
### 85. ARCH-8 - Attributi privati usati tra classi

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:158](wilab/wifi/manager.py#L158), [wilab/wifi/manager.py:525](wilab/wifi/manager.py#L525)

**Problema.** `NetworkManager.release_device` legge `self.hostapd_manager._instances`; lo stato usa
`st._expires_at_timestamp`. Un cambio interno a `HostapdManager` rompe il manager senza che i tipi lo
segnalino.

**Come si riproduce.** Cercare `\._[a-z]` su oggetti che non sono `self`.

**Come correggerlo.**

```diff
--- a/wilab/wifi/hostapd.py
+++ b/wilab/wifi/hostapd.py
+    def is_tracked(self, net_id: str) -> bool:
+        """True while resources of this network still need a stop()."""
+        return net_id in self._instances
```

e in `manager.py`: `self.hostapd_manager.is_tracked(device_id)`. Lo stesso per `DhcpServer`
(`list_active` esiste già). `_expires_at_timestamp` sparisce con ARCH-3.

---

<a id="arch-12"></a>
### 86. ARCH-12 - Cartelle senza `__init__.py` ✅

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** `wilab/wifi/`, `wilab/data/`

**Problema.** `wilab/wifi/` non contiene `__init__.py`, a differenza di `wilab/network/` e
`wilab/api/`. Funziona perché Python lo tratta come "namespace package", ma è un'incoerenza: alcuni
strumenti (mypy senza opzioni dedicate, strumenti di packaging, scoperta dei moduli) trattano i due
tipi in modo diverso, e un secondo `wilab/wifi` sul percorso di ricerca verrebbe fuso con questo senza
errori.

**Come si riproduce.** `ls wilab/wifi/__init__.py`.

**Come correggerlo.** Creare `wilab/wifi/__init__.py` vuoto. `wilab/data/` contiene solo dati e può
restare senza.

---

<a id="arch-11"></a>
### 87. ARCH-11 - Il layout di questo branch diverge dall'altro

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** radice del repository

**Problema.** In questo branch `mypy.ini`, `pytest.ini`, `run-tests.sh` e `update_version.sh` sono
nella radice. Le regole caricate all'inizio della sessione (dal branch `feature/device-capabilities`)
dicono che non devono esserci: la configurazione degli strumenti va in `pyproject.toml` e gli script in
`scripts/`. I due branch sono divergenti a partire da `main` (`67508ca`) ed entrambi rielaborano
reservation e configurazione. In questo branch non esistono `CLAUDE.md` né `required_capabilities`.

**Come si riproduce.** `git log --oneline feature/device-capabilities..fix/reservation-lifecycle`.

**Come correggerlo.** Non è un difetto del codice: è un rischio di integrazione. Prima di applicare le
correzioni di questo documento conviene decidere quale branch è la base e fare il merge, altrimenti
ogni patch su `reservation.py`, `config.py` e `models.py` andrà rifatta. Nota: questo documento è
scritto in italiano su richiesta esplicita, in deroga alla regola "tutto in inglese" dell'altro branch.

---

<a id="cap-5"></a>
## 5. Correlazioni tra i punti

Letti uno accanto all'altro, gli 87 punti non sono 87 difetti indipendenti. La maggior parte è
un'istanza di sette schemi. Correggere lo schema elimina le istanze e previene la prossima.

### Schema 1 - "Una volta, poi mai più"

WD-1 e WD-3 (un riavvio per vita), WD-2 (un tentativo, poi silenzio), WD-4 (quarantena senza uscita),
WD-5 (un dispositivo non viene mai ritirato), WD-9 (un ciclo che muore resta morto), BUG-4 (cache
riempita una volta), STAB-6 (upstream risolto una volta), BUG-5 (un adattatore rifiutato una volta lo
è per sempre).

Causa comune: il servizio è scritto come una sequenza di eventi ("è fallito questo, quindi fai quello")
e non ha un confronto periodico tra ciò che dovrebbe esistere e ciò che esiste. Ogni stato raggiunto da
un evento ha bisogno di un altro evento per uscirne, e per questi stati quell'evento non è stato
scritto. Un servizio che deve girare per mesi ha bisogno, per il lavoro di background, del disegno
opposto: un ciclo che ogni N secondi, per ogni dispositivo, confronta lo stato voluto (riservato o no,
parametri della rete) con quello osservato e fa il passo più piccolo per avvicinarli, con un ritardo
crescente. In quel disegno la quarantena è solo "l'ultimo passo è fallito, riprova più tardi".

### Schema 2 - Un errore transitorio diventa uno stato permanente

- NET-1 (collisione di lock, millisecondi) → cleanup fallito → `cleanup_failed` → WD-4 (permanente).
- HAP-1 (confronto dell'SSID) → tre "guasti radio" → quarantena → reset USB di un adattatore sano.
- HAP-4 (tentativo tagliato dal budget) → contato come guasto radio → più vicino alla quarantena.
- HAP-2 (gara di millisecondi) → decide tra il "500 generico" di HAP-3 e la quarantena.
- WD-10 (tre probe lenti) → riavvio → consuma l'unico riavvio di WD-1 → la volta dopo, quarantena.
- NET-6 (lancio di dnsmasq lento una volta) → cleanup impossibile → quarantena → dieci recovery falliti.

La quarantena è il punto in cui finisce ogni classificazione sbagliata, ed è l'unico stato senza
uscita. Per questo una classificazione unica e un'uscita dalla quarantena valgono più della correzione
dei singoli inneschi: trasformano ognuna di queste catene da "adattatore perso fino al riavvio" in
"adattatore non disponibile per qualche minuto".

### Schema 3 - Il rimedio è un riavvio, e il riavvio costa caro

WD-4, WD-5, WD-9, BUG-4, STAB-6 e l'adattatore "pending" di BUG-5 si risolvono riavviando il servizio.
Un riavvio cancella tutte le reservation e le reti, e STAB-4 dice che l'avvio successivo non pulisce
del tutto ciò che il precedente ha lasciato. Il rimedio documentato per un problema su un
adattatore è quindi un'interruzione per tutti gli altri, seguita da un avvio che può ereditare regole
`tc` o un file PID vecchio.

### Schema 4 - L'API riporta ciò che Wi-Lab ricorda, non ciò che il sistema fa

NET-2 (`internet_enabled: true` senza NAT), STAB-6 (lo stesso, dopo un cambio di route), BUG-2
(controlli di salute che cercano testo), WD-8 (QoS sparito, non riportato), STAB-4 (netem presente,
riportato inattivo), BUG-7 (TX power), WD-5 (una rete contata come attiva su un'interfaccia che non
c'è), WD-2 (una rete morta senza stato), STAB-2 (dnsmasq "non attivo" perché manca un file).

In entrambe le direzioni: "ok" quando è rotto, "degraded" quando funziona. Per l'obiettivo "le reti
devono funzionare davvero" questo schema conta quanto i crash: un sistema di controllo può riavviare
solo ciò che vede rotto. È legato ad ARCH-3 (il modello dell'API è lo stato interno) e a WD-7 (il
watchdog controlla due processi, non la rete).

### Schema 5 - Ogni logica che esiste due volte è già divergente

| Logica duplicata | Copie | Divergenza trovata |
|---|---|---|
| Politica di avvio e retry | richiesta di creazione, watchdog | 3 tentativi contro 1 (WD-2) |
| Classificazione dei guasti | tipo di eccezione, espressione `radio=` | HAP-3 |
| Regole di configurazione | `AppConfig`, `validate_config_file` | BUG-3 |
| Regole dei profili QoS | schema JSON, modello pydantic | BUG-9 |
| Cache dei canali | route, `NetworkManager` | BUG-4 |
| Controllo "supporta AP" | discovery, `interface.py` | BUG-6 |
| Controlli di salute | `/status`, `/debug` | hostapd solo in uno (BUG-2, API-1) |
| Rilascio da NetworkManager | tre moduli | gestione degli errori diversa (ARCH-7) |
| Esempi dell'API | modelli, correzioni a mano | API-9 |
| Elenco dei dispositivi | quattro registri | ARCH-4, radice di WD-5 |

È la ragione pratica dei punti ARCH: il refactoring non è estetico, ogni duplicazione elencata ha già
prodotto uno dei difetti sopra.

### Schema 6 - Decisioni prese confrontando testo

HAP-1 (`ssid[0] ==`), BUG-2 (`"UP" in`, `"MASQUERADE" in`), BUG-6 (`"AP" in`), NET-3
(`startswith("192.168.")`), ARCH-2 (`"already active" in` il messaggio di errore), e il classificatore
dell'output di hostapd. Ognuno funzionava sull'esempio per cui è stato scritto. `ip -j` produce già
JSON ed è usato nei moduli più recenti (`subnet.py`, `recovery.py`); quelli più vecchi leggono ancora
frasi. Il classificatore dell'output di hostapd è l'unico punto in cui il testo è inevitabile, ed è
anche il meglio scritto del gruppo (prefissi ancorati, elenco chiuso).

### Schema 7 - Lavoro lento sotto lock e attese senza limite

STAB-1 (un `wait()` senza timeout), RACE-1 (richieste in attesa del lock del dispositivo), PERF-6 e
BUG-7 (una pausa di 3 s sotto lock), NET-13 (un join di 5 s che fa fallire lo stop), STAB-8 (arresto
più lungo del limite di systemd), HAP-9 (75 s di attesa per un evento da 600 s). L'ordine dei lock è
corretto e non c'è deadlock; la debolezza è che tutto funziona solo finché ogni comando esterno
ritorna. Uno che non ritorna si prende un lock, poi i thread che lo aspettano, poi l'API. Tre regole
coprono tutto il gruppo: nessuna attesa senza timeout, nessuna acquisizione di lock senza timeout nel
percorso delle richieste, e un battito che un osservatore esterno (systemd) possa veder mancare.

### Due catene da nominare

**Da un client Wi-Fi alla configurazione di un processo root.**
SEC-3 (l'API ascolta sulle subnet degli AP) → SEC-1 (lettura di `config.yaml` senza autenticazione) →
il token → SEC-2 (`/debug` elenca tutte le reservation) e BUG-1 (iniezione di righe in
`hostapd.conf`). Ogni anello è piccolo. Insieme significano che un dispositivo collegato a una
qualunque rete di test può prendere il controllo del servizio. Chiudere SEC-1 spezza la catena nel
punto più economico; SEC-3 toglie l'ingresso.

**Da un'interrogazione di stato a un adattatore perso.**
Il frontend interroga `/status` → `iptables -S` senza il lock del firewall → collisione con la
rimozione di una regola durante lo stop di una rete (NET-1) → lo stop fallisce → nel percorso di
creazione o del watchdog è `cleanup_failed` → quarantena senza recovery (WD-4) → l'adattatore è perso
fino a un riavvio → il riavvio spegne le reti di tutti. Cinque punti, ciascuno minore se
preso da solo, formano il modo più plausibile in cui un'installazione sana perde un adattatore senza
alcun guasto hardware. Aggiungere `-w` in una funzione la spezza.

---

<a id="cap-6"></a>
## 6. API: modifiche non breaking e breaking

Superficie attuale (tutto sotto `/api/v1`):

| Metodo e percorso | Scopo |
|---|---|
| `POST /device-reservation` | Riserva un adattatore |
| `GET /device-reservation/{id}` | Legge una reservation |
| `DELETE /device-reservation/{id}` | Rilascia |
| `DELETE /device-reservation/all` | Rilascia tutto (operatore) |
| `GET /status`, `GET /debug` | Salute e diagnostica |
| `POST`, `GET`, `DELETE /interface/{id}/network` | Ciclo di vita della rete |
| `GET /interface/{id}/network/available-channels` | Canali dell'adattatore |
| `POST /interface/{id}/internet/enable`, `.../disable` | Interruttore di Internet |
| `GET`, `POST /interface/{id}/txpower` | TX power |
| `GET /qos/profiles` | Catalogo dei profili (senza autenticazione) |
| `POST`, `GET`, `DELETE /interface/{id}/qos/profile` | Profilo QoS di una rete |

### 6.1 Modifiche che non rompono i client

In ordine di priorità.

| Id | Modifica | Schede |
|---|---|---|
| N1 | Chiudere la lettura di file e aggiungere la validazione mancante (una richiesta che finiva in `500` ora finisce in `422`). | SEC-1, BUG-1, NET-11 |
| N2 | Nuovo valore di `runtime_state` (`restore_failed`) quando il watchdog sta ancora provando. Il campo è già una stringa aperta. | WD-2 |
| N3 | `GET /api/v1/health` senza autenticazione: processo vivo, cicli vivi, comandi bloccati. Serve al monitoraggio e al watchdog di systemd. | STAB-1, WD-9 |
| N4 | In `/status`: aggiungere hostapd e lo stato dei thread, calcolare correttamente NAT e upstream. Campi aggiunti, nessuno tolto. | BUG-2 |
| N5 | Risposta `503` con codice `1006` e `Retry-After` quando il dispositivo è occupato, invece di un'attesa senza limite. | RACE-1 |
| N6 | `POST .../network` e gli endpoint di Internet restituiscono anche lo stato della rete, accanto a `detail`. | API-5 |
| N7 | Aggiungere `PUT .../internet` con `{"enabled": true}` e `PUT .../txpower`, lasciando i vecchi endpoint. | API-7 |
| N8 | `tx_power_level` facoltativo nella creazione, default 4. Il supporto hardware è "non garantito", un campo obbligatorio è incoerente. | HAP-6 |
| N9 | Endpoint per l'operatore che riprova un adattatore in quarantena, dietro la password di conferma. | WD-4 |
| N10 | `PATCH /device-reservation/{id}` per prolungare una reservation. Oggi l'unico modo è rilasciare e perdere la rete. | - |
| N11 | Generare gli esempi dai modelli e togliere le correzioni a mano. Lo schema cambia solo dove era sbagliato. | API-9 |
| N12 | `404` invece di `200 null` per i percorsi `/api/...` e `/docs/...` sconosciuti. | SEC-1 |
| N13 | `GET /device-reservation` (elenco) dietro la password di conferma, al posto degli ID in `/debug`. | SEC-2 |

### 6.2 Modifiche che rompono i client

Da raggruppare in una sola versione, visto che la 4.0.0 cambia già il formato degli errori.

| Id | Modifica | Schede |
|---|---|---|
| B1 | Rinominare `/interface/{reservation_id}/...` in `/reservations/{id}/...` e `device-reservation` in `reservations`. | API-6 |
| B2 | Un solo codice per "rete non attiva" (`409`) anche su Internet e TX power. | API-2 |
| B3 | Un codice di dominio per ogni `409`; nessun `409` generico. | API-3 |
| B4 | `500 / 1003` diventa `503` con lo stesso codice. | API-4 |
| B5 | Togliere il retry lato client (`409 / 1001`): il server ritenta da solo e risponde una volta. | API-11 |
| B6 | Togliere `POST /internet/enable|disable` e `POST /txpower` dopo N7. | API-7 |
| B7 | Oggetto `dhcp` tipizzato senza percorsi di file e senza `process_stopped`; togliere `clients_connected`; un solo nome per il tempo residuo. | API-1, API-8 |
| B8 | `extra="forbid"` su tutti i corpi delle richieste. | API-10 |
| B9 | Le risposte di successo restituiscono la risorsa, non `{"detail": "..."}`; `DELETE` risponde `204`. | API-5 |
| B10 | Togliere gli ID di reservation da `/debug`. | SEC-2 |
| B11 | Togliere `encryption: "wpa"` (è WPA2). | HAP-10 |
| B12 | `dns_server` obbligatorio in `config.yaml` (rompe le configurazioni, non i client). | NET-8 |

---

<a id="cap-7"></a>
## 7. Test da aggiungere

La suite attuale (23 file) copre bene i casi felici e i guasti del percorso di creazione. Non copre:
il comportamento **nel tempo** (secondo guasto, guasti ripetuti, ore di attività), la validazione degli
ingressi, e il confronto tra ciò che l'API dichiara e ciò che è stato installato. I test proposti sono
ordinati per priorità e seguono le regole del progetto: nessun hardware reale, indipendenti dal sistema
operativo, tutti i comandi sostituiti.

### 7.1 Tre strumenti di prova da costruire prima

Molti dei test sotto diventano semplici con tre aiuti condivisi, da mettere in `tests/helpers.py` o in
`tests/conftest.py`.

**Orologio finto.** Tutti i punti legati al tempo (WD-1, WD-3, WD-6, STAB-5) richiedono di far
"passare" ore in millisecondi.

```python
class FakeClock:
    """Replaces time.monotonic, time.time and time.sleep in the modules under test."""

    def __init__(self) -> None:
        self.monotonic_now = 1000.0
        self.wall_now = 1_800_000_000.0

    def monotonic(self) -> float:
        return self.monotonic_now

    def time(self) -> float:
        return self.wall_now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.monotonic_now += seconds
        self.wall_now += seconds

    def jump_wall_clock(self, seconds: float) -> None:
        self.wall_now += seconds          # an NTP step: only the wall clock moves
```

Per usarlo, i moduli devono chiamare `time.monotonic()` tramite il modulo `time` (lo fanno già), così
`monkeypatch.setattr(watchdog.time, "monotonic", clock.monotonic)` funziona.

**Un giro di watchdog chiamabile.** Oggi `_watch` è un ciclo infinito con le variabili di stato locali:
non si può provare un singolo giro. Estrarre il corpo in un metodo `tick(state)` con lo stato in una
piccola dataclass per dispositivo. È un refactoring puro e rende provabili WD-1, WD-2, WD-3 e WD-10
senza thread e senza attese.

**Registratore di comandi.** Una sostituzione di `execute_command` che registra ogni lista di argomenti
e risponde da una tabella, con la possibilità di far fallire il comando N-esimo. Esiste già in forma
sparsa in `conftest.py`; va reso un oggetto riusabile:

```python
class CommandRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.failures: dict[tuple[str, ...], Exception] = {}     # command prefix -> error to raise
        self.outputs: dict[tuple[str, ...], str] = {}

    def __call__(self, cmd: list[str], **kwargs: object) -> str:
        self.calls.append(list(cmd))
        for prefix, error in self.failures.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                raise error
        for prefix, output in self.outputs.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                return output
        return ""
```

### 7.2 Test automatici

| Id | Cosa verifica | Schede | File proposto |
|---|---|---|---|
| T-01 | La route del frontend non esce dalla propria cartella | SEC-1 | `tests/test_frontend_static.py` |
| T-02 | Regole di validazione della richiesta di creazione | BUG-1 | `tests/test_models.py` |
| T-03 | Readiness con SSID non ASCII | HAP-1 | `tests/test_wifi.py` |
| T-04 | Classificazione uguale in ogni tentativo e in ogni percorso | HAP-2, HAP-3 | `tests/test_wifi.py` |
| T-05 | Secondo guasto dopo un'ora: la rete riparte | WD-1 | `tests/test_watchdog.py` |
| T-06 | Riavvio fallito: il watchdog riprova e lo stato è visibile | WD-2 | `tests/test_watchdog.py` |
| T-07 | Seconda morte di dnsmasq: la rete viene riparata | WD-3 | `tests/test_watchdog.py` |
| T-08 | Un dispositivo in quarantena torna disponibile | WD-4 | `tests/test_network_creation_recovery.py` |
| T-09 | Lo stop riesce quando l'interfaccia non esiste più | WD-5 | `tests/test_wifi.py` |
| T-10 | Ogni chiamata a `iptables` contiene `-w` | NET-1 | `tests/test_nat.py` |
| T-11 | Un guasto del NAT fa fallire la creazione | NET-2 | `tests/test_wifi.py` |
| T-12 | Un comando che non muore non blocca il chiamante | STAB-1 | `tests/test_commands.py` |
| T-13 | Nessun record `ERROR` in un ciclo crea/cancella | NET-5, ARCH-10 | `tests/test_logging.py` |
| T-14 | I cicli di background sopravvivono a ogni eccezione | WD-9 | `tests/test_startup.py` |
| T-15 | Validazione offline e avvio danno lo stesso verdetto | BUG-3 | `tests/test_config_validation.py` |
| T-16 | Gli esempi OpenAPI rispettano i modelli | API-9 | `tests/test_api.py` |
| T-17 | I controlli di `/status` | BUG-2 | `tests/test_api.py` |
| T-18 | Un salto dell'orologio non fa scadere le reservation | STAB-5 | `tests/test_reservation.py` |
| T-19 | Catalogo QoS con profili sbagliati e QoS inline | BUG-9, NET-11 | `tests/test_qos_profile.py` |
| T-20 | Simulazione di lunga durata con guasti casuali | schemi 1 e 2 | `tests/test_soak.py` |
| T-21 | Nessuna crescita di strutture dopo molti cicli | PERF-7 | `tests/test_soak.py` |
| T-22 | Dispositivo occupato: risposta rapida, API non bloccata | RACE-1 | `tests/test_reservation.py` |
| T-23 | La cache dei canali viene riletta prima di rifiutare | BUG-4 | `tests/test_channels.py` |

**T-01 - Route del frontend.** Creare una cartella temporanea `root/app/` con `index.html` e un file
`root/secret.txt` fuori da essa; sostituire `_candidate_frontend_paths` perché restituisca
`root/app`; costruire l'app. Chiamare direttamente la funzione della route (non il client HTTP, che
normalizza i percorsi) con tre valori di `full_path`: `"../secret.txt"`, il percorso assoluto di
`secret.txt`, e `"/" + percorso assoluto`. In tutti i casi la risposta non deve essere il file
segreto. Un quarto caso con `"index.html"` deve restituirlo. Per ottenere la funzione: cercare tra
`app.routes` quella con `path == "/{full_path:path}"` e usare `.endpoint`.

**T-02 - Validazione della creazione.** Test parametrizzato su coppie (corpo, esito atteso): password
di 7 e di 64 caratteri con `wpa2` (errore), password assente con `wpa2` (errore), password corta con
`open` (accettata), SSID vuoto, SSID di 33 byte, SSID di 32 byte con caratteri accentati (accettato),
SSID con `\n`, canale 99 a 5 GHz, canale 6 a 5 GHz. Un secondo test passa per l'API e verifica lo
stato `422` e che `hostapd_manager.start` non sia stato chiamato. Un terzo test chiama
`_generate_config` con un SSID che contiene un newline e si aspetta `HostapdError`.

**T-03 - Readiness con SSID non ASCII.** Come descritto nella scheda HAP-1: `hostapd_cli` finto che
restituisce `ssid[0]=Caff\xc3\xa8` (testo letterale con i backslash). `_wait_until_ready` deve
ritornare senza eccezioni; `is_enabled` deve restituire `True`.

**T-04 - Classificazione.** Tabella di casi: (eccezione sollevata da `hostapd_manager.start`,
`allow_internal_retry`, tentativo) → (`StartupFailure.radio` atteso). Le righe con
`HostapdInitFailure` devono dare `radio=True` in tutti i casi. Un test sull'API verifica che la seconda
richiesta dopo un `409 / 1001` risponda ancora `409 / 1001` e non `500`.

**T-05 - Budget del watchdog.** Con `FakeClock` e `tick`: rete attiva; hostapd muore; `tick` la
ripristina; avanzare l'orologio di 2 ore; hostapd muore; `tick` la ripristina di nuovo; il dispositivo
non è in `recovery_snapshot()`. Secondo caso: quattro morti in dieci minuti → alla quarta il
dispositivo va in quarantena.

**T-06 - Riavvio fallito.** hostapd muore; il riavvio fallisce con un guasto non radio. Verificare:
`watchdog.state(reservation) == "restore_failed"`; dopo aver avanzato l'orologio del primo ritardo,
`tick` richiama `start_network`; se questa volta riesce, lo stato torna `None` e la rete è in
`manager.active`. Caso aggiuntivo: la reservation viene rilasciata mentre la rete è "pending" → il
watchdog smette di provare.

**T-07 - DHCP.** dnsmasq muore due volte a distanza di un minuto: alla seconda il watchdog non resta in
`dhcp_failed` ma riavvia la rete intera; alla fine `dhcp_server.is_running` è vero.

**T-08 - Uscita dalla quarantena.** Mettere un dispositivo in quarantena con `recovering=False`;
chiamare `reprobe_unavailable` con il probe che fallisce (resta bloccato) e poi con il probe che
riesce (torna allocabile: `ReservationManager.create` lo assegna).

**T-09 - Interfaccia sparita.** `interface_present` restituisce `False`: `HostapdManager.stop` non
esegue i tre comandi sull'interfaccia, rimuove l'istanza e non solleva; `release_device` completa e il
dispositivo non è più in `manager.active`.

**T-10 - `iptables -w`.** Con `CommandRecorder`: ciclo completo (creazione con Internet e captive
portal, disattivazione di Internet, stop, `remove_stale_rules`, `/status`). Per ogni comando registrato
il cui primo elemento è `iptables`: `cmd[1] == "-w"`. Questo test impedisce che una nuova chiamata
dimentichi l'opzione.

**T-11 - NAT fallito.** `enable_nat` solleva: la creazione risponde `500`, la rete non è in
`manager.active`, hostapd e dnsmasq sono stati fermati, e nessuna regola di isolamento resta
registrata.

**T-12 - Comando bloccato.** `subprocess.Popen` sostituito da un oggetto il cui `communicate` solleva
sempre `TimeoutExpired`. `execute_command` deve sollevare `CommandStuck` in meno di
`timeout + KILL_GRACE + 1` secondi (misurato con un timeout di test breve) e `stuck_commands()` deve
valere 1.

**T-13 - Log puliti.** Con `caplog` a livello `ERROR`: creazione con Internet, lettura dello stato,
cambio di Internet, stop. `caplog.records` deve essere vuoto. È il test che fa rispettare la regola
"`ERROR` significa intervento".

**T-14 - Cicli di background.** Per ognuno dei tre cicli: far sollevare `TypeError` alla prima
iterazione e verificare che la seconda venga eseguita. Per la discovery: scrivere nel file di
configurazione una lista YAML e verificare che `scan_new_networks` sollevi `ValueError`, non
`AttributeError`.

**T-15 - Parità di configurazione.** Test parametrizzato su una decina di file: valido, `dns_server`
non valido, porta fuori intervallo, `max_timeout < min_timeout`, token vuoto, `networks` non lista,
livello principale non mappa. Per ognuno: `validate_config_file` segnala errori **se e solo se**
`load_config` termina con `SystemExit`.

**T-16 - Esempi OpenAPI.** Per ogni operazione dello schema con un `response_model`: prendere ogni
esempio della risposta `200` e validarlo con `Model.model_validate`. Per i corpi di richiesta: ogni
esempio deve essere accettato dal modello della richiesta. Fallisce oggi sugli esempi con `device_id`.

**T-17 - Controlli di stato.** Quattro casi: rete senza Internet su host senza regole NAT (stato non
`degraded`); rete con Internet e regola `wilab-nat-<id>` assente (`degraded`, `missing` contiene il
dispositivo); upstream con `operstate` `DOWN` e flag `UP` (`up: false`); hostapd morto
(`checks.hostapd.running: false`).

**T-18 - Salto dell'orologio.** Reservation di un'ora; `clock.jump_wall_clock(7200)`: `is_expired`
resta falso e `expires_in` resta circa 3600. Poi `clock.advance(3601)`: scade.

**T-19 - QoS.** Catalogo con un file che contiene un profilo valido e uno con `"advanced": {}`: il
manager parte, il profilo valido c'è. Schema illeggibile: il manager parte con catalogo vuoto. Inline
con `download_quality` diverso da `upload_quality`: `422`.

**T-20 - Simulazione di lunga durata.** È il test che manca di più. Con `FakeClock`, `tick` e hostapd,
dnsmasq e comandi simulati: un pool di quattro dispositivi con reti attive e reservation illimitate;
per 10.000 passi (ogni passo 5 s simulati, circa 14 ore) un generatore pseudo-casuale con seme fisso
inietta guasti: morte di hostapd, morte di dnsmasq, comando `iptables` che fallisce una volta,
`hostapd_cli` che va in timeout, avvio che fallisce con ognuna delle classi di eccezione. Alla fine,
dopo 30 minuti simulati senza guasti, devono valere le invarianti:

- ogni reservation ancora valida ha la sua rete attiva;
- nessun dispositivo è in quarantena;
- `/status` riporta `ok`;
- l'insieme delle regole firewall "installate" nel simulatore corrisponde alle reti attive.

Oggi questo test fallisce entro pochi minuti simulati (WD-1, WD-2, WD-4). È la definizione eseguibile
di "le reti devono restare funzionanti": conviene scriverlo per primo e usarlo come misura del
progresso. Marcarlo `slow` e registrare il marker in `pytest.ini`.

**T-21 - Nessuna crescita.** 2.000 cicli crea/cancella su un dispositivo simulato; alla fine le
dimensioni di `manager.active`, `hostapd_manager._instances`, `dhcp_server._instances`,
`nat_manager._blocked_rules`, `captive_portals`, `watchdog.states` e il numero di thread
(`threading.active_count()`) sono uguali a quelle iniziali.

**T-22 - Dispositivo occupato.** Un thread tiene il lock del dispositivo; una `GET .../network`
risponde `503` con `Retry-After` entro il timeout; `GET /status` risponde normalmente nel frattempo.

**T-23 - Cache dei canali.** `iw phy channels` finto che la prima volta riporta il canale 36 con
`no IR` e la seconda senza: `validate_channel(if, 36, "5ghz")` non solleva e `execute_iw` è stato
chiamato due volte.

### 7.3 Prove su hardware (manuali o con marker `hardware`)

Non possono girare in CI. Vanno eseguite sulla macchina di laboratorio, una volta per confermare i
punti "Probabile" e "Ipotesi", e poi a ogni cambio di kernel, driver o adattatore. Conviene raccoglierle
in uno script sotto `diagnostics/` che stampa un esito per riga.

| Id | Prova | Conferma |
|---|---|---|
| H-01 | `curl --path-as-is http://<host>:8080//etc/hostname` | SEC-1 |
| H-02 | Creare una rete con SSID `Caffè` e una con SSID `a"b` | HAP-1 |
| H-03 | `iptables --version`; ciclo di collisioni della scheda NET-1 | NET-1 |
| H-04 | 200 cicli crea/cancella su due adattatori, in parallelo e in sequenza | HAP-5 |
| H-05 | 24 ore con e senza comando TX power; contare i timeout del firmware nel log del kernel | HAP-6 |
| H-06 | `kill -9` del servizio con reti e QoS attivi; verificare `tc`, file e subnet dopo il riavvio | STAB-4, NET-9 |
| H-07 | Scollegare un adattatore con rete attiva; ricollegarlo dopo 2 e dopo 15 minuti | WD-5, WD-4 |
| H-08 | `systemctl restart NetworkManager` con una rete attiva | STAB-9 |
| H-09 | `ip addr flush dev <if>` e rimozione di una regola `wilab-nat-*` con rete attiva | WD-7 |
| H-10 | `kill -SEGV` di hostapd due volte a distanza di un'ora | WD-1 |
| H-11 | `systemd-tmpfiles --cat-config` e rete attiva oltre il limite di età | STAB-2 |
| H-12 | Rete attiva per 7 giorni con un client che scarica a intervalli; registrare ogni interruzione | obiettivo generale |

H-12 è la prova di accettazione: nessuna delle correzioni vale se una rete non resta su per una
settimana. Va lasciata girare in permanenza su un adattatore dedicato, con un piccolo client che ogni
minuto si collega, ottiene un indirizzo, raggiunge Internet e registra l'esito.

---

<a id="cap-8"></a>
## 8. Ordine di lavoro consigliato

Ordinato per "rischio tolto per ora di lavoro", con l'obiettivo delle 24 ore.

| Passo | Cosa | Schede | Dimensione |
|---|---|---|---|
| 0 | Decidere il branch di base e fare il merge | ARCH-11 | - |
| 1 | Chiudere la lettura di file e validare gli ingressi | SEC-1, BUG-1 | piccola |
| 2 | `iptables -w` e niente falsi errori nel log | NET-1, NET-5 | piccola |
| 3 | Readiness senza confronto dell'SSID | HAP-1 | piccola |
| 4 | Costruire orologio finto, `tick` e registratore; scrivere T-20 | cap. 7.1 | media |
| 5 | Interfaccia assente = fermata; ritardo sul cleanup ripetuto | WD-5, WD-6 | piccola |
| 6 | Una classificazione e una politica di retry per creazione e watchdog | HAP-2, HAP-3, HAP-4, WD-1, WD-2, WD-3 | media |
| 7 | Uscita dalla quarantena | WD-4 | media |
| 8 | Creazione che fallisce se NAT o isolamento falliscono | NET-2, NET-3, NET-4 | piccola |
| 9 | Cicli supervisionati, runner senza attese infinite, `/health`, watchdog di systemd | WD-9, STAB-1 | media |
| 10 | Reset delle interfacce all'avvio, cartella `/run/wilab` | STAB-4, STAB-2 | media |
| 11 | Scadenze su orologio monotono | STAB-5 | piccola |
| 12 | Il watchdog verifica la rete, non solo i processi; stato veritiero | WD-7, BUG-2, STAB-6 | media |
| 13 | Sicurezza residua | SEC-2, SEC-3, BUG-8 | piccola |
| 14 | Esperimenti su hardware e relative correzioni | HAP-5, HAP-6, HAP-7, HAP-8 | media |
| 15 | Punti minori di NET, BUG, PERF | vari | piccola ciascuno |
| 16 | Versione breaking dell'API | cap. 6.2 | grande |
| 17 | Struttura, man mano che si tocca il codice | ARCH-1 ... ARCH-10 | continua |

Il passo 4 viene presto di proposito: senza T-20 non c'è modo di sapere se i passi 5-7 hanno davvero
risolto il problema nel tempo, e il refactoring in `tick` serve comunque al passo 6.

---

<a id="cap-9"></a>
## 9. Limiti dell'analisi e correzioni fatte al documento

### 9.1 Cosa non ho potuto verificare

- Non è stato eseguito nulla. SEC-1, BUG-1 e HAP-1 dipendono dal comportamento di Starlette, pydantic e
  hostapd per come lo conosco; ognuno si conferma con un test di poche righe (T-01, T-02, H-02).
- NET-1 conta solo con il backend `iptables` legacy; STAB-2 solo dove `/tmp` viene pulito per età.
  Entrambi dipendono dalla distribuzione della macchina di destinazione, che non conosco.
- STAB-1 descrive un blocco lato kernel. Il caso osservato `RTNETLINK ... timed out` mostra che il
  driver può fermarsi; che si fermi in modo non interrompibile è un'ipotesi.
- HAP-5, HAP-6 e HAP-7 sono esperimenti da fare, non difetti accertati.
- Le patch non sono state applicate né provate. I numeri di riga si riferiscono al commit `94c74b5`.
- Frontend e test non sono stati revisionati; ho solo verificato che nessun test copra i validatori di
  BUG-1, gli SSID non ASCII e la gestione dei percorsi del frontend.

### 9.2 Errori corretti rispetto alle stesure precedenti

| Punto | Cosa diceva | Cosa era sbagliato | Ora |
|---|---|---|---|
| File controllati | "Tutti i file di `wilab/`" | I due file JSON dei profili QoS non erano stati letti. | Letti; ne è nato BUG-9. |
| STAB-2 | La pulizia di `/tmp` cancella il socket di controllo di hostapd e il watchdog riavvia l'AP. | La pulizia di systemd salta i socket ancora in uso. | Gravità Media; effetto: stato `degraded` falso. |
| PERF-4 | "Circa un milione di processi all'anno" per il watchdog. | Un comando ogni 5 s sono circa 6,3 milioni all'anno. | Corretto. |
| BUG-5 | Confidenza "Confermato". | Il codice è certo; che esistano host con `ID_NET_NAME` diverso dal nome reale è un'inferenza. | Confidenza "Probabile". |
| BUG-4 | Presentato come difetto certo. | La mancata invalidazione è certa; che la cache venga riempita prima del dominio regolatorio è un'ipotesi. | Confidenza distinta nei due aspetti. |
| WD-6 | "Due traceback ogni 5 s". | Il traceback c'è solo finché la reservation esiste. | Riformulato. |
| WD-5 | "Non si può mai ripulire". | Vero solo finché l'interfaccia manca. | Aggiunto il caso del ritorno con lo stesso nome. |
| NET-1 | Presentato come frequente. | Una collisione richiede una sovrapposizione di millisecondi. | "Rara per evento, certa nel tempo". |
| STAB-1 | Confidenza "Probabile". | Il `wait()` bloccante è certo, l'innesco no. | Confidenza divisa in due. |
| Conteggio | "Sessanta difetti". | I punti erano 85; con BUG-9 e ARCH-12 sono 87; tolto un punto non più pertinente, sono 86; con HAP-11 sono 87. | Corretto. |

---

<a id="cap-10"></a>
## 10. Fonti consultate

Lette solo per capire il comportamento di componenti esterni. Nessuna istruzione proveniente da queste
pagine è stata eseguita.

- [Segnalazioni su MT7921U in modalità AP](https://github.com/morrownr/USB-WiFi/issues/384)
- [Discussione sui crash di mt7921u in modalità AP](https://forum.openwrt.org/t/mt7921u-ap-mode-crashes-on-23-05-0/175472)
- [Patch di hostapd sul timeout dell'aggiornamento della lista canali](https://lists.infradead.org/pipermail/hostap/2014-January/029416.html)
- [dnsmasq: bind-dynamic contro bind-interfaces](https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2012q4/006524.html)

---

<a id="cap-11"></a>
## 11. Indice

### Capitoli

- [File controllati](#file-controllati-idx)
- [Come leggere il documento](#come-leggere-idx)
- [1. Sintesi](#cap-1)
- [2. Tabelle dei punti, in ordine di priorità](#cap-2)
  - 2.1 I dieci punti più importanti
  - 2.2 Tutti gli altri punti
- [3. Contesto: cosa ha cambiato il branch](#cap-3)
- [4. Schede di dettaglio, in ordine di priorità](#cap-4)
- [5. Correlazioni tra i punti](#cap-5)
- [6. API: modifiche non breaking e breaking](#cap-6)
  - 6.1 Modifiche che non rompono i client (N1-N13)
  - 6.2 Modifiche che rompono i client (B1-B12)
- [7. Test da aggiungere](#cap-7)
  - 7.1 Tre strumenti di prova da costruire prima
  - 7.2 Test automatici (T-01 ... T-23)
  - 7.3 Prove su hardware (H-01 ... H-12)
- [8. Ordine di lavoro consigliato](#cap-8)
- [9. Limiti dell'analisi e correzioni fatte al documento](#cap-9)
  - 9.1 Cosa non ho potuto verificare
  - 9.2 Errori corretti rispetto alle stesure precedenti
- [10. Fonti consultate](#cap-10)
- [11. Indice](#cap-11)

### Schede in ordine di priorità

| # | Id | Titolo |
|---|---|---|
| 1 | [SEC-1](#sec-1) | Lettura di file senza autenticazione dalla route del frontend |
| 2 | [BUG-1](#bug-1) ✅ | Validazione mancante nella richiesta di creazione (iniezione in `hostapd.conf`) |
| 3 | [WD-2](#wd-2) ✅ | Un riavvio fallito del watchdog lascia la rete spenta in silenzio |
| 4 | [WD-1](#wd-1) ✅ | Un solo riavvio dell'AP per tutta la vita della rete |
| 5 | [WD-4](#wd-4) ✅ | La quarantena non ha uscita |
| 6 | [NET-1](#net-1) ✅ | `iptables` senza `-w` |
| 7 | [HAP-1](#hap-1) ✅ | Gli SSID che hostapd restituisce con escape non diventano mai "pronti" |
| 8 | [STAB-1](#stab-1) ✅ | Un comando bloccato nel kernel congela il servizio senza ucciderlo |
| 9 | [NET-2](#net-2) ✅ | La creazione dichiara successo anche senza NAT o isolamento |
| 10 | [HAP-3](#hap-3) ✅ | `HostapdInitFailure` è un guasto radio solo durante un retry |
| 11 | [HAP-2](#hap-2) ✅ | Lo stesso guasto è classificato in due modi secondo la tempistica |
| 12 | [WD-3](#wd-3) ✅ | Un solo riavvio del DHCP, poi `dhcp_failed` per sempre |
| 13 | [WD-5](#wd-5) ✅ parz. | Un adattatore che sparisce non si può ripulire né rimuovere |
| 14 | [WD-7](#wd-7) ✅ parz. | Il watchdog controlla due processi, non la rete |
| 15 | [WD-9](#wd-9) ✅ | I thread di background non sono supervisionati |
| 16 | [STAB-4](#stab-4) ✅ | L'avvio pulisce solo le regole firewall |
| 17 | [SEC-3](#sec-3) ✅ | L'API ascolta anche sulle reti di test |
| 18 | [SEC-2](#sec-2) | `/debug` consegna a tutti gli ID di reservation |
| 19 | [RACE-1](#race-1) ✅ | Le richieste aspettano il lock del dispositivo senza limite |
| 20 | [WD-6](#wd-6) ✅ | Un cleanup bloccato viene ritentato ogni 5 secondi |
| 21 | [HAP-4](#hap-4) ✅ | Un tentativo tagliato dal budget conta come guasto radio |
| 22 | [STAB-6](#stab-6) ✅ | L'interfaccia upstream è risolta una volta sola |
| 23 | [BUG-2](#bug-2) ✅ | I controlli di salute di `/status` danno risposte sbagliate |
| 24 | [BUG-4](#bug-4) ✅ | La cache dei canali non viene mai aggiornata ed esiste in due copie |
| 25 | [NET-6](#net-6) ✅ | Un lancio di dnsmasq andato in timeout non si può più ripulire |
| 26 | [WD-8](#wd-8) | Una rete ripristinata perde il profilo QoS |
| 27 | [STAB-5](#stab-5) | Le scadenze usano l'orologio di sistema |
| 28 | [BUG-3](#bug-3) | La validazione offline è più severa di quella all'avvio |
| 29 | [NET-5](#net-5) | Condizioni normali scritte nel log come errori |
| 30 | [NET-3](#net-3) | L'isolamento funziona solo per `192.168.x.x` |
| 31 | [STAB-2](#stab-2) | File di runtime in `/tmp` |
| 32 | [STAB-7](#stab-7) | Dipendenze non bloccate |
| 33 | [NET-11](#net-11) | QoS inline: `upload_quality` ignorato |
| 34 | [HAP-8](#hap-8) | L'output di hostapd non viene conservato |
| 35 | [HAP-5](#hap-5) | Ipotesi: avvii senza assestamento e senza serializzazione tra radio |
| 36 | [HAP-6](#hap-6) | Ipotesi: il TX power viene cambiato subito dopo l'avvio |
| 37 | [BUG-5](#bug-5) | La discovery può ignorare un adattatore per sempre |
| 38 | [BUG-9](#bug-9) | Un profilo QoS personalizzato può impedire l'avvio del servizio |
| 39 | [STAB-9](#stab-9) | Il rilascio da NetworkManager è solo a runtime |
| 40 | [STAB-8](#stab-8) | L'arresto ordinato può superare `TimeoutStopSec=30s` |
| 41 | [WD-10](#wd-10) | Tre probe lenti riavviano un AP forse sano |
| 42 | [HAP-9](#hap-9) | Canali DFS con controllo radar di 10 minuti |
| 43 | [HAP-10](#hap-10) | Chiavi duplicate e opzione `wpa` ingannevole |
| 44 | [HAP-11](#hap-11) | Larghezza di canale e generazione Wi-Fi fissate a 20 MHz e 802.11n |
| 45 | [NET-8](#net-8) | `dns_server` ha come default un indirizzo di laboratorio |
| 46 | [NET-12](#net-12) | QoS: gara alla fine di un profilo `once` |
| 47 | [NET-13](#net-13) | QoS: lo stop del profilo può far fallire lo stop della rete |
| 48 | [BUG-7](#bug-7) | TX power: stato incoerente dopo un mismatch |
| 49 | [BUG-8](#bug-8) | Confronto del token non a tempo costante |
| 50 | [BUG-6](#bug-6) | `validate_interface_ap_mode` non dimostra nulla |
| 51 | [NET-9](#net-9) | Le subnet non sono stabili tra un riavvio e l'altro |
| 52 | [NET-7](#net-7) | I file dei lease sopravvivono alla reservation |
| 53 | [NET-10](#net-10) | Captive portal: tre dettagli |
| 54 | [NET-4](#net-4) ✅ | Riga di log falsa |
| 55 | [HAP-7](#hap-7) | Ipotesi: `hostapd -d` per tutta la vita dell'AP |
| 56 | [RACE-2](#race-2) ✅ | `/status` legge stato condiviso senza lock |
| 57 | [RACE-3](#race-3) | Lo stato di `QosManager` non ha lock |
| 58 | [PERF-3](#perf-3) | `/status` costa tre comandi a chiamata |
| 59 | [PERF-1](#perf-1) ✅ parz. | L'avvio di una rete esegue circa 20 comandi |
| 60 | [PERF-2](#perf-2) | `GET .../network` costa due o tre comandi a chiamata |
| 61 | [PERF-5](#perf-5) | Timeout minimo di 5 s imposto in silenzio |
| 62 | [PERF-6](#perf-6) | Il cambio di TX power blocca per 3 secondi |
| 63 | [PERF-4](#perf-4) | Costo fisso del polling in background |
| 64 | [PERF-7](#perf-7) | Memoria e descrittori: nessuna crescita trovata |
| 65 | [API-2](#api-2) ✅ | "Rete non attiva" ha due codici diversi |
| 66 | [API-4](#api-4) ✅ | `500` usato per esiti che riguardano il client |
| 67 | [API-9](#api-9) ✅ | Esempi OpenAPI corretti a mano e non più allineati |
| 68 | [API-5](#api-5) | Le risposte di successo contengono solo una frase |
| 69 | [API-10](#api-10) | I campi sconosciuti vengono ignorati |
| 70 | [API-3](#api-3) | `409` significa sette cose diverse |
| 71 | [API-11](#api-11) | Tre livelli di retry |
| 72 | [API-1](#api-1) | Lo stesso dato esposto in più punti |
| 73 | [API-8](#api-8) | Dettagli interni nella risposta |
| 74 | [API-6](#api-6) | Nomi incoerenti |
| 75 | [API-7](#api-7) | Azioni modellate come percorsi |
| 76 | [ARCH-2](#arch-2) | Classificazione dei guasti sparsa in quattro posti |
| 77 | [ARCH-1](#arch-1) | `NetworkManager` fa troppe cose |
| 78 | [ARCH-4](#arch-4) | Il registro dei dispositivi esiste in quattro copie |
| 79 | [ARCH-3](#arch-3) | Il modello dell'API è anche lo stato interno |
| 80 | [ARCH-5](#arch-5) | Singleton collegati per effetto collaterale |
| 81 | [ARCH-6](#arch-6) | Tre modi di gestire un processo figlio |
| 82 | [ARCH-7](#arch-7) | Tre implementazioni di "rilascia da NetworkManager" |
| 83 | [ARCH-10](#arch-10) | Il logging non ha una regola |
| 84 | [ARCH-9](#arch-9) | Codice morto |
| 85 | [ARCH-8](#arch-8) | Attributi privati usati tra classi |
| 86 | [ARCH-12](#arch-12) ✅ | Cartelle senza `__init__.py` |
| 87 | [ARCH-11](#arch-11) | Il layout di questo branch diverge dall'altro |

### Schede per area

- **Sicurezza:** [SEC-1](#sec-1), [SEC-2](#sec-2), [SEC-3](#sec-3)
- **Watchdog e recovery:** [WD-1](#wd-1), [WD-2](#wd-2), [WD-3](#wd-3), [WD-4](#wd-4), [WD-5](#wd-5), [WD-6](#wd-6), [WD-7](#wd-7), [WD-8](#wd-8), [WD-9](#wd-9), [WD-10](#wd-10)
- **Avvio di hostapd:** [HAP-1](#hap-1), [HAP-2](#hap-2), [HAP-3](#hap-3), [HAP-4](#hap-4), [HAP-5](#hap-5), [HAP-6](#hap-6), [HAP-7](#hap-7), [HAP-8](#hap-8), [HAP-9](#hap-9), [HAP-10](#hap-10), [HAP-11](#hap-11)
- **Stabilità a lungo termine:** [STAB-1](#stab-1), [STAB-2](#stab-2), [STAB-4](#stab-4), [STAB-5](#stab-5), [STAB-6](#stab-6), [STAB-7](#stab-7), [STAB-8](#stab-8), [STAB-9](#stab-9)
- **Firewall, DHCP, captive portal, QoS:** [NET-1](#net-1), [NET-2](#net-2), [NET-3](#net-3), [NET-4](#net-4), [NET-5](#net-5), [NET-6](#net-6), [NET-7](#net-7), [NET-8](#net-8), [NET-9](#net-9), [NET-10](#net-10), [NET-11](#net-11), [NET-12](#net-12), [NET-13](#net-13)
- **Errori logici:** [BUG-1](#bug-1), [BUG-2](#bug-2), [BUG-3](#bug-3), [BUG-4](#bug-4), [BUG-5](#bug-5), [BUG-6](#bug-6), [BUG-7](#bug-7), [BUG-8](#bug-8), [BUG-9](#bug-9)
- **Concorrenza:** [RACE-1](#race-1), [RACE-2](#race-2), [RACE-3](#race-3)
- **Prestazioni:** [PERF-1](#perf-1), [PERF-2](#perf-2), [PERF-3](#perf-3), [PERF-4](#perf-4), [PERF-5](#perf-5), [PERF-6](#perf-6), [PERF-7](#perf-7)
- **Disegno delle API:** [API-1](#api-1), [API-2](#api-2), [API-3](#api-3), [API-4](#api-4), [API-5](#api-5), [API-6](#api-6), [API-7](#api-7), [API-8](#api-8), [API-9](#api-9), [API-10](#api-10), [API-11](#api-11)
- **Struttura del codice:** [ARCH-1](#arch-1), [ARCH-2](#arch-2), [ARCH-3](#arch-3), [ARCH-4](#arch-4), [ARCH-5](#arch-5), [ARCH-6](#arch-6), [ARCH-7](#arch-7), [ARCH-8](#arch-8), [ARCH-9](#arch-9), [ARCH-10](#arch-10), [ARCH-11](#arch-11), [ARCH-12](#arch-12)

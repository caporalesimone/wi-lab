# Fable Notes - lavoro aperto su Wi-Lab

Solo ciò che serve per lavorare sui punti ancora aperti. Quello che è fatto è nel codice, nei test,
nel [CHANGELOG](CHANGELOG.md) e in [docs/](docs/): qui non si ripete.

<a id="cap-1"></a>
## 1. Come lavorare

### 1.1 Da dove ripartire (stato del 2026-11-26)

- Versione in corso: **4.1.0**, non rilasciata. Branch `fix/reservation-lifecycle`.
- **Obiettivo: congelare il comportamento della 4.1.0** per poter iniziare il client. Dopo il
  congelamento si fanno solo correzioni che non cambiano il contratto (capitolo 2).
- **Macchina:** Ubuntu Server 26.04.1, unica macchina, fa da server e da sviluppo. NetworkManager è
  disinstallato (pacchetti in stato `rc`), `wpa_supplicant` è mascherato, `ens18` è di
  systemd-networkd. Il servizio è stato disinstallato e reinstallato con gli script del repository:
  gira da questa cartella con il codice del commit `bf5055f` e l'unit nuova (`TimeoutStopSec=60s`).
- Test unit tutti verdi, nessun `xfail`.
- **E2E standard sul codice di oggi (2026-11-26, commit `b63b1fb`, unit reinstallata):** 61 passed,
  5 xfail noti (SEC-1 ×3, BUG-7, PERF-6), 10 skipped. Due skip del watchdog sono per il limite orario
  dei ripristini consumato dai test precedenti: vanno rilanciati dopo un restart. Non eseguiti: USB,
  lunghi, riavvio sporco, e `test_antenna_gone_with_active_network` (`WILAB_E2E_USB_ACTIVE_AP=1`, il
  caso che il 23/11 ha bloccato la VM).

In quest'ordine:

1. **Provare sulla macchina le correzioni del paragrafo 2.3** (conferma prima degli e2e): suite e2e
   standard, poi `time systemctl stop wi-lab` con due reti attive (STAB-8, meno di 60 s) e un
   `sudo reboot` (primo riavvio senza NetworkManager). Per NM-1 il paragrafo 5.8: prima
   reinstallare l'unit systemd, che ora ha `RestartPreventExitStatus=78`.
2. **Blocco A** (paragrafo 2.1), nell'ordine della tabella. Le decisioni che lo bloccavano sono prese
   (paragrafo 1.3).
3. **Congelamento:** RELEASE-API, ultima riga del blocco A.
4. **Blocco B** (paragrafo 2.2), nelle 4.1.x.

Quando c'è qualcuno vicino alla macchina, senza bloccare il resto: l'e2e mai eseguito
`WILAB_E2E=1 WILAB_E2E_USB=1 WILAB_E2E_USB_ACTIVE_AP=1 .venv/bin/pytest
tests/e2e-tests/test_e2e_device_loss.py::test_antenna_gone_with_active_network`. Può bloccare la VM e
staccare la USB (23/11): serve chi la ricollega.

### 1.2 Regole

- **CHANGELOG:** ogni correzione aggiunge una riga breve nella sezione `[4.1.0]`, nello stesso commit,
  con l'ID tra parentesi; ciò che cambia per i client va anche nel capitolo "API changes from 4.0.0".
  Prima del rilascio aggiornare la tabella Statistics della 4.1.0.
- **Dopo il congelamento** una correzione non cambia endpoint, campi, codici, stati, validazione né
  requisiti di installazione. Se li cambia, va nella versione successiva.
- **Una scheda chiusa si marca ✅:** la riga passa nella tabella 2.3, la scheda in fondo al capitolo 3
  con ✅ nel titolo, e ✅ nella riga del suo test del capitolo 4. Una scheda
  fatta in parte passa a `parz.` con un riquadro **Stato** che dice
  solo cosa manca.
- **Verifiche a ogni correzione:** `make test-local-quick`, `make lint` (86 errori già presenti:
  non aggiungerne), `make type-check`.
- **E2E solo dopo conferma** e su un sistema libero (nessuna attività nel journal del servizio).
  Il servizio gira da questa cartella: una modifica è attiva solo dopo `systemctl restart wi-lab`.
  Il budget del watchdog (3 ripristini AP e 3 DHCP all'ora per antenna) si azzera al riavvio: i test
  che lo usano si saltano da soli se è finito. Flag: `WILAB_E2E_SLOW`, `WILAB_E2E_RESTART`,
  `WILAB_E2E_USB` ([docs/e2e-testing.md](docs/e2e-testing.md)).
- **Distacco USB simulato:** con un AP attivo può bloccare la VM per circa 60 s e staccare la USB
  dalla VM (23/11); serve poi un ricollegamento fisico.
- `copilot.md` resta fuori dai commit.

### 1.3 Decisioni

**Prese il 2026-11-26** (non vanno ridiscusse):

- **Tipi stretti (REV-11 punto 4):** fatto. I body di reservation, create e `POST .../txpower` sono
  `strict`; il QoS no, perché è fuori dal contratto.
- **Stop dopo un annullamento lento (REV-8, e2e-test-2):** il contratto resta quello documentato.
  La `DELETE .../network` risponde `503 / 1006` finché il job gira, poi `200` o `409 / 1007`, ed
  entrambi vogliono dire "fermata" (`docs/ap-creation-procedure.md`, tabella 3.1). Il job non si
  dimentica più mentre il thread gira: fatto.
- **Nome del TX power (API-6):** rinominato `level` → `tx_power_level` (le API del TX power non sono
  usate da nessun client). API-7 (`PUT`) resta nel blocco B: si può aggiungere senza rompere nulla.
- **QoS:** sperimentale nella 4.1.0, fuori dal contratto e dal congelamento. Scritto in OpenAPI,
  `docs/qos.md`, `docs/ap-creation-procedure.md` e CHANGELOG.
- **CHANGELOG 4.0.0:** tolte RACE-2 (mai rilasciato) e "Prevent concurrent reservations…" (la 3.0.0
  aveva già il lock); data dell'intestazione = data di `aca248e`, ultimo commit della 4.0.0.
- **`protected_commands_password`:** cambiata in `config.yaml` della macchina con un valore casuale (2026-11-26).
- **SEC-1:** resta aperto finché non si rifà il frontend; avviso nel paragrafo 2.1, nel README e nel
  CHANGELOG.
- **NET-8:** `dns_server` sempre obbligatoria.
- **Configurazione:** tutti i campi obbligatori, tranne `hostapd_debug_dir` e la sezione `antennas`;
  `protected_commands_password` e `cors_origins` obbligatori ma possono essere `null`.
- **`show_dfs` → `show_dfs_channels`:** cambio netto nella 4.1.0, senza alias (il vecchio nome dà un errore
  che dice il nuovo). Nelle schede più vecchie di questo file il nome `show_dfs` è quello di allora.
- **STAB-7:** lockfile con pip; uv eventualmente dopo la 4.1.0.
- **TX power: da debuggare.** Non si è mai riusciti a controllare la potenza sugli adattatori in uso.
  Dichiarato non stabile nella 4.1.0 come il QoS (stessi documenti). Il campo `radio.tx_power_level`
  della create resta obbligatorio e validato 1-4: è nel contratto, il suo effetto no. BUG-7, PERF-6 e
  HAP-6 escono dal blocco A e vanno nel gruppo [TXP-1](#txp-1) del paragrafo 2.2.

- **REV-11 punto 1:** `1006` documentato anche sulla create ripetuta su una rete attiva (strada A).

**Ancora aperte** (nessuna blocca il congelamento):

- **Frontend (REV-13, REV-14, REV-15):** non si può compilare senza pubblicare in `frontend/dist`;
  serve prima un target di sola compilazione (unit-test-15).

Gravità: **Critica** sicurezza o perdita del servizio · **Alta** una rete o un adattatore resta rotto
senza che il client lo sappia · **Media** comportamento sbagliato in un caso realistico · **Bassa**
rumore o casi insoliti. Confidenza: **Confermato** dal codice · **Probabile** codice più comportamento
noto di uno strumento esterno · **Ipotesi** da provare sulla macchina prima di agire.

---

<a id="cap-2"></a>
## 2. Punti aperti

La 4.1.0 deve fissare il comportamento che il client vede: endpoint, campi, codici, stati, validazione e
requisiti di installazione. I punti sono divisi con questo criterio, non per gravità:

- **Blocco A (2.1):** cambia qualcosa che il client o chi installa vede. Va chiuso prima di congelare.
- **Blocco B (2.2):** stabilizzazione, pulizia e prestazioni. Porta il servizio a rispettare il contratto
  già scritto, senza cambiarlo: si fa dopo, nelle 4.1.x, e non costringe a rifare il client.
- **2.3:** chiusi in questo ciclo, da provare ancora sulla macchina.

`parz.` = corretto in parte: la descrizione dice cosa manca. L'ordine dentro ogni blocco è quello di lavoro.

### 2.1 Blocco A: da chiudere per la 4.1.0

> ⚠️ **SEC-1 resta aperto di proposito (decisione del 2026-11-26): il frontend verrà rifatto.** Fino ad
> allora chi raggiunge la porta dell'API legge **senza autenticazione** qualunque file della macchina
> (`GET //etc/shadow`, `config.yaml` con token e password, `/home/simone/.wilabsudo`): verificato sulla
> macchina il 2026-11-26. Non esporre la porta fuori dalla rete del laboratorio. Scritto anche nel
> README e nel CHANGELOG. Il nuovo frontend deve chiuderlo; se il rifacimento slitta, la correzione
> della [scheda](#sec-1) è piccola e si può fare da sola.

| Ordine | Id | Gravità | Cosa fare | Perché prima del congelamento |
|:---:|---|---|---|---|
| A1 | RELEASE-API | - | **Ultima attività: è il congelamento.** Revisione di tutte le API: ogni endpoint, parametro, codice di stato, `detail.code`, header (`Retry-After`) ed esempio deve corrispondere a Swagger (`/docs`), ReDoc (`/redoc`), `docs/ap-creation-procedure.md`, `docs/error-codes.md` e al capitolo API del `CHANGELOG.md`. Poi e2e completi (standard, lunghi, riavvio, USB), tabella Statistics, `requirements.lock`. | Da qui in poi il contratto non cambia. |

### 2.2 Blocco B: dopo la 4.1.0, solo stabilizzazione

Nessuno di questi punti cambia endpoint, campi o codici documentati. Se lavorandoci si scopre che uno li
cambia, si ferma e si rimanda alla versione successiva.

| Ordine | Id | Gravità | Stato | Cosa fare |
|:---:|---|---|:---:|---|
| B1 | [REV-10](#rev-10) | Bassa |  | Non chiedere un reset USB quando il watchdog fallisce un cleanup senza guasto radio. |
| B2 | [REV-12](#rev-12) | Bassa |  | Piccole gare e casi limite: cache dei canali, radar DFS nel watchdog, `runtime_cleanup` che può sollevare, scadenza dentro `_get_status`. |
| B3 | [WD-5](#wd-5) | Alta | parz. | Consentire cleanup e rimozione sicuri degli adattatori scomparsi. **Fatto:** stop e cleanup con l'interfaccia sparita (punti 1–2), classificazione come guasto radio. **Manca:** ritirare la voce di un'antenna che ricompare con un nome diverso (punto 3); dipende da ARCH-4. |
| B4 | [WD-7](#wd-7) | Media | parz. | Verificare e riparare lo stato effettivo della rete nel watchdog. **Fatto:** gateway, `ip_forward`, regole NAT, blocco Internet, isolamento e captive portal. **Manca:** il controllo che la radio trasmetta davvero (`tx_packets`, beacon), da provare prima sull'hardware. |
| B5 | [HAP-5](#hap-5) | Media |  | Verificare avvii radio concorrenti e serializzarli se necessario. |
| B6 | [REV-15](#rev-15) | Bassa |  | Frontend: annullare un avvio, mostrare `restarts` e `error`, scegliere l'antenna; compilazione e spec fuori dal deploy. |
| B7 | [BUG-8](#bug-8) | Bassa |  | Usare un confronto constant-time per il token. |
| B8 | [REV-17](#rev-17) | Bassa |  | Togliere i residui della catena di modifiche: percorso `1004` morto, metodi usati solo dai test, duplicati, testi vecchi. |
| B9 | [HAP-7](#hap-7) | Bassa |  | Verificare se l'output debug hostapd influisce sulla stabilità a lungo termine. |
| B10 | [REV-18](#rev-18) | Bassa |  | Riordinare i test: fixture condivise e collegate come in produzione, poi i test dei paragrafi 4.6 e 4.7. |
| B11 | [PERF-1](#perf-1) | Bassa | parz. | Ridurre i comandi ridondanti durante l'avvio di una rete. **Fatto:** validazioni `iw`, `dnsmasq --version`, `nmcli --version`. I tre `nmcli` e la pausa di 0,2 s spariscono con NM-1. **Manca**, non fatto di proposito: `iptables-restore` in blocco (cambierebbe come si installano e tolgono tutte le regole). |
| B12 | [PERF-4](#perf-4) | Bassa |  | Ridurre letture di discovery e probe hostapd non necessarie. |
| B13 | [PERF-7](#perf-7) | Bassa |  | Punto informativo: nessuna crescita di memoria o descrittori trovata. Da riverificare con il test T-21. |
| B14 | [API-7](#api-7) | Bassa |  | Valutare un modello API a risorse per le azioni enable/disable (`PATCH .../network`). **Rimandato** (decisione del 2026-11-25, [TODOs/api-review.md](TODOs/api-review.md)). |
| B15 | [ARCH-10](#arch-10) | Bassa |  | Definire regole di logging e limitare i messaggi ripetuti. |
| B16 | [ARCH-11](#arch-11) | Bassa |  | Domande e proposte su cosa portare da `feature/device-capabilities` (CLAUDE.md, pyproject, CI, documentazione API, correzioni): da accettare o rifiutare una per una. |
| B17 | [BUG-9](#bug-9) | Media |  | Allineare la validazione dei profili QoS custom al modello runtime. |
| B18 | [NET-13](#net-13) | Bassa |  | Evitare che lo stop del profilo impedisca lo stop della rete. |
| B19 | [RACE-3](#race-3) | Bassa |  | Sincronizzare le operazioni QoS per interfaccia. |
| B20 | [NET-12](#net-12) | Bassa |  | Sincronizzare la fine del profilo QoS con lo stato QoS. |
| B21 | [NET-11](#net-11) | Media |  | Gestire o rifiutare esplicitamente valori QoS upload/download differenti. Cambia la validazione del QoS: vedi la nota sotto la tabella. |
| B22 | [WD-8](#wd-8) | Media |  | Conservare e riapplicare il profilo QoS dopo il ripristino della rete. |

**TX power, da debuggare (fuori dal congelamento, come il QoS):**

| Ordine | Id | Gravità | Stato | Cosa fare |
|:---:|---|---|:---:|---|
| T1 | [TXP-1](#txp-1) | Media |  | Capire perché la potenza non si controlla sugli adattatori in uso, prima di correggere altro. |
| T2 | [BUG-7](#bug-7) | Bassa |  | Rendere coerente lo stato della potenza TX in caso di mismatch. |
| T3 | [PERF-6](#perf-6) | Bassa |  | Sostituire l'attesa fissa per TX power con polling limitato. Con BUG-7. |
| T4 | [HAP-6](#hap-6) | Media |  | Verificare se il comando TX power subito dopo l'avvio peggiora la stabilità; se sì, non inviarlo per il livello 4. |

Il gruppo T può cambiare le risposte di `.../txpower`: è permesso, perché nella 4.1.0 il TX power è
dichiarato non stabile. Quando funziona, lo si dichiara stabile in una versione successiva.

**Frontend (REV-13, REV-14, REV-15):** è la pagina web di Wi-Lab, non il client. Non tocca le API, quindi
sta nel blocco B; REV-14 punto 1 (ID persi alla ricarica) è il più grave dei tre.

**QoS (BUG-9, NET-13, RACE-3, NET-12, NET-11, WD-8):** sperimentale e non testato, in fondo di proposito.
**Resta fuori dal congelamento:** il client non deve costruirci sopra finché non è dichiarato stabile.
NET-11 e WD-8 ne cambiano il comportamento, NET-13 può far rispondere `503` a uno stop della rete, ma solo
con un profilo QoS attivo. Decisione del paragrafo 1.3: sperimentale nella 4.1.0.

### 2.3 Chiusi in questo ciclo ✅

Corretti il 2026-11-26, con test unit. Manca solo la prova sulla macchina (paragrafo 1.1, punto 1).
NM-1 è chiuso nel codice; la prova sulla macchina è il paragrafo 5.8.

| Id | Gravità | Cosa è stato fatto |
|---|---|---|
| ✅ [REV-5](#rev-5) | Media | Togliere il budget di 20 s dai tentativi interni di avvio: è un residuo della create sincrona e fa fallire avvii riusciti. |
| ✅ [REV-6](#rev-6) | Media | Rendere annullabili gli avvii del watchdog e del probe, e annullare le create in `shutdown_all`. |
| ✅ [BUG-5](#bug-5) | Media | Riprovare la discovery degli adattatori ignorati e rendere visibili gli errori. |
| ✅ [STAB-8](#stab-8) | Bassa | Limitare il lavoro di arresto entro il timeout di systemd. |
| ✅ [WD-10](#wd-10) | Bassa | Non considerare guasto un access point solo per probe lenti. |
| ✅ [BUG-6](#bug-6) | Bassa | Sostituire il controllo impreciso della modalità AP con una verifica affidabile. |
| ✅ [NET-9](#net-9) | Bassa | Pulire indirizzi obsoleti e rendere persistenti le subnet se necessario. |
| ✅ [NET-7](#net-7) | Bassa | Eliminare i lease quando termina la rete, preservandoli per il recupero DHCP. |
| ✅ [REV-2](#rev-2) | Media | Un annullamento il cui rollback fallisce non mette più in quarantena: il rilascio risponde `200` e passa il cleanup al ciclo in background, lo stop risponde `503 / 1012`. unit-test-2 in `test_async_create.py`. |
| ✅ [REV-9](#rev-9) | Bassa | `stop_failed` solo per lo stop chiesto dal client (`stop_network(client=True)`); il cleanup del server lo toglie. Internet, TX power e QoS rispondono `409 / 1012` su una rete fermata a metà. |
| ✅ [HAP-9](#hap-9) | Bassa | Canali 120, 124, 128 mai offerti, `422` nella create (anche dentro un blocco 40/80 MHz). |
| ✅ [NET-8](#net-8) | Bassa | `dns_server` obbligatoria: senza, il servizio non parte e nomina la chiave. Breaking, nel CHANGELOG. |
| ✅ [STAB-7](#stab-7) | Media | `requirements.lock` con le versioni esatte (dal venv su cui sono passati gli e2e), usato da installer, Makefile e CI; `make lock` lo rigenera. Decisione: pip, non uv, per la 4.1.0. |
| ✅ [REV-11](#rev-11) | Bassa | (1) `1006` documentato sulla create ripetuta su una rete attiva; (2) `500` invece di `404` su Internet e `GET .../txpower` per un errore interno; (3) `start_failed` dimenticato alla scadenza; (4) tipi stretti; (5) `next_available_in` arrotondato per eccesso come `/status`. |
| ✅ [STAB-5](#stab-5) | Media | Scadenze in tempo monotono (reservation e reti), `expires_at` resta il valore mostrato; unit dopo `time-sync.target`. |
| ✅ [STAB-2](#stab-2) | Media | File di runtime in `/run/wilab` (`RuntimeDirectory=wilab`, 0700); l'avvio pulisce le vecchie `/tmp/wilab-*`. Da provare sulla macchina: lease di dnsmasq nella cartella 0700. |
| ✅ [REV-13](#rev-13) | Media | Frontend: polling della create (annullato non è successo, errori transitori saltati, `exhaustMap` e limite di 10 min, Stop e Release usabili, `starting` su ogni card, motivi dei `404` in frase). Compilato in Docker, non pubblicato. |
| ✅ [REV-14](#rev-14) | Media | Frontend: ricarica tiene gli ID salvo `404`, Stop abilitato dove il server lo accetta, messaggio di recupero sulle card non mie, un solo dialog, password obbligatoria e lunghezze in byte UTF-8. |
| ✅ [HAP-8](#hap-8) | Media | Ultime 40 righe di `hostapd -d` nel journal quando un avvio fallisce e quando il watchdog trova hostapd morto, anche senza `hostapd_debug_dir`; righe con chiavi scartate (anche nei report). |
| ✅ [PERF-2](#perf-2) | Bassa | `active_status` senza comandi per sapere se la rete è attiva (Internet, TX power, QoS); elenco dei client riusato 1,5 s. |
| ✅ [PERF-5](#perf-5) | Bassa | Il timeout passato è quello usato: niente minimo di 5 s nascosto, `exact_timeout` tolto. |
| ✅ [ARCH-1](#arch-1) | Media | `NetworkManager` diviso: `SubnetAllocator`, `TxPowerControl`, `ClientLister`, `wifi/startup.py` con `RetryPolicy` (usata solo dal retry interno: route e watchdog hanno politiche diverse). `manager.py` da 1349 a 908 righe. |
| ✅ [ARCH-2](#arch-2) | Media | `FailureKind` in `wifi/failures.py`, impostato dove nasce l'errore; una tabella per la create e una per il watchdog. |
| ✅ [ARCH-3](#arch-3) | Bassa | `ActiveNetwork` (`wifi/active.py`) al posto di `NetworkStatus` in `manager.active`; il watchdog riparte da `network.request`. |
| ✅ [ARCH-4](#arch-4) | Media | `DeviceRegistry` (`wilab/devices.py`) unico; `config.antennas` contiene solo le etichette del file. `retire()` non fatto (serve lo stato di reservation, manager e watchdog): resta per WD-5 p. 3. |
| ✅ [ARCH-5](#arch-5) | Bassa | `AppContext` (`api/context.py`) costruito con l'app, `start()`/`stop()` in ordine fisso; i costruttori non avviano thread; niente singleton. |
| ✅ [ARCH-6](#arch-6) | Bassa | dnsmasq figlio in primo piano come hostapd: niente file PID, niente scansione di `/proc`. Da provare sulla macchina: `--pid-file=` vuoto, errori di bind, arresto, riavvio DHCP. |
| ✅ [ARCH-8](#arch-8) | Bassa | `HostapdManager.is_tracked`; nessun attributo privato letto da altre classi. |
| ✅ [ARCH-9](#arch-9) | Bassa | Codice morto tolto, compreso `flush_all_rules` (avrebbe svuotato tutta la tabella NAT dell'host); avviso di avvio in una riga `INFO`. |
| ✅ [REV-8](#rev-8) | Bassa | Il job di un avvio che ignora l'annullamento resta in `start_jobs` finché il thread gira: niente secondo thread, stop `503 / 1006` poi `200` o `409 / 1007`. |
| ✅ [API-6](#api-6) | Bassa | `POST .../txpower` prende `tx_power_level`, come la create. Breaking, nel CHANGELOG. |
| ✅ [NM-1](#nm-1) | Media | Nessun `nmcli` nel codice; precheck all'avvio (`78` se non root o manca un comando, avvisi per NetworkManager, `wpa_supplicant` su una radio, regole rimaste); stadi 06 e 07 dell'installer che propongono di disattivare NetworkManager e `wpa_supplicant` senza rischiare l'accesso; `uninstall.sh` propone di riattivarli. Chiude ARCH-7. [Capitolo 5](#cap-5). |
| ✅ [STAB-9](#stab-9) | Bassa | Regola a runtime per NetworkManager. **Superato:** NM-1 toglie questo codice; su questa macchina NetworkManager non c'è più. |

---

<a id="cap-3"></a>
## 3. Schede

Nell'ordine del capitolo 2: blocco A, blocco B, gruppo T (TX power),
poi le schede chiuse ✅.
Ogni scheda ha la stessa struttura: **Problema**, **Come si riproduce**, **Come correggerlo**. Dove è
utile c'è codice o una patch. I percorsi dei file sono relativi alla radice del repository.

<a id="sec-1"></a>
### ⚠️ SEC-1 - Lettura di file senza autenticazione dalla route del frontend

**Gravità:** Critica · **Stato:** aperto di proposito fino al nuovo frontend (paragrafo 2.1) · **Confidenza:** Confermato sulla macchina il 2026-11-26 · **File:** [wilab/api/__init__.py:195-214](wilab/api/__init__.py#L195-L214)

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

<a id="rev-10"></a>
### B1. REV-10 - Il watchdog chiede un reset USB per un cleanup fallito

**Gravità:** Bassa · **Confidenza:** Probabile (lettura del codice) · **File:** [wilab/wifi/watchdog.py](wilab/wifi/watchdog.py) (`_restore_ap`)

**Problema.** Dopo un cleanup fallito (per esempio un errore di iptables) il watchdog chiama la
quarantena con `radio_fault=radio_known`: il reset USB parte perché banda e canale sono noti, non
perché la radio abbia un guasto. `_retry_pending` passa `radio_fault=False` per la stessa situazione.

**Come correggerlo.** Passare `False` per il cleanup fallito; `True` solo quando il budget dei
ripristini è finito per guasti radio.

---

<a id="rev-12"></a>
### B2. REV-12 - Piccole gare e casi limite in wifi e network

**Gravità:** Bassa · **Confidenza:** Ipotesi · **File:** [wilab/wifi/channels.py](wilab/wifi/channels.py), [wilab/wifi/watchdog.py](wilab/wifi/watchdog.py), [wilab/runtime_cleanup.py](wilab/runtime_cleanup.py), [wilab/wifi/manager.py](wilab/wifi/manager.py) (`_get_status`)

**Problema.**

- `get_channels` risolve fuori dal lock: una lettura partita prima di `invalidate()` riscrive il suo
  risultato vecchio dopo. Annulla BUG-4 in una finestra stretta.
- DFS e watchdog: dopo un evento radar hostapd lascia `ENABLED` o cambia canale. Tre probe mancati
  sono un ripristino e tre eventi in un'ora mettono in quarantena un'antenna sana; il cambio di canale
  non arriva mai in `status.channel`. Si lega a [WD-10](#wd-10) e [HAP-9](#hap-9).
- `runtime_cleanup` dichiara "Never raises", ma `os.makedirs`, `iterdir()` e la lettura di `/proc`
  possono sollevare `OSError` durante l'avvio del servizio.
- `_get_status` fa scadere una rete con uno `stop_network` diretto: salta `_tracked_stop` e può far
  uscire `NetworkStopError` da una `GET`. Il percorso giusto è `_expire_network`.

**Come correggerlo.** Un contatore di generazione nella cache dei canali; trattare `DFS` come stato
atteso nel watchdog; `try/except OSError` in `runtime_cleanup`; togliere la scadenza da `_get_status`.

---

<a id="wd-5"></a>
### B3. WD-5 - Un adattatore che sparisce non si può ripulire né rimuovere (parziale)

**Gravità:** Alta · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:378-389](wilab/wifi/hostapd.py#L378-L389), [wilab/wifi/manager.py:449-465](wilab/wifi/manager.py#L449-L465), [wilab/config.py:172-182](wilab/config.py#L172-L182)

> **Stato (2026-11-25):** Fatti i punti 1 e 2 (stop e cleanup completi anche con l'interfaccia sparita) e la classificazione come guasto radio. **Manca** il punto 3: ritirare la voce di un'antenna che ricompare con un nome diverso; dipende da ARCH-4.

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
### B4. WD-7 - Il watchdog controlla due processi, non la rete (parziale)

**Gravità:** Media · **Confidenza:** Confermato · **File:** [wilab/wifi/watchdog.py:64-82](wilab/wifi/watchdog.py#L64-L82)

> **Stato (2026-11-25):** Il watchdog verifica ogni 30 s e ripara sul posto indirizzo del gateway, `ip_forward`, regole NAT, blocco Internet, isolamento e captive portal. **Manca** il controllo che la radio trasmetta davvero (`tx_packets`, beacon), da provare prima sull'hardware.

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

<a id="hap-5"></a>
### B5. HAP-5 - Ipotesi: avvii senza assestamento e senza serializzazione tra radio

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

<a id="rev-15"></a>
### B6. REV-15 - Frontend: funzioni dell'API 4.0.0 non usate

**Gravità:** Bassa · **Confidenza:** Confermato (lettura) · **File:** [frontend/src/app](frontend/src/app)

**Problema.**

- **Non si può annullare un avvio dalla pagina.** Nella scheda che lo ha lanciato `loading` disabilita
  tutto; nelle altre Stop è disabilitato. Il backend è pronto (`DELETE` durante `starting`).
- **`restarts` non è mostrato**, anche se il modello TypeScript lo contiene.
- **`error` di `start_failed` compare solo nel toast** della scheda che ha fatto il polling.
- **`interface` nel reserve è nel modello ma non viene mai inviato:** non si può scegliere l'antenna.
- **Nessuna compilazione né test del frontend fuori dal deploy:** non esistono `*.spec.ts` e il
  Makefile ha solo `build-frontend` (Docker, che pubblica in `frontend/dist`). Un errore di tipo si
  scopre al deploy. I test `test_frontend_*.py` controllano solo che certe stringhe siano nel sorgente.

**Come correggerlo.** Stop (o "Cancel start") abilitato con `runtimeState === 'starting'`: annulla la
sottoscrizione, chiama `stopNetwork`, poi `checkStatus` (richiede il punto 1 di [REV-13](#rev-13)).
Una riga "Watchdog restarts: AP n, DHCP m, last <reason>" quando `ap + dhcp > 0`. `status.error` sotto
l'etichetta. Una select dell'antenna nel dialog di reservation. Un target `make check-frontend` che
compila in una directory temporanea senza pubblicare.

Test: [unit-test-15](#unit-test-15).

---

<a id="bug-8"></a>
### B7. BUG-8 - Confronto del token non a tempo costante

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

<a id="rev-17"></a>
### B8. REV-17 - Residui della catena di modifiche

**Gravità:** Bassa · **Confidenza:** Confermato (lettura) · **File:** vari, elencati sotto

**Problema.** Codice e testi rimasti da passaggi intermedi. Si aggiunge a [ARCH-9](#arch-9).

- **Percorso `1004` morto:** `ReservationCleanupError` non può più arrivare a una richiesta. Sono
  morti il gestore in [wilab/api/__init__.py](wilab/api/__init__.py), `ApiErrorCode.CLEANUP_FAILED`,
  il parametro `continue_on_error` e il valore di ritorno di `_purge_expired`. `all_active`,
  `is_device_reserved` e `device_for` in [wilab/reservation.py](wilab/reservation.py) sono usati solo
  dai test.
- **Usati solo dai test:** `heartbeat.forget`, `NetworkManager.get_summary`, `services_status`,
  `execute_pkill` (con una logica `signal` sbagliata), `NatManager.disable_ip_forwarding` e
  `flush_all_rules`, `IsolationManager.flush_all` e `get_active_subnets`, `stop_all` in hostapd e
  dhcp, `check_ip_forwarding`, `command_deadline` (non più usato dopo REV-5).
- **Duplicati:** `unhandled_api_exception` ripete il middleware `answer_unexpected_errors`; "elenca
  con `-S`, trova il commento, cancella" è scritto quattro volte (nat ×2, captive, host guard); il
  test DFS `52 <= c <= 144` è in hostapd e nella route invece di `requires_dfs`; la ricerca
  dell'antenna in `config.antennas` è ripetuta una decina di volte.
- **Testi vecchi:** testi `404` delle singole route, sovrascritti da `document_errors`; descrizione
  `200` di `/status` senza `network_stop_incomplete` e `cleanup_failed`; `NetworkStatus.expires_in`
  ("until network auto-shutdown"); docstring di `channels.py`, `dhcp.py`, `isolation.flush_all`,
  `runtime_cleanup`; commento "check both self.active and hostapd" in `manager.py`; percorsi del
  frontend commentati in `wilab/api/__init__.py`.
- **Piccoli:** `disable_nat(..., subnet)` non usa il parametro; `"5"` scritto a mano in
  `host_guard.py` invece di `IPTABLES_LOCK_WAIT`; `"pid_file": None` in `hostapd.status()`;
  `execute_command(["iw", ...])` invece di `execute_iw` in due punti; la regola
  `wilab-protect-existing` resta dopo lo stop del servizio (la tolgono l'avvio successivo e `uninstall.sh`); `safety.py` consiglia uno script di
  pulizia subito prima che il servizio pulisca da solo; `scan_new_networks` documenta `ValueError` ma
  riceve `TypeError`.
- **Frontend:** `RecoveryCode.RetryLater`, `ApiErrorDetail.reservation_invalidated`, il parametro
  `showNotification` di `checkStatus`, `clientsCount`, `durationMinutes`, `token$`, il nome
  `buildSlots(networks…)`, il testo sul CORS nel messaggio di stato 0.
- **Lint:** `ruff` segnala 55 punti in `wilab/api` e 23 in `wilab/wifi` e `wilab/network`, quasi
  tutti `except Exception` generici (BLE001).

**Come correggerlo.** Un commit per gruppo, ognuno con la suite verde. Togliere prima i metodi usati
solo dai test insieme ai loro test.

---

<a id="hap-7"></a>
### B9. HAP-7 - Ipotesi: `hostapd -d` per tutta la vita dell'AP

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

<a id="rev-18"></a>
### B10. REV-18 - Struttura dei test

**Gravità:** Bassa · **Confidenza:** Confermato (lettura e misura della copertura) · **File:** [tests/unit-tests](tests/unit-tests), [tests/e2e-tests](tests/e2e-tests)

**Problema.** Copertura complessiva 89 % (5.339 istruzioni), sbilanciata:

| Area | Copertura | Nota |
|---|---|---|
| `reservation.py` | 96 % | |
| `api/routes/network.py` | 93 % | mancano i casi limite del job asincrono |
| `wifi/manager.py` | 83 % | rami di errore dello stop e TX power |
| `wifi/watchdog.py` | 80 % | ogni ramo "cleanup fallito, quindi quarantena" |
| `wifi/recovery.py` | 78 % | |
| `wifi/discovery.py` | 76 % | |
| `wifi/interface.py` | 42 % | |
| `network/safety.py` | 32 % | |

- `test_api.py` e `test_reservation.py` definiscono ciascuno le proprie fixture `client`,
  `valid_token` e `reservation_id`. Quella di `test_api` usa un `ReservationManager` senza cleanup,
  lock del dispositivo e `before_release`: il collegamento rilascio → stop della rete è saltato in
  circa 40 test.
- Una decina di test ripete lo stesso blocco di otto `monkeypatch` per avere una rete attiva: una
  fixture condivisa toglie circa 150 righe.
- I test senza `with TestClient(...)` non eseguono il lifespan. La fixture
  `_stop_background_threads`, aggiunta il 2026-11-26, ferma i thread ma nasconde il problema.
- `test_frontend_*.py` e `test_ci_workflow.py` verificano il testo di altri componenti: fragili e
  poco significativi.
- I due test più lenti (`test_commands.py`, 5 s e 2 s) usano `sleep` reali: un sesto della suite.
- In `tests/e2e-tests` non c'è alcun test per `start_failed`, `restarts`, la scelta di `interface`,
  `1009` e `1012`. I due helper `network_body` (unit ed e2e) sono copie.
- Letti solo per campione, quindi possono contenere asserzioni superate: `test_wifi`, `test_channels`,
  `test_nat`, `test_qos`, `test_dhcp`, `test_commands`, `test_config`, `test_discovery`,
  `test_isolation`, `test_captive`.

**Come correggerlo.** REV-16 è fatto (i test usano la create asincrona tramite `create_network`): ora
una sola fixture `client` con i manager collegati come in produzione, una fixture `running_network`,
poi i test dei paragrafi 4.6 e 4.7.

---

<a id="perf-1"></a>
### B11. PERF-1 - L'avvio di una rete esegue circa 20 comandi (parziale)

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:94-109](wilab/wifi/manager.py#L94-L109), [wilab/wifi/manager.py:254-272](wilab/wifi/manager.py#L254-L272), [wilab/network/dhcp.py:186-200](wilab/network/dhcp.py#L186-L200), [wilab/network/nat.py:187-313](wilab/network/nat.py#L187-L313)

> **Stato (2026-11-25):** Fatti i tagli a basso rischio (validazioni `iw` ripetute, `dnsmasq --version`, `nmcli --version`). **Manca**, non fatto di proposito, `iptables-restore` in blocco: cambierebbe come si installano e tolgono tutte le regole, appena consolidato con NET-2, SEC-3 e WD-7. I tre `nmcli` e la pausa di 0,2 s dell'elenco sotto spariscono con [NM-1](#nm-1).

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

<a id="perf-4"></a>
### B12. PERF-4 - Costo fisso del polling in background

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
### B13. PERF-7 - Memoria e descrittori: nessuna crescita trovata

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

<a id="api-7"></a>
### B14. API-7 - Azioni modellate come percorsi

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/internet.py](wilab/api/routes/internet.py), [wilab/api/routes/txpower.py:51-87](wilab/api/routes/txpower.py#L51-L87)

**Problema.** `POST /internet/enable` e `POST /internet/disable` sono due endpoint per un booleano;
impostare il TX power è una `POST`, pur essendo un'operazione idempotente.

**Come si riproduce.** Leggere l'elenco dei percorsi.

**Come correggerlo.** Aggiungere il nuovo endpoint (non breaking) e poi togliere i vecchi (breaking). Decisione del 2026-11-25: rimandato, annotato in [TODOs/api-review.md](TODOs/api-review.md).

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

<a id="arch-10"></a>
### B15. ARCH-10 - Il logging non ha una regola

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

<a id="arch-11"></a>
### B16. ARCH-11 - Cosa portare dal branch `feature/device-capabilities` (domande e proposte)

**Gravità:** Bassa · **Confidenza:** Confermato (`git show feature/device-capabilities:<file>`, 2026-11-26) · **File:** radice del repository

**Contesto.** `feature/device-capabilities` non verrà unito: è nato prima di questo branch (49 commit
da `67508ca`) e contiene migliorie mai entrate qui. Non si fa un merge: si sceglie cosa riportare,
una voce alla volta. Ogni voce sotto è una proposta da **accettare o rifiutare**; con la risposta
diventa un lavoro del blocco B (nessuna cambia il contratto delle API, tranne dove è scritto).

**A. Regole del progetto e strumenti**

| # | Proposta | Domanda | Note |
|---|---|---|---|
| A1 | Aggiungere `CLAUDE.md` con le regole del progetto, ripreso dall'altro branch e adattato a questo. | Accetti? Quali regole tenere? | Da tenere così: tutto in inglese nel repository (Fable-Notes resta l'eccezione in italiano); "cambio netto, niente compatibilità"; nessun `subprocess` fuori da `wilab/network/commands.py`; tipi ovunque; niente `print`; documentazione allineata al codice nello stesso commit; chiudere un lavoro con "cosa resta da fare". Da togliere o riscrivere: le regole sulle capability e su `POST /api/v1/device-reservation` (qui non esistono), il token GitHub in `.git/gh_token` (da confermare se lo usi ancora). Da aggiungere: le regole di questa sessione (e2e solo con conferma e a sistema libero, una riga di CHANGELOG per correzione, `copilot.md` mai nei commit, nessuna stampa di token o password). |
| A2 | Un solo `pyproject.toml` con la configurazione di pytest, ruff e mypy; togliere `pytest.ini` e `mypy.ini`. | Accetti? | Nessuna tabella `[project]` e nessuna versione lì: la versione resta in `VERSION`. Va tenuto il marker `slow` e gli altri già registrati. |
| A3 | Fissare le regole di ruff come nell'altro branch (`E4`, `E7`, `E9`, `F`). | Quale insieme di regole vuoi? | Oggi `make lint` usa le regole predefinite della versione installata e ha 83 errori già presenti (molti `B008` su `Depends()` e `BLE001`). Con l'insieme dell'altro branch gli errori quasi spariscono e `make lint` può entrare in CI. In alternativa: tenere le regole attuali e correggere o escludere i casi uno per uno. |
| A4 | Spostare `update_version.sh` in `scripts/` e togliere `run-tests.sh` (si usano pytest e il Makefile). | Accetti? | Va aggiornato chi li cita (README, docs, Makefile). |
| A5 | Report di copertura a ogni run di pytest. | Accetti? | Rallenta un po' `make test-local-quick`; si può tenere solo in `make test-local` e in CI. |
| A6 | Test indipendenti dal sistema operativo (anche Windows). | Ti serve davvero? | Qui il codice usa `/proc`, `/sys`, `/run` e comandi Linux: è molto lavoro per un servizio che gira solo su Ubuntu. Proposta: **no**. |

**B. CI e rilasci** (`.github/workflows/`)

| # | Proposta | Domanda |
|---|---|---|
| B1 | Riepilogo nel job di CI con test e copertura di backend e frontend (`scripts/ci_summary.py`). | Accetti? |
| B2 | Tenere solo le 3 run più recenti di ogni pull request (`scripts/cleanup_pr_runs.py`), senza cron. | Accetti? |
| B3 | Bundle della documentazione API con nome che porta la versione, tenuto 90 giorni, e allegato a ogni release GitHub (`release-docs.yml`). | Accetti? |
| B4 | Test unit del frontend e build del container del frontend in CI. | Accetti? Il frontend verrà rifatto: forse solo la build. |

**C. Documentazione delle API**

| # | Proposta | Domanda |
|---|---|---|
| C1 | `OPENAPI_TAGS` con una descrizione per ogni gruppo e `System` sempre per primo; foglio di stile condiviso (`wilab/api/docs_style.py`) che mostra le descrizioni sotto il titolo in `/docs` e nello `swagger.html` esportato. | Accetti? Da confrontare con quanto c'è già qui. |
| C2 | `swagger.html` esportato autonomo, con i riferimenti allo schema già risolti. | Accetti? |

**D. Correzioni e funzioni dell'altro branch**

| # | Proposta | Domanda | Stato qui |
|---|---|---|---|
| D1 | `make reload-drivers` e `scripts/reload-drivers.sh`: ricaricare il driver degli adattatori a servizio fermo, con il Python del servizio installato. | Ti serve? | Non c'è. |
| D2 | Un hostapd ucciso da un segnale riportato come crash con un suggerimento sul driver (`122215e`). | Accetti? | In parte: qui `HostapdSegfault` esiste; manca il suggerimento nel messaggio. |
| D3 | Capability dichiarate in `config.yaml` e `required_capabilities` nella reservation. | Le vuoi in futuro? | No in questo branch: qui le antenne sono scoperte e la scelta dei canali passa da `GET /antennas/{interface}`. Riportarle è un cambio di API: non nella 4.1. |
| D4 | Avviso "TX power non garantito" in API, UI, troubleshooting e CHANGELOG. | — | Già coperto qui: TX power dichiarato in debug (gruppo T). |
| D5 | Pulizia delle regole all'avvio e NAT limitato alla subnet; Internet disattivato che taglia le connessioni aperte. | — | Già presenti qui (4.0.0). |

**E. Regole sul CHANGELOG** (dall'altro branch)

Sezioni nell'ordine Breaking Changes, Features, Bug Fixes, Maintenance, CI/CD, Tests; frasi brevi
scritte per chi usa il prodotto; test elencati solo se danno valore; data aggiornata quando si
modifica una versione già datata. **Domanda:** le adottiamo, in aggiunta alla regola già in uso qui
"una riga per correzione e il capitolo di migrazione delle API"?

Nota: l'altro branch usa CRLF nel working tree; qui `.gitattributes` impone LF ovunque. Proposta:
tenere LF.

---

<a id="bug-9"></a>
### B17. BUG-9 - Un profilo QoS personalizzato può impedire l'avvio del servizio

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

<a id="net-13"></a>
### B18. NET-13 - QoS: lo stop del profilo può far fallire lo stop della rete

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

<a id="race-3"></a>
### B19. RACE-3 - Lo stato di `QosManager` non ha lock

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

<a id="net-12"></a>
### B20. NET-12 - QoS: gara alla fine di un profilo `once`

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

<a id="net-11"></a>
### B21. NET-11 - QoS inline: `upload_quality` ignorato

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

<a id="wd-8"></a>
### B22. WD-8 - Una rete ripristinata perde il profilo QoS

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

<a id="txp-1"></a>
### T1. TXP-1 - TX power da debuggare

**Gravità:** Media · **Confidenza:** Confermato (nessun adattatore in uso ha mai applicato la potenza
richiesta) · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py) (`_set_tx_power`,
`set_tx_power_level`, `get_tx_power_info`), [wilab/api/routes/txpower.py](wilab/api/routes/txpower.py)

**Problema.** `iw dev <if> set txpower fixed <mBm>` non ha mai prodotto un cambio verificabile sugli
adattatori in uso (mt7921u): `POST .../txpower` risponde spesso `422` "does not support dynamic power
change", e il valore riportato da `iw dev <if> info` non segue quello richiesto. Il comando viene
comunque inviato a ogni avvio (HAP-6). Nella 4.1.0 la funzione è dichiarata non stabile.

**Come procedere.** Prima capire, poi correggere:

1. Sulla macchina, con un AP attivo e nessun client: `iw dev <if> info` (riga `txpower`), poi
   `iw dev <if> set txpower fixed 1000`, attesa di 1 s, di nuovo `iw dev <if> info`; ripetere con
   `limit` invece di `fixed` e con `auto`. Annotare cosa cambia.
2. Controllare il dominio regolatorio (`iw reg get`) e il limite del canale (`iw phy <phy> channels`):
   il driver può rifiutare un valore sopra il limite o ignorare uno sotto il minimo dell'hardware.
3. Controllare se `mt7921u` supporta il controllo per interfaccia o solo per phy
   (`iw phy <phy> set txpower fixed ...`), e se `hostapd` sovrascrive la potenza all'avvio.
4. Se il driver non lo supporta: dirlo nelle API (per esempio `max_dbm` e `levels_dbm` vuoti, un `409`
   o `422` con un motivo stabile) e non inviare più il comando all'avvio. Se lo supporta: correggere
   comando e verifica, poi BUG-7 e PERF-6.

Solo dopo questo punto il TX power si può dichiarare stabile.

---

<a id="bug-7"></a>
### T2. BUG-7 - TX power: stato incoerente dopo un mismatch

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

<a id="perf-6"></a>
### T3. PERF-6 - Il cambio di TX power blocca per 3 secondi

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

<a id="hap-6"></a>
### T4. HAP-6 - Ipotesi: il TX power viene cambiato subito dopo l'avvio

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

<a id="perf-2"></a>
### ✅ PERF-2 - `GET .../network` costa due o tre comandi a chiamata

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:505-565](wilab/wifi/manager.py#L505-L565), [wilab/wifi/manager.py:660-713](wilab/wifi/manager.py#L660-L713)

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
### ✅ PERF-5 - Timeout minimo di 5 s imposto in silenzio

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:160-183](wilab/network/commands.py#L160-L183), [wilab/network/subnet.py:12](wilab/network/subnet.py#L12)

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

<a id="arch-1"></a>
### ✅ ARCH-1 - `NetworkManager` fa troppe cose

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py)

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

<a id="arch-2"></a>
### ✅ ARCH-2 - Classificazione dei guasti sparsa in quattro posti

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/wifi/hostapd.py:62-78](wilab/wifi/hostapd.py#L62-L78), [wilab/wifi/manager.py:60-64](wilab/wifi/manager.py#L60-L64), [wilab/api/routes/network.py:232-251](wilab/api/routes/network.py#L232-L251), [wilab/wifi/watchdog.py:133-142](wilab/wifi/watchdog.py#L133-L142)

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

<a id="arch-3"></a>
### ✅ ARCH-3 - Il modello dell'API è anche lo stato interno (parziale)

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:374-394](wilab/wifi/manager.py#L374-L394), [wilab/wifi/manager.py:516-565](wilab/wifi/manager.py#L516-L565)

> **Stato (2026-11-25):** La create usa `NetworkCreateBody` e la `GET .../network` `NetworkResponse`, separati dal modello interno. **Manca** una dataclass interna al posto di `NetworkStatus` in `manager.active` (che porta ancora `_expires_at_timestamp`).

**Problema.** `NetworkStatus`, il modello di risposta, è conservato in `manager.active`, modificato a
ogni lettura, e porta un attributo nascosto impostato con `object.__setattr__` e letto con `hasattr`
(`_expires_at_timestamp`). È la ragione per cui lo stato riportato è "ciò che Wi-Lab ricorda" e non
"ciò che il sistema fa".

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

<a id="arch-4"></a>
### ✅ ARCH-4 - Il registro dei dispositivi esiste in quattro copie

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/config.py:26-39](wilab/config.py#L26-L39), [wilab/reservation.py:83-87](wilab/reservation.py#L83-L87), [wilab/wifi/watchdog.py:23](wilab/wifi/watchdog.py#L23), [wilab/wifi/manager.py:81](wilab/wifi/manager.py#L81), [wilab/api/dependencies.py:66-89](wilab/api/dependencies.py#L66-L89)

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

<a id="arch-5"></a>
### ✅ ARCH-5 - Singleton collegati per effetto collaterale

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/api/dependencies.py:20-56](wilab/api/dependencies.py#L20-L56), [wilab/wifi/manager.py:86-91](wilab/wifi/manager.py#L86-L91)

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
### ✅ ARCH-6 - Tre modi di gestire un processo figlio

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:49-157](wilab/network/commands.py#L49-L157), [wilab/network/dhcp.py](wilab/network/dhcp.py)

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

<a id="arch-8"></a>
### ✅ ARCH-8 - Attributi privati usati tra classi

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:158](wilab/wifi/manager.py#L158), [wilab/wifi/manager.py:525](wilab/wifi/manager.py#L525)

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

<a id="arch-9"></a>
### ✅ ARCH-9 - Codice morto

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-27 · **Confidenza:** Confermato (ogni nome è stato cercato in `wilab/`) · **File:** vari

**Problema.** Funzioni e modelli senza chiamanti nel codice di produzione:

| Elemento | File | Nota |
|---|---|---|
| `NatManager.flush_all_rules` | `network/nat.py` | Svuoterebbe tutta la tabella NAT dell'host, Docker compreso. Non deve esistere nemmeno inutilizzata. |
| `NatManager.disable_ip_forwarding` | `network/nat.py` | |
| `IsolationManager.flush_all`, `get_active_subnets` | `network/isolation.py` | |
| `execute_pkill` | `network/commands.py` | |
| `HostapdManager.stop_all`, `DhcpServer.stop_all` | `wifi/hostapd.py`, `network/dhcp.py` | |
| `NetworkManager.get_summary` | `wifi/manager.py` | "Backward-compatible", contro la regola del progetto |
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

<a id="stab-5"></a>
### ✅ STAB-5 - Le scadenze usano l'orologio di sistema

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Confermato · **File:** [wilab/reservation.py:48-71](wilab/reservation.py#L48-L71), [wilab/wifi/manager.py:952-955](wilab/wifi/manager.py#L952-L955), [install/systemd/wi-lab.service.template](install/systemd/wi-lab.service.template)

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

<a id="stab-2"></a>
### ✅ STAB-2 - File di runtime in `/tmp`

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Probabile · **File:** [wilab/wifi/hostapd.py:23](wilab/wifi/hostapd.py#L23), [wilab/network/dhcp.py:11-12](wilab/network/dhcp.py#L11-L12), [wilab/network/dhcp.py:317-331](wilab/network/dhcp.py#L317-L331)

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

<a id="rev-13"></a>
### ✅ REV-13 - Frontend: errori nel polling della create

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Probabile (lettura; il frontend non è stato compilato) · **File:** [frontend/src/app/services/wilab-api.service.ts](frontend/src/app/services/wilab-api.service.ts) (`startNetwork`), [frontend/src/app/components/network-card/network-card.component.ts](frontend/src/app/components/network-card/network-card.component.ts), [network-card.component.html](frontend/src/app/components/network-card/network-card.component.html), [frontend/src/app/services/recovery-response.ts](frontend/src/app/services/recovery-response.ts)

**Problema.**

1. **Un avvio annullato è riportato come riuscito.** Il polling finisce con
   `runtime_state !== 'starting'` e la card considera successo tutto tranne `start_failed`. Dopo un
   annullamento da un'altra scheda la `GET` risponde `active: false, runtime_state: null`: compare
   "WiFi network started successfully" su una rete non attiva.
2. **Un errore su una sola `GET` ferma il polling.** Uno stato 0, un `502/504` di un proxy o un
   `503 / 1006` appena finito il job mostrano "Failed to start network" mentre il server continua.
   Se l'esito è `start_failed`, `error.stage` e `error.message` non vengono mai mostrati.
3. **Il polling può restare senza risposta e non ha limite di tempo.** `timer(1500, 1500)` con
   `switchMap` annulla la `GET` in corso a ogni tick: se la `GET` impiega più di 1,5 s (dopo il job
   prende il lock ed esegue `iw`), nessuna arriva mai. La card resta su "Starting WiFi..." con tutti i
   pulsanti disabilitati, Release compreso.
4. **Una card che non ha lanciato l'avvio è incoerente durante `starting`** (ricarica della pagina,
   seconda scheda): mostra "Starting the access point..." e sotto "Access point not active"; Start WiFi
   è abilitato e con altri parametri risponde `409 / 1008` con il testo "already running … Stop it
   first" mentre Stop è disabilitato.
5. **Etichetta `start_failed` vecchia durante un nuovo avvio:** `checkStatus` è sospeso mentre
   `createMessage` è impostato.
6. **Stato già finito ancora mostrato:** `status?.runtime_state ?? slot.runtimeState` tratta `null`
   (rete attiva) come "sconosciuto" e usa il valore di `/status`, aggiornato ogni 10 s.
7. **`404` con `reservation_released` o `reservation_not_found`:** messaggio generico con il JSON
   grezzo.

**Come correggerlo.** (1) Successo solo con `active: true`; `!active && runtime_state == null` è
"avvio annullato". (2) Ripetere la `GET` su stato 0, `5xx` e `1006`; mostrare `status.error` nella
card. (3) `exhaustMap` e un limite superiore che ricade sul polling normale. (4) Un getter `starting`
che disabilita Start, nasconde il messaggio "non attiva" e mostra lo spinner; testo `1008` che copre
anche "is starting". (5) Impostare `status` dalla risposta `202`. (6) Usare `slot.runtimeState` solo
con `status === null`. (7) Una frase per ogni `reason`.

Test: [unit-test-15](#unit-test-15).

---

<a id="rev-14"></a>
### ✅ REV-14 - Frontend: difetti già presenti prima di questo ciclo

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Probabile (lettura) · **File:** [frontend/src/app/app.component.ts](frontend/src/app/app.component.ts) (`restoreReservations`), [network-card.component.html](frontend/src/app/components/network-card/network-card.component.html), [network-form-dialog.component.ts](frontend/src/app/components/network-form-dialog/network-form-dialog.component.ts)

**Problema.**

1. **Una ricarica durante un problema del backend dimentica tutti gli ID.** `restoreReservations`
   scarta una reservation salvata per qualunque errore della `GET /reservations/{id}`, non solo per
   `404`, e poi sovrascrive il localStorage. Ricaricando mentre il servizio riparte (stato 0), con un
   `401` o un `5xx`, gli ID spariscono: le card mostrano "Reserved by another user" e una reservation
   illimitata si libera solo con Release All. È il più grave dei punti del frontend.
2. **Etichette che indicano un pulsante disabilitato.** `restore_failed` dice "Stop WiFi to give up",
   ma la `GET` riporta `active: false` e Stop è disabilitato con `!status?.active`; lo stesso per
   `start_failed`. Il backend risponde `200` alla `DELETE` in entrambi gli stati.
3. **Il messaggio di quarantena è nel blocco sbagliato:** sta dentro `*ngIf="isMine"`, ma
   un'antenna in quarantena di norma non è mia (la quarantena invalida la reservation): la card resta
   vuota.
4. **Doppio clic su Start WiFi:** due dialog sovrapposti; il risultato del secondo è scartato.
5. **Password vuota accettata dal dialog** (manca `required` all'inizio) e `maxLength(32)` conta i
   caratteri mentre il backend conta i byte UTF-8.

**Come correggerlo.** (1) Scartare solo con `404`; negli altri casi tenere l'ID e mostrare l'errore.
(2) Abilitare Stop con `restore_failed`, `start_failed` e `starting`. (3) Spostare il blocco fuori da
`isMine`. (4) Un flag mentre `getAntenna` è in corso. (5) `Validators.required` e un validatore sui
byte.

---

<a id="hap-8"></a>
### ✅ HAP-8 - L'output di hostapd non viene conservato (parziale)

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Confermato · **File:** [wilab/network/commands.py:52-83](wilab/network/commands.py#L52-L83), [wilab/wifi/hostapd.py:330-339](wilab/wifi/hostapd.py#L330-L339)

> **Stato (2026-11-25):** Con `hostapd_debug_dir` impostato in `config.yaml`, ogni avvio di hostapd fallito scrive un report con la configurazione (senza password) e le ultime 400 righe di `hostapd -d`. **Manca** l'output quando il watchdog trova morto hostapd su una rete attiva, e un estratto anche senza `hostapd_debug_dir`, oggi facoltativo.

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

<a id="rev-11"></a>
### ✅ REV-11 - Risposte delle API fuori dal contratto in casi rari

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-26: punto 1 documentato (`1006` sulla create ripetuta), punti 2, 3, 5 corretti, punto 4 con REV-11 strict · **Confidenza:** Confermato per i primi due punti (TestClient); Probabile per gli altri · **File:** [wilab/api/routes/network.py](wilab/api/routes/network.py), [wilab/api/routes/txpower.py](wilab/api/routes/txpower.py), [wilab/api/routes/internet.py](wilab/api/routes/internet.py), [wilab/models.py](wilab/models.py)

**Problema.**

1. **La create può rispondere `503 / 1006`.** Il ramo "stesso body su una rete attiva" usa
   `hold_reservation` con il timeout di 5 s. Documentazione e OpenAPI dicono che la create non risponde
   mai `1006`.
2. **`404` con `reason: not_found` su una reservation valida.** In TX power, Internet e rete ogni
   `ValueError` diventa `404`: per esempio `GET .../txpower` quando `_get_channel_capabilities`
   solleva "Channel N not supported". Il contratto dice che un `404` su queste chiamate ha sempre uno
   dei quattro motivi della reservation. I rami `UNKNOWN_ANTENNA` sembrano irraggiungibili.
3. **Un `start_failed` sopravvive alla scadenza.** La scadenza non chiama `before_release`: il job
   resta in `start_jobs` finché la reservation successiva su quell'antenna fa una chiamata. Al massimo
   uno per antenna, non visibile ai client.
4. **Tipi accettati per sbaglio.** pydantic in modalità non stretta accetta `radio.channel: true`
   (canale 1), `"6"`, `duration_seconds: "120"` e `level: true`.
5. **`next_available_in` arrotondato in modo diverso.** Per un'antenna con il cleanup fallito il reserve
   (`409 / 1005`) dà `next_available_in` troncato (`int` di una differenza di orari), mentre `/status`
   arrotonda per eccesso (`ceil`) la stessa attesa: 4 contro 5 s. Trovato dal test del 2026-11-26.

**Come correggerlo.** (1) Costruire il `200` senza lock del dispositivo, oppure documentare `1006`
anche sulla create. (2) `422` o `503` per i casi raggiungibili; togliere i rami morti. (3) Chiamare
`cancel_start` anche alla scadenza. (4) `strict=True` su quegli interi (è una modifica visibile ai
client: decidere prima del rilascio). (5) Calcolare `next_available_in` come `/status`, con `ceil`.

Test: `test_error_codes.py::test_every_operation_with_a_reservation_id_answers_404_with_the_exact_reason`
(i motivi della reservation; il punto 2 manca), `test_cleanup_backoff.py::test_reserve_next_available_in_equals_the_cleanup_wait`
(`xfail` stretto finché il punto 5 non è corretto).

---

<a id="net-8"></a>
### ✅ NET-8 - `dns_server` ha come default un indirizzo di laboratorio

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Confermato · **File:** [wilab/config.py:37](wilab/config.py#L37)

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

<a id="stab-7"></a>
### ✅ STAB-7 - Dipendenze non bloccate

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26 · **Confidenza:** Confermato · **File:** [requirements.txt](requirements.txt)

**Problema.** `requirements.txt` ha solo limiti inferiori (`fastapi>=0.110.0`, `pydantic>=2.6.0`,
`uvicorn>=0.27.0`, ...). Una reinstallazione tra sei mesi può portare una versione che cambia
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

<a id="rev-2"></a>
### ✅ REV-2 - Annullare un avvio il cui rollback fallisce mette l'antenna in quarantena

**Gravità:** Media · **Stato:** ✅ corretto il 2026-11-26, con test unit · **Confidenza:** Confermato (riprodotto con il TestClient) · **File:** [wilab/api/routes/network.py](wilab/api/routes/network.py) (`_run_start`)

**Problema.** Con una `DELETE` della reservation o della rete durante `starting`, se il rollback
solleva `StartupFailure(cleanup_failed=True)` l'annullamento viene ignorato e il codice prosegue fino a
`quarantine_radio`:

- `DELETE /reservations/{id}` risponde `404` con `reservation_invalidated` (il contratto dice che il
  rilascio non fallisce mai) e l'antenna va in `recovery_state: unavailable`;
- `DELETE .../network` risponde `200` "stopped", ma la `GET` successiva è `404` con
  `reservation_invalidated`.

**Come si riproduce.** Avvio bloccato, `DELETE` della reservation, rollback che fallisce (stop di
hostapd che solleva).

**Come correggerlo.** Quando `cancel.is_set()` e il cleanup è fallito, sollevare `StartCancelled` e
lasciare il dispositivo al percorso normale: il rilascio lo consegna al cleanup in background (come
ogni rilascio con cleanup fallito), la stop della rete risponde `503 / 1012`.

Test: [unit-test-2](#unit-test-2).

---

<a id="rev-9"></a>
### ✅ REV-9 - `stop_failed` segna anche stop che non sono del client

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-26, con test unit · **Confidenza:** Probabile (lettura del codice) · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py) (`_stop_failed`), [wilab/api/routes/status.py](wilab/api/routes/status.py)

**Problema.** Anche un rollback di avvio fallito, uno stop per scadenza o un cleanup del watchdog
impostano `_stop_failed`. `/status` riporta allora `runtime_state: stop_failed` e
`network_stop_incomplete` ("il proprietario ripete la `DELETE`") per un'antenna la cui reservation è
in quarantena o scaduta, e nasconde per essa i motivi di hostapd, dnsmasq e NAT. Inoltre, mentre una
rete è `stop_failed`, resta in `manager.active` con `active: true`: Internet, TX power e QoS operano
su una rete fermata a metà invece di rispondere `1012`.

**Come correggerlo.** Impostare il flag solo nello stop di una rete attiva chiesto dal client; nelle
route di Internet, TX power e QoS rispondere `409 / 1012` quando `manager.stop_failed(device)`.

---

<a id="hap-9"></a>
### ✅ HAP-9 - Canali DFS con controllo radar di 10 minuti

**Gravità:** Bassa · **Stato:** ✅ corretto il 2026-11-26, con test unit · **Confidenza:** Probabile · **File:** [wilab/wifi/hostapd.py:29](wilab/wifi/hostapd.py#L29), [wilab/wifi/hostapd.py:249](wilab/wifi/hostapd.py#L249)

> **Aggiornamento (2026-11-25).** Con la create asincrona il client non va più in timeout: riceve `202` e legge lo stato. Resta il problema del server: sui canali radar meteo (120, 124, 128) i 75 s di `DFS_READY_TIMEOUT` non bastano e l'avvio fallisce come guasto radio. `allow_dfs_channels` si chiama ora `show_dfs` ed è per antenna.

**Problema.** Il timeout per i canali da 52 a 144 è 75 s. In Europa i canali dei radar meteo (120, 124,
128) richiedono 600 s di ascolto. Con `allow_dfs_channels: true` una richiesta su quei canali va sempre
in timeout e viene trattata come guasto radio, fino alla quarantena.

**Come si riproduce.** Con `allow_dfs_channels: true` e `country_code` europeo, creare una rete sul
canale 124.

**Come correggerlo.** Per la 4.1.0 solo la via semplice: rifiutare quei canali. `allow_dfs_channels`
qui sotto è il vecchio nome di `show_dfs`.

```python
# wilab/wifi/channels.py
# ETSI weather-radar channels need a 10-minute radar check, longer than any request can wait.
LONG_CAC_CHANNELS = frozenset({120, 124, 128})
```

In `validate_channel`, per la banda `5ghz`: se `channel in LONG_CAC_CHANNELS` sollevare
`ValueError("Channel ... requires a 10-minute radar check and is not supported")`, e toglierli
dall'elenco di `GET .../channels`. La via completa, non per la 4.x perché aggiunge uno stato alle API:
leggere `cac_time` dalla riga `DFS-CAC-START` di hostapd e usarlo come timeout, rispondendo subito al
client con uno stato "radar check in corso".

---

<a id="rev-5"></a>
### ✅ REV-5 - Il budget di 20 s dei tentativi interni è un residuo della create sincrona

**Gravità:** Media · **Confidenza:** Probabile (lettura del codice) · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py) (`STARTUP_RETRY_BUDGET`, `_start_network`)

**Problema.** Il budget serviva a tenere corta la richiesta HTTP. Con `202` e polling non serve più e
produce esiti sbagliati:

- un tentativo che porta su tutta la rete subito dopo `retry_deadline` viene smontato e riportato come
  `StartupFailure(radio=False, stage="hostapd")`, cioè `start_failed`;
- durante un tentativo ogni comando è limitato da `command_deadline`: se il budget finisce in una fase
  successiva, `bounded_timeout` solleva "Deadline expired before running command" e il guasto viene
  attribuito a `gateway`, `dhcp`, `nat` o `host_guard`, che non hanno colpa;
- sui canali DFS un nuovo tentativo non può riuscire: `_wait_until_ready` riceve al massimo 19 s e il
  CAC ne richiede 60.

**Come correggerlo.** Togliere il limite di tempo dal percorso del job: restano il numero dei
tentativi e la scadenza della reservation (`_start_time(req)`). Non far mai fallire un avvio che è
arrivato in fondo. Si lega a [HAP-9](#hap-9).

Test: [unit-test-4](#unit-test-4).

---

<a id="rev-6"></a>
### ✅ REV-6 - Gli avvii che non passano dal job della create non si possono annullare

**Gravità:** Media · **Confidenza:** Probabile (lettura del codice) · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py) (`shutdown_all`, `probe_recovered_radio`), [wilab/wifi/watchdog.py](wilab/wifi/watchdog.py) (`_restore_ap`, `_retry_pending`)

**Problema.**

- `shutdown_all` non chiama `cancel_start`: `release_device` aspetta il lock del dispositivo, che una
  create tiene per tutta la sua durata (pause di 5 e 10 s comprese). Nel caso peggiore più volte 75 s
  su DFS, oltre il timeout di arresto di systemd: `SIGKILL` e processi orfani. Aggrava
  [STAB-8](#stab-8).
- Il watchdog chiama `start_network` senza `cancelled`: una `DELETE` della reservation durante un
  ripristino non trova job e aspetta il lock senza limite (fino a 75 s + 20 s su DFS). Il rilascio
  "immediato" del contratto vale solo durante una create.
- `probe_recovered_radio` prova sull'ultimo canale usato anche se è DFS: 60 s di CAC sotto il lock.

**Come correggerlo.** `shutdown_all` imposta `cancel` su ogni job prima di rilasciare; il watchdog
passa `cancelled=lambda: self._cancelled(reservation)`; il probe usa un canale non DFS.

Test: [unit-test-5](#unit-test-5).

---

<a id="bug-5"></a>
### ✅ BUG-5 - La discovery può ignorare un adattatore per sempre

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

<a id="stab-8"></a>
### ✅ STAB-8 - L'arresto ordinato può superare `TimeoutStopSec=30s`

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
### ✅ WD-10 - Tre probe lenti riavviano un AP forse sano

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

<a id="bug-6"></a>
### ✅ BUG-6 - `validate_interface_ap_mode` non dimostra nulla

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
### ✅ NET-9 - Le subnet non sono stabili tra un riavvio e l'altro

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/wifi/manager.py:111-141](wilab/wifi/manager.py#L111-L141)

**Problema.** L'allocatore salta ogni subnet che si sovrappone a una route dell'host. Dopo un riavvio
non pulito, una radio che ha ancora il vecchio indirizzo fa sembrare "in uso" la propria subnet
precedente: il dispositivo riceve la successiva e la tiene per tutta la vita del processo. I client che
si aspettano una subnet precisa la vedono cambiare.

**Come si riproduce.** Rete attiva sul primo adattatore (subnet base), `kill -9` del servizio, riavvio,
nuova rete sullo stesso adattatore: la subnet è la base più uno.

**Come correggerlo.** La causa sparisce con `reset_interface` alla scoperta del dispositivo (STAB-4),
che toglie l'indirizzo prima di qualunque allocazione.

> **Stato (2026-11-26):** già risolto da STAB-4; il test
> `test_a_stale_gateway_address_does_not_shift_the_subnet` lo dimostra.

---

<a id="net-7"></a>
### ✅ NET-7 - I file dei lease sopravvivono alla reservation

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

<a id="rev-8"></a>
### ✅ REV-8 - `cancel_start` dimentica il job dopo 30 s anche se il thread gira ancora

**Gravità:** Bassa · **Confidenza:** Probabile (lettura del codice) · **File:** [wilab/wifi/manager.py](wilab/wifi/manager.py) (`cancel_start`)

**Problema.** Dopo `CANCEL_TIMEOUT` il job viene tolto da `start_jobs` mentre il suo thread lavora
ancora. `DELETE .../network` risponde `503 / 1006` e il job resta orfano: un suo guasto successivo non
è mai visibile come `start_failed`, e una nuova create accoda un secondo thread che può finire in
`start_failed` se l'orfano riesce. Serve un avvio bloccato per più di 30 s fuori dall'attesa di
hostapd (l'annullamento è controllato solo lì e prima di un nuovo tentativo).

> **Fatto (2026-11-26):** `cancel_start` toglie il job solo se è finito; il test è unit-test-7.

**Come correggerlo.** Non cancellare un job che non è `done`: lo toglie `_run_job` quando finisce.

Test: [unit-test-7](#unit-test-7).

---

<a id="api-6"></a>
### ✅ API-6 - Nomi incoerenti

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/](wilab/api/routes/)

> **Fatto (2026-11-26):** `POST .../txpower` prende `tx_power_level` invece di `level`, come `radio.tx_power_level` della create (test `test_strict_types.py`). Il resto era già fatto nella 4.0.0.

**Problema.** Il percorso dice `/interface/{reservation_id}`: il parametro è una reservation, non
un'interfaccia. La creazione usa `tx_power_level`, l'endpoint del TX power usa `level`. Gli errori
citano `device_id`, un nome che nell'API non esiste. `device-reservation` è al singolare.

**Come si riproduce.** Leggere l'elenco dei percorsi in `/docs`.

**Come correggerlo.** **Breaking**, da fare una volta sola insieme alle altre (i percorsi sono già stati rinominati nella 4.0.0, vedi il riquadro Stato).

- `/api/v1/reservations` e `/api/v1/reservations/{id}` al posto di `/device-reservation`;
- `/api/v1/reservations/{id}/network`, `/internet`, `/txpower`, `/qos/profile`, `/channels`;
- messaggi di errore con "reservation" o "network" al posto di `device_id`.

Per una transizione morbida si possono registrare gli stessi router due volte, con il vecchio prefisso
marcato `deprecated=True`, per una versione. La regola del progetto ("cambio netto, niente livelli di
compatibilità") suggerisce invece di farlo in una sola versione maggiore.

---

<a id="stab-9"></a>
### ✅ STAB-9 - Il rilascio da NetworkManager è solo a runtime (superato da NM-1)

**Fatto e superato.** `nmcli device set <if> managed no` si perdeva a ogni riavvio di NetworkManager;
[wilab/network/unmanaged.py](wilab/network/unmanaged.py) scrive anche
`/run/NetworkManager/conf.d/00-wilab-unmanaged.conf`. [NM-1](#nm-1) toglie tutto questo codice: Wi-Lab
non parla più con NetworkManager. Non c'è nulla da provare: su questa macchina NetworkManager non è
più installato.

---

<a id="cap-4"></a>
## 4. Test e prove da fare

Solo test di punti aperti o generali. I test unit vanno in `tests/unit-tests/` (hardware simulato), gli e2e in
`tests/e2e-tests/` ([docs/e2e-testing.md](docs/e2e-testing.md)). Un test che oggi fallirebbe si scrive insieme alla correzione.

### 4.1 Strumenti di prova

✅ `FakeClock` e `CommandRecorder` sono in `tests/unit-tests/helpers.py` (con `test_helpers.py`).
**Manca** il terzo: un giro di watchdog chiamabile. `_watch` è ancora un ciclo infinito con lo stato
in variabili locali; va estratto in un metodo `tick(state)` con lo stato in una piccola dataclass per
dispositivo. È un refactoring puro, serve a T-20 e rende provabili WD-1, WD-2, WD-3 e WD-10 senza
thread e senza attese.

### 4.2 Test automatici

Fatti e tolti da qui: T-13 e T-21 (`test_lifecycle_hygiene.py`; T-21 con 200 cicli invece di 2.000, per
restare nella suite veloce), T-18 (`TestWallClockJumps` in `test_reservation.py`, con STAB-5).
Restano quelli che oggi fallirebbero e si scrivono con la correzione: T-01 (SEC-1, aperto di
proposito), T-19 (BUG-9, NET-11, QoS sperimentale), T-20 (serve il giro di watchdog del 4.1).

| Id | Cosa verifica | Schede | File proposto |
|---|---|---|---|
| T-01 | La route del frontend non esce dalla propria cartella | SEC-1 | `tests/test_frontend_static.py` |
| T-19 | Catalogo QoS con profili sbagliati e QoS inline | BUG-9, NET-11 | `tests/test_qos_profile.py` |
| T-20 | Simulazione di lunga durata con guasti casuali | WD, HAP (regressione) | `tests/test_soak.py` |

**T-01 - Route del frontend.** Creare una cartella temporanea `root/app/` con `index.html` e un file
`root/secret.txt` fuori da essa; sostituire `_candidate_frontend_paths` perché restituisca
`root/app`; costruire l'app. Chiamare direttamente la funzione della route (non il client HTTP, che
normalizza i percorsi) con tre valori di `full_path`: `"../secret.txt"`, il percorso assoluto di
`secret.txt`, e `"/" + percorso assoluto`. In tutti i casi la risposta non deve essere il file
segreto. Un quarto caso con `"index.html"` deve restituirlo. Per ottenere la funzione: cercare tra
`app.routes` quella con `path == "/{full_path:path}"` e usare `.endpoint`.

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

### 4.3 Prove su hardware (manuali o con marker `hardware`)

Non possono girare in CI. Vanno eseguite sulla macchina di laboratorio, una volta per confermare i
punti "Probabile" e "Ipotesi", e poi a ogni cambio di kernel, driver o adattatore. Conviene raccoglierle
in uno script sotto `diagnostics/` che stampa un esito per riga.

| Id | Prova | Conferma |
|---|---|---|
| H-01 | `curl --path-as-is http://<host>:8080//etc/hostname` | SEC-1 |
| H-04 | 200 cicli crea/cancella su due adattatori, in parallelo e in sequenza | HAP-5 |
| H-05 | 24 ore con e senza comando TX power; contare i timeout del firmware nel log del kernel | HAP-6 |
| H-06 | `kill -9` del servizio con reti e QoS attivi; verificare `tc`, file e subnet dopo il riavvio | NET-9 |
| H-11 | `systemd-tmpfiles --cat-config` e rete attiva oltre il limite di età | STAB-2 |
| H-12 | Rete attiva per 7 giorni con un client che scarica a intervalli; registrare ogni interruzione | obiettivo generale |

H-12 è la prova di accettazione: nessuna delle correzioni vale se una rete non resta su per una
settimana. Va lasciata girare in permanenza su un adattatore dedicato, con un piccolo client che ogni
minuto si collega, ottiene un indirizzo, raggiunge Internet e registra l'esito.

### 4.4 Prove sulla macchina: tester (solo API)

Prerequisito: il servizio deve girare con l'ultimo commit (`GET /api/v2/status` → `version`, e il
journal all'avvio). Ogni modifica è attiva solo dopo un riavvio del servizio successivo al suo commit.
Il contratto delle API è in [docs/ap-creation-procedure.md](docs/ap-creation-procedure.md) e
[docs/error-codes.md](docs/error-codes.md).

#### Monitoraggio continuo, da tenere attivo in ogni run

| # | Passi | Esito atteso | E2E |
|---|---|---|---|
| M1 | Interrogare `GET /api/v2/status` ogni 10–30 s per tutta la run e registrare `status`, ogni voce di `degraded_reasons` e ogni antenna con `recovery_state` o `runtime_state`. | Con un'antenna in quarantena: `status: degraded` anche con `active_networks: 0`. Nessun `degraded` senza un motivo. | ✅ [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py) |
| M2 | Per ogni create che finisce con `404` e `reason: reservation_invalidated`, annotare l'antenna e seguirla in `/status`. | L'antenna torna senza `recovery_state` da sola: entro circa 11 minuti se `recovering`, entro il backoff (al massimo 15 minuti) se `unavailable`. | ✅ [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py) |
| M3 | Leggere `GET .../network` prima e dopo ogni test e confrontare `restarts`. | Ogni aumento di `restarts.ap` corrisponde a un `restoring_ap` visto in M1; `last_reason` dice il motivo. |  |

#### Run di regressione (SOAK)

Rieseguire la run completa (sameres, parallel, herd, chaos, mix) con entrambe le antenne per
almeno 90 minuti, con M1–M3 attivi.

Atteso:
- ogni create risponde `202` (o `200` con lo stesso body su una rete attiva) e il polling finisce con la
  rete, con `start_failed` o con `404` e un `reason`; mai uno stato `starting` che non finisce;
- nessun `500` generico, nessun `409 / 1001` e nessun `503 / 1004` (non esistono più);
- nessuna antenna `unavailable` alla fine;
- create con SSID non validi → `422`.

#### Test previsti per gli ID aperti

| ID | Test via API | Esito atteso dopo il fix | E2E |
|---|---|---|---|
| WD-10 | Run lunga con M1 e M3. | Nessun `restoring_ap` e nessun aumento di `restarts.ap` su reti senza guasti. |  |
| HAP-9 | Con `show_dfs: true`, create sul canale 124. | Rifiuto esplicito (`422`) o attesa gestita, non un guasto radio con quarantena. |  |
| NET-11 | QoS con `download_quality: 40`, `upload_quality: 90`. | Rifiuto esplicito, oppure valori diversi nelle due direzioni (`GET .../qos`). |  |
| BUG-7 | `POST .../txpower` con ogni livello, poi `GET .../txpower`. | Il `GET` riporta il valore reale, non quello richiesto. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| PERF-6 | Durata di `POST .../txpower`. | Sotto i 3 s. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| SEC-1 | `curl --path-as-is http://<host>:8080//etc/passwd` e `/../config.yaml`. | `404`. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| API-7 | Confronto di percorsi e campi con `/docs`. | Quanto deciso nel paragrafo 1.3. |  |
| HAP-5, HAP-6, HAP-7 | Run SOAK identiche con la configurazione cambiata sulla macchina tra una run e l'altra. | Confronto del numero di `404 reservation_invalidated` e di `restarts.ap` tra le run. |  |
| ARCH-1 … ARCH-11 | Run SOAK di regressione. | Nessuna differenza rispetto alla run precedente. |  |

### 4.5 Prove sulla macchina: root o intervento fisico

Non eseguibili dal tester. Li eseguo io con `sudo` (distacco USB simulato via sysfs,
`kill`, `systemctl`); le prove con un telefono e il ricollegamento fisico di un'antenna che la VM
ha perso richiedono una persona vicino alla macchina.

Attenzione: il distacco simulato con un AP attivo può bloccare la VM per circa 60 s e far staccare
la USB dalla VM (visto il 23/11 alle 17:50, come alle 13:37). Serve poi un ricollegamento fisico.

| ID | Intervento | Esito atteso | E2E |
|---|---|---|---|
| WD-5 (p. 3) | Antenna che ricompare con un nome diverso. | La voce vecchia viene ritirata; `/status` non resta `degraded`. |  |
| WD-7 (resto) | AP con il processo vivo ma la radio che non trasmette. | Il watchdog se ne accorge e riavvia l'AP. |  |
| WD-8 | Rete attiva con profilo QoS: `kill -9` di hostapd. | `restoring_ap`, poi rete attiva con il profilo QoS di nuovo attivo. |  |
| HAP-8 (resto) | Rete attiva: `kill -SEGV` di hostapd. | Report con le ultime righe di hostapd anche per il guasto visto dal watchdog. |  |
| NET-9 | `kill -9` del servizio con una rete attiva, poi riavvio. | Nessun indirizzo residuo; nuova rete sulla stessa antenna. |  |
| STAB-8 | Due reti attive; `time systemctl stop wi-lab`. | Arresto in meno di 60 s, nessun "stop-sigterm timed out" nel journal. |  |
| STAB-5 | Spostare l'orologio della VM di +2 h con una reservation attiva. | La reservation non scade in anticipo. |  |
| BUG-5 | Collegare un'antenna nuova a servizio avviato. | Compare in `/status` entro 30 s, oppure il motivo dello scarto è nel journal. |  |
| PERF-1, PERF-2, PERF-4, PERF-5 | `strace -f -e trace=execve` sui processi del servizio durante create, `GET .../network` e a riposo. | Come descritto nelle schede. |  |
| Telefono | Connessione reale: SSID `Caffè ☕` e `my"net\` visibili; rete nascosta non ASCII; password di 8 e 63 caratteri; `wpa2-wpa3` con client WPA3 e WPA2 e `wpa1` annotando avvisi o rifiuti dei client recenti; velocità a 20, 40 e 80 MHz sui 5 GHz con un client Wi-Fi 5 e uno Wi-Fi 6; `nslookup` (NET-8); `/docs` e `ssh` verso il gateway rifiutati; isolamento tra reti; captive portal su `http://<gateway>:8081/`. | Connessione e DHCP funzionanti; host non raggiungibile dalla rete di test. | ✅ regole dell'host: [test_e2e_firewall.py](tests/e2e-tests/test_e2e_firewall.py) |

### 4.6 Test unit da scrivere

| Id | Cosa verifica | Schede | File proposto |
|---|---|---|---|
| [unit-test-14](#unit-test-14) | Rami di guasto del watchdog | REV-10 | `test_watchdog.py` |
| [unit-test-15](#unit-test-15) | Frontend: spec di `startNetwork` | REV-13, REV-15 | `frontend/src/app/services/*.spec.ts` |

Fatti e tolti: unit-test-2, 4, 5, 7.

<a id="unit-test-14"></a>
**unit-test-14 - Watchdog: rami di guasto.** `dhcp_server.stop` che solleva in `_restore_dhcp`; cleanup
che fallisce in `_retry_pending`; rilascio subito dopo un nuovo tentativo riuscito. Atteso:
`release_device` chiamato, quarantena con `radio_fault=False`, `404 reservation_invalidated`, antenna
`unavailable`. Oggi fallisce (REV-10). I contatori `restarts` dalle API sono già in `test_watchdog.py`.

<a id="unit-test-15"></a>
**unit-test-15 - Frontend.** ✅ La compilazione senza pubblicare c'è: `make frontend-check`. **Mancano**
le spec di `startNetwork` con un `HttpClient` finto: `202` → rete attiva; `202` →
`start_failed`; `404` per ognuno dei quattro `reason`; errore a metà polling; avvio annullato
(`active: false`, `runtime_state: null`); `unsubscribe`.

### 4.7 Test e2e da scrivere

| Id | Cosa verifica | Accesso |
|---|---|---|
| [e2e-test-8](#e2e-test-8) | Stop incompleto: `1012` | root, difficile da provocare |

<a id="e2e-test-8"></a>
**e2e-test-8 - Stop incompleto.** `SIGSTOP` al PID di hostapd, poi `DELETE .../network`. Atteso:
risposta entro circa 15-17 s, `200` oppure `503 / 1012` con `Retry-After: 5`; con `1012` la `GET`
mostra `stop_failed`, la create risponde `409 / 1012`, e dopo `SIGCONT` la `DELETE` risponde `200`.
Provare prima su una VM sacrificabile: un processo fermato con un segnale può comportarsi in modo
diverso da uno bloccato nel kernel.

---

<a id="cap-5"></a>
<a id="nm-1"></a>
## 5. NM-1 - Togliere NetworkManager come dipendenza e disattivarlo all'installazione

**Gravità:** Media · **Confidenza:** Confermato (codice, installer e stato della macchina letti il
2026-11-26) · **Stato:** ✅ nel codice, da provare sulla macchina. Comprende `wpa_supplicant` (5.4 bis).

> **Stato (2026-11-26).** **Fatto** nel codice: commit 1-4 del 5.9 (`d92e05d`, `07f21f3`,
> `86d0c9a` e il commit docs). **Manca:** la verifica sulla macchina del 5.8, con la conferma
> dell'utente, e reinstallare la unit systemd per avere `RestartPreventExitStatus=78`.

Questo capitolo basta da solo per fare il lavoro. Le decisioni del paragrafo 5.2 sono già prese: non
vanno ridiscusse, vanno applicate. L'ordine dei passi è quello del paragrafo 5.9.

### 5.1 Analisi: perché NetworkManager non serve

**Wi-Lab non usa NetworkManager per nessuna funzione.** `nmcli` compare in tre punti del codice e fa
sempre la stessa cosa: dire a NetworkManager di non toccare una radio.

| Dove | Cosa fa |
|---|---|
| [wilab/wifi/manager.py](wilab/wifi/manager.py) `_configure_networkmanager_unmanaged` (chiamata in `_start_network`) | Prima di ogni avvio AP: `nmcli device set <radio> managed no`, `nmcli device disconnect <radio>`, poi `time.sleep(0.2)` |
| [wilab/network/unmanaged.py](wilab/network/unmanaged.py) `exclude_from_host_managers` | Quando la discovery aggiunge antenne: `nmcli ... managed no` per ogni radio, e il file `/run/NetworkManager/conf.d/00-wilab-unmanaged.conf` (STAB-9) |
| [wilab/wifi/recovery.py](wilab/wifi/recovery.py) `_quiesce` | Dopo un reset USB e prima di ogni re-probe: `nmcli ... managed no` |

**Era l'installer di Wi-Lab a installarlo**, fino al commit `da5c2a6`: `04-tools.sh` aveva `nmcli` tra
i comandi obbligatori (dal commit `617328c`, 2026-03-17), mentre il codice lo tratta come facoltativo.
Su Ubuntu Server NetworkManager di base non c'è: la rete è di systemd-networkd tramite netplan. Le
installazioni fatte con un installer precedente lo hanno ancora, attivo.

**Stato di questa macchina** (Ubuntu Server 26.04.1):

- prima della pulizia del 2026-11-26 NetworkManager era attivo e non gestiva nessuna interfaccia
  (`unmanaged` per `ens18`, `docker0`, `lo` e le radio): è la situazione che gli stadi dell'installer
  troveranno sulle altre installazioni;
- oggi i pacchetti `network-manager`, `network-manager-pptp`, `libnm0`, `ppp` e `pptp-linux` sono
  rimossi (stato `rc`), `nmcli` non esiste, `wpa_supplicant` è `masked`;
- `ens18` (unica interfaccia di accesso, default route) è di systemd-networkd: `networkctl list` la dà
  `routable / configured`; netplan ha `wifis: {}`.

**Problemi che porta:**

- può prendersi una radio (la accende, avvia la scansione) mentre fa da AP o subito dopo un reset USB:
  è il motivo dei tre punti sopra e di STAB-9;
- dimentica `managed no` a ogni suo riavvio (aggiornamento del pacchetto): STAB-9;
- costringe a non fare mai un reload, perché un reload una volta ha cambiato l'indirizzo
  dell'interfaccia di gestione (commit `87c3ce1`);
- costa due comandi e 0,2 s a ogni avvio AP.

**`wpa_supplicant`.** Wi-Lab non lo usa (l'AP è hostapd). Su questa macchina non era arrivato con
NetworkManager: lo aveva installato l'installer di Ubuntu il 2026-10-06 (`/var/log/apt/history.log.1.gz`,
comando di curtin), quasi certamente perché c'erano adattatori Wi-Fi collegati durante l'installazione
del sistema. `ubuntu-server` non dipende da `wpasupplicant`; `netplan-generator` lo suggerisce soltanto.
Gira come servizio D-Bus (`wpa_supplicant -u -s`, alias `dbus-fi.w1.wpa_supplicant1.service`): senza
`-i` non prende interfacce da solo, aspetta che un client gliele chieda via D-Bus. L'unico client qui era
NetworkManager; i `p2p-dev-wlx…` che `nmcli device status` mostrava indicano che lo faceva con le radio
di Wi-Lab, cioè un secondo processo sulla radio di hostapd. Senza NetworkManager resta inattivo, ma un
qualunque programma via D-Bus può riattivarlo e dargli una radio.

**Conclusione.** Con il requisito "Ubuntu Server, VM o host dedicato" NetworkManager va tolto dalle
dipendenze e disattivato dove c'è. Resta systemd-networkd, da cui Wi-Lab tiene già lontane le radio
con `/run/systemd/network/00-wilab-unmanaged.network` (`Unmanaged=yes`): quella parte non si tocca.

### 5.2 Decisioni prese

1. **Requisito di sistema:** Ubuntu Server con la rete di systemd-networkd (netplan), e NetworkManager
   non installato oppure disattivato e mascherato.
2. **Nessun codice parla più con NetworkManager.** Si tolgono tutte le chiamate a `nmcli` e il file di
   STAB-9. Nessun ripiego "se c'è lo uso": se l'utente rifiuta la disattivazione, l'installazione è
   fuori requisito e lo dicono l'installer e il precheck a ogni avvio.
3. **L'installer non installa e non disinstalla il pacchetto** (non lo installa più dal commit `da5c2a6`). Se NetworkManager è attivo, spiega il
   rischio e chiede se disattivarlo (`disable --now` + `mask`). Rifiutare non blocca l'installazione.
4. **L'accesso alla macchina non si rischia mai.** La disattivazione è offerta solo se le condizioni
   del paragrafo 5.4 sono tutte vere; altrimenti l'installer non tocca nulla e spiega perché.
5. **All'avvio del servizio NetworkManager attivo è un avviso, non un errore.** Il servizio parte lo
   stesso (l'utente può aver rifiutato), con un `WARNING` nel log a ogni avvio.
6. **`wpa_supplicant`: l'installer avvisa e chiede se disattivarlo** (`disable --now` + `mask`; il
   `mask` serve perché è attivabile via D-Bus). Solo dopo NetworkManager e solo se NetworkManager è
   fermo, e solo se l'host non lo usa come client Wi-Fi (paragrafo 5.4, stadio 07). Il pacchetto non si
   disinstalla. Il precheck all'avvio avvisa solo se ha in carico una radio di Wi-Lab, non per la sola
   presenza. `ModemManager` non si tocca.
7. **Nessun cambiamento alle API.** `/status` non riporta l'esito del precheck.

### 5.3 Codice da togliere

| File | Cosa togliere |
|---|---|
| [wilab/wifi/manager.py](wilab/wifi/manager.py) | `_nmcli_available`, `_configure_networkmanager_unmanaged`, la sua chiamata in `_start_network` con il commento "Best-effort: prevent NetworkManager/wpa_supplicant…", e `import shutil` se non serve ad altro |
| [wilab/wifi/recovery.py](wilab/wifi/recovery.py) | In `_quiesce` il blocco `try/except` con `nmcli`; resta `ip link set dev <radio> down`. Aggiornare la docstring: solo systemd-networkd |
| [wilab/network/unmanaged.py](wilab/network/unmanaged.py) | Il ciclo `nmcli`, `NM_RUNTIME_DIR`, `NM_RULES` e il blocco che scrive il file. Resta tutta la parte systemd-networkd. Riscrivere la docstring del modulo. Il nome `exclude_from_host_managers` resta |
| [diagnostics/diagnose-ap.py](diagnostics/diagnose-ap.py) (sezione "NetworkManager Status") | Sostituire con `systemctl is-active NetworkManager` e `networkctl list` |
| [diagnostics/troubleshooting/issue_network_creation_fails.sh](diagnostics/troubleshooting/issue_network_creation_fails.sh) | `nmcli dev \|\| true` → `networkctl list \|\| true` |

Dopo le modifiche `grep -rn "nmcli" wilab/ diagnostics/` non deve trovare nulla. In `install/` restano
il commento di `04-tools.sh` e gli usi del nuovo stadio 06.

**Test unit da adeguare:**

| File | Cosa cambia |
|---|---|
| `tests/unit-tests/test_unmanaged.py` | I comandi attesi sono solo `networkctl reload`; togliere `test_networkmanager_restart_keeps_the_radios_unmanaged` e `test_no_networkmanager_rule_without_networkmanager`; aggiungere l'asserzione che nessun comando inizia con `nmcli` |
| `tests/unit-tests/test_wifi.py` | Togliere `test_configure_networkmanager_unmanaged_when_nmcli_available` e `..._when_nmcli_missing`, e la riga `monkeypatch.setattr(mgr, "_configure_networkmanager_unmanaged", …)` in `test_startup_segfault_retry` |
| `tests/unit-tests/test_startup_classification.py` | In `test_start_runs_no_redundant_commands`: via `_nmcli_available`; l'asserzione diventa "nessun comando `nmcli`" |
| `tests/unit-tests/test_network_creation_recovery.py` | Il finto host (`"""Fake ip/nmcli/usbreset layer…"""`) e le due asserzioni su `nmcli`: la radio si riporta giù solo con `ip link set … down` |

### 5.4 Installer: nuovo stadio `install/01-preconditions/06-network-manager.sh`

Gli stadi di `01-preconditions` girano in ordine di nome; questo va dopo `05-network.sh`. Stile e
funzioni (`log_info`, `log_warning`, `log_error`, `state_set`, `read -r REPLY`) come in
`04-tools.sh`. L'installer gira già come root. `jq` non è tra i comandi richiesti dall'installer: non
usarlo. `nmcli` invece si può usare dal passo 2 in poi, perché è nello stesso pacchetto di
NetworkManager: se il servizio è attivo, c'è.

**Passo 1 - C'è?** Se `systemctl is-active --quiet NetworkManager` fallisce **e**
`systemctl is-enabled NetworkManager` non dà `enabled`: `log_success`, `state_set NM_STATE "absent"`,
fine. Se è già `masked`: lo stesso, con `NM_STATE "masked"`.

**Passo 2 - Si può disattivare senza perdere l'accesso?** Tutte le condizioni devono essere vere:

| # | Condizione | Come si controlla |
|---|---|---|
| a | netplan non usa NetworkManager | `netplan get network.renderer` non è `NetworkManager` |
| b | Ogni interfaccia con una default route è `unmanaged` per NetworkManager | `ip -o route show default \| awk '{for (i=1; i<NF; i++) if ($i=="dev") print $(i+1)}'`, poi lo stato in `nmcli -t -f DEVICE,STATE device` |
| c | La stessa interfaccia è di systemd-networkd | colonna SETUP = `configured` in `networkctl list --no-legend` |
| d | Con una sessione SSH (`$SSH_CONNECTION`), l'interfaccia che ha l'indirizzo locale della sessione rispetta b e c | terzo campo di `$SSH_CONNECTION`, cercato in `ip -o -4 addr` |
| e | NetworkManager non ha nessun dispositivo `connected` o `connecting` | `nmcli -t -f DEVICE,TYPE,STATE device` |

Se una condizione è falsa: **non offrire la disattivazione**. `log_error` con la condizione fallita e
il testo: "NetworkManager manages the network of this host. Wi-Lab requires Ubuntu Server with
systemd-networkd. Move the host network to systemd-networkd (netplan `renderer: networkd`) and run the
installer again." Poi chiedere se continuare comunque (`y/N`, default No): con No uscire con `1`, con
Sì `state_set NM_STATE "active_unsupported"` e proseguire.

**Passo 3 - Informare e chiedere.** Testo da mostrare:

```
⚠️  NetworkManager is active on this host.
    Wi-Lab does not use it. While it runs it can take a Wi-Fi adapter back
    (after its own restart or a USB reset) and bring a running AP down.
    It manages no interface of this host: <interfaccia> is handled by systemd-networkd,
    so disabling it does not change the network access to this machine.

Disable NetworkManager now (systemctl disable --now + mask)? (y/N)
```

Con No: `log_warning` "NetworkManager left active: AP drops and failed recoveries are expected",
`state_set NM_STATE "active_declined"`, proseguire.

**Passo 4 - Disattivare.**

```bash
systemctl disable --now NetworkManager-wait-online.service NetworkManager-dispatcher.service NetworkManager.service
systemctl mask NetworkManager.service
```

`mask` impedisce che un aggiornamento del pacchetto o un altro servizio lo riavvii. `network-online.target`
resta servito da `systemd-networkd-wait-online`, quindi l'unit di Wi-Lab non cambia.

**Passo 5 - Verificare, e tornare indietro se serve.** Entro 10 s: la default route c'è ancora
(`ip route show default` non vuoto) e il gateway risponde (`ping -c 1 -W 2 <gateway>`). Se uno dei due
manca: `systemctl unmask NetworkManager && systemctl enable --now NetworkManager`, `log_error`,
`state_set NM_STATE "rollback"`, uscire con `1`. Altrimenti `state_set NM_STATE "disabled"` e
`log_success`.

### 5.4 bis Installer: nuovo stadio `install/01-preconditions/07-wpa-supplicant.sh`

Gira dopo `06-network-manager.sh`, con le stesse convenzioni.

**Passo 1 - Serve chiedere?** Uscire con `log_success` senza domande se:
- `systemctl is-active --quiet wpa_supplicant` fallisce e `is-enabled` non dà `enabled`
  (`state_set WPA_STATE "absent"`), oppure dà già `masked` (`WPA_STATE "masked"`);
- NetworkManager è ancora attivo (`systemctl is-active --quiet NetworkManager`): fermare
  `wpa_supplicant` sotto NetworkManager gli toglie la gestione del Wi-Fi e riempie il log di errori.
  `log_info` "wpa_supplicant left as it is: NetworkManager is active", `WPA_STATE "kept_nm_active"`.

**Passo 2 - L'host lo usa come client Wi-Fi?** Tutte vere, altrimenti non offrire la disattivazione,
`log_warning` con la condizione fallita, `WPA_STATE "in_use"`, proseguire:

| # | Condizione | Come si controlla |
|---|---|---|
| a | netplan non ha reti Wi-Fi | `netplan get network.wifis` vuoto o `null` |
| b | Nessuna unit client attiva | `systemctl list-units --state=active --no-legend 'netplan-wpa-*' 'wpa_supplicant@*'` vuoto |
| c | Nessuna default route su un'interfaccia wireless | per ogni `dev` di `ip -o route show default` (come nella condizione b dello stadio 06), `/sys/class/net/<dev>/wireless` non esiste |

**Passo 3 - Informare e chiedere:**

```
⚠️  wpa_supplicant is active on this host.
    Wi-Lab does not use it (the APs run on hostapd). If a program asks it to
    manage a Wi-Fi adapter, it competes with hostapd on that radio.
    No Wi-Fi client connection of this host uses it.

Disable wpa_supplicant now (systemctl disable --now + mask)? (y/N)
```

Con No: `log_warning`, `WPA_STATE "active_declined"`, proseguire.

**Passo 4 - Disattivare:** `systemctl disable --now wpa_supplicant.service` poi
`systemctl mask wpa_supplicant.service`; `WPA_STATE "disabled"`. Non serve il controllo della default
route: il passo 2 ha già escluso che l'accesso dipenda da `wpa_supplicant`.

**`uninstall.sh`** (nuovo passo dopo lo Step 3, che oggi toglie regole, file di runtime e dispositivi):
per `NetworkManager` e per `wpa_supplicant`, se `systemctl is-enabled` dà `masked`,
chiedere se riattivarlo (`y/N`); con Sì `systemctl unmask <unit> && systemctl enable --now <unit>`.
Riattivare prima `wpa_supplicant`, poi NetworkManager. Lo stato dell'installer è in `/tmp` e non
sopravvive: non usarlo per questa scelta.

### 5.5 Precheck all'avvio del servizio

Oggi [main.py](main.py) chiama `log_host_impact_warning()` e `check_existing_wilab_rules()` di
[wilab/network/safety.py](wilab/network/safety.py) prima di caricare la configurazione. Diventano una
fase unica.

**Nuovo modulo `wilab/precheck.py`:**

```python
@dataclass(frozen=True)
class Finding:
    check: str                              # stable name, e.g. "network_manager"
    level: Literal["fatal", "warning"]
    message: str                            # what is wrong and what to do

def run_prechecks() -> list[Finding]: ...   # runs every check, never raises
```

`main()` chiama `run_prechecks()` come prima cosa, scrive ogni `Finding` nel log (`CRITICAL` o
`WARNING`) e, se ce n'è almeno uno `fatal`, esce con codice `78`. Nessun `Finding`: una riga `INFO`
"Startup prechecks passed".

| Controllo | Livello | Regola |
|---|---|---|
| `root` | fatal | `os.geteuid() != 0`: nessun comando di rete può funzionare |
| `commands` | fatal | Manca uno dei comandi che il servizio esegue: `hostapd`, `hostapd_cli`, `dnsmasq`, `iw`, `ip`, `tc`, `iptables`, `ip6tables`, `udevadm`, `usbreset`, `modprobe`, `networkctl` (`shutil.which`). È l'elenco `REQUIRED_CMDS` di `04-tools.sh` senza `python3` e `systemctl`: tenerli allineati. Il messaggio elenca tutti quelli che mancano |
| `network_manager` | warning | `systemctl is-active --quiet NetworkManager` riesce. Messaggio: "NetworkManager is active: it can take Wi-Fi adapters back and bring APs down. Wi-Lab requires it disabled: sudo systemctl disable --now NetworkManager && sudo systemctl mask NetworkManager (first check that it manages no interface: nmcli device status)". Non eseguire `nmcli` dal precheck. Se `systemctl` manca o fallisce in altro modo: nessun `Finding` |
| `wpa_supplicant` | warning | Per ogni antenna configurata o scoperta esiste `/run/wpa_supplicant/<radio>` (il socket di controllo che `wpa_supplicant` crea per un'interfaccia che gestisce). Messaggio: "wpa_supplicant manages <radio>: it competes with hostapd. Disable it: sudo systemctl disable --now wpa_supplicant && sudo systemctl mask wpa_supplicant". La sola presenza del servizio non è un avviso. Il controllo gira anche alla discovery (antenne aggiunte dopo l'avvio): `log` una volta per radio |
| `leftover_rules` | warning | L'attuale `check_existing_wilab_rules`, senza il consiglio "Consider running cleanup script" (il servizio pulisce da solo all'avvio: nota di REV-17) |

`log_host_impact_warning` resta com'è, chiamata dopo il precheck. Le funzioni di `safety.py` usate dal
precheck si spostano o si richiamano da `precheck.py`; `main.py` non importa più `safety`.

**Unit systemd** ([install/systemd/wi-lab.service.template](install/systemd/wi-lab.service.template)):
aggiungere `RestartPreventExitStatus=78`, così un precheck fatale lascia il servizio `failed` con il
motivo nel journal invece di riavviarlo ogni 10 s.

**Test unit** (`tests/unit-tests/test_precheck.py`), con `os.geteuid`, `shutil.which` ed
`execute_command` finti:

- tutto a posto: lista vuota;
- non root: un `fatal` `root`;
- manca `hostapd`: un `fatal` `commands` che lo nomina;
- NetworkManager attivo: un `warning` `network_manager`, nessun `fatal`;
- `/run/wpa_supplicant/<radio>` presente (cartella finta in `tmp_path`): un `warning` `wpa_supplicant`
  che nomina la radio; servizio attivo ma nessun socket per le radio: nessun `Finding`;
- `systemctl` assente (`CommandError`): nessun `Finding` per `network_manager`;
- `main()` con un `fatal`: `SystemExit(78)` e `create_app` mai chiamata.

I test unit girano senza root: `conftest.py` deve rendere `run_prechecks` innocuo dove un test avvia
`main()`.

### 5.6 Documentazione

| File | Cosa scrivere |
|---|---|
| [README.md](README.md), tabella Requirements | **OS:** "Ubuntu Server 25+ (tested on 26.04), network managed by systemd-networkd (netplan)". Nuova riga **NetworkManager:** "Must not be installed, or must be disabled and masked. The installer detects it and offers to disable it; it never does so if NetworkManager manages the host's network." Nuova riga **wpa_supplicant:** "Not used by Wi-Lab. The installer offers to disable and mask it when the host does not use it as a Wi-Fi client." Negli elenchi di pacchetti `nmcli`/`network-manager` non c'è già più |
| [docs/networking.md](docs/networking.md), "6. Host Network Manager Exclusion" | Solo systemd-networkd; togliere `nmcli` e il file in `/run/NetworkManager`; dire che NetworkManager non è supportato |
| [docs/architecture.md](docs/architecture.md) | Togliere `nmcli` dai due diagrammi dei comandi; "release from NetworkManager" nel diagramma del recovery; il paragrafo "NetworkManager:" di "Host network managers" (sostituire con il requisito); il comando `sudo nmcli device set …` della procedura di recovery manuale; la riga "Host network manager exclusion" della tabella dei file. Aggiungere un paragrafo "Startup prechecks" con la tabella del 5.5 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Nuove voci: `WARNING … NetworkManager is active` e `WARNING … wpa_supplicant manages <radio>` nel journal, con i comandi per controllare e disattivare |
| [docs/unit-testing.md](docs/unit-testing.md), [docs/e2e-testing.md](docs/e2e-testing.md) | Aggiornare l'elenco dei file di test |
| [CHANGELOG.md](CHANGELOG.md), sezione `[4.1.0]` | **Breaking Changes:** requisito di sistema (Ubuntu Server senza NetworkManager; l'installer propone di disattivarlo; chi aggiorna deve rieseguire l'installer o dare i due comandi). **Features:** fase di precheck all'avvio. **Bug Fixes:** sostituire la riga di STAB-9 con una riga NM-1 (la 4.1.0 non è rilasciata: non lasciare due righe che si contraddicono). Aggiornare la tabella Statistics |
| Questo file | NM-1 passa nella tabella 2.3 con ✅; togliere il riquadro Stato di questo capitolo |

### 5.7 Cosa non fare

- L'installer non disinstalla i pacchetti `network-manager` e `wpasupplicant` e non tocca `ModemManager`
  (su questa macchina la disinstallazione è stata fatta a mano, su richiesta).
- Non disattivare `wpa_supplicant` mentre NetworkManager è attivo.
- Non modificare netplan né nessuna configurazione di rete dell'host.
- Non dare `systemctl stop/disable/mask` a NetworkManager o `wpa_supplicant` senza avere prima
  verificato le condizioni del 5.4 e del 5.4 bis, e mai su questa macchina senza la conferma
  dell'utente (serve `sudo`).
- Non toccare la parte systemd-networkd di `unmanaged.py`.

### 5.8 Verifica sulla macchina (dopo conferma, sistema libero)

**Su questa macchina** NetworkManager non c'è e `wpa_supplicant` è già mascherato: si provano solo i
rami "niente da fare".

1. Stadio `06-network-manager.sh`: esce subito con `NM_STATE "absent"`, senza domande. Stadio
   `07-wpa-supplicant.sh`: `WPA_STATE "masked"`, senza domande.
2. `systemctl restart wi-lab`: nel journal "Startup prechecks passed", nessun avviso e nessun `nmcli`.
3. E2E standard, poi `WILAB_E2E_USB=1` (reset USB e re-probe senza `nmcli`): tutti verdi come prima.
4. `sudo reboot`: la macchina torna raggiungibile, le radio sono `unmanaged` in `networkctl list`,
   `iw dev` non mostra interfacce `P2P-device`.

**I rami "chiedi e disattiva"** non si possono provare qui senza reinstallare i pacchetti. Servono una
VM Ubuntu Server con NetworkManager attivo e un adattatore Wi-Fi, oppure, su questa macchina e solo
con la conferma dell'utente, `apt-get install network-manager` e `systemctl unmask wpa_supplicant`
prima della prova e la pulizia dopo. Lì:

5. Stadio 06 da una sessione SSH, risposta `y`: la sessione non cade, `systemctl is-enabled
   NetworkManager` dà `masked`, la default route è invariata. Risposta `n`: `NM_STATE
   "active_declined"`, l'installazione prosegue.
6. Stadio 07, risposta `y`: `systemctl is-enabled wpa_supplicant` dà `masked` e
   `/run/wpa_supplicant/` non ha socket delle radio.
7. Prova negativa: con NetworkManager attivo, riavviare Wi-Lab: il journal ha il `WARNING` del
   precheck e il servizio funziona. L'avviso su `wpa_supplicant` non si prova sulla macchina
   (servirebbe dargli una radio via D-Bus): lo copre il test unit del precheck.
8. `uninstall.sh`: chiede se riattivare i due servizi mascherati e lo fa nell'ordine giusto.

### 5.9 Ordine dei commit

1. `refactor(host)`: via `nmcli` da codice, test e diagnostica (5.3). Suite unit verde.
2. `feat(startup)`: `wilab/precheck.py`, `main.py`, unit systemd, test (5.5).
3. `feat(install)`: nuovi stadi `06-network-manager.sh` e `07-wpa-supplicant.sh`,
   `uninstall.sh` (5.4, 5.4 bis).
4. `docs`: README, docs, CHANGELOG, questo file (5.6).
5. Verifica sulla macchina (5.8), solo dopo la conferma dell'utente.

Il commit 1 non cambia nulla per i client e si può fare subito; i commit 2-4 portano il requisito di
sistema e il precheck, e vanno chiusi prima del congelamento della 4.1.0.

A ogni commit: `make test-local-quick`, `make lint` (86 errori già presenti), `make type-check`.

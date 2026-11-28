# Fable Notes - lavoro aperto su Wi-Lab

Solo ciò che serve per lavorare sui punti ancora aperti. Quello che è fatto è nel codice, nei test,
nel [CHANGELOG](CHANGELOG.md) e in [docs/](docs/): qui non si ripete.

<a id="cap-1"></a>
## 1. Come lavorare

### 1.1 Da dove ripartire (stato del 2026-11-27)

- Versione in corso: **4.1.0**, non rilasciata. Branch `fix/reservation-lifecycle`, mai spinto.
- **Obiettivo: congelare il comportamento della 4.1.0** per poter iniziare il client. Dopo il
  congelamento si fanno solo correzioni che non cambiano il contratto (capitolo 2).
- **Macchina:** Ubuntu Server 26.04.1, kernel 7.0.0-44, unica macchina, fa da server e da sviluppo.
  NetworkManager disinstallato, `wpa_supplicant` mascherato, `ens18` di systemd-networkd, radio
  `unmanaged`. Due antenne `mt7921u`. La unit systemd installata è quella nuova
  (`RestartPreventExitStatus=78`, `TimeoutStopSec=60s`). Wi-Lab è escluso da needrestart.
- **Test del 2026-11-27, sul codice di oggi** (servizio riavviato alle 14:12, frontend ripubblicato):
  1132 unit verdi, copertura 94 %, `make lint` e `make type-check` puliti, 13 spec del frontend.
  E2E standard: 65 passed, 2 xfail noti (BUG-7, PERF-6), 11 skipped (USB, lunghi, riavvio sporco,
  lock xtables assente con nf_tables, 3 per budget del watchdog consumato), nessun `ERROR` di Wi-Lab
  nel journal. Long run di 2 ore (prima di REV-12 e WD-5): 1332 reti, 0 avvii falliti, scimmia del
  caos 8/8 recuperati. Non eseguiti: e2e USB, lunghi e riavvio sporco, long run con il controllo
  PERF-7.

In quest'ordine:

1. **Blocco A** (paragrafo 2.1): RELEASE-API, il congelamento.
2. **Blocco B** (paragrafo 2.2), nelle 4.1.x.
3. Le prove sulla macchina del capitolo 4 quando c'è qualcuno vicino alla macchina o una VM di prova.

### 1.2 Regole

- **CHANGELOG** (regole adottate il 2026-11-27, ARCH-11 E): sezioni nell'ordine Breaking Changes,
  Features, Bug Fixes, Maintenance, CI/CD, Tests, poi il capitolo di migrazione delle API; frasi brevi
  scritte per chi usa o installa Wi-Lab; test elencati solo se dicono qualcosa di utile; ogni
  correzione aggiunge una riga nella sezione `[4.1.0]` nello stesso commit, con l'ID tra parentesi;
  ciò che cambia per i client va anche nel capitolo "API changes from 4.0.0"; la data si aggiorna
  quando si modifica una versione già datata. Prima del rilascio aggiornare la tabella Statistics.
- **Dopo il congelamento** una correzione non cambia endpoint, campi, codici, stati, validazione né
  requisiti di installazione. Se li cambia, va nella versione successiva.
- **Una scheda chiusa si toglie da qui** (capitolo 2, capitolo 3 e la sua riga nel capitolo 4): resta
  nel CHANGELOG e nel codice. Una scheda fatta in parte ha un riquadro **Stato** che dice solo cosa manca.
- **Verifiche a ogni correzione:** `make test-local-quick`, `make lint` (zero errori: le regole sono
  in `pyproject.toml`), `make type-check`.
- **E2E solo dopo conferma** e su un sistema libero (nessuna attività nel journal del servizio).
  Il servizio gira da questa cartella: una modifica è attiva solo dopo `systemctl restart wi-lab`.
  Il budget del watchdog (`watchdog:` in `config.yaml`; su questa macchina 5 ripristini AP e 3
  riavvii DHCP all'ora per `mt7921u`) si azzera al riavvio: i test che lo usano si saltano da soli se
  è finito. Flag: `WILAB_E2E_SLOW`, `WILAB_E2E_RESTART`, `WILAB_E2E_USB`
  ([docs/e2e-testing.md](docs/e2e-testing.md)).
- **Distacco USB simulato:** con un AP attivo può bloccare la VM per circa 60 s e staccare la USB
  dalla VM (23/11); serve poi un ricollegamento fisico.
- **sudo:** password in `~/.wilabsudo` (0600), mai stampata: `sudo -k -S -p '' ... < ~/.wilabsudo`.
- `copilot.md` resta fuori dai commit.

### 1.3 Decisioni

Prese (non vanno ridiscusse):

- **Nessun riavvio senza la volontà dell'utente (2026-11-27).** L'installer esclude Wi-Lab da
  needrestart (`/etc/needrestart/conf.d/wilab.conf`, stadio `06-needrestart.sh`): un aggiornamento
  automatico (libexpat1 il 2026-11-27) aveva riavviato il servizio e tolto ogni rete. Il servizio lo
  dice da sé: `restart_required` in `GET /status` (librerie sostituite in `/proc/self/maps`,
  `/run/reboot-required`, `/run/reboot-needed`, kernel più nuovo in `/lib/modules`), barra rossa nella
  pagina web, controllo `updates` in `/monitoring`. Non rende mai lo stato `degraded`.
- **Ubuntu Server 25.04 o più recente è un requisito** (README, controllato dall'installer), provato su
  26.04.1 LTS. Il controllo dei riavvii resta portabile (openSUSE, Arch), ma il supporto è Ubuntu.
- **Budget del watchdog in `config.yaml` (2026-11-27):** sezione `watchdog:` obbligatoria, prima di
  `antennas`, con `ap_restores` e `dhcp_restarts` (`limit`, `window_minutes`); `drivers` opzionale, con
  valori per driver del kernel (non per antenna). Finestra scorrevole: il conteggio si libera da sé.
  Nell'esempio `drivers` è commentato.
- **`health` in `GET /antennas/{interface}` (2026-11-27):** budget usati e limite del driver, quando si
  libera il prossimo, quarantene e ultimo reset USB, dall'avvio del servizio. Non in `GET /antennas`.
- **Frontend:** riscritto in un container Docker separato, Wi-Lab solo API, niente CORS; account da
  decidere. Tutto in [TODOs/frontend/](TODOs/frontend/) (container, nuova applicazione, account; ciò che era REV-15 è in [missing-functions.md](TODOs/frontend/missing-functions.md)).
- **HAP-5 non confermata (2026-11-27):** su 4.378 avvii nel journal del 26-27/11, quelli in parallelo con
  l'altra antenna falliscono come quelli isolati (±1 s: 5,0 % contro 7,1 %; ±3 s: 6,5 % contro 5,8 %).
  Gli avvii non si serializzano. Il 6 % di primi tentativi falliti sono i segfault di hostapd 2.11
  ([TODOs/reliability/hostapd-segfault-fix.md](TODOs/reliability/hostapd-segfault-fix.md)), recuperati dal retry.
- **WD-7, trasmissione reale (2026-11-27):** con `mt7921u` i beacon partono dal firmware e
  `tx_packets` non li conta (3 pacchetti in 10 s con l'AP attivo), `survey dump` è vuoto in modalità AP.
  Il controllo serve per driver che contano i beacon (Realtek): va in
  [TODOs/reliability/beacon-check.md](TODOs/reliability/beacon-check.md), con un'opzione per driver.
- **Tipi stretti, nome del TX power, QoS e TX power non stabili nella 4.1.0:** come nel CHANGELOG
  (capitolo API). Il gruppo T del paragrafo 2.2 può cambiare le risposte di `.../txpower`.
- **Configurazione:** tutti i campi obbligatori tranne `hostapd_debug_dir` e `antennas`;
  `protected_commands_password` e `cors_origins` obbligatori ma possono essere `null`.
- **STAB-7:** lockfile con pip; uv eventualmente dopo la 4.1.0.
- **API-7 e "estendere una reservation":** rimandati ([TODOs/api/patch-access-point.md](TODOs/api/patch-access-point.md), [TODOs/reservations/extend.md](TODOs/reservations/extend.md)).

Gravità: **Critica** sicurezza o perdita del servizio · **Alta** una rete o un adattatore resta rotto
senza che il client lo sappia · **Media** comportamento sbagliato in un caso realistico · **Bassa**
rumore o casi insoliti. Confidenza: **Confermato** dal codice · **Probabile** codice più comportamento
noto di uno strumento esterno · **Ipotesi** da provare sulla macchina prima di agire.

---

<a id="cap-2"></a>
## 2. Punti aperti

La 4.1.0 deve fissare il comportamento che il client vede: endpoint, campi, codici, stati, validazione e
requisiti di installazione.

- **Blocco A (2.1):** cambia qualcosa che il client o chi installa vede. Va chiuso prima di congelare.
- **Blocco B (2.2):** stabilizzazione, pulizia e prestazioni, senza cambiare il contratto: nelle 4.1.x.

### 2.1 Blocco A: da chiudere per la 4.1.0

| Ordine | Id | Cosa fare | Perché prima del congelamento |
|:---:|---|---|---|
| A1 | RELEASE-API | **Ultima attività: è il congelamento.** Revisione di tutte le API: ogni endpoint, parametro, codice di stato, `detail.code`, header (`Retry-After`) ed esempio deve corrispondere a Swagger (`/docs`), ReDoc (`/redoc`), `docs/ap-creation-procedure.md`, `docs/error-codes.md` e al capitolo API del `CHANGELOG.md`. Poi e2e completi (standard, lunghi, riavvio, USB), tabella Statistics, `requirements.lock`. | Da qui in poi il contratto non cambia. |

### 2.2 Blocco B: dopo la 4.1.0, solo stabilizzazione

Nessuno di questi punti cambia endpoint, campi o codici documentati. Se lavorandoci si scopre che uno li
cambia, si ferma e si rimanda alla versione successiva.

| Ordine | Id | Gravità | Cosa fare |
|:---:|---|---|---|
| B1 | [NET-14](#net-14) | Media | Provare con un client vero le tre garanzie del firewall (pulizia all'avvio, NAT solo dalla subnet, Internet disattivato che taglia le connessioni aperte). Nel codice dalla 4.0.0. |
| B2 | [ARCH-11](#arch-11) | Bassa | Cosa resta da portare da `feature/device-capabilities`: `CLAUDE.md`, CI (riepilogo, pulizia delle run, documentazione nelle release, frontend), documentazione delle API, suggerimento sul driver nei crash. |
| B3 | [HAP-7](#hap-7) | Bassa | Verificare se l'output debug di hostapd influisce sulla stabilità a lungo termine. |
| B4 | [API-7](#api-7) | Bassa | `PATCH .../network` o `PUT` per Internet e TX power. **Rimandato** ([TODOs/api/patch-access-point.md](TODOs/api/patch-access-point.md)). |
| B5 | [NET-13](#net-13) | Bassa | Evitare che lo stop del profilo QoS impedisca lo stop della rete. |
| B6 | [RACE-3](#race-3) | Bassa | Sincronizzare le operazioni QoS per interfaccia. |
| B7 | [NET-12](#net-12) | Bassa | Sincronizzare la fine del profilo QoS con lo stato QoS. |
| B8 | [WD-8](#wd-8) | Media | Conservare e riapplicare il profilo QoS dopo il ripristino della rete. |

**TX power, da debuggare (fuori dal congelamento, come il QoS):**

| Ordine | Id | Gravità | Cosa fare |
|:---:|---|---|---|
| T1 | [TXP-1](#txp-1) | Media | Capire perché la potenza non si controlla sugli adattatori in uso, prima di correggere altro. |
| T2 | [BUG-7](#bug-7) | Bassa | Rendere coerente lo stato della potenza TX in caso di mismatch. |
| T3 | [PERF-6](#perf-6) | Bassa | Sostituire l'attesa fissa per TX power con polling limitato. Con BUG-7. |
| T4 | [HAP-6](#hap-6) | Media | Verificare se il comando TX power subito dopo l'avvio peggiora la stabilità; se sì, non inviarlo per il livello 4. |

**QoS (NET-13, RACE-3, NET-12, WD-8):** sperimentale e non testato, in fondo di proposito; fuori dal
congelamento: il client non deve costruirci sopra finché non è dichiarato stabile.

---

<a id="cap-3"></a>
## 3. Schede

Nell'ordine del capitolo 2. Ogni scheda ha la stessa struttura: **Problema**, **Come si riproduce**,
**Come correggerlo**. I percorsi dei file sono relativi alla radice del repository.

<a id="net-14"></a>
### B1. NET-14 - Garanzie del firewall da provare con un client vero

**Gravità:** Media · **Confidenza:** Confermato (codice e test unit, 2026-11-27) · **File:**
[wilab/network/nat.py](wilab/network/nat.py), [wilab/network/captive.py](wilab/network/captive.py),
[wilab/network/host_guard.py](wilab/network/host_guard.py), [wilab/network/rules.py](wilab/network/rules.py),
[wilab/api/context.py](wilab/api/context.py) (`start`)

Era la riga D5 di ARCH-11 ("già presenti qui"). Sono tre garanzie per chi usa il laboratorio; il codice
le dà dalla 4.0.0, i test unit controllano le regole, ma nessun test le ha mai viste funzionare con un
client Wi-Fi.

| Garanzia | Come è fatta | Test che c'è | Cosa manca |
|---|---|---|---|
| **Pulizia all'avvio.** Un arresto sporco non lascia regole di Wi-Lab che cambiano la rete dell'host. | `AppContext.start`: `remove_stale_rules` (FORWARD e POSTROUTING, solo regole con commento `wilab-nat-`, `wilab-forward-`, `wilab-block-`, `wilab-isolation`, `wilab-protect-existing`), `remove_stale_captive_rules`, `remove_stale_guards` (anche IPv6), poi `cleanup_runtime`. Mai un flush di catene dell'host. | `test_nat.py`, `test_captive.py`, `test_host_guard.py` (solo regole di Wi-Lab, anche duplicate); e2e `test_e2e_unclean_restart.py` (`kill -9` del servizio: indirizzi, shaping e file di runtime). | L'e2e non controlla le regole iptables dopo il riavvio sporco. |
| **NAT solo dalla subnet della rete.** Un client di una rete non esce con l'indirizzo dell'host da un'altra interfaccia, e una regola di Docker non nasconde quella di Wi-Lab. | `MASQUERADE` con `-s <subnet> -o <upstream>`; FORWARD in uscita `-i <radio> -o <upstream>` e in entrata `RELATED,ESTABLISHED` verso la radio. | `test_nat.py::test_nat_rules_use_only_the_selected_network_subnet`; e2e `test_e2e_firewall.py::test_success_means_the_firewall_is_in_place`. | Nessuna. |
| **Internet disattivato taglia le connessioni aperte.** Un download in corso si ferma, non solo le connessioni nuove. | `block_internet` inserisce in cima a FORWARD (`-I FORWARD 1`): `REJECT --reject-with tcp-reset` per il TCP in uscita dalla radio, `REJECT` per il resto, `DROP` verso la radio. Stanno prima delle regole `ESTABLISHED` di Wi-Lab e di `wilab-protect-existing` (che è in coda). | `test_nat.py` (ordine e contenuto delle regole); e2e `test_e2e_network_check.py::test_disabled_internet_stays_disabled` (le regole restano). | **La prova con un client:** nessun test apre una connessione e la vede cadere. |

**Come si prova (sulla macchina, con un telefono o un portatile, conferma prima).** Rete con Internet
attivo; dal client un download lungo (`curl -o /dev/null https://.../file-grande`) e una sessione
`ssh` verso un host esterno. Poi `POST .../internet/disable`: entro 1 s il download si interrompe con
"connection reset" e la sessione `ssh` cade; `curl https://example.com` fallisce subito. `POST
.../internet/enable`: le connessioni nuove passano. Poi `systemctl kill --signal=SIGKILL wi-lab` con la
rete attiva: dopo il riavvio `iptables -S FORWARD`, `iptables -t nat -S POSTROUTING` e `ip6tables -S
INPUT` non hanno regole `wilab-` di reti che non esistono più.

**Come correggerlo.** Niente, se la prova passa. Se un client resta connesso dopo il disable,
cercare un'altra regola `ACCEPT ... ESTABLISHED` inserita in cima a FORWARD da un altro programma
(Docker, ufw) e documentare il caso in `docs/troubleshooting.md`.

---

<a id="arch-11"></a>
### B2. ARCH-11 - Cosa portare dal branch `feature/device-capabilities`

**Gravità:** Bassa · **Confidenza:** Confermato (`git show feature/device-capabilities:<file>`) ·
**File:** radice del repository, `.github/workflows/`, `scripts/`

> **Stato (2026-11-27):** Fatti A2, A3, A4, A5 (proposta "local"), D1, E; D4 era già coperto; D5 è
> diventato [NET-14](#net-14). **Restano** A1, A6, il blocco B (CI), C1, C2, D2, D3: ognuna da
> accettare o rifiutare.

`feature/device-capabilities` non verrà unito: è nato prima di questo branch (49 commit da `67508ca`).
Si sceglie cosa riportare, una voce alla volta; nessuna cambia il contratto delle API, tranne dove è
scritto.

**A. Regole del progetto e strumenti**

| # | Proposta | Stato | Note |
|---|---|---|---|
| A1 | `CLAUDE.md` con le regole del progetto, ripreso dall'altro branch e adattato. | Da decidere | Da tenere: tutto in inglese nel repository (Fable-Notes resta in italiano); "cambio netto, niente compatibilità"; nessun `subprocess` fuori da `wilab/network/commands.py`; tipi ovunque; niente `print`; documentazione allineata al codice nello stesso commit; chiudere un lavoro con "cosa resta da fare". Da togliere: capability e `POST /api/v1/device-reservation` (qui non esistono), il token GitHub in `.git/gh_token`. Da aggiungere: e2e solo con conferma e a sistema libero, una riga di CHANGELOG per correzione e le regole del paragrafo 1.2, `copilot.md` mai nei commit, nessuna stampa di token o password. |
| A2 | Un solo `pyproject.toml` per pytest, ruff e mypy. | ✅ 2026-11-27 | Senza tabella `[project]`: la versione resta in `VERSION`. `pytest.ini` e `mypy.ini` tolti. |
| A3 | Regole di ruff fissate. | ✅ 2026-11-27 | `E4`, `E7`, `E9`, `F` più `G004` (log senza f-string, ARCH-10). Zero errori; `make lint` è in CI. |
| A4 | `update_version.sh` in `scripts/`, `run-tests.sh` tolto. | ✅ 2026-11-27 | Citazioni aggiornate (docs, istruzioni). |
| A5 | Report di copertura. | ✅ 2026-11-27 | Proposta "local": in `make test-local` e in CI, non in `make test-local-quick`. |
| A6 | Test indipendenti dal sistema operativo (anche Windows). | Proposta: **no** | Il codice usa `/proc`, `/sys`, `/run` e comandi Linux; il servizio gira solo su Ubuntu. |

**B. CI e rilasci** (`.github/workflows/`)

Oggi `ci.yml` ha due job, su ogni pull request e su `main`:

- **backend** (Python 3.12, `requirements-dev.txt`, che include `requirements.lock`): validazione di
  `config.example.yaml`, `make lint`, `make type-check`, `make test-local` (con il report di copertura
  nel log), export della documentazione API (`scripts/export_api_docs.py`) caricata come artifact
  `wi-lab-api-docs-<sha>` (conservazione predefinita di GitHub, 90 giorni).
- **frontend** (Node 20): `npm ci` e `npm run build:prod`. Le spec (`make frontend-test`) non girano.

Non ci sono workflow di rilascio. L'altro branch aveva in più:

| # | Proposta | Cosa cambia qui | Costo e dipendenze | Stato |
|---|---|---|---|---|
| B1 | **Riepilogo della run** (`scripts/ci_summary.py`, 140 righe con i suoi test): test passati e falliti (da `--junitxml`) e copertura in Markdown nella pagina della run (`$GITHUB_STEP_SUMMARY`), invece di cercarli nel log. | Job backend: `pytest --junitxml=junit.xml`, poi `ci_summary.py junit` e `coverage report --format=markdown`; job frontend: lo stesso per le spec. | Piccolo. Lo script va portato con i suoi test; per il frontend serve prima che le spec producano un file di risultati (oggi Node `--test` stampa TAP: `--test-reporter=junit`). | Da decidere |
| B2 | **Pulizia delle run delle pull request** (`scripts/cleanup_pr_runs.py`): a ogni run di una PR tiene le 3 più recenti di quella PR e cancella le altre con i loro artifact. Mai le run di `main`, dei rilasci e manuali; niente cron. | Nuovo job `cleanup-runs` dopo gli altri, solo su `pull_request` dello stesso repository, con `permissions: actions: write`. | Piccolo. Serve solo se le PR accumulano molte run (spazio degli artifact). | Da decidere |
| B3 | **Documentazione API nei rilasci** (`release-docs.yml`): alla pubblicazione di una release GitHub allega `wi-lab-api-docs-<versione>.zip` (`openapi.json`, `swagger.html`, `redoc.html` che si aprono senza server); manuale con `workflow_dispatch`. Nella CI l'artifact prende il nome dalla versione e dura 90 giorni. | Nuovo workflow con `permissions: contents: write`; nella CI cambia solo il nome dell'artifact. | Piccolo; ha senso dal primo rilascio fatto con GitHub Releases (la 4.1.0). Va con C2 se il `swagger.html` deve essere autonomo. | Da decidere |
| B4 | **Frontend in CI**: spec e build del container. | Job frontend: `make frontend-test` (oggi solo build). Con il nuovo frontend ([TODOs/frontend/docker-container.md](TODOs/frontend/docker-container.md)): build dell'immagine su ogni PR, pubblicazione su `ghcr.io` ai tag. | Le spec subito (minuti di Docker in più). L'immagine dipende dal container del nuovo frontend: il TODO lo prevede già. | Spec: da decidere; immagine: con il nuovo frontend |

**C. Documentazione delle API**

| # | Proposta | Stato |
|---|---|---|
| C1 | `OPENAPI_TAGS` con una descrizione per gruppo e `System` primo; foglio di stile condiviso (`wilab/api/docs_style.py`) per le descrizioni sotto il titolo in `/docs` e nello `swagger.html` esportato. Da confrontare con quanto c'è già qui. | Da decidere |
| C2 | `swagger.html` esportato autonomo, con i riferimenti allo schema già risolti. | Da decidere |

**D. Correzioni e funzioni dell'altro branch**

| # | Proposta | Stato |
|---|---|---|
| D1 | `make reload-drivers` e `scripts/reload-drivers.sh`. | ✅ 2026-11-27, adattato: le antenne sono quelle della discovery, mai il driver dell'interfaccia di rete dell'host, rifiutato a servizio attivo (codice 3). Non provato sulla macchina (serve fermare il servizio). |
| D2 | Un hostapd ucciso da un segnale riportato come crash con un suggerimento sul driver (`122215e`). | Da decidere. Qui `HostapdSegfault` esiste; manca il suggerimento nel messaggio (ora può citare `make reload-drivers`). |
| D3 | Capability in `config.yaml` e `required_capabilities` nella reservation. | No nella 4.1: cambio di API; qui le antenne si scelgono con `GET /antennas/{interface}`. |
| D4 | Avviso "TX power non garantito". | Già coperto: TX power dichiarato in debug (gruppo T). |

**E. Regole sul CHANGELOG:** ✅ adottate il 2026-11-27 (paragrafo 1.2) e applicate a tutto il file.
L'altro branch usa CRLF; qui `.gitattributes` impone LF: si tiene LF.

---

<a id="hap-7"></a>
### B3. HAP-7 - Ipotesi: `hostapd -d` per tutta la vita dell'AP

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

<a id="api-7"></a>
### B4. API-7 - Azioni modellate come percorsi

**Gravità:** Bassa · **Confidenza:** Confermato · **File:** [wilab/api/routes/internet.py](wilab/api/routes/internet.py), [wilab/api/routes/txpower.py:51-87](wilab/api/routes/txpower.py#L51-L87)

**Problema.** `POST /internet/enable` e `POST /internet/disable` sono due endpoint per un booleano;
impostare il TX power è una `POST`, pur essendo un'operazione idempotente.

**Come si riproduce.** Leggere l'elenco dei percorsi.

**Come correggerlo.** Aggiungere il nuovo endpoint (non breaking) e poi togliere i vecchi (breaking). Decisione del 2026-11-25: rimandato, annotato in [TODOs/api/patch-access-point.md](TODOs/api/patch-access-point.md).

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

<a id="net-13"></a>
### B5. NET-13 - QoS: lo stop del profilo può far fallire lo stop della rete

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
### B6. RACE-3 - Lo stato di `QosManager` non ha lock

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
### B7. NET-12 - QoS: gara alla fine di un profilo `once`

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

<a id="wd-8"></a>
### B8. WD-8 - Una rete ripristinata perde il profilo QoS

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

<a id="cap-4"></a>
## 4. Prove da fare

I test automatici dei punti chiusi sono tutti scritti (unit in `tests/unit-tests/`, e2e in
`tests/e2e-tests/`, long run in `tests/long-run/`). Restano le prove che chiedono la macchina, una
persona o una VM di prova.

### 4.1 Prove su hardware (manuali, da raccogliere in `diagnostics/`)

Da eseguire una volta per confermare i punti "Ipotesi", poi a ogni cambio di kernel, driver o adattatore.

| Id | Prova | Conferma |
|---|---|---|
| H-05 | 24 ore con e senza comando TX power; contare i timeout del firmware nel log del kernel. | HAP-6 |
| H-06 | `kill -9` del servizio con reti e QoS attivi; verificare `tc`, file e subnet dopo il riavvio. | NET-9, NET-14 |
| H-07 | 24 ore con e senza `hostapd -d` sullo stesso traffico; confrontare `restarts.ap`. | HAP-7 |
| H-11 | `systemd-tmpfiles --cat-config` e rete attiva oltre il limite di età. | STAB-2 |
| H-12 | Rete attiva per 7 giorni con un client che ogni minuto si collega, ottiene un indirizzo, raggiunge Internet e registra l'esito. | obiettivo generale |

H-12 è la prova di accettazione: nessuna correzione vale se una rete non resta su per una settimana.

### 4.2 Prove sulla macchina: root o intervento fisico (con conferma, sistema libero)

Le eseguo io con `sudo`; telefono e ricollegamento fisico di un'antenna richiedono una persona vicino
alla macchina. Il distacco simulato con un AP attivo può bloccare la VM (23/11).

| ID | Intervento | Esito atteso |
|---|---|---|
| NET-14 | Client vero: download e `ssh` aperti, poi Internet disattivato; `kill -9` del servizio e regole dopo il riavvio. | Scheda [NET-14](#net-14). |
| WD-5 | Antenna scollegata per più di 2 minuti senza reservation, poi ricollegata (stesso nome e, se capita, un altro). | La voce sparisce da `/status` dopo circa 2 minuti, `degraded` finisce; l'antenna ricollegata torna come nuova. |
| WD-5 (AP attivo) | `WILAB_E2E=1 WILAB_E2E_USB=1 WILAB_E2E_USB_ACTIVE_AP=1 .venv/bin/pytest tests/e2e-tests/test_e2e_device_loss.py::test_antenna_gone_with_active_network`, mai eseguito. | Può bloccare la VM e staccare la USB (23/11): serve chi la ricollega. |
| WD-8 | Rete attiva con profilo QoS: `kill -9` di hostapd. | `restoring_ap`, poi rete attiva con il profilo QoS di nuovo attivo (dopo la correzione). |
| STAB-8 | Due reti attive; `time systemctl stop wi-lab`. | Arresto in meno di 60 s, nessun "stop-sigterm timed out" nel journal. |
| STAB-5 | Spostare l'orologio della VM di +2 h con una reservation attiva. | La reservation non scade in anticipo. |
| BUG-5 | Collegare un'antenna nuova a servizio avviato. | Compare in `/status` entro 30 s, oppure il motivo dello scarto è nel journal. |
| ARCH-11 D1 | `make stop`, `make reload-drivers`, `make start`. | `OK mt7921u: reloaded (...)`; le due antenne tornano nella discovery. |
| Telefono | SSID `Caffè ☕` e `my"net\` visibili; rete nascosta non ASCII; password di 8 e 63 caratteri; `wpa2-wpa3` con client WPA3 e WPA2 e `wpa1`; velocità a 20, 40 e 80 MHz sui 5 GHz con un client Wi-Fi 5 e uno Wi-Fi 6; `nslookup`; `/docs` e `ssh` verso il gateway rifiutati; isolamento tra reti; captive portal su `http://<gateway>:8081/`. | Connessione e DHCP funzionanti; host non raggiungibile dalla rete di test. |

### 4.3 Run sulla macchina via API (tester)

- **Monitoraggio continuo in ogni run:** `GET /api/v2/status` ogni 10-30 s (`status`, ogni voce di
  `degraded_reasons`, `recovery_state` e `runtime_state` delle antenne); `restarts` di
  `GET .../network` prima e dopo ogni test: ogni aumento corrisponde a un `restoring_ap` visto.
- **Long run** (`WILAB_LONG_RUN=1 .venv/bin/pytest tests/long-run -s`, 2 ore): da rieseguire prima del
  rilascio; ora finisce con il confronto di memoria, descrittori e thread del servizio (PERF-7).
- **HAP-6, HAP-7:** run lunghe identiche con la configurazione cambiata tra una run e l'altra;
  confronto di `404 reservation_invalidated` e `restarts.ap`.

---

<a id="cap-5"></a>
<a id="nm-1"></a>
## 5. NM-1 - Prova dei rami dell'installer che disattivano NetworkManager

**Stato (2026-11-27):** fatto nel codice e verificato su questa macchina (stadi 06 e 07 senza domande,
"Startup prechecks passed", nessun `nmcli`, riavvio della macchina con le radio `unmanaged` e nessuna
interfaccia P2P, unit con `RestartPreventExitStatus=78`). **Manca** la prova dei rami "chiedi e
disattiva", che qui non si possono provare: NetworkManager non è installato.

Serve una VM Ubuntu Server con NetworkManager attivo e un adattatore Wi-Fi, oppure, su questa macchina e
solo con la conferma dell'utente, `apt-get install network-manager` e `systemctl unmask
wpa_supplicant` prima della prova e la pulizia dopo. Lì:

1. Stadio `06-network-manager.sh` da una sessione SSH, risposta `y`: la sessione non cade,
   `systemctl is-enabled NetworkManager` dà `masked`, la default route è invariata. Risposta `n`:
   `NM_STATE "active_declined"`, l'installazione prosegue.
2. Stadio `07-wpa-supplicant.sh`, risposta `y`: `systemctl is-enabled wpa_supplicant` dà `masked` e
   `/run/wpa_supplicant/` non ha socket delle radio.
3. Con NetworkManager attivo, riavviare Wi-Lab: il journal ha il `WARNING` del precheck e il servizio
   funziona.
4. `uninstall.sh`: chiede se riattivare i due servizi mascherati e lo fa nell'ordine giusto.

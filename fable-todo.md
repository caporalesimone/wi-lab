# Attività da Fable-Notes

Gli ID rimandano direttamente al capitolo corrispondente in [Fable-Notes.md](Fable-Notes.md).
La priorità 1 raccoglie i bug concreti che compromettono creazione, avvio, perdita o ripristino delle reti.
La colonna **Done** segna con ✅ i punti implementati e committati (i test live possono essere ancora in corso).
Le ipotesi da verificare, i refactoring e le ottimizzazioni restano tra le altre attività, in ordine Fable e numerate da 2 in poi.

| Prio | ID | Done | Breve descrizione |
|---:|---|:---:|---|
| 1 | [BUG-1](Fable-Notes.md#L309) | ✅ | Validare gli input della richiesta di creazione e rifiutare SSID non sicuri. |
| 1 | [WD-2](Fable-Notes.md#L424) |  | Segnalare e ritentare il ripristino quando il watchdog fallisce. |
| 1 | [WD-1](Fable-Notes.md#L504) |  | Consentire più tentativi di ripristino dell'access point. |
| 1 | [WD-4](Fable-Notes.md#L559) | ✅ | Rendere la quarantena recuperabile e completare il cleanup. |
| 1 | [NET-1](Fable-Notes.md#L620) |  | Attendere il lock di iptables durante le operazioni firewall. |
| 1 | [HAP-1](Fable-Notes.md#L694) | ✅ | Riconoscere correttamente gli SSID con escape restituiti da hostapd. |
| 1 | [STAB-1](Fable-Notes.md#L756) |  | Limitare l'attesa dei processi e recuperare dai comandi bloccati. |
| 1 | [NET-2](Fable-Notes.md#L861) |  | Non dichiarare riuscita una rete se NAT o isolamento non sono configurati. |
| 1 | [STAB-3](Fable-Notes.md#L929) |  | Ripristinare reservation e reti dopo il riavvio del servizio. |
| 1 | [HAP-3](Fable-Notes.md#L994) |  | Classificare in modo coerente i guasti di inizializzazione hostapd. |
| 1 | [HAP-2](Fable-Notes.md#L1069) |  | Uniformare la classificazione dei guasti hostapd disabilitati. |
| 1 | [WD-3](Fable-Notes.md#L1111) |  | Ritentare il recupero DHCP e, se serve, ripristinare l'intera rete. |
| 1 | [WD-5](Fable-Notes.md#L1156) | ✅ parz. | Consentire cleanup e rimozione sicuri degli adattatori scomparsi. Fatti i punti 1–2 e la classificazione come guasto radio; il ritiro delle antenne rinominate (punto 3) dipende da ARCH-4. |
| 1 | [WD-7](Fable-Notes.md#L1221) |  | Verificare e riparare lo stato effettivo della rete nel watchdog. |
| 1 | [STAB-4](Fable-Notes.md#L1360) |  | Pulire all'avvio anche indirizzi, QoS, file e PID obsoleti. |
| 1 | [RACE-1](Fable-Notes.md#L1488) |  | Limitare l'attesa del lock sul dispositivo e restituire un esito occupato. |
| 1 | [WD-6](Fable-Notes.md#L1540) |  | Applicare backoff ai tentativi ripetuti di cleanup falliti. |
| 1 | [HAP-4](Fable-Notes.md#L1591) |  | Distinguere l'esaurimento del budget da un guasto radio reale. |
| 1 | [STAB-6](Fable-Notes.md#L1627) |  | Aggiornare l'interfaccia upstream quando cambiano le route. |
| 1 | [NET-6](Fable-Notes.md#L1772) |  | Ripulire i processi dnsmasq anche dopo un timeout di avvio. |
| 1 | [WD-8](Fable-Notes.md#L1823) |  | Conservare e riapplicare il profilo QoS dopo il ripristino della rete. |
| 1 | [BUG-3](Fable-Notes.md#L1912) |  | Allineare la validazione offline a quella eseguita all'avvio. |
| 1 | [NET-3](Fable-Notes.md#L2013) |  | Applicare l'isolamento anche a subnet diverse da `192.168.*`. |
| 1 | [BUG-5](Fable-Notes.md#L2307) |  | Riprovare la discovery degli adattatori ignorati e rendere visibili gli errori. |
| 1 | [BUG-9](Fable-Notes.md#L2362) |  | Allineare la validazione dei profili QoS custom al modello runtime. |
| 1 | [STAB-9](Fable-Notes.md#L2435) |  | Ripristinare le impostazioni unmanaged se NetworkManager si riavvia. |
| 1 | [STAB-8](Fable-Notes.md#L2469) |  | Limitare il lavoro di arresto entro il timeout di systemd. |
| 1 | [WD-10](Fable-Notes.md#L2502) |  | Non considerare guasto un access point solo per probe lenti. |
| 1 | [HAP-9](Fable-Notes.md#L2535) |  | Gestire attese DFS/CAC e timeout di avvio dei canali. |
| 1 | [HAP-10](Fable-Notes.md#L2562) |  | Correggere chiavi hostapd duplicate e mappatura della cifratura. |
| 1 | [NET-13](Fable-Notes.md#L2660) |  | Evitare che lo stop del profilo impedisca lo stop della rete. |
| 1 | [BUG-6](Fable-Notes.md#L2751) |  | Sostituire il controllo impreciso della modalità AP con una verifica affidabile. |
| 1 | [NET-9](Fable-Notes.md#L2783) |  | Pulire indirizzi obsoleti e rendere persistenti le subnet se necessario. |
| 1 | [NET-7](Fable-Notes.md#L2802) |  | Eliminare i lease quando termina la rete, preservandoli per il recupero DHCP. |
| 2 | [SEC-1](Fable-Notes.md#L227) |  | Limitare la route frontend ai file contenuti nella directory frontend. |
| 3 | [WD-9](Fable-Notes.md#L1283) |  | Supervisionare i loop in background e riavviare quelli terminati. |
| 4 | [SEC-3](Fable-Notes.md#L1406) |  | Limitare gli indirizzi e le interfacce su cui ascolta l'API. |
| 5 | [SEC-2](Fable-Notes.md#L1448) |  | Proteggere o oscurare gli ID reservation nell'output debug. |
| 6 | [BUG-2](Fable-Notes.md#L1673) |  | Correggere i controlli di salute di `/status` usando output strutturato. |
| 7 | [BUG-4](Fable-Notes.md#L1722) |  | Aggiornare e unificare la cache dei canali. |
| 8 | [STAB-5](Fable-Notes.md#L1863) |  | Usare scadenze monotone per misurare il tempo trascorso. |
| 9 | [NET-5](Fable-Notes.md#L1964) |  | Non registrare come errori le verifiche negative attese. |
| 10 | [STAB-2](Fable-Notes.md#L2058) |  | Spostare i file runtime in una directory privata e gestita. |
| 11 | [STAB-7](Fable-Notes.md#L2111) |  | Aggiungere un lockfile con versioni esatte delle dipendenze. |
| 12 | [NET-11](Fable-Notes.md#L2137) |  | Gestire o rifiutare esplicitamente valori QoS upload/download differenti. |
| 13 | [HAP-8](Fable-Notes.md#L2176) |  | Conservare un estratto sicuro dell'output hostapd per la diagnosi. |
| 14 | [HAP-5](Fable-Notes.md#L2216) |  | Verificare avvii radio concorrenti e serializzarli se necessario. |
| 15 | [HAP-6](Fable-Notes.md#L2266) |  | Verificare se ritardare la modifica della potenza TX migliora l'avvio. |
| 16 | [NET-8](Fable-Notes.md#L2594) |  | Sostituire il DNS predefinito specifico del laboratorio. |
| 17 | [NET-12](Fable-Notes.md#L2620) |  | Sincronizzare la fine del profilo QoS con lo stato QoS. |
| 18 | [BUG-7](Fable-Notes.md#L2695) |  | Rendere coerente lo stato della potenza TX in caso di mismatch. |
| 19 | [BUG-8](Fable-Notes.md#L2728) |  | Usare un confronto constant-time per il token. |
| 20 | [NET-10](Fable-Notes.md#L2836) |  | Gestire conflitti sulla porta 80, richieste malformate e regole firewall. |
| 21 | [NET-4](Fable-Notes.md#L2874) |  | Rimuovere il messaggio di log fuorviante sull'isolamento. |
| 22 | [HAP-7](Fable-Notes.md#L2897) |  | Verificare se l'output debug hostapd influisce sulla stabilità a lungo termine. |
| 23 | [RACE-2](Fable-Notes.md#L2917) |  | Costruire `/status` da uno snapshot coerente dello stato condiviso. |
| 24 | [RACE-3](Fable-Notes.md#L2938) |  | Sincronizzare le operazioni QoS per interfaccia. |
| 25 | [PERF-3](Fable-Notes.md#L2963) |  | Memorizzare brevemente i risultati dei controlli di salute. |
| 26 | [PERF-1](Fable-Notes.md#L2997) |  | Ridurre i comandi ridondanti durante l'avvio di una rete. |
| 27 | [PERF-2](Fable-Notes.md#L3033) |  | Separare i controlli di stato attivo dalle query dettagliate. |
| 28 | [PERF-5](Fable-Notes.md#L3061) |  | Rispettare il timeout richiesto senza imporre un minimo nascosto. |
| 29 | [PERF-6](Fable-Notes.md#L3094) |  | Sostituire l'attesa fissa per TX power con polling limitato. |
| 30 | [PERF-4](Fable-Notes.md#L3128) |  | Ridurre letture di discovery e probe hostapd non necessarie. |
| 31 | [API-2](Fable-Notes.md#L3176) |  | Uniformare i codici di stato per le reti non attive. |
| 32 | [API-4](Fable-Notes.md#L3214) |  | Usare codici di errore appropriati per gli esiti causati dal client. |
| 33 | [API-9](Fable-Notes.md#L3246) |  | Allineare gli esempi OpenAPI ai modelli correnti. |
| 34 | [API-5](Fable-Notes.md#L3271) |  | Restituire dati strutturati sullo stato della rete insieme al messaggio. |
| 35 | [API-10](Fable-Notes.md#L3306) |  | Rifiutare i campi sconosciuti nelle richieste. |
| 36 | [API-3](Fable-Notes.md#L3327) |  | Chiarire e uniformare i significati dei conflitti HTTP 409. |
| 37 | [API-11](Fable-Notes.md#L3358) |  | Semplificare e documentare i retry tra server e client. |
| 38 | [API-1](Fable-Notes.md#L3384) |  | Consolidare dati API duplicati e uniformare i nomi. |
| 39 | [API-8](Fable-Notes.md#L3403) |  | Rimuovere dettagli implementativi dai modelli di risposta pubblici. |
| 40 | [API-6](Fable-Notes.md#L3432) |  | Uniformare i nomi di endpoint e campi. |
| 41 | [API-7](Fable-Notes.md#L3455) |  | Valutare un modello API a risorse per le azioni enable/disable. |
| 42 | [ARCH-2](Fable-Notes.md#L3482) |  | Centralizzare la classificazione dei guasti. |
| 43 | [ARCH-1](Fable-Notes.md#L3519) |  | Separare le responsabilità di `NetworkManager`. |
| 44 | [ARCH-4](Fable-Notes.md#L3557) |  | Consolidare lo stato dei dispositivi in un registro unico. |
| 45 | [ARCH-3](Fable-Notes.md#L3602) |  | Separare il modello interno della rete dai modelli API. |
| 46 | [ARCH-5](Fable-Notes.md#L3636) |  | Costruire e avviare i manager esplicitamente tramite un contesto applicativo. |
| 47 | [ARCH-6](Fable-Notes.md#L3672) |  | Gestire dnsmasq come processo figlio in foreground. |
| 48 | [ARCH-7](Fable-Notes.md#L3700) |  | Consolidare in un helper il rilascio delle interfacce da NetworkManager. |
| 49 | [ARCH-10](Fable-Notes.md#L3728) |  | Definire regole di logging e limitare i messaggi ripetuti. |
| 50 | [ARCH-9](Fable-Notes.md#L3751) |  | Rimuovere codice, modelli e test inutilizzati. |
| 51 | [ARCH-8](Fable-Notes.md#L3782) |  | Sostituire l'accesso agli attributi privati di altre classi con metodi pubblici. |
| 52 | [ARCH-12](Fable-Notes.md#L3808) |  | Aggiungere `wilab/wifi/__init__.py`. |
| 53 | [ARCH-11](Fable-Notes.md#L3826) |  | Definire la strategia di integrazione prima di applicare patch specifiche del branch. |

## Test

Questo capitolo elenca i test che servono per considerare validato ogni ID.
I test automatici (U) li scrivo ed eseguo io a ogni commit; gli altri sono per il tester.

| Tipo | Significato |
|---|---|
| U | Test automatico pytest nel repository, senza hardware. |
| API | Test live solo tramite API (script del tester), nessun intervento fisico. |
| HW | Test live con intervento su hardware o host: staccare USB, `kill`, riavvio di servizi. |
| SOAK | Durata lunga o carico (ore, migliaia di cicli). |
| ISP | Ispezione su macchina: log, `iptables`, `tc`, file, processi. |

Per ogni test live raccogliere: ora UTC, antenna (interfaccia **e** `display_name` da `/status`,
non dedotta dall'ordine), banda/canale, status HTTP con `detail.code`, e le righe di
`journalctl -u wi-lab` e `journalctl -k` nella stessa finestra temporale.

### Test per i fix già fatti

#### BUG-1 - Validazione della richiesta di creazione (commit `d4054d8`)

Tipo: U (in `tests/test_models.py`, `tests/test_api.py`, `tests/test_wifi.py`) + API + ISP.

| # | Passi | Esito atteso |
|---|---|---|
| 1 | Create con SSID di 33 caratteri ASCII, poi di 80 caratteri. | `422` subito, nessun log hostapd per quell'antenna. Prima: `500` "hostapd exited with code 1". |
| 2 | Create con SSID di esattamente 32 caratteri ASCII. | `200`, SSID visibile e completo sul telefono. |
| 3 | Create con SSID di 16 caratteri `è` (32 byte) e poi di 17 (34 byte). | Il primo `200`, il secondo `422`. |
| 4 | Create con `"ssid": "x\ninterface=eth0"`, poi `"x\rabc"`, poi con un TAB. | `422`. |
| 5 | Create `wpa2` con password `abc`, poi di 64 caratteri, poi senza password. | `422` in tutti i casi. Prima: `500`. |
| 6 | Create `wpa2` con password di 8 e di 63 caratteri. | `200`, il client si connette con quella password. |
| 7 | Create con `channel: 36` e `band: 2.4ghz`. | `422`. |
| 8 | ISP: con una rete attiva, leggere `/tmp/wilab-hostapd/ap-*/hostapd.conf`. | C'è `ssid2=<esadecimale>` e nessuna riga `ssid=`. |

#### HAP-1 - SSID con escape (commit `d4054d8`)

Tipo: U (`tests/test_wifi.py`) + API + SOAK breve.

| # | Passi | Esito atteso |
|---|---|---|
| 1 | Create WPA2 con SSID `Caffè ☕` su 2.4 GHz e su 5 GHz. | `200` subito, senza `409/1001`. Nome corretto sul telefono; connessione e DHCP funzionano. |
| 2 | Create con SSID `my"net\`. | `200`, nome corretto sul telefono. |
| 3 | Tenere attiva la rete del punto 1 per 15 minuti. | Nessun `restoring_ap` in `/status`, nessuna quarantena, nessun "AP restart" nel journal. |
| 4 | Create con `hidden: true` e SSID non ASCII; connettersi inserendo il nome a mano. | Connessione riuscita (verifica di `ssid2` con `ignore_broadcast_ssid`). |
| 5 | Regressione: 50 cicli create/delete con SSID ASCII su entrambe le antenne. | Tutti `200`. |

#### Documentazione dello stato `degraded` (commit `c55458f`)

Tipo: U (esempi OpenAPI) + API.

| # | Passi | Esito atteso |
|---|---|---|
| 1 | Aprire `/docs` → System → `GET /api/v1/status` → Responses 200 → Examples. | Tre esempi: `standby`, `ok`, `degraded_quarantine`, con la descrizione delle cause di `degraded`. |
| 2 | Nello script del tester, interrogare `/status` ogni 10–30 s per tutta la run. | Ogni voce con `recovery_state` o `runtime_state` viene registrata con ora, interfaccia e `display_name`. |
| 3 | Con un'antenna in quarantena e nessuna rete attiva. | `status: degraded` (non `standby`), `active_networks: 0`. |

#### WD-5 e classificazione dell'interfaccia sparita (commit `7d99d90`)

Tipo: U (`tests/test_device_loss.py`) + HW. È lo scenario dell'incidente del 23/11 alle 12:23.

| # | Passi | Esito atteso |
|---|---|---|
| 1 | Reservation su antenna-1. Avviare una create e, durante l'avvio, staccare la USB di antenna-1; riattaccarla dopo circa 5 s. | La create risponde `409/1001` con `Retry-After: 5` (non `500/1003`). Journal: `Interface ... disappeared during startup` e, nello stop, `Interface ... is gone; skipping interface reset`. Nessun `Startup rollback failed`. |
| 2 | Dopo il punto 1, ripetere la stessa POST con lo stesso ID dopo `Retry-After`. | `200` se l'antenna è tornata; altrimenti un altro `409/1001` (`Retry-After: 10`). |
| 3 | Come al punto 1, ma tenere l'antenna staccata per più di 20 s, ripetendo la POST rispettando `Retry-After`. | Terzo tentativo: `500/1003`, `/status` mostra antenna-1 `recovering` (recovery USB avviato), **non** `unavailable`. |
| 4 | Dopo il punto 3, riattaccare l'antenna entro 10 minuti. | Entro circa 1 minuto: `USB recovery verified`, `recovery_state` sparisce, l'antenna si può prenotare. |
| 5 | Antenna libera (nessuna reservation): staccare e riattaccare la USB. | Nessuna quarantena; una create successiva su quell'antenna funziona. |
| 6 | Rete attiva su antenna-1: staccare la USB per 30 s e riattaccarla. | Il watchdog prova a ripristinare. Esiti accettabili: rete ripristinata, oppure reservation invalidata (`404`) con antenna `recovering` e poi di nuovo libera. Mai `unavailable` permanente. (Il numero di tentativi del watchdog cambierà con WD-1/WD-2.) |

#### WD-4 - Ri-verifica periodica delle antenne `unavailable` (commit `7d99d90`)

Tipo: U (`tests/test_device_loss.py`) + HW + ISP.

| # | Passi | Esito atteso |
|---|---|---|
| 1 | Come WD-5 punto 3, ma tenere l'antenna staccata più di 11 minuti (il recovery USB esaurisce i 10 tentativi). | `/status` passa da `recovering` a `unavailable`. Journal: `USB recovery exhausted`, poi `still unavailable after re-probe N; next attempt in S s` con S = 30, 60, 120, 300, 600, 900. |
| 2 | Riattaccare l'antenna. | Entro il prossimo intervallo di backoff (al massimo 15 minuti): `passed the probe and is allocatable again`, `recovery_state` sparisce, `status` torna `standby`/`ok`. **Senza riavviare il servizio.** |
| 3 | Subito dopo il punto 2: reservation e create su quell'antenna. | `200`, rete funzionante. |
| 4 | ISP durante la ri-verifica: `iw dev`, `ip -br link`. | La rete di prova è nascosta (`wilab-check-…`) e sparisce dopo la verifica; l'interfaccia resta `DOWN` e in modalità managed. L'interfaccia upstream (`ens18`) non viene mai toccata. |
| 5 | Antenna sparita dal bus USB (`lsusb` non la mostra). | Resta `unavailable`; nel journal `is not present; re-probe skipped`. Nessun altro effetto. |

#### Regressione generale dopo questi fix

Tipo: SOAK. Rieseguire la run completa del tester (sameres, parallel, herd, chaos, mix) con entrambe
le antenne per almeno 90 minuti. Atteso: nessuna antenna `unavailable` alla fine; ogni `500/1003`
deve essere seguito da un ritorno automatico dell'antenna (journal: `USB recovery verified` o
`allocatable again`).

### Test previsti per gli altri ID

I test U li scrivo insieme al fix. Le colonne indicano cosa servirà al tester per validare.

| ID | Tipo | Test | Esito atteso dopo il fix |
|---|---|---|---|
| WD-5 (p. 3) | HW | Staccare un'antenna e farla ricomparire con un nome diverso (oppure rimuovere il driver). | La voce vecchia viene ritirata dopo N scansioni; `/status` non resta `degraded`. |
| WD-2 | U + HW | Rete attiva; far fallire il riavvio del watchdog per una causa non radio (es. `kill -9` di hostapd e porta occupata). | `/status` mostra un `runtime_state` di errore e il watchdog riprova; la rete non resta spenta in silenzio. |
| WD-1 | U + HW + SOAK | Rete attiva; `kill -9` di hostapd, attendere il ripristino; ripeterlo 3 volte a distanza di minuti. | Ogni volta `restoring_ap` e poi rete attiva; nessuna quarantena al secondo guasto. |
| NET-1 | U + SOAK + ISP | Molte create/delete concorrenti sulle due antenne; `iptables -V` per sapere se è legacy o nft. | Nessun errore "Another app is currently holding the xtables lock"; nessuna quarantena per stop falliti. |
| STAB-1 | U | Comando finto che non termina mai. | `CommandStuck` entro il tempo di grazia; il lock del dispositivo viene rilasciato. Test live solo se si trova un modo sicuro per bloccare `iw`. |
| NET-2 | U + API + ISP | Create con `internet_enabled: true` mentre le regole NAT non si possono inserire (simulazione da concordare). | La create fallisce (o `internet_enabled: false` nello stato), mai `200` con NAT assente. |
| STAB-3 | HW | Reservation e rete attive, poi `systemctl restart wi-lab`. | Dopo il riavvio la reservation esiste (`GET` → `200`) e l'SSID torna visibile. |
| HAP-3 | U + SOAK | Run lunga di create con statistiche per codice. | Lo stesso guasto beacon dà sempre `409/1001`, mai `500` generico. |
| HAP-2 | U + SOAK | Come HAP-3. | Nessun `500` generico per `interface_init_failed`; classificazione stabile. |
| WD-3 | U + HW | Rete attiva; `kill -9` di dnsmasq due volte a distanza di minuti. | Ogni volta `restoring_dhcp` e poi DHCP di nuovo attivo; un nuovo client ottiene l'indirizzo. |
| WD-7 | HW + ISP | Rete attiva con client; togliere a mano l'indirizzo del gateway (`ip addr del`) o una regola NAT. | Il watchdog se ne accorge e ripara entro pochi cicli; il client torna a navigare. |
| STAB-4 | HW + ISP | Rete con profilo QoS; `kill -9` del servizio e di dnsmasq; riavvio. | Dopo il riavvio: nessun `netem`/`ifb` residuo (`tc qdisc show`), nessun PID vecchio; nuova rete sulla stessa antenna `200`. |
| RACE-1 | U + API | Tenere occupata un'antenna (create lunga su DFS) e lanciare 45 `GET .../network` più `/status`. | `/status` risponde subito; le richieste in attesa ottengono un esito "occupato" entro un limite. |
| WD-6 | U + ISP | Far fallire sempre il cleanup alla scadenza (simulazione da concordare). | Nel journal i tentativi si diradano (backoff), non uno ogni 5 s. |
| HAP-4 | U + SOAK | Run lunga. | Nessuna quarantena causata da un tentativo interrotto dal budget di 15 s. |
| STAB-6 | HW | Con `upstream_interface: auto`, cambiare la route di default verso un'altra interfaccia, poi creare una rete. | La nuova regola NAT usa la nuova interfaccia; il client naviga. |
| NET-6 | U | dnsmasq che va in timeout all'avvio. | Lo stop successivo riesce; nessuna antenna bloccata. |
| WD-8 | U + HW | Rete con profilo QoS attivo; `kill -9` di hostapd. | Dopo `restoring_ap` il profilo QoS è di nuovo attivo (`GET .../qos`). |
| BUG-3 | U | Configurazione con `dns_server: foo`. | Validazione offline e avvio danno lo stesso esito. |
| NET-3 | U + API + ISP | Due reti su subnet `10.x` (configurazione da concordare). | Regole di isolamento presenti; un client di una rete non raggiunge l'altra. |
| BUG-5 | U + HW | Collegare un'antenna nuova a servizio avviato. | Compare in `/status` entro 30 s; se viene scartata, il motivo appare a livello INFO o WARNING. |
| BUG-9 | U | Profilo QoS custom valido per lo schema ma non per il runtime. | Profilo rifiutato con errore chiaro; il servizio si avvia comunque. |
| STAB-9 | HW | Rete attiva; `systemctl restart NetworkManager`. | `nmcli device status` mostra la radio come unmanaged; l'AP resta su. |
| STAB-8 | HW | Due reti attive; `time systemctl stop wi-lab`. | Arresto in meno di 30 s, nessun "stop-sigterm timed out". |
| WD-10 | U + SOAK | Run lunga con carico CPU alto sulla VM. | Nessun riavvio AP con il processo vivo e lo stato ENABLED. |
| HAP-9 | API | Con DFS abilitato, create sul canale 124 (attesa radar fino a 10 min). | Risposta coerente (attesa gestita o rifiuto esplicito), non un timeout a 75 s. |
| HAP-10 | U + API | Create `wpa2-wpa3` e `wpa`. | Una sola riga `wpa_key_mgmt` in `hostapd.conf`; i client WPA2 e WPA3 si connettono. |
| NET-13 | U | Stop della rete durante un profilo QoS con `tc` lento. | Lo stop della rete riesce comunque. |
| BUG-6 | U | `iw phy` senza modalità AP. | Interfaccia rifiutata. |
| NET-9 | HW | Rete attiva, `kill -9` del servizio, riavvio, nuova rete sulla stessa antenna. | Indirizzo vecchio rimosso; stessa subnet di prima. |
| NET-7 | API + ISP | Rete con client, rilascio, nuova rete sulla stessa antenna. | File dei lease vuoto all'inizio della nuova rete. |
| SEC-1 | API | `curl --path-as-is http://<host>:8080//etc/passwd` e `/../config.yaml`. | `404`; solo i file del frontend sono serviti. |
| WD-9 | U + HW | `config.yaml` malformato per 1 minuto, poi ripristinato. | La discovery continua a girare (log di errore, poi ripresa). |
| SEC-3 | API | Da un telefono collegato a una rete Wi-Lab: `curl http://<gateway>:8080/docs`. | Connessione rifiutata. |
| SEC-2 | API | Client B chiama `/debug` mentre A ha una reservation. | Gli ID di A non sono visibili. |
| BUG-2 | U + API | Rete con `internet_enabled: false` e nessun'altra rete. | `/status` non è `degraded`. |
| BUG-4 | U | Canale `no IR` che diventa disponibile. | La validazione accetta il canale dopo l'aggiornamento della cache. |
| STAB-5 | U + HW | Spostare l'orologio della VM di +2 h con una reservation attiva. | La reservation non scade in anticipo. |
| NET-5 | U + ISP | Create con Internet. | Nessuna riga `ERROR` nel journal per una creazione riuscita. |
| STAB-2 | ISP | Dopo l'aggiornamento: dove stanno i file runtime. | In una directory privata (es. `/run/wilab`), non in `/tmp`. |
| STAB-7 | ISP | Due installazioni pulite in giorni diversi. | `pip freeze` identico. |
| NET-11 | API + ISP | QoS con `download_quality: 40`, `upload_quality: 90`. | Rifiuto esplicito oppure `tc` con valori diversi per le due direzioni. |
| HAP-8 | HW + ISP | Provocare un guasto di avvio. | Nel journal c'è un estratto dell'output hostapd senza password o SSID in chiaro. |
| HAP-5 | SOAK | Run di avvii concorrenti con e senza serializzazione tra antenne. | Confronto del tasso di guasti radio (ipotesi da verificare). |
| HAP-6 | SOAK | Run con ritardo della TX power e senza. | Confronto del tasso di guasti (ipotesi). |
| NET-8 | API | Configurazione senza `dns_server`; client collegato: `nslookup example.com`. | Risoluzione riuscita. |
| NET-12 | U | Fine di un profilo `once` mentre ne parte un altro. | Il nuovo profilo resta attivo. |
| BUG-7 | U + API | `POST .../txpower` che non viene applicato dall'hardware. | `GET .../txpower` riporta lo stato reale. |
| BUG-8 | U | Confronto del token. | Usa `hmac.compare_digest`; token errato → `401`. |
| NET-10 | API + ISP | Porta 80 occupata sull'host, create con captive portal; POST `/login` con `Content-Length: abc`. | Errore chiaro alla create; `400` per la richiesta malformata, il portale resta su. |
| NET-4 | ISP | Creare una rete e leggere il log. | Nessuna riga "Isolation disabled for testing". |
| HAP-7 | SOAK | Run lunga con `hostapd -d` e senza. | Confronto di stabilità (ipotesi). |
| RACE-2 | U + API | `/status` in ciclo stretto durante create/delete ripetuti. | Nessun `degraded` spurio. |
| RACE-3 | U | Operazioni QoS concorrenti sulla stessa interfaccia. | Stato QoS coerente. |
| PERF-3 | ISP | `strace -f -e trace=execve` durante 10 `/status`. | Meno processi creati per chiamata (cache breve). |
| PERF-1 | ISP | Tempo di una create e numero di `execve`. | Meno comandi rispetto a oggi, tempo non peggiore. |
| PERF-2 | ISP | `execve` durante `GET .../network` e `internet/enable`. | Niente `iw station dump` non necessari. |
| PERF-5 | U | `execute_command(["sleep","3"], timeout=1)`. | Timeout dopo 1 s. |
| PERF-6 | API | Durata di `POST .../txpower`. | Sotto i 3 s quando la potenza è applicata subito. |
| PERF-4 | ISP | `perf stat` sui fork in 60 s a riposo. | Meno processi creati dal polling. |
| API-2 | API | Reservation senza rete: `internet/enable`, `qos/profile`, `txpower`. | Stesso status HTTP per "rete non attiva". |
| API-4 | API | Terza create fallita per guasto radio. | Status HTTP non `500` per esiti causati dal client o dal dispositivo (da definire). |
| API-9 | U | Confronto automatico tra esempi OpenAPI e modelli. | Test che fallisce se un esempio non corrisponde al modello. |
| API-5 | API | Create riuscita. | La risposta contiene lo stato strutturato della rete. |
| API-10 | API | Create con `"captive-portal": true` (campo sconosciuto). | `422`. |
| API-3 | API | `409` su rete già attiva, durante un ripristino, su cooldown. | `detail.code` diversi per ogni significato; retry dopo timeout con lo stesso body riconoscibile (caso "already active" visto nei test del 23/11). |
| API-11 | API | Script client che segue solo il contratto documentato. | Nessun retry ridondante; comportamento identico. |
| API-1, API-8, API-6, API-7 | API | Confronto delle risposte e dei percorsi con la documentazione. | Nomi uniformi; nessun dettaglio interno (`pid_file`); vecchi nomi deprecati ma funzionanti se previsto. |
| ARCH-1 … ARCH-12 | U | Refactoring senza cambi di comportamento. | Tutta la suite U passa; run SOAK di regressione senza differenze. |

# Attività da Fable-Notes

Gli ID rimandano direttamente al capitolo corrispondente in [Fable-Notes.md](Fable-Notes.md).
La priorità 1 raccoglie i bug concreti che compromettono creazione, avvio, perdita o ripristino delle reti.
La colonna **Done** segna con ✅ i punti implementati e committati (i test live possono essere ancora in corso).
Le ipotesi da verificare, i refactoring e le ottimizzazioni restano tra le altre attività, in ordine Fable e numerate da 2 in poi.

| Prio | ID | Done | Breve descrizione |
|---:|---|:---:|---|
| 1 | [BUG-1](Fable-Notes.md#L309) | ✅ | Validare gli input della richiesta di creazione e rifiutare SSID non sicuri. |
| 1 | [WD-2](Fable-Notes.md#L424) | ✅ | Segnalare e ritentare il ripristino quando il watchdog fallisce. |
| 1 | [WD-1](Fable-Notes.md#L504) | ✅ | Consentire più tentativi di ripristino dell'access point. |
| 1 | [WD-4](Fable-Notes.md#L559) | ✅ | Rendere la quarantena recuperabile e completare il cleanup. |
| 1 | [NET-1](Fable-Notes.md#L620) | ✅ | Attendere il lock di iptables durante le operazioni firewall. |
| 1 | [HAP-1](Fable-Notes.md#L694) | ✅ | Riconoscere correttamente gli SSID con escape restituiti da hostapd. |
| 1 | [STAB-1](Fable-Notes.md#L756) | ✅ | Limitare l'attesa dei processi e recuperare dai comandi bloccati. Il runner smette di aspettare 2 s dopo il SIGKILL (`checks.commands.stuck`); se un ciclo interno si blocca, Wi-Lab si riavvia tramite il watchdog di systemd solo quando non ci sono reservation attive. Un comando bloccato nel kernel non fa riavviare. |
| 1 | [NET-2](Fable-Notes.md#L861) | ✅ | Non dichiarare riuscita una rete se NAT o isolamento non sono configurati. |
| 1 | [HAP-3](Fable-Notes.md#L929) | ✅ | Classificare in modo coerente i guasti di inizializzazione hostapd. |
| 1 | [HAP-2](Fable-Notes.md#L1004) | ✅ | Uniformare la classificazione dei guasti hostapd disabilitati. |
| 1 | [WD-3](Fable-Notes.md#L1046) | ✅ | Ritentare il recupero DHCP e, se serve, ripristinare l'intera rete. |
| 1 | [WD-5](Fable-Notes.md#L1091) | ✅ parz. | Consentire cleanup e rimozione sicuri degli adattatori scomparsi. Fatti i punti 1–2 e la classificazione come guasto radio; il ritiro delle antenne rinominate (punto 3) dipende da ARCH-4. |
| 1 | [WD-7](Fable-Notes.md#L1156) | ✅ parz. | Verificare e riparare lo stato effettivo della rete nel watchdog. Fatti gateway, `ip_forward`, regole NAT, blocco Internet, isolamento e captive portal. Manca il controllo che la radio trasmetta davvero (`tx_packets`), da verificare prima sull'hardware. |
| 1 | [STAB-4](Fable-Notes.md#L1295) | ✅ | Pulire all'avvio anche indirizzi, QoS, file e PID obsoleti. |
| 1 | [RACE-1](Fable-Notes.md#L1425) | ✅ | Limitare l'attesa del lock sul dispositivo e restituire un esito occupato. |
| 1 | [WD-6](Fable-Notes.md#L1477) | ✅ | Applicare backoff ai tentativi ripetuti di cleanup falliti. |
| 1 | [HAP-4](Fable-Notes.md#L1528) | ✅ | Distinguere l'esaurimento del budget da un guasto radio reale. |
| 1 | [STAB-6](Fable-Notes.md#L1564) | ✅ | Aggiornare l'interfaccia upstream quando cambiano le route. |
| 1 | [NET-6](Fable-Notes.md#L1709) | ✅ | Ripulire i processi dnsmasq anche dopo un timeout di avvio. |
| 1 | [HAP-10](Fable-Notes.md#L2499) | ✅ | Correggere chiavi hostapd duplicate e mappatura della cifratura; `wpa` diventa `422` (breaking, documentato); aggiungere `wpa1` (WPA/TKIP) solo sulle antenne in cui la discovery lo conferma utilizzabile. Dettagli nel capitolo 43. La discovery controlla il cifrario TKIP del driver (`iw phy`); la prova reale di `wpa1` è nell'e2e, da eseguire. |
| 1 | [HAP-11](Fable-Notes.md#L2587) | ✅ | Larghezza di canale (20/40/80 MHz) e generazione Wi-Fi (802.11n/ac/ax) su entrambe le bande. Decisioni (2026-11-25): due campi `channel_width` e `wifi_generation`; 40 MHz sui 2,4 GHz permesso, con la larghezza effettiva in `reported_channel_width`; 802.11ax subito, dove la discovery vede HE in modalità AP; default 20 MHz / 802.11n. Prove su hardware e telefono da fare. |
| 1 | [BUG-3](Fable-Notes.md#L1849) |  | Allineare la validazione offline a quella eseguita all'avvio. |
| 1 | [NET-3](Fable-Notes.md#L1950) |  | Applicare l'isolamento anche a subnet diverse da `192.168.*`. |
| 1 | [BUG-5](Fable-Notes.md#L2244) |  | Riprovare la discovery degli adattatori ignorati e rendere visibili gli errori. |
| 1 | [STAB-9](Fable-Notes.md#L2372) |  | Ripristinare le impostazioni unmanaged se NetworkManager si riavvia. |
| 1 | [STAB-8](Fable-Notes.md#L2406) |  | Limitare il lavoro di arresto entro il timeout di systemd. |
| 1 | [WD-10](Fable-Notes.md#L2439) |  | Non considerare guasto un access point solo per probe lenti. |
| 1 | [HAP-9](Fable-Notes.md#L2472) |  | Gestire attese DFS/CAC e timeout di avvio dei canali. |
| 1 | [BUG-6](Fable-Notes.md#L2834) |  | Sostituire il controllo impreciso della modalità AP con una verifica affidabile. |
| 1 | [NET-9](Fable-Notes.md#L2866) |  | Pulire indirizzi obsoleti e rendere persistenti le subnet se necessario. |
| 1 | [NET-7](Fable-Notes.md#L2884) |  | Eliminare i lease quando termina la rete, preservandoli per il recupero DHCP. |
| 2 | [SEC-1](Fable-Notes.md#L227) |  | Limitare la route frontend ai file contenuti nella directory frontend. |
| 3 | [WD-9](Fable-Notes.md#L1218) | ✅ | Supervisionare i loop in background e riavviare quelli terminati. |
| 4 | [SEC-3](Fable-Notes.md#L1341) | ✅ | Limitare gli indirizzi e le interfacce su cui ascolta l'API. Fatto con una regola `INPUT` per rete (IPv4 e IPv6): i client delle reti Wi-Lab non raggiungono l'host, né API né SSH; restano DHCP, ping e, con il captive portal, DNS e pagina del portale. |
| 5 | [SEC-2](Fable-Notes.md#L1383) |  | Proteggere o oscurare gli ID reservation nell'output debug. **Decisione:** `/debug` per ora resta; in futuro verrà tolto e sostituito da un sistema diverso. |
| 6 | [BUG-2](Fable-Notes.md#L1610) | ✅ | Correggere i controlli di salute di `/status` usando output strutturato. |
| 7 | [BUG-4](Fable-Notes.md#L1659) | ✅ | Aggiornare e unificare la cache dei canali. |
| 8 | [STAB-5](Fable-Notes.md#L1800) |  | Usare scadenze monotone per misurare il tempo trascorso. |
| 9 | [NET-5](Fable-Notes.md#L1901) |  | Non registrare come errori le verifiche negative attese. |
| 10 | [STAB-2](Fable-Notes.md#L1995) |  | Spostare i file runtime in una directory privata e gestita. |
| 11 | [STAB-7](Fable-Notes.md#L2048) |  | Aggiungere un lockfile con versioni esatte delle dipendenze. |
| 13 | [HAP-8](Fable-Notes.md#L2113) |  | Conservare un estratto sicuro dell'output hostapd per la diagnosi. |
| 14 | [HAP-5](Fable-Notes.md#L2153) |  | Verificare avvii radio concorrenti e serializzarli se necessario. |
| 15 | [HAP-6](Fable-Notes.md#L2203) |  | Verificare se ritardare la modifica della potenza TX migliora l'avvio. |
| 16 | [NET-8](Fable-Notes.md#L2677) |  | Sostituire il DNS predefinito specifico del laboratorio. |
| 18 | [BUG-7](Fable-Notes.md#L2778) |  | Rendere coerente lo stato della potenza TX in caso di mismatch. |
| 19 | [BUG-8](Fable-Notes.md#L2811) |  | Usare un confronto constant-time per il token. |
| 20 | [NET-10](Fable-Notes.md#L2918) |  | Gestire conflitti sulla porta 80, richieste malformate e regole firewall. |
| 21 | [NET-4](Fable-Notes.md#L2956) | ✅ | Rimuovere il messaggio di log fuorviante sull'isolamento. |
| 22 | [HAP-7](Fable-Notes.md#L2979) |  | Verificare se l'output debug hostapd influisce sulla stabilità a lungo termine. |
| 23 | [RACE-2](Fable-Notes.md#L2999) | ✅ | Costruire `/status` da uno snapshot coerente dello stato condiviso. |
| 25 | [PERF-3](Fable-Notes.md#L3045) |  | Memorizzare brevemente i risultati dei controlli di salute. |
| 26 | [PERF-1](Fable-Notes.md#L3079) | ✅ parz. | Ridurre i comandi ridondanti durante l'avvio di una rete. Fatti i tagli a basso rischio (validazioni `iw`, `dnsmasq --version`, `nmcli --version`). Non fatto di proposito `iptables-restore` in blocco: cambierebbe come si installano e tolgono tutte le regole, appena consolidato con NET-2, SEC-3 e WD-7. |
| 27 | [PERF-2](Fable-Notes.md#L3115) |  | Separare i controlli di stato attivo dalle query dettagliate. |
| 28 | [PERF-5](Fable-Notes.md#L3143) |  | Rispettare il timeout richiesto senza imporre un minimo nascosto. |
| 29 | [PERF-6](Fable-Notes.md#L3176) |  | Sostituire l'attesa fissa per TX power con polling limitato. |
| 30 | [PERF-4](Fable-Notes.md#L3210) |  | Ridurre letture di discovery e probe hostapd non necessarie. |
| 31 | [API-2](Fable-Notes.md#L3258) | ✅ | Uniformare i codici di stato per le reti non attive. |
| 32 | [API-4](Fable-Notes.md#L3296) | ✅ | Usare codici di errore appropriati per gli esiti causati dal client. |
| 33 | [API-9](Fable-Notes.md#L3328) | ✅ | Allineare gli esempi OpenAPI ai modelli correnti. |
| 34 | [API-5](Fable-Notes.md#L3353) |  | Restituire dati strutturati sullo stato della rete insieme al messaggio. |
| 35 | [API-10](Fable-Notes.md#L3388) |  | Rifiutare i campi sconosciuti nelle richieste. |
| 36 | [API-3](Fable-Notes.md#L3409) |  | Chiarire e uniformare i significati dei conflitti HTTP 409. |
| 37 | [API-11](Fable-Notes.md#L3440) |  | Semplificare e documentare i retry tra server e client. |
| 38 | [API-1](Fable-Notes.md#L3466) |  | Consolidare dati API duplicati e uniformare i nomi. |
| 39 | [API-8](Fable-Notes.md#L3485) | ✅ | Rimuovere dettagli implementativi dai modelli di risposta pubblici. Fatto con la `GET .../network` a sezioni (`radio`, `wifi`, `ip`, ...): niente più `dhcp.*_file`, `network_addr`, `interface`/`subnet` ripetuti, `clients_connected`. |
| 40 | [API-6](Fable-Notes.md#L3514) |  | Uniformare i nomi di endpoint e campi. |
| 41 | [API-7](Fable-Notes.md#L3537) |  | Valutare un modello API a risorse per le azioni enable/disable. |
| 42 | [ARCH-2](Fable-Notes.md#L3564) |  | Centralizzare la classificazione dei guasti. |
| 43 | [ARCH-1](Fable-Notes.md#L3601) |  | Separare le responsabilità di `NetworkManager`. |
| 44 | [ARCH-4](Fable-Notes.md#L3639) |  | Consolidare lo stato dei dispositivi in un registro unico. |
| 45 | [ARCH-3](Fable-Notes.md#L3684) | ✅ parz. | Separare il modello interno della rete dai modelli API. Fatto: la create usa `NetworkCreateBody` e la `GET` `NetworkResponse`, separati dai modelli interni. Manca la dataclass interna al posto di `NetworkStatus` in `manager.active` (con `_expires_at_timestamp`). |
| 46 | [ARCH-5](Fable-Notes.md#L3718) |  | Costruire e avviare i manager esplicitamente tramite un contesto applicativo. |
| 47 | [ARCH-6](Fable-Notes.md#L3754) |  | Gestire dnsmasq come processo figlio in foreground. |
| 48 | [ARCH-7](Fable-Notes.md#L3782) |  | Consolidare in un helper il rilascio delle interfacce da NetworkManager. |
| 49 | [ARCH-10](Fable-Notes.md#L3810) |  | Definire regole di logging e limitare i messaggi ripetuti. |
| 50 | [ARCH-9](Fable-Notes.md#L3833) |  | Rimuovere codice, modelli e test inutilizzati. |
| 51 | [ARCH-8](Fable-Notes.md#L3864) |  | Sostituire l'accesso agli attributi privati di altre classi con metodi pubblici. |
| 52 | [ARCH-12](Fable-Notes.md#L3890) | ✅ | Aggiungere `wilab/wifi/__init__.py`. |
| 53 | [ARCH-11](Fable-Notes.md#L3908) |  | Definire la strategia di integrazione prima di applicare patch specifiche del branch. |
| 54 | [BUG-9](Fable-Notes.md#L2299) |  | Allineare la validazione dei profili QoS custom al modello runtime. |
| 55 | [NET-13](Fable-Notes.md#L2743) |  | Evitare che lo stop del profilo impedisca lo stop della rete. |
| 56 | [RACE-3](Fable-Notes.md#L3020) |  | Sincronizzare le operazioni QoS per interfaccia. |
| 57 | [NET-12](Fable-Notes.md#L2703) |  | Sincronizzare la fine del profilo QoS con lo stato QoS. |
| 58 | [NET-11](Fable-Notes.md#L2074) |  | Gestire o rifiutare esplicitamente valori QoS upload/download differenti. |
| 59 | [WD-8](Fable-Notes.md#L1760) |  | Conservare e riapplicare il profilo QoS dopo il ripristino della rete. |
| Ultima | RELEASE-API |  | **Da fare solo alla fine, quando si dichiara completata la release.** Revisione con Fable di tutte le API: ogni endpoint, parametro, codice di stato, `detail.code`, header (`Retry-After`) ed esempio deve corrispondere a quanto documentato in Swagger (`/docs`) e ReDoc (`/redoc`), oltre che in `docs/ap-creation-procedure.md` e nel capitolo API della 4.0.0 in `CHANGELOG.md`. Correggere ogni differenza prima del rilascio. |

Le voci 54–59 riguardano il **QoS**, ancora sperimentale e non testato: sono in fondo di proposito e si fanno dopo tutte le altre. BUG-9 e NET-13 toccano anche l'avvio del servizio e lo stop della rete, ma solo quando esiste un profilo QoS personalizzato o attivo.

La voce **RELEASE-API** resta l'ultima attività della release: si esegue dopo tutte le altre, sullo stato finale del codice.

## Test

Il tester lavora da una macchina esterna e usa solo le API. Per questo il capitolo è diviso in due:

- **Test per il tester:** solo chiamate API, eseguibili da remoto.
- **Test con root o intervento fisico:** staccare la USB, `kill`, `systemctl`, file di root.
  Non li può fare il tester. Li eseguo io se mi viene dato `sudo`, altrimenti chi è vicino alla macchina.

I test automatici li eseguo io a ogni fix e non sono elencati qui; gli esiti sono nel messaggio di commit.

- `tests/unit-tests/`: hardware simulato, girano a ogni modifica e in CI.
- `tests/e2e-tests/`: girano sulla macchina contro il servizio attivo e uniscono chiamate API e azioni
  sul server (journal, `iw`, `kill`, distacco USB simulato). Li lancio solo su un sistema libero e dopo
  conferma. Vedi [docs/e2e-testing.md](docs/e2e-testing.md).

La colonna **E2E** delle tabelle indica i test già automatizzati in `tests/e2e-tests/`:

- ✅ coperto da un test e2e e fix fatto: il tester può saltarlo (resta utile nella run lunga);
- 🧪 test e2e già scritto ma ID non ancora fixato: il test è `xfail` e diventa verde con il fix.

Coperti fuori dalle tabelle: BUG-1 e HAP-1 in [test_e2e_create_validation.py](tests/e2e-tests/test_e2e_create_validation.py) e
[test_e2e_stability.py](tests/e2e-tests/test_e2e_stability.py); WD-4 e WD-5 in [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py).

Per ogni test live raccogliere: ora UTC, `display_name` e `interface` presi da `/status`
(non dedotti dall'ordine), banda e canale, status HTTP con `detail.code` e header `Retry-After`.

### Test per il tester (solo API)

Prerequisito: il servizio deve girare con l'ultimo commit (`/status` → `version`, e il journal
all'avvio). Ogni fix è attivo solo dopo un riavvio del servizio successivo al suo commit
(WD-1, WD-2, NET-1, NET-2 e NET-4: dal commit `2da9e77`).

#### Monitoraggio continuo, da tenere attivo in ogni run

| # | Passi | Esito atteso | E2E |
|---|---|---|---|
| M1 | Interrogare `GET /api/v1/status` ogni 10–30 s per tutta la run e registrare ogni voce di `networks` con `recovery_state` o `runtime_state`, più il campo `status`. | Con un'antenna in quarantena: `status: degraded` anche con `active_networks: 0`. | ✅ [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py) |
| M2 | Per ogni `500/1003` ricevuto, annotare l'antenna e seguirla in `/status`. | Dopo il fix WD-4/WD-5 l'antenna torna senza `recovery_state` da sola: entro circa 11 minuti se `recovering`, entro il backoff (al massimo 15 minuti) se `unavailable`. Un'antenna `unavailable` per più di 30 minuti va segnalata. | ✅ [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py) |
| M3 | Per ogni `409/1001`, ripetere la stessa POST dopo `Retry-After`. | `Retry-After` vale 5 e poi 10; al terzo fallimento `500/1003`. Non devono comparire `500` senza `detail.code`. | ✅ [test_e2e_device_loss.py](tests/e2e-tests/test_e2e_device_loss.py) |

#### Regressione dopo BUG-1, HAP-1, WD-4 e WD-5 (SOAK)

Rieseguire la run completa (sameres, parallel, herd, chaos, mix) con entrambe le antenne per
almeno 90 minuti, con M1–M3 attivi.

Atteso:
- nessuna antenna `unavailable` alla fine;
- nessun `500` generico;
- create con SSID non validi → `422`, mai `500`.

Se durante la run un'antenna si stacca da sola (come alle 12:23 e alle 12:42 del 23/11), la create
in corso deve dare `409/1001`, non `500/1003`, e l'antenna deve tornare da sola (M2).

#### Test previsti per gli altri ID

| ID | Test via API | Esito atteso dopo il fix | E2E |
|---|---|---|---|
| WD-1 | Run lunga con M1: contare i `restoring_ap` per rete. | Una rete può avere più `restoring_ap` nella sua vita; ogni volta torna attiva. Nessuna invalidazione al secondo guasto. | ✅ [test_e2e_watchdog.py](tests/e2e-tests/test_e2e_watchdog.py) |
| WD-2 | Come WD-1. | Nessuna rete che risulta attiva in `GET .../network` ma è ferma, senza `runtime_state` di errore. | ✅ [test_e2e_watchdog.py](tests/e2e-tests/test_e2e_watchdog.py) |
| NET-1 | Molte create/delete concorrenti sulle due antenne (parallel, herd). | Nessun `500` e nessuna quarantena dopo un delete. | ✅ [test_e2e_firewall.py](tests/e2e-tests/test_e2e_firewall.py) |
| HAP-3, HAP-2 | Run lunga di create con statistiche per `status` e `detail.code`. | Solo `200`, `409/1001` o `500/1003`; mai `500` generico. |  |
| HAP-4, WD-10 | Run lunga con M1. | Nessuna quarantena dopo una create con `409/1001` isolato; nessun `restoring_ap` su reti senza guasti. |  |
| RACE-1 | Create su canale DFS (es. 100) e, nello stesso momento, 45 `GET .../network` più `/status`. | `/status` risponde subito; le altre richieste ottengono `200` o `503 / 1006` con `Retry-After: 2` entro circa 5 s, non un timeout. | ✅ [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) (senza DFS) |
| RACE-2 | `/status` in ciclo stretto durante create/delete ripetuti. | Nessun `degraded` spurio. | ✅ [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| HAP-9 | Con DFS abilitato, create sul canale 124. | Risposta coerente (attesa gestita o rifiuto esplicito), non un timeout del client a 75 s. |  |
| HAP-10 | Create con `open`, `wpa2`, `wpa3`, `wpa2-wpa3`, `wpa1` e `wpa`; `hostapd_cli get_config`. | `200` per le prime cinque (`wpa1` solo se l'antenna lo supporta, altrimenti `422`) con `key_mgmt` e cifrario coerenti; `422` per `wpa`. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| HAP-11 | Create a 5 GHz canale 36 con 20/40/80 MHz e Wi-Fi 4/5/6; 2,4 GHz canale 1 a 40 MHz; serie di create a 80 MHz. | `iw dev <if> info` riporta la larghezza chiesta e `GET .../network` la stessa in `reported_channel_width`; sui 2,4 GHz 20 o 40 MHz, coerente con `iw`; nessun aumento dei guasti all'avvio. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| NET-11 | QoS con `download_quality: 40`, `upload_quality: 90`. | Rifiuto esplicito, oppure applicazione accettata con valori diversi nelle due direzioni (`GET .../qos`). |  |
| BUG-2 | Una sola rete con `internet_enabled: false`. | `/status` non è `degraded`. | ✅ [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| BUG-7 | `POST .../txpower` con ogni livello, poi `GET .../txpower`. | Il `GET` riporta il valore reale, non quello richiesto. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| PERF-6 | Durata di `POST .../txpower`. | Sotto i 3 s. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| SEC-1 | `curl --path-as-is http://<host>:8080//etc/passwd` e `/../config.yaml`. | `404`. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| SEC-2 | Il client B chiama `/debug` mentre A ha una reservation. | Gli ID di A non sono visibili. Non previsto per ora: `/debug` resta finché non sarà sostituito. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| API-2 | Reservation senza rete: `internet/enable`, `qos/profile`, `txpower`. | Stesso status HTTP per "rete non attiva": `409 / 1007`. | ✅ [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| API-3 | `409` su rete già attiva, durante un ripristino, durante il cooldown; retry di una create dopo un timeout del client. | `detail.code` diverso per ogni caso; il retry con lo stesso body viene riconosciuto. |  |
| API-4 | Terza create fallita per guasto radio. | Status HTTP come definito dal fix (non `500`). |  |
| API-5 | Create riuscita. | La risposta contiene lo stato strutturato della rete. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| API-10 | Create con un campo sconosciuto (`"captive-portal": true`). | `422`. | 🧪 [test_e2e_api.py](tests/e2e-tests/test_e2e_api.py) |
| API-11 | Client che segue solo il contratto documentato in `/docs`. | Nessun retry ridondante; stessi risultati della run normale. |  |
| API-1, API-6, API-7, API-8 | Confronto di risposte e percorsi con `/docs`. | Nomi uniformi; nessun dettaglio interno (`pid_file`); vecchi nomi deprecati ma funzionanti, se previsto. |  |
| HAP-5, HAP-6, HAP-7 | Run SOAK identiche con la configurazione cambiata sulla macchina tra una run e l'altra. | Confronto del tasso di `409/1001` e `500/1003` tra le run. |  |
| ARCH-1 … ARCH-12 | Run SOAK di regressione. | Nessuna differenza rispetto alla run precedente. |  |

### Test con root o intervento fisico

Non eseguibili dal tester. Li eseguo io con `sudo` (distacco USB simulato via sysfs,
`kill`, `systemctl`); le prove con un telefono e il ricollegamento fisico di un'antenna che la VM
ha perso richiedono una persona vicino alla macchina.

Attenzione: il distacco simulato con un AP attivo può bloccare la VM per circa 60 s e far staccare
la USB dalla VM (visto il 23/11 alle 17:50, come alle 13:37). Serve poi un ricollegamento fisico.

| ID | Intervento | Esito atteso | E2E |
|---|---|---|---|
| WD-5 (p. 3) | Antenna che ricompare con un nome diverso. | La voce vecchia viene ritirata; `/status` non resta `degraded`. |  |
| WD-1, WD-8 | Rete attiva (con profilo QoS per WD-8): `kill -9` di hostapd 3 volte a distanza di minuti. | Ogni volta `restoring_ap` e poi rete attiva; profilo QoS di nuovo attivo. | ✅ WD-1: [test_e2e_watchdog.py](tests/e2e-tests/test_e2e_watchdog.py) |
| WD-2 | `kill -9` di hostapd con il riavvio che fallisce per una causa non radio. | `runtime_state` di errore in `/status`; il watchdog riprova. | ✅ [test_e2e_watchdog.py](tests/e2e-tests/test_e2e_watchdog.py) |
| WD-3 | `kill -9` di dnsmasq due volte. | Ogni volta `restoring_dhcp` e poi DHCP attivo. | ✅ [test_e2e_watchdog.py](tests/e2e-tests/test_e2e_watchdog.py) |
| WD-7 | Togliere a mano l'indirizzo del gateway o una regola NAT. | Il watchdog ripara entro pochi cicli. | ✅ [test_e2e_network_check.py](tests/e2e-tests/test_e2e_network_check.py) |
| STAB-4, NET-9 | `kill -9` del servizio con una rete attiva (QoS per STAB-4), poi riavvio. | Nessun `netem`/`ifb` o indirizzo residuo; nuova rete sulla stessa antenna `200`. | ✅ STAB-4: [test_e2e_unclean_restart.py](tests/e2e-tests/test_e2e_unclean_restart.py) |
| STAB-8 | Due reti attive; `time systemctl stop wi-lab`. | Arresto in meno di 30 s. |  |
| STAB-9 | Rete attiva; `systemctl restart NetworkManager`. | La radio resta unmanaged e l'AP resta attivo. |  |
| STAB-5 | Spostare l'orologio della VM di +2 h con una reservation attiva. | La reservation non scade in anticipo. |  |
| STAB-6 | Cambiare la route di default verso un'altra interfaccia, poi creare una rete. | La nuova regola NAT usa la nuova interfaccia. |  |
| BUG-5 | Collegare un'antenna nuova a servizio avviato. | Compare in `/status` entro 30 s, oppure il motivo dello scarto è nel journal. |  |
| WD-9 | `config.yaml` malformato per 1 minuto, poi ripristinato. | La discovery continua dopo il ripristino. |  |
| NET-2, WD-6, NET-10 | Far fallire l'inserimento NAT o il cleanup; occupare la porta 80. | NET-2: mai `200` con NAT assente. WD-6: tentativi di cleanup in backoff. NET-10: errore chiaro alla create. | ✅ NET-2 (percorso positivo): [test_e2e_firewall.py](tests/e2e-tests/test_e2e_firewall.py) |
| NET-1, PERF-1…5, BUG-1 | Ispezioni di root: `iptables -V`, `strace`/`perf` sui processi del servizio, `hostapd.conf` nella directory privata. | Come descritto in Fable-Notes. | ✅ NET-1: [test_e2e_firewall.py](tests/e2e-tests/test_e2e_firewall.py) |
| Telefono | Connessione reale: SSID `Caffè ☕` e `my"net\` visibili; rete nascosta non ASCII; password di 8 e 63 caratteri; `wpa2-wpa3` con client WPA3 e WPA2 e `wpa1` annotando avvisi o rifiuti dei client recenti (HAP-10); velocità a 20, 40 e 80 MHz sui 5 GHz con un client Wi-Fi 5 e uno Wi-Fi 6 (HAP-11); `nslookup` (NET-8); `/docs` dal gateway rifiutato (SEC-3), anche `ssh` al gateway; isolamento tra reti (NET-3). | Connessione e DHCP funzionanti; per SEC-3 connessione rifiutata. | ✅ SEC-3 (solo regole): [test_e2e_firewall.py](tests/e2e-tests/test_e2e_firewall.py) |

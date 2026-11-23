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

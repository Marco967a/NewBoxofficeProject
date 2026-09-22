# Report audit DB e architettura

Data: 2026-09-21 · DB: PostgreSQL 18.4 locale `boxoffice` · Audit in sola lettura, poi Fase 0 e Fase 1 applicate (vedi "Stato").

## Sintesi

La pipeline scrive senza errori ma i dati non erano affidabili: l'80% della tabella `weekly_box_office`
era generato dal backfill (una sola classifica ricopiata con 20 date diverse) e `movie_id` non funzionava.

## `movie_id`

- Popolata in 2 righe su 500 (Toy Story 5, Michael, run 3 del 14/07).
- `_normalize_record` la forzava a `None` (weekly_box_office_service.py) e l'upsert la riscriveva a NULL.
- Il matching `find_movie_id_by_title` è stato rimosso nel commit `f378065` (31/07).
- Anche ripristinato, solo 2 titoli su 62 avrebbero un match: `movies` contiene i top-revenue mondiali in
  inglese, mentre ComingSoon usa titoli italiani. Il flusso è al contrario (i film dovrebbero essere scaricati
  a partire dai titoli dei box office).
- Nessuna FK verso `movies(id)`. Il parser scarta l'ID film ComingSoon (69 ID distinti sulla pagina).

## Falle

**Critiche**
1. Il backfill inventa dati: ComingSoon ignora i parametri data e serve sempre la classifica corrente; il parser
   rietichettava `week_start/end` con la data richiesta. Run 14: 400 righe, un solo hash di classifica.
2. I run falliti non venivano registrati (il rollback annullava anche la riga `failed`; id 8 mancante) e
   `finished_at = started_at` (`NOW()` = inizio transazione).
3. Dati di test in produzione: run `comingsoon_test`, 3 righe datate 2024-02-15 etichettate `comingsoon`.

**Alte**
4. Chiave di upsert per `rank`: fragile, lascia righe vecchie, 3 formati di finestra settimanale.
5. Nessuna validazione: anomalie di sorgente passano in silenzio (Coyote vs. Acme "504.61", Oceania 1.478.383 al rank 7).
6. `ingestion_run_id` sovrascritto: 7 run su 14 senza righe; nessun dato grezzo per il replay.
7. Nessuna migrazione; DDL (con `DROP COLUMN`) eseguito a ogni caricamento; schema reale di `movies` diverso dal codice.

**Medie**
8. App connessa come superuser `postgres`; mancano indici; timestamp senza fuso.
9. `main_v3.py` riscarica 100 film a ogni esecuzione; `movies` ferma al 31/07, senza `language=it-IT`.
10. Test senza DB reale; CI senza Postgres.
11. Chiavi in history git: vedi SECURITY_REPORT.md.

## Piano

- **Fase 0 – messa in sicurezza**: backup, quarantena righe false/di test, DB di sviluppo.
- **Fase 1 – correttezza**: parser senza rietichettatura, run `failed` persistiti, `source_name` dal chiamante, validazioni.
- **Fase 2 – schema con migrazioni**: `source_movies` (ID ComingSoon → `movie_id`), unicità su
  `(source, territory, week_start, source_movie_id)`, FK, `CHECK (week_end >= week_start)`, indici, `TIMESTAMPTZ`,
  `raw_snapshots`, ruolo applicativo a privilegi minimi, DDL fuori dal percorso di esecuzione.
- **Fase 3 – risoluzione `movie_id`**: cache per ID ComingSoon; ricerca TMDB `language=it-IT&region=IT&year`;
  scoring su titolo/originale/alternativi + anno; soglia di auto-accettazione e coda `needs_review`; override manuali;
  scaricare in `movies` solo i film senza match; rieseguire sui 62 titoli esistenti.
- **Fase 4 – operatività**: scheduler settimanale (giovedì–lunedì), Postgres in CI, vista `v_weekly_enriched`, query di controllo qualità.

## Stato (2026-09-21)

Fasi 0, 1, 2, 3 e 4 completate. Restano le decisioni in sospeso (vedi in fondo).

- Backup: `backups/boxoffice_pre_cleanup_20260921.dump` (ignorato da git).
- `weekly_box_office`: da 500 a 97 righe (5 settimane reali). Le 403 righe rimosse sono in `weekly_box_office_quarantine`
  con il motivo, ripristinabili con un INSERT…SELECT.
- Creato `boxoffice_dev` con lo stesso schema.
- Settimane reali mancanti (16/07, 13/08–10/09): recuperabili solo da un'altra fonte.

### Fase 2 (2026-09-21): schema con migrazioni

- `migrations/001–003` + runner `app/migrations.py` / `scripts/migrate.py` (checksum, lock, una transazione per migrazione).
  Provate su una copia di produzione e su un DB vuoto (schemi identici), poi applicate a `boxoffice` e `boxoffice_dev`.
- Il codice non esegue più DDL: `create_table` rimosso; `ensure_schema_current` fallisce con un messaggio chiaro se mancano migrazioni.
- Nuova chiave `(source, territory, week_start, external_movie_title)`; `rank` è un attributo; FK reale su `movie_id`;
  `movie_id` non viene più azzerato dagli upsert.
- `source_movies` (ID ComingSoon → `movie_id`, stato del match) e `raw_snapshots`; il parser ora cattura ID e URL del film.
- `TIMESTAMPTZ`, CHECK (`week_end >= week_start`, `rank > 0`, stato dei run), indici su `week_start`, `movie_id`, `ingestion_run_id`.
- Drift di `movies` corretto (`title NOT NULL`, `created_at`, DEFAULT).
- Test: 10 di integrazione su Postgres reale (`RUN_DB_TESTS=1`), 27 unitari.
- **Non fatto**: ruolo applicativo a privilegi minimi (richiede scegliere come gestire le credenziali in `.env`).
  Le righe legacy (4 settimane su 5) non hanno ID ComingSoon: l'ID arriva solo dai nuovi run.

### Fase 3 (2026-09-21): risoluzione di `movie_id`

- `app/matching.py` (logica pura) + `MovieMatchingService` + `scripts/resolve_matches.py`; migrazione `004` (`match_candidates`, `movies.original_title`).
- Ricerca TMDB in italiano; i 3 migliori candidati sono verificati con titoli alternativi IT e data di uscita in Italia
  (segnale forte: conferma le riedizioni e smentisce gli omonimi). Auto-accetta solo con score ≥ 0.85 e margine ≥ 0.10.
- `movies` ora contiene solo film davvero in classifica; `main_v3.py` esegue weekly → match (il bootstrap top-revenue resta opzionale).
- Righe storiche collegate per titolo; i `movie_id` già presenti (Toy Story 5, Michael) sono adottati e propagati a tutte le settimane.
- Risultato in produzione: 53 film → 49 automatici + 2 adottati, 4 da rivedere, 0 errori; `movie_id` su 92/97 righe; 0 incoerenze; seconda esecuzione idempotente.
- Bug trovato in prova generale e corretto: l'adozione dei match storici non veniva propagata alle altre settimane.
- Test: 22 di integrazione su Postgres reale (TMDB finto), unitari per punteggi/decisione e client TMDB.

### Fase 4 (2026-09-21): operatività

- **Scheduler**: attività `NewBoxOffice-WeeklyRun` (Utilità di pianificazione) ogni lunedì e venerdì alle 12:00, come l'utente
  corrente, solo con sessione aperta; `StartWhenAvailable`; una sola istanza; limite 1 h. Esegue `scripts/run_weekly.ps1`
  (pipeline + health check, log in `logs/`). Provata dal vivo: risultato 0. Rimozione: `register_weekly_task.ps1 -Remove`.
- **Health check** (`app/health.py`, `scripts/health_check.py`): ultimo run, ultima settimana, buchi, coerenza `movie_id`,
  righe non collegate, coda match, copertura, anomalie di sorgente. Solo i FAIL danno exit 1 (`--strict` include i WARN).
- **Vista** `v_weekly_enriched` (migrazione 005).
- **CI**: servizio Postgres 18 + `RUN_DB_TESTS=1`, verifica delle migrazioni da zero e idempotenza. Simulata in locale (90 test
  ok); il workflow non è stato eseguito su GitHub.
- Trovato in verifica e corretto: una query con f-string in `SourceMovieRepository.get` avrebbe fatto fallire `bandit` in CI.
- Stato dell'health check in produzione: 0 FAIL, 3 WARN (6 settimane storiche mancanti, 4 match da rivedere, 2 anomalie di sorgente).

### Decisioni / attività in sospeso

- 4 film in `needs_review`: Cars: Motori Ruggenti, Calle Malaga, Blue, Borgo (decisione rimandata dall'utente).
- Ruolo applicativo a privilegi minimi (richiede scegliere come gestire le credenziali in `.env`).
- Settimane storiche mancanti (16/07, 13/08–10/09): solo da un'altra fonte.
- Nessuna notifica automatica in caso di guasto (solo «Ultimo risultato», log e health check).

### Recupero settimane mancanti (2026-09-21)

- Strumento riutilizzabile: `app/wayback.py` + `scripts/recover_from_wayback.py` (retry con attese crescenti, verifica della
  settimana scritta nella pagina, run con `pipeline_name = 'weekly_box_office_recovery'`, pagina archiviata in `raw_snapshots`).
- Recuperate 2 settimane su 6 da snapshot Wayback (16/07: 19 righe; 10/09: 20 righe). La settimana del 10/09 coincide riga per riga
  con la cattura live del 14/09 messa in quarantena (0 differenze); `weeks_in_release` e totali cumulati sono coerenti tra settimane.
- Restano 4 buchi (13/08, 20/08, 27/08, 03/09): nel periodo Wayback ha solo 3 snapshot (20/07, 21/07, 15/09).
- Box Office Mojo escluso: `robots.txt` con `Disallow: /` per i bot e importi in dollari (non comparabili).
- `link_legacy_rows` ora unifica i film 'legacy' con l'omonimo reale comparso dopo (42 righe riunite, 16 voci legacy eliminate) e
  l'health check segnala i titoli abbinati a più film TMDB.
- Conferma indiretta delle anomalie di sorgente: il totale cumulato di Oceania sale di 311.177 € tra 10/09 e 17/09, non di 1.478.383 €.

### Proposte in sospeso (decisione dell'utente)

**4 film in `needs_review`**, con le prove raccolte (nessun match applicato):

| Film (id source_movies) | Proposta | Prove |
|---|---|---|
| Cars: Motori Ruggenti (#2) | `--set 2 --tmdb-id 920` | scheda ComingSoon: titolo originale *Cars*, anno 2006, uscita 17/09/2026 (riedizione); TMDB 920 = *Cars - Motori ruggenti* (2006) |
| Calle Malaga (#18) | `--set 18 --tmdb-id 1399462` | scheda ComingSoon: *Calle Málaga*, 2025, Movies Inspired; TMDB: stesso titolo originale, 116 min, MA/FR/ES/DE/BE |
| Blue (#27) | `--set 27 --tmdb-id 1432207` | film italo-polacco 2026 di Eleonora Puglia (PiperFilm, 23/07/2026); TMDB 1432207 compare nei crediti di regista e cast (Alexia Cozzi, Shaen Barletta) ma la ricerca per titolo non lo mostra |
| Borgo (#28) | `--set 28 --tmdb-id 989474` | film di Stéphane Demoustier (Corsica, Hafsia Herzi), Movies Inspired, 06/08/2026; la trama TMDB coincide |

Miglioramenti dell'algoritmo emersi: usare titolo originale e anno di produzione dalla scheda ComingSoon (risolve le riedizioni),
cercare per regista/cast su TMDB (risolve i titoli generici come *Blue*), esaminare più pagine di risultati.

**Credenziali** (stato verificato): le credenziali storiche della history git sono revocate (password DB rifiutata, chiave TMDB 401).
Ma l'app usa l'unico ruolo esistente, `postgres` (superutente: può eseguire comandi sul sistema con `COPY ... PROGRAM`), la password è
in chiaro in `.env`, `listen_addresses = *` (con la protezione affidata al solo firewall)
e la cartella del progetto, `.env` incluso, è leggibile per ereditarietà da altri gruppi locali. Piano in ordine di
efficacia: ruoli a privilegi minimi (`boxoffice_owner` solo per le migrazioni, `boxoffice_app` senza DDL, `boxoffice_ro` in sola lettura),
`listen_addresses = 'localhost'`, segreti fuori dal progetto (Gestione credenziali di Windows via `keyring`, oppure `pgpass.conf`, oppure
SSPI senza password), ACL ristretta su `.env`/`backups`/`logs`, chiave TMDB in header `Authorization: Bearer` invece che nell'URL,
secret scanning con push protection su GitHub.

### Match manuali e hardening (2026-09-21)

- Applicati i 4 match proposti (Cars→920, Calle Malaga→1399462, Blue→1432207, Borgo→989474; Blue verificato anche sui crediti TMDB: stessa regista e 4 attori in comune).
  Copertura `movie_id`: 20/20 righe nell'ultima settimana, 135/136 in totale (resta solo *Discover Rome*, `no_match` automatico senza candidati).
- **Ruoli a privilegi minimi** (`app/roles.py`, `scripts/setup_db_roles.py`): `boxoffice_owner` (DDL, migrazioni, backup), `boxoffice_app`, `boxoffice_ro`, `boxoffice_test`;
  nessuno superutente; privilegi dichiarati tabella per tabella e riapplicati da `migrate.py`; proprietà di database e oggetti trasferita all'owner (produzione e sviluppo).
- **Segreti nella Gestione credenziali di Windows** (`app/credentials.py`, `scripts/manage_secrets.py`): `.env` contiene solo valori non segreti; variabili d'ambiente con precedenza (CI).
- Migrazione 006 (tabella di quarantena sotto controllo delle migrazioni), `scripts/backup_db.py`, `scripts/harden_permissions.ps1`, supporto al token TMDB in header.
- L'attività pianificata funziona con i nuovi ruoli (letta dal deposito, risultato 0). Test: 143 (unitari + integrazione), CI simulata senza deposito.
- **Da fare a mano**: riavvio del servizio PostgreSQL come amministratore (`Restart-Service postgresql-x64-18`) per attivare `listen_addresses = 'localhost'`;
  attivare secret scanning e push protection su GitHub; opzionale: salvare `tmdb_read_token` (`manage_secrets.py set tmdb_read_token`).

### Analisi generale e correzioni mirate (2026-09-22)

Riletto tutto il codice da zero (non solo quanto toccato nelle sessioni precedenti). Trovati e corretti, nei limiti del
possibile, i tre problemi a rilevanza media:

- **Python 3.14 in locale (venv, attività pianificata) vs 3.12 in CI**: disallineamento che rendeva "i test passano"
  non equivalente nei due posti. CI allineata a 3.14 (`.github/workflows/ci.yml`), stessa versione del runtime reale.
- **Chiave naturale di `weekly_box_office` senza normalizzazione**: `(source_name, territory, week_start,
  external_movie_title)` confrontava lettera per lettera. Migrazione 007: colonna generata `title_key =
  lower(btrim(external_movie_title))`, nuovo vincolo su quella, dedup difensivo delle righe già esistenti (0 gruppi
  trovati in produzione). Il repository ora normalizza allo stesso modo prima dell'INSERT (necessario: Postgres
  rifiuta un batch con due righe che risolvono allo stesso target di conflitto) e aggiorna `external_movie_title`
  sull'upsert, cosi' l'ultima grafia vista resta quella salvata.
- **Nessun retry su TMDB**: `app/http_retry.py` (nuovo, condiviso con `app/wayback.py` che usava già lo stesso
  schema) riprova su 429/5xx/timeout con attese crescenti (5s, 15s, 45s) invece di segnare subito il film come errore.

Verificato tutto su una copia/i database reali prima e dopo: backup (`boxoffice_pre_007_*.dump`), migrazione applicata
a `boxoffice` e `boxoffice_dev` (136 righe invariate, nessun duplicato), un `weekly_run.py` reale post-migrazione per
confermare il nuovo `ON CONFLICT` in produzione. Test: 154 (unitari + integrazione su Postgres reale), `bandit` 0 issue.

**Notifica sui guasti** (`app/notifications.py`, `scripts/notify.py`, integrata in `run_weekly.ps1`): niente per i
soli WARN (stessa soglia di `health_check.py`); su un guasto vero, notifica desktop (Centro notifiche di Windows,
via WinRT, AppID di PowerShell già registrato — nessun modulo/dipendenza aggiuntivi) sempre tentata, più un webhook
opzionale (`notify_webhook_url` nel deposito credenziali, formato compatibile Slack/Discord). Il messaggio estrae le
righe più rilevanti del log (errori/traceback). Provato end-to-end: un guasto simulato (DB inesistente, senza
toccare `boxoffice`) ha prodotto pipeline=1, notifica scritta e letta correttamente, nessun errore nel ramo toast; un
run pulito su `boxoffice_dev` non ha creato nessun file di notifica. Toast confermato visivamente dall'utente (22/09).

**`listen_addresses`**: già `localhost` e attivo (nessun riavvio in sospeso), con `pg_hba.conf` che comunque limitava
le connessioni a `127.0.0.1`/`::1` anche quando era `*`. Confermato che la porta 5432 ascolta solo su loopback.

### I quattro punti a bassa rilevanza (2026-09-22)

Nella risposta precedente ne avevo ricontati solo tre (dimenticando il terzo qui sotto); corretti tutti e quattro:

- **`get_db_config` ripiegava in silenzio sul ruolo `app`.** Per `ro` resta così (innecuo: `app` ha comunque i
  permessi di lettura, e un test lo impone esplicitamente). Per `owner` il primo tentativo (controllare in anticipo
  se `db:<owner>` esiste nel deposito, e fallire subito se manca) **ha rotto la CI**: lì non esiste un ruolo owner
  separato, si usa `postgres` per tutto, e il ripiego silenzioso su `app` funzionava benissimo (un solo superutente
  ha già tutti i permessi). Il controllo anticipato presumeva "nessun segreto owner = DDL impossibile", il che è
  falso quando il ruolo di ripiego ha comunque i privilegi. Corretto spostando il controllo dove serve davvero:
  `app/migrations.py::apply_pending` ora intercetta `psycopg2.errors.InsufficientPrivilege` sul DDL e lo traduce in
  un `RuntimeError` leggibile (ruolo coinvolto + `setup_db_roles.py`), senza toccare i casi in cui il ripiego basta.
  Verificato dal vivo in entrambi i sensi: un database nuovo con solo il ruolo `boxoffice_app` (senza DDL) e nessun
  owner configurato dà ora il messaggio chiaro; lo stesso scenario con `postgres` (un solo ruolo per tutto, come in
  CI) applica le 7 migrazioni senza problemi.
- **`set_secret`/`delete_secret` senza try/except.** Ora traducono un guasto del deposito in `RuntimeError`
  leggibile (con `from exc`, senza perdere la traccia originale); `manage_secrets.py` lo intercetta e lo trasforma
  in un `SystemExit` pulito invece di un traceback grezzo di `keyring`.
- **Gestione errori troppo permissiva nel resolver.** `resolve_pending` ora distingue una connessione al database
  persa (`psycopg2.OperationalError`/`InterfaceError`) — si ferma subito, marca `summary.stopped_early` — da un
  errore per singolo film (TMDB, dati) — continua con gli altri, come prima. Gestito anche il caso in cui la
  connessione muoia solo alla chiusura finale (dopo che tutti gli item sono già stati elaborati): il riepilogo
  parziale viene comunque restituito, non perso in un'eccezione. `resolve_matches.py` stampa un avviso ed esce con
  1 se si è fermato in anticipo.
- **`requirements.txt` senza limite superiore.** Aggiunto `<major successiva` a tutte le dipendenze; verificato che
  l'installazione nel venv reale non cambia nulla (tutte le versioni attuali erano già compatibili). Niente lockfile
  con hash: aggiungerebbe uno strumento (pip-tools/uv) senza un beneficio proporzionato per queste dimensioni.

Test aggiunti: 14 (unitari, nessuno richiede Postgres). Suite completa: 186 (51 saltati senza `RUN_DB_TESTS=1`, tutti
verdi con Postgres reale). `bandit` 0 issue, `pip-audit` nessuna vulnerabilità. Verificato anche dal vivo su
`boxoffice_dev`: `resolve_matches.py` e `manage_secrets.py list` invariati nel funzionamento normale.

### Regressione in CI e correzione (stesso giorno, 22/09)

Il commit con i quattro fix sopra, una volta pubblicato, ha fatto fallire la CI su GitHub (job `test`, passo
migrazioni): il controllo anticipato sul ruolo owner presumeva un segreto nel deposito che in CI non esiste, perché
lì `DB_USER=postgres` è già un superutente usato per tutto, senza ruoli separati. La stessa cosa vale per chi non ha
ancora eseguito `setup_db_roles.py` in locale. Corretto spostando il controllo dal momento della connessione (prima
di sapere se serviva davvero) al momento del DDL vero e proprio (`app/migrations.py`, cattura
`psycopg2.errors.InsufficientPrivilege`): non cambia nulla quando il ripiego basta, dà un messaggio chiaro quando non
basta. 5 nuovi test (2 in `tests/test_db.py`, riscritto perché testava il comportamento rimosso; 3 nuovi in
`tests/test_migrations_permissions.py`), più le due verifiche dal vivo del punto precedente. Suite: 191 test, tutti
verdi. Pubblicato in un commit correttivo separato subito dopo, con la CI ripassata.

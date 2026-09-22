# Security report – NewBoxofficeProject

Data: 2026-09-20 · Branch analizzato: `main` (commit `6740cac`) · Ambito: tutto il codice tracciato (`app/`, `scripts/`, `tests/`, `init_db.py`, `main_v3.py`, `test_project.py`), configurazione, dipendenze, history git, CI.

Strumenti: lettura manuale completa del codice, `bandit` 1.9.4, `pip-audit` (su `requirements.txt`), ispezione della history git, esecuzione dei test in ambiente pulito (senza `.env`).

## Sintesi

| # | Severità | Problema | Stato |
|---|----------|----------|-------|
| 1 | **Critica** | `.env` con credenziali reali committato e pubblicato su GitHub (repo pubblico) | **Azione manuale richiesta** (rotazione) |
| 2 | Media | La chiave TMDB può finire nei log (URL con `api_key` dentro le eccezioni di `requests`) | Corretto |
| 3 | Media | `test_project.py` stampa i primi 10 caratteri della chiave TMDB | Corretto |
| 4 | Media | `import app` richiede tutti i segreti (`setup_logging()` → `get_settings()`); senza `.env` test e CI falliscono | Corretto |
| 5 | Bassa | Dipendenze senza vincoli di versione | Corretto (lower bound) |
| 6 | Bassa | `.env.example` citato in `.gitignore` ma inesistente | Corretto |
| 7 | Info | CI presente solo sul branch `preview`, assente su `main`; nessun controllo di sicurezza | Corretto (workflow aggiunto su `main`) |
| 8 | Info | Connessione PostgreSQL senza `sslmode` esplicito | Raccomandazione |
| 9 | Info | Nessun limite alla dimensione della risposta di ComingSoon, regex su HTML esterno | Raccomandazione (rischio basso) |

Risultati scanner: **bandit: 0 issue** (781 righe) · **pip-audit: nessuna vulnerabilità nota**.

## Dettaglio

### 1. [CRITICA] Segreti nella history git, pubblicati su GitHub
- `.env` è stato committato in `9e8e5e8` ("Debug code 1") e `28b0450`; rimosso dall'indice in `48d96c7`. Ora è correttamente in `.gitignore`, ma **la history conserva i valori**.
- `9e8e5e8` è raggiungibile da `origin/main`, `origin/development` e `origin/preview`. Il repo `Marco967a/NewBoxofficeProject` risulta **pubblico** (API GitHub non autenticata: HTTP 200).
- Confronto per hash: **`TMDB_API_KEY`, `DB_PASSWORD`, `DB_HOST`, `DB_USER` attuali sono identici a quelli leakati**. Vanno considerati compromessi.
- Impatto: chiave TMDB utilizzabile da terzi (quota/abuso, ban dell'account); password DB nota (il rischio reale dipende da quanto il DB è raggiungibile e se la password è riusata altrove).

**Cosa fare (nell'ordine):**
1. Rigenerare la chiave API su TMDB e aggiornare `.env`.
2. Cambiare la password dell'utente PostgreSQL (e ovunque sia riusata) e aggiornare `.env`.
3. Solo dopo, se si vuole ripulire la history: `git filter-repo --path .env --invalidate-blobs` + force-push di tutti i branch. Non è stato eseguito perché è distruttivo e riscrive la history condivisa; ed è secondario rispetto alla rotazione (i valori vecchi restano comunque in eventuali fork/cache).

### 2. [MEDIA] Chiave TMDB nei log – `app/tmdb_client.py`
La chiave viene passata come query string (`api_key=`, unico metodo per le chiavi v3). Se la richiesta fallisce, `requests` include l'URL completo nel messaggio dell'eccezione, e `MovieIngestionService` la logga con `logger.exception(...)` (messaggio + traceback concatenato). Risultato: chiave in chiaro nei log.
**Fix:** `_get` cattura `requests.RequestException` e rilancia un errore senza URL (`from None`, così anche il traceback originale non viene stampato). Aggiunto test di regressione.

### 3. [MEDIA] Stampa parziale della chiave – `test_project.py`
`print(f"TMDB API Key: {settings.tmdb_api_key[:10]}...")` scrive parte del segreto su console/log CI.
**Fix:** ora stampa solo "configurata".

### 4. [MEDIA] Import di `app` dipendente dai segreti
`app/__init__.py` chiama `setup_logging()`, che chiama `get_settings()`, che solleva `RuntimeError` se manca una qualsiasi variabile. Effetti: 4 test su 6 falliscono senza `.env` (verificato su un checkout pulito), quindi la CI non può passare; inoltre incoraggia a tenere un `.env` reale ovunque, anche dove non serve.
**Fix:** il logging legge solo `LOG_LEVEL` (nuova `get_log_level()` in `settings.py`); la validazione dei segreti resta in `get_settings()` e scatta dove servono davvero.

### 5. [BASSA] Dipendenze non vincolate
`requirements.txt` non ha versioni: build non riproducibili e rischio supply-chain/regressioni. Con `pip-audit` oggi non emergono CVE.
**Fix:** aggiunti lower bound sicuri (es. `requests>=2.32.4`, che chiude CVE-2024-35195 e CVE-2024-47081). Raccomandato in futuro un lockfile (`pip-tools`/`uv`) con hash.

### 6. [BASSA] `.env.example` mancante
`.gitignore` lo esclude dall'ignore (`!.env.example`) ma il file non esiste.
**Fix:** creato con soli placeholder.

### 7. CI – vedi sezione dedicata sotto.

### 8. [INFO] `sslmode` PostgreSQL
`app/settings.py` non consente di impostare `sslmode`. Con `DB_HOST=localhost` va bene; se il DB diventa remoto, credenziali e dati viaggerebbero in chiaro. Raccomandato: variabile opzionale `DB_SSLMODE` (`require`/`verify-full`).

### 9. [INFO] Parser ComingSoon
URL costruiti solo da host fisso + date tipizzate (nessun SSRF), timeout presente, nessun `verify=False`. Non c'è un tetto alla dimensione della risposta e `FIELDS_PATTERN` usa quantificatori pigri su testo esterno: con una fonte fidata il rischio è basso, ma un HTML enorme/ostile potrebbe rallentare il job.

## Aspetti verificati e risultati positivi
- **SQL injection:** tutte le query sono parametrizzate (`%s` / `execute_values`); nessuna interpolazione di input utente nelle query.
- Nessuna `eval`/`exec`/`pickle`/`subprocess`/`shell=True`/`yaml.load`; nessun `verify=False`.
- Nessun segreto hardcoded nel codice attuale (le sole occorrenze sono placeholder nei test).
- `.env`, `.venv`, `__pycache__` sono nel `.gitignore`; `.env` non è più tracciato.
- Timeout su tutte le richieste HTTP; commit/rollback gestiti nel context manager `get_connection`.

## Continuous Integration
- **Esiste** un workflow GitHub Actions (`.github/workflows/ci.yml`, commit `4201fe2`, "docs: organize project documentation and CI") **ma solo sul branch `preview`**. Su `main` (branch predefinito) e `development` **non c'è nulla**: quindi sul ramo principale la CI oggi **non gira**.
- Contenuto su `preview`: trigger `push` + `pull_request`, `permissions: contents: read` (buono), Python 3.12 con cache pip, install da `requirements.txt`, `unittest discover`. Nessun lint, nessuna analisi di sicurezza, nessun controllo dipendenze/segreti.
- Su `main` sarebbe comunque fallita (punto 4).
- **Fix applicato:** aggiunto su `main` un workflow con job `test` e job `security` (bandit + pip-audit). Raccomandati inoltre: Dependabot, secret scanning + push protection dalle impostazioni del repo GitHub, e branch protection su `main` con check richiesti.

## Aggiornamento 2026-09-21: hardening di credenziali e ruoli

**Stato del punto 1 (segreti nella history).** Le credenziali attuali sono diverse da quelle committate e le vecchie sono
**revocate** (verificato: la vecchia password del database viene rifiutata, la vecchia chiave TMDB risponde 401). La history git
contiene ancora i valori vecchi, ora innocui. Resta consigliato attivare *Secret scanning* e *Push protection* su GitHub (`gh` non
era autenticato: passo manuale).

| # | Severità | Problema | Stato |
|---|----------|----------|-------|
| 10 | Alta | L'applicazione usava l'unico ruolo esistente, `postgres`, **superutente** (può eseguire comandi sul sistema con `COPY ... PROGRAM` e leggere file del server) | **Corretto**: ruoli `owner`/`app`/`ro`, nessuno superutente |
| 11 | Alta | Password del database e chiave TMDB in chiaro in `.env`, dentro la cartella del progetto (backup, sincronizzazioni, altri gruppi locali) | **Corretto**: Gestione credenziali di Windows (DPAPI); `.env` senza segreti |
| 12 | Media | `.env`, `backups/` e `logs/` leggibili per ereditarietà da altri gruppi locali | **Corretto**: permessi limitati a utente, SYSTEM, Administrators (`scripts/harden_permissions.ps1`) |
| 13 | Media | PostgreSQL in ascolto su tutte le interfacce (`listen_addresses = *`), con la protezione affidata al solo firewall | **Corretto** (2026-09-22): servizio riavviato, `listen_addresses = 'localhost'` attivo, verificato che la 5432 ascolta solo su 127.0.0.1/::1. `pg_hba.conf` limitava comunque le connessioni al solo loopback già prima del riavvio |
| 14 | Bassa | Chiave TMDB nell'URL (`api_key=`) | **Corretto**: supporto a `Authorization: Bearer` con `tmdb_read_token`; la chiave API resta come ripiego finché non si salva il token |
| 15 | Bassa | Password dei ruoli visibili nei log del server se un `ALTER ROLE` fallisce | **Corretto**: le password arrivano a PostgreSQL già come hash SCRAM |

**Verifiche eseguite** (sul database reale e su una copia): 23 prove dei permessi tramite `scripts/setup_db_roles.py --verify-only` (l'app non può fare
`CREATE/DROP/ALTER/TRUNCATE`, `DELETE` su `weekly_box_office`, `COPY ... PROGRAM`, `pg_read_file`; il ruolo `ro` non può scrivere), pipeline, health check, migrazioni,
backup e attività pianificata funzionanti con i nuovi ruoli, 8 test di integrazione sui ruoli con ruoli temporanei, `bandit` 0 issue, `pip-audit` nessuna vulnerabilità.

**Rischio residuo.** Un programma malevolo che gira con il tuo account può leggere dal deposito le stesse password dell'applicazione: il danno è limitato dai privilegi
minimi, non azzerato. La password del superutente `postgres` è nel deposito (recuperabile con `manage_secrets.py get db:postgres --show`) e non è usata dall'applicazione:
conviene conservarla in un gestore di password ed eliminarla dal deposito. Le password dei ruoli si ruotano con `scripts/setup_db_roles.py --rotate`.

## Aggiornamento 2026-09-22: chiusura punto 13, resilienza e osservabilità

Il punto 13 (`listen_addresses`) è chiuso: verificato che la porta 5432 ascolta solo su `127.0.0.1`/`::1`.

Fuori dall'ambito stretto della sicurezza, ma legati alla disponibilità del servizio:

| # | Severità | Problema | Stato |
|---|----------|----------|-------|
| 16 | Bassa | Nessun retry su TMDB: un 429 (rate limit) o un 5xx transitorio marcava subito un film come "errore" | **Corretto**: `app/http_retry.py` (condiviso con Wayback), attese crescenti 5/15/45s |
| 17 | Bassa | Nessuna notifica sui guasti della pipeline non presidiata: si vedevano solo aprendo log/Utilità di pianificazione | **Corretto**: notifica desktop (WinRT, sempre tentata) + webhook opzionale (`notify_webhook_url`), solo sui guasti veri (non sui WARN) |

Il messaggio di notifica non contiene segreti: estrae solo le righe di log con errori/traceback, mai variabili
d'ambiente o output di `manage_secrets.py`. Il webhook, se configurato, è un URL nel deposito credenziali (stesso
meccanismo delle password); l'invio è *best effort* e non blocca né fa fallire l'esecuzione.

## Aggiornamento 2026-09-22 (2): gli ultimi quattro punti a bassa rilevanza

| # | Severità | Problema | Stato |
|---|----------|----------|-------|
| 18 | Bassa | `get_db_config` ripiegava in silenzio sul ruolo `app` se `owner`/`ro` non erano configurati: per `owner` un fallimento a metà migrazione, poco chiaro | **Corretto**: `get_connection("owner")` fallisce subito con un messaggio leggibile se il ruolo owner non è configurato. Per `ro` il ripiego resta (innocuo, testato) |
| 19 | Bassa | `set_secret`/`delete_secret` senza gestione degli errori: un guasto del deposito credenziali usciva come traceback grezzo di `keyring` | **Corretto**: tradotto in `RuntimeError` leggibile; `manage_secrets.py` lo trasforma in un messaggio pulito |
| 20 | Bassa | Il resolver dei match continuava a provare i film successivi anche con la connessione al database persa, riempiendo l'output dello stesso errore ripetuto | **Corretto**: si ferma alla prima perdita di connessione, distinguendola dagli errori per singolo film (TMDB/dati), che invece non fermano il ciclo |
| 21 | Bassa | `requirements.txt` senza limite superiore di versione: una major nuova poteva installarsi senza preavviso | **Corretto**: limite `<major successiva` su tutte le dipendenze; nessun lockfile con hash (scelta deliberata, sproporzionata per queste dimensioni) |

Nessuno di questi tocca dati segreti o privilegi: sono correzioni di robustezza e diagnosticabilità. Verificati dal
vivo (ruolo owner mancante → errore immediato; funzionamento normale invariato) e con 14 nuovi test unitari.

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

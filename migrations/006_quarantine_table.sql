-- La tabella di quarantena era stata creata a mano durante la pulizia dei dati falsi (Fase 0):
-- la si porta sotto il controllo delle migrazioni, così esiste e ha proprietario/privilegi definiti
-- anche in un database nuovo. Nel database di produzione esiste già: qui è un no-op.
CREATE TABLE IF NOT EXISTS weekly_box_office_quarantine (
    LIKE weekly_box_office INCLUDING DEFAULTS,
    quarantine_reason TEXT NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

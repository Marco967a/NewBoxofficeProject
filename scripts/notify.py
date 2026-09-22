"""Notifica sui guasti dell'esecuzione settimanale.

Chiamato da scripts/run_weekly.ps1 dopo pipeline e health check. Se non c'è nulla da segnalare non
scrive nulla ed esce con 0. Se c'è un guasto: prova un webhook (se configurato nel deposito credenziali
o nell'ambiente, nome 'notify_webhook_url'/NOTIFY_WEBHOOK_URL) e, con --out, scrive il messaggio in un
file UTF-8 che run_weekly.ps1 legge per mostrare una notifica desktop.

Non fallisce mai per colpa propria: un problema qui non deve nascondere il guasto originale della pipeline.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.credentials import get_secret
from app.notifications import describe_failure, send_webhook


def main() -> None:
    parser = argparse.ArgumentParser(description="Notifica sui guasti della pipeline settimanale")
    parser.add_argument("--pipeline-exit", type=int, required=True)
    parser.add_argument("--health-exit", type=int, required=True)
    parser.add_argument("--log", help="Log dell'esecuzione, per estrarne le righe più rilevanti")
    parser.add_argument("--out", help="File (UTF-8) dove scrivere il messaggio, se c'è un guasto")
    args = parser.parse_args()

    log_text = ""
    if args.log:
        log_path = Path(args.log)
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")

    report = describe_failure(args.pipeline_exit, args.health_exit, log_text)
    if report is None:
        return

    webhook_url = get_secret("notify_webhook_url", "NOTIFY_WEBHOOK_URL")
    if webhook_url and not send_webhook(report, webhook_url):
        print("(webhook configurato ma invio fallito: vedi log)", file=sys.stderr)

    print(report.message)
    if args.out:
        Path(args.out).write_text(report.message, encoding="utf-8")


def run() -> None:
    """Involucro di main(): un errore imprevisto qui non deve mascherare l'esito reale della pipeline."""
    try:
        main()
    except Exception as exc:
        print(f"notify.py fallito ({type(exc).__name__}): {exc}", file=sys.stderr)


if __name__ == "__main__":
    run()

# (File solo ASCII: PowerShell 5.1 legge i .ps1 senza BOM come ANSI.)
# Esecuzione settimanale non presidiata: pipeline (weekly + match) e poi health check.
# Scrive un log per esecuzione in logs\ e ritorna un codice di uscita diverso da 0 se qualcosa non va,
# cosi l'esito compare come "Ultimo risultato" nell'Utilita di pianificazione.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Interprete non trovato: $python (crea il venv come da README)"
    exit 2
}

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("weekly_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))
$env:PYTHONIOENCODING = "utf-8"

# cmd.exe scrive l'output di Python cosi com'e (UTF-8): il redirect di PowerShell 5.1 lo convertirebbe in UTF-16.
function Invoke-Logged([string]$title, [string[]]$pythonArgs) {
    Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} {1} ===" -f (Get-Date), $title)
    $argLine = ($pythonArgs | ForEach-Object { '"{0}"' -f $_ }) -join " "
    cmd.exe /c ('"{0}" {1} >> "{2}" 2>&1' -f $python, $argLine, $log)
    return $LASTEXITCODE
}

# Notifica desktop sui guasti (Action Center di Windows). Usa l'AppID gia' registrato di PowerShell,
# cosi' non serve un collegamento nel menu Start per un AppID personalizzato.
function Show-ToastNotification([string]$Title, [string]$Message) {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null

    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($template.CreateTextNode($Title)) | Out-Null
    $textNodes.Item(1).AppendChild($template.CreateTextNode($Message)) | Out-Null

    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}

$pipelineExit = Invoke-Logged "pipeline (weekly + match)" @("main_v3.py")
$healthExit = Invoke-Logged "health check" @("scripts\health_check.py")
Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} fine: pipeline={1} health={2} ===" -f (Get-Date), $pipelineExit, $healthExit)

# Notifica solo sui guasti veri (health_check.py esce 0 sui soli WARN): notify.py decide se c'e'
# qualcosa da segnalare e, in tal caso, prova anche un webhook opzionale (deposito credenziali /
# NOTIFY_WEBHOOK_URL). Il messaggio passa da un file UTF-8 (mai dalla cattura diretta dell'output di
# un processo figlio: PowerShell 5.1 la decodifica con la codepage di sistema, non UTF-8).
$notifyOut = Join-Path $logDir ("notify_{0:yyyyMMdd_HHmmss}.txt" -f (Get-Date))
Invoke-Logged "notifica" @("scripts\notify.py", "--pipeline-exit", "$pipelineExit", "--health-exit", "$healthExit", "--log", $log, "--out", $notifyOut) | Out-Null
if (Test-Path $notifyOut) {
    try {
        $notifyMessage = Get-Content -Path $notifyOut -Encoding UTF8 -Raw
        if ($notifyMessage) {
            Show-ToastNotification -Title "NewBoxOffice: guasto nella pipeline settimanale" -Message $notifyMessage
        }
    } catch {
        Add-Content -Path $log -Encoding utf8 -Value ("=== notifica desktop fallita: {0} ===" -f $_.Exception.Message)
    } finally {
        Remove-Item -Path $notifyOut -Force -ErrorAction SilentlyContinue
    }
}

# Pubblica i KPI sul sito vetrina (repo separato boxoffice-site, cartella sorella di questo repo).
# export_site_data.py rifiuta di scrivere se l'health check e' in FAIL: in quel caso non c'e' nulla
# da pubblicare e il sito resta con l'ultimo JSON buono. Un fallimento qui (repo assente, git, rete)
# non tocca $pipelineExit/$healthExit: e' un guasto del sito vetrina, non della pipeline dati.
$siteRepo = Join-Path (Split-Path -Parent $repo) "boxoffice-site"
if (Test-Path $siteRepo) {
    $siteDataOut = Join-Path $siteRepo "src\data\boxoffice.json"
    $exportExit = Invoke-Logged "export dati sito" @("scripts\export_site_data.py", "--out", $siteDataOut)
    if ($exportExit -eq 0) {
        Push-Location $siteRepo
        git add "src\data\boxoffice.json" | Out-Null
        git diff --cached --quiet
        $hasChanges = -not $?
        if ($hasChanges) {
            git commit -m ("Aggiorna KPI box office ({0:yyyy-MM-dd})" -f (Get-Date)) | Out-Null
            if ($LASTEXITCODE -eq 0) {
                git push | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} sito pubblicato ===" -f (Get-Date))
                } else {
                    Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} push del sito fallito (exit $LASTEXITCODE) ===" -f (Get-Date))
                }
            } else {
                Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} commit del sito fallito ===" -f (Get-Date))
            }
        } else {
            Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} sito: nessuna modifica da pubblicare ===" -f (Get-Date))
        }
        Pop-Location
    } else {
        Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} export dati sito saltato (health in FAIL) ===" -f (Get-Date))
    }
} else {
    Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} repo del sito non trovato in {1}: pubblicazione saltata ===" -f (Get-Date), $siteRepo)
}

# conserva 90 giorni di log
Get-ChildItem -Path $logDir -Filter "weekly_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
    Remove-Item -Force

if ($pipelineExit -ne 0) { exit $pipelineExit }
exit $healthExit

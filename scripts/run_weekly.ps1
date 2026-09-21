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

$pipelineExit = Invoke-Logged "pipeline (weekly + match)" @("main_v3.py")
$healthExit = Invoke-Logged "health check" @("scripts\health_check.py")
Add-Content -Path $log -Encoding utf8 -Value ("=== {0:s} fine: pipeline={1} health={2} ===" -f (Get-Date), $pipelineExit, $healthExit)

# conserva 90 giorni di log
Get-ChildItem -Path $logDir -Filter "weekly_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
    Remove-Item -Force

if ($pipelineExit -ne 0) { exit $pipelineExit }
exit $healthExit

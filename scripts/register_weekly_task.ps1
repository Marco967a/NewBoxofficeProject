# Registra (o rimuove con -Remove) l'attivita pianificata che esegue scripts\run_weekly.ps1.
# (File volutamente solo ASCII: PowerShell 5.1 legge i .ps1 senza BOM come ANSI e storpia gli accenti.)
#
# Perche lunedi E venerdi: ComingSoon pubblica la classifica del weekend (giovedi-domenica) entro
# lunedi e la mantiene fino al weekend successivo, ma NON ha archivio: una settimana persa non si
# recupera. Il venerdi e una rete di sicurezza per il caso in cui il PC fosse spento lunedi;
# l'upsert e idempotente, quindi rieseguire non crea duplicati.
#
# Uso:   .\scripts\register_weekly_task.ps1            # registra (lunedi e venerdi alle 12:00)
#        .\scripts\register_weekly_task.ps1 -Time 09:30
#        .\scripts\register_weekly_task.ps1 -Remove
param(
    [string]$TaskName = "NewBoxOffice-WeeklyRun",
    [string]$Time = "12:00",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Attivita '$TaskName' rimossa."
    return
}

$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\run_weekly.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $script) `
    -WorkingDirectory $repo

$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $Time
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $Time
)

# StartWhenAvailable: se il PC era spento all'ora prevista, parte appena possibile.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# Esegue come l'utente corrente (formato COMPUTER\utente), solo con sessione aperta,
# senza privilegi elevati e senza salvare la password.
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "NewBoxofficeProject: carica la classifica weekly di ComingSoon, collega i film a TMDB e verifica i dati." `
    -Force | Out-Null

# Verifica che l'attivita esista davvero prima di dichiararla registrata.
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Attivita '$TaskName' registrata per $currentUser."
Write-Host "Prossima esecuzione: $($info.NextRunTime)"
Write-Host "Log in: $(Join-Path $repo 'logs')"
Write-Host "Per rimuoverla: .\scripts\register_weekly_task.ps1 -Remove"

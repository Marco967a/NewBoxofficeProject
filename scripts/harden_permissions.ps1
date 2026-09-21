# Restringe i permessi di .env, backups\ e logs\ al solo utente corrente (piu SYSTEM e Administrators).
# Per default questi percorsi ereditano i permessi della cartella del progetto e risultavano leggibili anche da
# altri gruppi locali. Idempotente. (File volutamente solo ASCII: PowerShell 5.1 legge i .ps1 senza BOM come ANSI.)
#
# Uso:  .\scripts\harden_permissions.ps1
param(
    [string[]]$Paths = @(".env", "backups", "logs")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

foreach ($p in $Paths) {
    $full = Join-Path $repo $p
    if (-not (Test-Path $full)) {
        Write-Host "salto '$p': non esiste"
        continue
    }
    $isDir = (Get-Item $full -Force).PSIsContainer
    $perm = if ($isDir) { "(OI)(CI)F" } else { "F" }

    # /inheritance:r toglie i permessi ereditati; /grant:r sostituisce quelli espliciti
    icacls $full /inheritance:r /grant:r "${me}:$perm" "NT AUTHORITY\SYSTEM:$perm" "BUILTIN\Administrators:$perm" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls ha fallito su $full (codice $LASTEXITCODE)" }

    $acl = (Get-Acl $full).Access | ForEach-Object { $_.IdentityReference.Value } | Sort-Object -Unique
    Write-Host ("{0,-10} accessibile a: {1}" -f $p, ($acl -join ", "))
}

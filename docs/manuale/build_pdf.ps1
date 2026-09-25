<#
.SYNOPSIS
  Genera docs\Manuale_Utente_NewBoxoffice.pdf da docs\manuale\manuale.html con Microsoft Edge headless.
#>
$ErrorActionPreference = "Stop"

$html = Join-Path $PSScriptRoot "manuale.html"
$pdf = Join-Path (Split-Path $PSScriptRoot -Parent) "Manuale_Utente_NewBoxoffice.pdf"

$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge non trovato." }

if (Test-Path $pdf) { Remove-Item $pdf -Force }

# Profilo temporaneo: evita conflitti con un Edge già aperto.
$profile = Join-Path $env:TEMP ("edge_pdf_" + [guid]::NewGuid().ToString("N"))
try {
    $uri = ([System.Uri]$html).AbsoluteUri
    & $edge --headless --disable-gpu --no-pdf-header-footer "--user-data-dir=$profile" "--print-to-pdf=$pdf" $uri | Out-Null
    for ($i = 0; $i -lt 30 -and -not (Test-Path $pdf); $i++) { Start-Sleep -Milliseconds 500 }
}
finally {
    Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $pdf)) { throw "PDF non generato." }
Write-Host "Creato: $pdf ($([math]::Round((Get-Item $pdf).Length / 1KB)) KB)"

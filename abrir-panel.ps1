param([int]$Puerto = 8765)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Ejecuta primero .\preparar-local.ps1' }
    & $venvPython -X utf8 ui.py --port $Puerto --open
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar el panel. Comprueba si ya esta abierto o usa -Puerto 8766.' }
} finally { Pop-Location }

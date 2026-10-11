param([switch]$SinDemo)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Ejecuta primero .\preparar-local.ps1' }
    & $venvPython -X utf8 agent.py diagnostico
    if ($LASTEXITCODE -ne 0) { throw 'Fallo el diagnostico.' }
    & $venvPython -X utf8 -m unittest discover -s tests -v -b
    if ($LASTEXITCODE -ne 0) { throw 'Hay pruebas fallidas.' }
    & $venvPython -X utf8 -O -m unittest discover -s tests -p test_validation.py -v -b
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la validacion con Python optimizado.' }
    if (-not $SinDemo) {
        & $venvPython -X utf8 agent.py demo
        if ($LASTEXITCODE -ne 0) { throw 'Fallo la generacion de la demo.' }
    }
    Write-Host 'Pruebas locales completadas. No se llamo a OpenAI ni a YouTube.'
} finally { Pop-Location }

param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (-not $PythonPath) {
            $candidates = @('python', 'python3', (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
            foreach ($candidate in $candidates) {
                if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                    try {
                        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
                        if ($LASTEXITCODE -eq 0) { $PythonPath = $candidate; break }
                    } catch { }
                }
            }
        }
        if (-not $PythonPath) { throw 'Instala Python 3.11+ o usa -PythonPath con la ruta a python.exe.' }
        & $PythonPath -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear .venv.' }
    }
    & $venvPython -m pip --version
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m ensurepip --upgrade --default-pip
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar pip.' }
    }
    & $venvPython -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    & $venvPython -X utf8 agent.py diagnostico
    if ($LASTEXITCODE -ne 0) { throw 'El diagnostico detecto problemas.' }
    Write-Host 'Preparacion completa. Ejecuta .\probar-local.ps1'
} finally { Pop-Location }

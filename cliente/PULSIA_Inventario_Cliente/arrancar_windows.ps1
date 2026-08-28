param(
    [switch]$ReinstalarDependencias
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root '.dev-venv-windows'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $Venv '.requirements.sha256'

function Fail([string]$Message) {
    Write-Host ''
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    Write-Host ''
    Read-Host 'Pulsa ENTER para cerrar'
    exit 1
}

function Find-Python {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $ok = & py.exe -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
            if ($LASTEXITCODE -eq 0) { return 'py' }
        } catch {}
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        try {
            $ok = & python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
            if ($LASTEXITCODE -eq 0) { return 'python' }
        } catch {}
    }
    return $null
}

Write-Host '============================================================'
Write-Host ' PULSIA Inventario Cliente - modo desarrollo Windows'
Write-Host '============================================================'
Write-Host "Proyecto: $Root"

if (-not (Test-Path -LiteralPath $Requirements)) {
    Fail "No existe requirements.txt en $Root"
}

if (-not (Test-Path -LiteralPath $Python)) {
    $basePython = Find-Python
    if (-not $basePython) {
        Fail 'Se necesita Python 3.10 o superior. Instala Python y vuelve a ejecutar este BAT.'
    }
    Write-Host '[INFO] Creando entorno virtual de desarrollo...'
    if ($basePython -eq 'py') {
        & py.exe -3 -m venv $Venv
    } else {
        & python.exe -m venv $Venv
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
        Fail 'No se pudo crear el entorno virtual.'
    }
}

try {
    $version = & $Python -c "import sys; print(sys.version.split()[0])"
    Write-Host "[OK] Python del entorno: $version"
} catch {
    Fail "El entorno virtual no es utilizable: $($_.Exception.Message)"
}

$requirementsHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $Stamp) { (Get-Content -LiteralPath $Stamp -Raw).Trim() } else { '' }
$needInstall = $ReinstalarDependencias -or ($requirementsHash -ne $installedHash)

if (-not $needInstall) {
    & $Python -c "import PySide6, keyring, psutil" 2>$null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
}

if ($needInstall) {
    Write-Host '[INFO] Instalando dependencias. La primera ejecucion puede tardar varios minutos...'
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail 'No se pudo actualizar pip.' }
    & $Python -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { Fail 'No se pudieron instalar las dependencias.' }
    Set-Content -LiteralPath $Stamp -Value $requirementsHash -Encoding ASCII
}

Write-Host '[INFO] Verificando dependencias...'
& $Python -c "import PySide6, keyring, psutil; from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6/QtWebEngine/keyring/psutil OK')"
if ($LASTEXITCODE -ne 0) { Fail 'La comprobacion de dependencias ha fallado.' }

Write-Host '[INFO] Verificando sintaxis Python...'
& $Python -m compileall -q (Join-Path $Root 'src')
if ($LASTEXITCODE -ne 0) { Fail 'Hay un error de sintaxis en src.' }

Write-Host ''
Write-Host '[OK] Entorno preparado. Arrancando PULSIA Inventario Cliente...'
Write-Host '     Cierra la ventana de la aplicacion para volver a esta consola.'
Write-Host ''

& $Python (Join-Path $Root 'src\main.py')
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    Fail "La aplicacion termino con codigo $rc. Revisa el error mostrado arriba."
}

Write-Host ''
Write-Host '[OK] Aplicacion cerrada normalmente.'

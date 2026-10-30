param(
    [string]$PythonExecutable = "python",
    [string]$Version = "3.0.0"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    throw "Este build debe ejecutarse en Windows 10/11 de 64 bits. PyInstaller no genera ejecutables Windows desde Linux/macOS."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el comando: $FilePath $($Arguments -join ' ') (código $LASTEXITCODE)"
    }
}

function Remove-TreeRobust {
    param([Parameter(Mandatory=$true)][string]$Path)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($Root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "No se puede limpiar un directorio fuera del proyecto: $resolved"
    }
    if (-not (Test-Path -LiteralPath $resolved)) { return }

    for ($i = 1; $i -le 6; $i++) {
        try {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($i -eq 6) {
                throw "No pude limpiar '$Path'. Cerrá SmartPost y cualquier ventana del Explorador que esté usando esa carpeta y volvé a ejecutar el build. Detalle: $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds (400 * $i)
        }
    }
}

$Venv = Join-Path $Root ".build-venv"
if (-not (Test-Path $Venv)) {
    & $PythonExecutable -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "No pude crear el entorno virtual de build." }
}
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Invoke-Checked $Python -m pip install --upgrade pip wheel
Invoke-Checked $Python -m pip install -r (Join-Path $Root "packaging\requirements-build.txt")

$BrowserDir = Join-Path $Root "build\playwright-browsers"
New-Item -ItemType Directory -Force -Path $BrowserDir | Out-Null
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserDir
Invoke-Checked $Python -m playwright install chromium

# Verificación previa: el paquete de Playwright instalado debe contener su driver Node.
$PlaywrightNode = & $Python -c "import pathlib, playwright; p=pathlib.Path(playwright.__file__).resolve().parent/'driver'/'node.exe'; print(p); raise SystemExit(0 if p.exists() else 2)"
if ($LASTEXITCODE -ne 0) {
    throw "La instalación de Playwright del entorno de build no contiene driver\node.exe. Reinstalá dependencias antes de empaquetar."
}
Write-Host "Playwright Node fuente OK -> $PlaywrightNode"

# Tests que no requieren sesión real de Epresis/WhatsApp.
$env:SMARTPOST_DATA_DIR = Join-Path $Root "build\test-data"
$env:SMARTPOST_WEB_PIN = "246810"
$env:SMARTPOST_WEB_SESSION_SECRET = "ci-only-test-secret-0123456789012345678901234567890123456789"
$env:QT_QPA_PLATFORM = "offscreen"
$env:SMARTPOST_TEST_BROWSER = (& $Python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()")
Invoke-Checked $Python -m pytest -q tests

# Limpieza robusta del build anterior. El error WinError 5 suele ocurrir si SmartPost sigue abierto.
Remove-TreeRobust (Join-Path $Root "build\SmartPost")
Remove-TreeRobust (Join-Path $Root "dist\SmartPost")

Invoke-Checked $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\SmartPost.spec")

# Fallar inmediatamente si Playwright's Node driver no quedó empaquetado.
$NodeCandidates = @(
    (Join-Path $Root "dist\SmartPost\_internal\playwright\driver\node.exe"),
    (Join-Path $Root "dist\SmartPost\playwright\driver\node.exe")
)
$BundledNode = $NodeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $BundledNode) {
    throw "El build terminó pero no encuentro playwright/driver/node.exe dentro de dist\SmartPost. No se crea el instalador."
}
Write-Host "Playwright Node empaquetado OK -> $BundledNode"

# Verify the frozen program, not just the source environment.
$SmokeReport = Join-Path $Root "build\frozen-self-test.json"
$AppProcess = Start-Process -FilePath (Join-Path $Root "dist\SmartPost\SmartPost.exe") -ArgumentList @("--self-test", ('"' + $SmokeReport + '"')) -WindowStyle Hidden -PassThru
if (-not $AppProcess.WaitForExit(120000)) { $AppProcess.Kill(); throw "El ejecutable no terminó su prueba de arranque." }
if ($AppProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $SmokeReport)) { throw "Falló la prueba del ejecutable empaquetado." }
$SmokeResult = Get-Content -LiteralPath $SmokeReport -Raw | ConvertFrom-Json
if (-not $SmokeResult.ok) { throw "El ejecutable empaquetado no pasó la validación: $($SmokeResult.error)" }

$Signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
$Thumbprint = $env:SMARTPOST_SIGN_CERT_THUMBPRINT
if ($Signtool -and $Thumbprint) {
    Write-Host "Firmando SmartPost.exe con certificado del almacén de Windows..."
    Invoke-Checked $Signtool.Source sign /sha1 $Thumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 (Join-Path $Root "dist\SmartPost\SmartPost.exe")
}

$ProgramFiles = [Environment]::GetFolderPath("ProgramFiles")
$ProgramFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
$IsccCandidates = @(
    (Join-Path $ProgramFiles "Inno Setup 7\ISCC.exe"),
    (Join-Path $ProgramFilesX86 "Inno Setup 7\ISCC.exe"),
    (Join-Path $ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and $_.Trim() -ne "" }
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "No encontré Inno Setup 6/7. Instalalo en la PC de build y volvé a ejecutar este script."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist-installer") | Out-Null
if ($Version -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') { throw "Versión inválida: $Version" }
Invoke-Checked $Iscc ("/DMyAppVersion=" + $Version) (Join-Path $Root "packaging\SmartPost.iss")

$Installer = Join-Path $Root "dist-installer\SmartPost_Instalador.exe"
if ($Signtool -and $Thumbprint -and (Test-Path $Installer)) {
    Write-Host "Firmando instalador..."
    Invoke-Checked $Signtool.Source sign /sha1 $Thumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $Installer
}

Write-Host ""
Write-Host "OK -> $Installer"

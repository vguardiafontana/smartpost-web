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
    if (-not (Test-Path $Path)) { return }

    for ($i = 1; $i -le 6; $i++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
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

# Evita que una copia de SmartPost abierta bloquee DLL/PYD dentro de dist\SmartPost.
$running = Get-Process -Name "SmartPost" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "SmartPost está abierto. Cerrando la aplicación para poder recompilar..."
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

$Venv = Join-Path $Root ".build-venv"
if (-not (Test-Path $Venv)) {
    py -3 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "No pude crear el entorno virtual de build." }
}
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Invoke-Checked $Python -m pip install --upgrade pip wheel
Invoke-Checked $Pip install -r (Join-Path $Root "packaging\requirements-build.txt")

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
Invoke-Checked $Iscc (Join-Path $Root "packaging\SmartPost.iss")

$Installer = Join-Path $Root "dist-installer\SmartPost_Instalador.exe"
if ($Signtool -and $Thumbprint -and (Test-Path $Installer)) {
    Write-Host "Firmando instalador..."
    Invoke-Checked $Signtool.Source sign /sha1 $Thumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $Installer
}

Write-Host ""
Write-Host "OK -> $Installer"

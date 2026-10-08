# Build del instalador de Windows

El usuario final **no usa estas instrucciones**. Son solo para construir una nueva versión del instalador.

## Estrategia elegida

Se usa **PyInstaller `--onedir --windowed` + Inno Setup**. Aunque PyInstaller `--onefile` parece más simple, incluir Chromium en un único binario hace que cada arranque deba extraer cientos de MB a una carpeta temporal, aumenta el tiempo de inicio y suele elevar los falsos positivos de antivirus. Inno Setup sigue entregando **un único `SmartPost_Instalador.exe`**, pero instala internamente la aplicación en formato onedir, que es más estable para Playwright/Chromium.

## Requisitos de la PC de build

- Windows 10/11 x64
- Python 3.11 o 3.12 x64
- Inno Setup 6
- Internet durante el build para instalar dependencias y descargar Chromium
- Opcional: Windows SDK `signtool.exe` + certificado de firma de código

## Build

Desde PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\build_windows.ps1
```

Salida esperada:

`dist-installer\SmartPost_Instalador.exe`

El Chromium de Playwright se descarga durante el build a `build\playwright-browsers` y luego se incluye dentro de la aplicación. La PC del usuario final no ejecuta `playwright install`.

## Firma opcional

Si el certificado está instalado en el almacén de certificados de Windows, definir antes del build:

```powershell
$env:SMARTPOST_SIGN_CERT_THUMBPRINT="HUELLA_DEL_CERTIFICADO"
```

El script firmará primero `SmartPost.exe` y luego `SmartPost_Instalador.exe`, ambos con SHA-256 y timestamp.

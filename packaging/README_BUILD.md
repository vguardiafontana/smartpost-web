# Build del instalador de Windows

## Publicación automática

Los cambios de Desktop en main activan `.github/workflows/build-installer.yml`. GitHub construye un instalador con Python, bibliotecas, Chromium y su driver, ejecuta las pruebas y prueba una instalación limpia. Sólo después publica `SmartPost_Instalador.exe` en un Release. Los cambios exclusivos de `app/web/` no activan una nueva entrega de Desktop.

Enlace fijo: https://github.com/vguardiafontana/smartpost-web/releases/latest/download/SmartPost_Instalador.exe

La versión del instalador concatena la versión base de `SmartPost.iss` y el número de compilación de GitHub, por ejemplo `2.9.7.1`. Una ejecución fallida conserva el último Release válido. Se publican además el SHA-256 y el resultado de la prueba del ejecutable instalado.

Este enlace no hace pública una cuenta o repositorio privado. El usuario debe tener acceso al repositorio. La PC de uso no requiere Python ni descargas de paquetes. Excel sigue siendo necesario para los reportes que usan COM. En una PC nueva se configura Epresis y se vincula WhatsApp desde la aplicación.

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

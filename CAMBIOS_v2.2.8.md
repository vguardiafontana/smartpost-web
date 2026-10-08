# SmartPost Desktop v2.2.8 — Parche Playwright empaquetado

- Corrige `WinError 2` al iniciar Playwright desde el EXE.
- Incluye explícitamente `playwright/driver/node.exe` y el paquete JS del driver en PyInstaller.
- Configura `PLAYWRIGHT_NODEJS_PATH` al driver incluido en la aplicación.
- Mantiene Chromium embebido mediante `PLAYWRIGHT_BROWSERS_PATH`.
- No cambia la lógica de Reportes, Visitas ni Denuncias.

# SmartPost Desktop: cambios sobre SmartPost_Unificado

Esta versión no reescribe la lógica de Epresis, normalización, generación Excel ni WhatsApp. Agrega una capa de escritorio y adapta únicamente infraestructura/configuración para ejecución empaquetada.

## Cambios

- `desktop.py` reemplaza la interacción por consola como punto de entrada de producción.
- GUI PySide6 con calendario, Ejecutar, dry-run, logs en vivo, progreso por etapa y resumen por seller.
- Wizard inicial y pantalla Configuración; el usuario no edita YAML manualmente.
- Contraseña Epresis continúa almacenada con `keyring`.
- Configuración mutable, logs, SQLite, perfiles, temporales y reportes se resuelven bajo `%APPDATA%\SmartPost`.
- Template, Prompt Maestro e ícono son recursos de solo lectura incluidos en la aplicación.
- Chromium de Playwright se empaqueta y se selecciona mediante `PLAYWRIGHT_BROWSERS_PATH`.
- Login de WhatsApp ya no requiere `input()`/ENTER; la GUI espera automáticamente a que el QR quede vinculado.
- `run_pipeline()` acepta eventos opcionales de progreso sin cambiar la lógica de negocio.
- Se eliminaron los BAT de usuario, configurador CLI y `run.py` de la distribución desktop.

## Empaquetado

PyInstaller onedir/windowed + Inno Setup = un único instalador distribuible, con inicio más rápido y menos superficie de falsos positivos que un onefile con Chromium.

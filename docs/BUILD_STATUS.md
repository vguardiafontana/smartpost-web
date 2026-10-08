# Estado de build

El código desktop, la GUI, la configuración de PyInstaller, la inclusión de Chromium, el script de Inno Setup, la firma opcional y la documentación están preparados.

Validaciones realizadas en el entorno de desarrollo disponible:

- compilación sintáctica de módulos Python;
- 11 tests unitarios del pipeline: aprobados;
- verificación del instructivo PDF: 1 página;
- revisión estática de rutas empaquetadas y recursos.

## Validaciones que necesariamente requieren Windows

PyInstaller no realiza cross-compilation de un ejecutable Windows desde Linux, e Inno Setup es una herramienta Windows. Por eso el `.exe` final debe compilarse en una PC/runner Windows mediante `packaging/build_windows.ps1` o el workflow de GitHub incluido.

Después del build se debe cumplir `docs/PLAN_PRUEBAS_WINDOWS.md`, especialmente la prueba en una PC limpia sin Python y la prueba COM con Microsoft Excel instalado.

No se debe declarar una versión como lista para distribución hasta completar esa validación real en Windows.

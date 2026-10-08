# SmartPost v2.9.0 — Actualización

## Web: Reportes y Visitas

- Se agrega el módulo **Reportes y Visitas** a SmartPost Web.
- Permite elegir una fecha y generar el lote sin enviar nada por WhatsApp.
- Mantiene la descarga de sellers desde Epresis, incluido el filtro especial de sábados y el rango mensual de sellers configurados.
- Genera un XLSX por cliente usando el mismo template y las mismas reglas de normalización del desktop.
- Agrega **VISITAS** al mismo lote cuando hay datos.
- Permite descargar cada archivo por separado o todos juntos en un ZIP.
- Cada reporte de cliente muestra el mensaje configurado listo para copiar con un botón grande para móvil.
- Los archivos generados se guardan como artefactos persistentes en PostgreSQL/Neon cuando `DATABASE_URL` está configurado, para no depender del disco efímero de Render.
- La generación corre en segundo plano; bloquear el iPhone no detiene el proceso.
- Se reutiliza el mismo bloqueo de operaciones Epresis para no superponer Reportes con Cambio de estado v2.

## Compatibilidad

- **Cambio de estado v2 no fue modificado.**
- **Búsqueda de guías se mantiene.**
- La app desktop conserva todos sus módulos y su generación con Microsoft Excel/COM.
- La versión web no incorpora Cambio de estado v1, Denuncias, Archivar/Desarchivar WhatsApp ni Vincular WhatsApp.

## Excel en servidor

Render/Linux no dispone de Microsoft Excel/COM. Para la web se incorporó un generador XLSX portable que reutiliza `TEMPLATE_REPORTE.xlsx`, conserva logo, encabezados, anchos, fórmulas, tabla, validación, formatos de fecha y reglas de datos. El desktop sigue usando Excel real sin cambios.

VISITAS se genera en XLSX con todas las celdas como texto, encabezado en negrita, autofiltro, fila superior inmovilizada y ancho de columnas limitado como en desktop.

## Dependencias

- Se agrega `openpyxl` únicamente a `requirements-web.txt`.

## Pruebas

- Suite completa: **77 tests OK**.
- No se realizaron cambios reales ni pruebas contra producción de Epresis.

# SmartPost Desktop v2.1 — VISITAS

Se agregó al flujo un Excel global de **VISITAS** sin modificar las reglas existentes de reportes por seller.

## Flujo

1. Descarga los crudos normales por seller.
2. Genera y audita los reportes normales.
3. Busca VISITAS en Epresis para la fecha elegida, sin filtro de cliente.
4. Filtra los estados configurados.
5. Descarga el CSV de Epresis y lo convierte a `VISITAS DD-MM-YY.xlsx` usando Microsoft Excel.
6. Si existen visitas, envía ese XLSX al grupo configurado.
7. Continúa con los envíos normales de WhatsApp.

Si la búsqueda de VISITAS devuelve 0 filas, no genera un archivo vacío y no intenta enviarlo.

## Configuración inicial incluida

- Grupo: `CONSULTAS / Operación nocturna`
- Mensaje: vacío (se envía únicamente el archivo)
- Estados:
  - 127 — 1° VISITA
  - 119 — 2° VISITA
  - 183 — 3° VISITA
  - 48 — DIRECCIÓN INCORRECTA
  - 51 — RECHAZADO POR DESTINATARIO
  - 117 — REPROGRAMACIÓN
  - 63 — ZONA PELIGROSA - DIFICIL ACCESO

Todo esto puede modificarse desde **Configuración → Visitas** sin editar archivos manualmente.

## Actualización desde una versión anterior

El `config.yaml` existente del usuario se conserva. Al abrir la nueva versión, SmartPost agrega automáticamente las nuevas claves de VISITAS que falten, sin borrar usuarios, grupos de sellers ni otras preferencias ya guardadas.

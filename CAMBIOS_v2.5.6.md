# SmartPost v2.5.6 — Parche

- Búsqueda de guías: el teléfono del distribuidor ahora se resuelve prioritariamente desde **EXPORTAR COMPLETO A EXCEL** de `/distribuidores/excelDistribuidores`.
- El Excel se descarga una sola vez por búsqueda masiva y se indexa localmente por DNI/código.
- Se usa `telefono`; si está vacío, se usa `celular`.
- Si el DNI no aparece en el Excel, se conservan los fallbacks anteriores de grilla/ficha.

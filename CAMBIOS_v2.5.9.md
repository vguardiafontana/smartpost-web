# Parche v2.5.9

- Búsqueda de guías: corrige la descarga de la base completa de Distribuidores. El endpoint `/distribuidores/excelDistribuidores` devuelve 405 ante GET; SmartPost ahora abre la grilla real y pulsa `#expor-excel`, igual que el operador, y usa POST autenticado como respaldo.
- La búsqueda de guías habilita descargas en el contexto de Playwright y carga el XLS exportado una sola vez para resolver DNI -> teléfono/celular.
- Archivar/desarchivar: amplía la detección del menú contextual de WhatsApp para la vista Archivados. Prueba variantes de `data-testid`, `data-icon`, aria/title, detección DOM del chevron, click por coordenadas del borde derecho, evento `contextmenu` y right-click final.
- Se conserva la lógica de archivar que ya funcionaba y el fallback horario existente.

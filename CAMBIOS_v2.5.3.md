# Parche v2.5.3

- Corrige el teléfono del distribuidor en Búsqueda de guías.
- Lee correctamente las columnas reales de la tabla de Distribuidores de Epresis: Teléfono (columna 10) y Celular (columna 11).
- Si Teléfono está vacío usa Celular, y viceversa.
- Tolera respuestas de Distribuidores como JSON, filas HTML `<tr>/<td>` o arrays de celdas.
- Conserva la tabla copiable y el tema gris/negro de v2.5.2.

Validación: 37 tests OK.

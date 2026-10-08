# SmartPost v2.5.5

## Parche

- Corrige el teléfono del distribuidor en Búsqueda de guías.
- La app ahora entra realmente a `/distribuidores/lista-distribuidores`, identifica la columna DNI, usa el filtro de esa columna y lee las columnas visibles `Teléfono` y `Celular` de la fila encontrada.
- Si `Teléfono` está vacío usa `Celular`.
- Se mantiene como respaldo el endpoint interno y la ficha `/distribuidores/show/<id>`.

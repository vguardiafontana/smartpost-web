# Parche v2.5.4

- Búsqueda de guías: corregida la obtención del teléfono del distribuidor.
- Ahora consulta `/distribuidores/lista-distribuidores` usando primero el DNI exacto del distribuidor y, como respaldo, el apellido.
- Lee Teléfono y Celular de la fila real de Distribuidores.
- Si la grilla no devuelve el número, abre `/distribuidores/show/{id}` y toma Teléfono/Celular desde la ficha del distribuidor.

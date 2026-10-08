# SmartPost v2.6.2 — Parche

- Corrige Cambio de estado v2 cuando una guía no expone el distribuidor como enlace directo.
- Agrega detección del distribuidor desde campos estructurados (`distribuidor_id`, objeto `distribuidor`, DNI/código y nombre) de la búsqueda de guía.
- Agrega respaldo leyendo el campo visible "Distribuidor" / "Distribuidor Recorrido" del detalle de la guía aunque no sea un enlace.
- Si sólo se obtiene DNI o nombre, consulta el combo oficial de distribuidores y prioriza coincidencia exacta por DNI.
- Mantiene la validación posterior: la guía debe aparecer realmente dentro de una planilla del distribuidor antes de cambiar el estado.
- Mejora el mensaje de error mostrando el DNI/nombre detectado cuando no puede resolver al distribuidor.

# SmartPost v2.5.0

## Nuevo módulo: Búsqueda de guías

- Nueva tarjeta **Búsqueda de guías** en la pantalla principal.
- Acepta múltiples identificadores mezclados: número de guía, remito o Guía Agente.
- Resuelve cada envío usando la sesión existente de Epresis sin modificar datos.
- Muestra por envío: Guía Agente, remito, número de guía, cliente, servicio, destinatario, domicilio, localidad, provincia, código postal, teléfono, estado y distribuidor.
- El distribuidor se enriquece con la página de Distribuidores para mostrar nombre, DNI y teléfono cuando Epresis lo informa.
- Cada resultado incluye **Abrir en Chrome**, que abre `guias/editar-guia-v2/show/{guia}` directamente en Google Chrome cuando está instalado; si Chrome no se encuentra, usa el navegador predeterminado como respaldo.
- Identificadores diferentes que resuelven a la misma guía se muestran una sola vez.

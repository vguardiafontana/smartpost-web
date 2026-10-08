# SmartPost v2.8.0 — Actualización web: Búsqueda de guías

- Se agrega una pantalla de inicio móvil con acceso a módulos web.
- Cambio de estado v2 conserva sus endpoints y flujo existentes.
- Se migra **Búsqueda de guías** a la web reutilizando `app/busqueda_guias/service.py` sin duplicar la lógica desktop.
- La búsqueda acepta guía, remito y guía agente, igual que escritorio.
- Resultados móviles: guía, guía agente, remito, cliente, servicio, destinatario, domicilio, localidad, provincia, CP, teléfono, estado, distribuidor, DNI y teléfono del distribuidor.
- Se conservan enlaces de guía y distribuidor cuando Epresis los expone.
- La API web exige la misma sesión por PIN.
- La operación comparte el lock con Cambio de estado v2 para evitar que dos automatizaciones usen el perfil Epresis al mismo tiempo.
- No se realizaron pruebas contra Epresis de producción.

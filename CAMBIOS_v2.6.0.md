# SmartPost v2.6.0 — Actualización

## Cambio de estado v2

Se agrega un apartado separado **Cambio de estado v2** basado en el nuevo flujo operativo de **Rendición de Chofer** de Epresis.

- Resuelve guía, remito o Guía Agente a `retiro_id` usando la lógica existente.
- Obtiene el distribuidor exacto desde el enlace `/distribuidores/show/<id>` de la guía.
- Busca las planillas del distribuidor en `/recorridos/list-route-json` usando la fecha actual de la PC.
- Si existen varias planillas para el mismo chofer, revisa desde la más nueva hasta encontrar en cuál está cada `retiro_id`.
- Nunca envía un cambio si el pedido no fue encontrado dentro de una planilla del distribuidor.
- Agrupa todos los pedidos que pertenecen a la misma planilla y los confirma juntos.
- Habilita automáticamente un nuevo Nro. de Rendición mediante `/rendicion/habilitarNroRendicion`.
- Confirma mediante `/rendicion/confirmarRecepcionados` con el estado elegido por el operador.
- Usa fecha y hora actuales de la PC para los campos de recepción.
- Tras cada confirmación vuelve a consultar la planilla e intenta verificar `rendido = SI`.
- Un error en una guía o planilla no frena el resto del lote.
- Genera auditoría `cambio_estado_v2_*.json` sin guardar CSRF/cookies.

El módulo anterior **Cambio de estado** se conserva como flujo v1.

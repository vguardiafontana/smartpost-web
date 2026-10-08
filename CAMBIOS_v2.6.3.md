# Parche v2.6.3

## Cambio de estado v2

- Agrega fallback de Rendición cuando no se puede determinar el distribuidor de una guía.
- Si falla la resolución del distribuidor, SmartPost obtiene una planilla real del día como sonda y llama a `confirmarRecepcionados` con la guía.
- Si Epresis responde que la guía está en otro recorrido (por ejemplo: `está en el recorrido: 98149`), SmartPost extrae ese número y usa esa planilla exacta.
- Si la planilla sonda resulta ser la correcta y Epresis confirma el cambio, no se reenvía el pedido.
- Los pedidos detectados por este fallback se agrupan por planilla para mantener el cambio masivo.
- Se mantiene la fecha/hora de la PC y el mismo número de rendición habilitado para el lote.

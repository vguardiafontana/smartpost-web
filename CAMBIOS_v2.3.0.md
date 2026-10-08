# SmartPost Desktop v2.3.0

## Actualización: Cambio de estado masivo

Se agrega un nuevo módulo **Cambio de estado** en la pantalla principal.

### Seguridad operativa
- `ANALIZAR SIN CAMBIAR` resuelve todos los identificadores sin modificar Epresis.
- Acepta mezcla de N° de guía, Remito y Guía Agente.
- La guía normal se valida de forma no destructiva antes de considerarla válida.
- Remito usa `/tracker/searchByRemitoCliente` y Guía Agente usa `/tracker/searchByGuiaAgente`.
- Deduplica por `retiro_id`, evitando cambiar dos veces la misma guía.
- Si hay una entrada sin resolver, el cambio real queda bloqueado.
- Antes del primer cambio se muestra una confirmación explícita con cantidad y estado destino.

### Cambio real
- Endpoint: `/guias/arribo_paquetes-cambio-estado`.
- Se envían `_token`, `retiro_id` y `estado_id`.
- Los cambios se procesan secuencialmente, una guía por vez.
- Un `result: ERROR` de Epresis se registra y el lote continúa con la siguiente guía.
- Se guarda una auditoría local JSON sin cookies ni CSRF en la carpeta de logs.

### Estados
El selector reproduce los IDs y textos observados en `#estado_id` de Arribo de Paquetes.

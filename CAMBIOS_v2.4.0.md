# SmartPost Desktop v2.4.0

## Actualización: Cambio de estado directo

- Se elimina el paso manual **ANALIZAR SIN CAMBIAR**.
- Ahora alcanza con pegar guías/remitos/Guías Agente, seleccionar el estado y tocar **CAMBIAR ESTADO**.
- Internamente SmartPost conserva la resolución segura, deduplicación por `retiro_id`, validación de identificadores y procesamiento secuencial.
- Entradas que no se pueden resolver se omiten y se informan en el resultado; no provocan cambios sobre otra guía.
- Los `result: ERROR` de Epresis siguen registrándose y no detienen el lote.

## Actualización: Archivar / desarchivar chats de WhatsApp

- Se agrega un botón pequeño **Archivar / desarchivar** al costado del menú principal.
- Si WhatsApp Web muestra **Archivados**, entra allí y desarchiva todos los chats.
- Si no hay chats archivados, abre la lista/filtro **Smart Post** y archiva todos los chats visibles de esa lista.
- La lista objetivo se puede ajustar con `whatsapp.company_chat_list` (por defecto `Smart Post`).
- El proceso reutiliza el mismo perfil de WhatsApp ya vinculado por SmartPost.

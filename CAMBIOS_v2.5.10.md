# Parche v2.5.10

- Corrige `TargetClosedError` al desarchivar chats en WhatsApp.
- Si WhatsApp cierra la pestaña durante una operación, SmartPost crea una pestaña nueva dentro del mismo perfil y reintenta; si se cierra también el contexto, relanza el contexto una vez.
- Mejora la detección de la acción rápida `Desarchivar` cuando WhatsApp la renderiza fuera del DOM de la fila del chat.
- Mantiene sin cambios la lógica de archivado que ya funcionaba.

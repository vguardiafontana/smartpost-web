# SmartPost v2.5.8 — Parche

- WhatsApp: aumenta el tiempo real de espera de resultados a un mínimo de 15 segundos.
- WhatsApp: cada búsqueda de grupo hace reintentos controlados y limpia la caja de búsqueda entre intentos.
- WhatsApp: si un seller falla en la primera pasada, se guarda como pendiente y se reintenta al final del lote.
- Los sellers ya enviados no se vuelven a enviar; StateDB sigue funcionando como protección anti-duplicados.
- VISITAS también recibe un reintento controlado si falla.
- Si después de todos los reintentos todavía quedan pendientes, el proceso ya no se marca como fallo fatal: termina como `partial_success`, conserva el detalle en logs/run_summary y muestra una advertencia clara en la GUI.
- En un fallo final se guarda una captura de diagnóstico en `runtime/logs/whatsapp_screens`.
- Mantiene la validación estricta del nombre exacto del grupo antes de enviar.

# SmartPost Desktop v2.2.12 — Parche espera final de WhatsApp

- Tras enviar VISITAS al grupo de consultas, SmartPost mantiene WhatsApp Web abierto 5 segundos antes de cerrar el navegador.
- La espera solo se aplica cuando el envío fue real y quedó con estado `sent`.
- No retrasa `Probar sin enviar`, archivos ya enviados ni errores.
- El tiempo queda configurable como `whatsapp.performance.final_visitas_close_delay_ms` (por defecto 5000 ms).

# SmartPost Desktop v2.2.29 — Parche

- Corrige la carrera al guardar el PDF oficial cuando Provincia cierra la pestaña/navegador inmediatamente después de iniciar la descarga.
- La descarga se persiste en cuanto Playwright emite el evento, sin esperar al siguiente ciclo de polling.
- Se agrega un directorio de spool de descargas por ejecución y un fallback que copia cualquier PDF válido desde ese spool si `Download.save_as()` falla con `TargetClosedError`.
- Mantiene CAPTCHA manual.

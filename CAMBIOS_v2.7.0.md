# SmartPost v2.7.0 — Etapa 2 Web

- Nueva API web privada para Cambio de estado v2, sin modificar el flujo PySide6 existente.
- Login por PIN con cookie firmada, `HttpOnly`, `Secure` y `SameSite=Strict`.
- Vista previa obligatoria antes de confirmar; la vista previa sólo resuelve identificadores y no cambia estados.
- Ejecución de trabajos en segundo plano en el servidor: continúa aunque Safari se cierre o el iPhone se bloquee.
- Cola secuencial para evitar dos procesos Epresis simultáneos sobre el mismo perfil de Chromium.
- Progreso consultable por polling y persistencia local de cada trabajo.
- Resumen separado en realizados, Estado ya asignado, advertencias, errores, sin resolver y duplicados.
- Reintento sólo de entradas realmente fallidas.
- PWA móvil con diseño para iPhone y restauración del último trabajo al volver a abrirla.
- `requirements-web.txt` separado para Linux: no instala PySide6 ni pywin32.
- Servicio systemd y guía de despliegue con Tailscale Serve.
- No se ejecutaron pruebas contra Epresis de producción.

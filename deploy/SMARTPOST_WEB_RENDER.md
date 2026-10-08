# SmartPost Web en Render Free + Neon

## Arquitectura
- Render Free: ejecuta FastAPI + Playwright/Chromium.
- Neon Free: persiste trabajos y resultados mediante `DATABASE_URL`.
- UptimeRobot: consulta `/healthz` cada 5 minutos para evitar el spin-down por inactividad.
- La app de escritorio no cambia. Sin `DATABASE_URL`, SmartPost usa los JSON locales de siempre.

## Variables requeridas
- `SMARTPOST_EPRESIS_USER`
- `SMARTPOST_EPRESIS_PASSWORD`
- `SMARTPOST_WEB_PIN`
- `SMARTPOST_WEB_SESSION_SECRET` (Render puede generarla)
- `DATABASE_URL` (Neon)

## Seguridad
La URL de Render es pública, pero las operaciones están detrás del PIN y cookie firmada. `/healthz` es público y sólo devuelve estado básico; no permite operar Epresis.

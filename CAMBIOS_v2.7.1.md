# SmartPost v2.7.1 — Render Free

- Despliegue reproducible en Render mediante `Dockerfile` y `render.yaml`.
- `web_server.py` soporta `PORT` de Render y binding `0.0.0.0` sólo en cloud.
- Persistencia opcional de trabajos en PostgreSQL mediante `DATABASE_URL` (recomendado: Neon Free).
- En Windows/local, sin `DATABASE_URL`, se conserva la persistencia JSON actual y no cambia el escritorio.
- Nuevo `/healthz` para health checks/monitor externo; no expone datos sensibles.
- Los trabajos `queued/running` persistidos se marcan `interrupted` tras un reinicio para permitir reintento seguro.
- Se agrega `psycopg` sólo a `requirements-web.txt`.
- No se realizaron pruebas contra Epresis de producción.

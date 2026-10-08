# SmartPost Desktop v2.2.11 — Parche acceso directo a Denuncias GBA

- Denuncias usa exclusivamente `https://seguridad.gba.gob.ar/#/robo-otros`.
- Se elimina la navegación automática por Home -> Denunciá -> categorías.
- Si la SPA deriva temporalmente a `#/home`, se reintenta el enlace directo.
- CAPTCHA continúa siendo un paso manual.
- No se generan fechas de nacimiento ficticias: se usa la fecha real guardada/ingresada para el chofer.

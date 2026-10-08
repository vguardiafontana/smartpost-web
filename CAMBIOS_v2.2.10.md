# SmartPost Desktop v2.2.10 — Parche navegación Denuncias GBA

- Corrige el caso en que `https://seguridad.gba.gob.ar/#/robo-otros` redirige una sesión nueva a `#/home`.
- SmartPost ya no intenta completar `Apellido` mientras sigue en la portada.
- Navega por la interfaz: **DENUNCIÁ → Robo/Hurto → OTROS** y recién después completa el formulario.
- Si el portal presenta un CAPTCHA/verificador antes de ingresar, espera que el usuario lo resuelva manualmente.
- Conserva un fallback al enlace `#/robo-otros` una vez inicializada la SPA.
- Si el portal cambia nuevamente, el error informa URL y texto visible de la pantalla donde quedó.

# SmartPost Desktop v2.2.28 — Parche

- Corrige la selección automática de direcciones alternativas en Provincia.
- La lista de alternativas se busca ahora bajo `app-paso-hecho`, que es donde realmente la renderiza el sitio, aunque visualmente aparezca dentro del bloque de domicilio.
- Se intenta hacer clic tanto en el enlace como en el `li` contenedor y se dispara un evento de mouse como respaldo.
- El diagnóstico de la ambigüedad también inspecciona `app-paso-hecho`.
- 22 tests pasan.

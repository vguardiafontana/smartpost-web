# SmartPost v2.6.4 — Parche

- Cambio de estado v2 ahora preserva el código exacto del perfil del distribuidor (por ejemplo `37424493APP` vs `37424493P`) y lo prioriza por encima de coincidencias ambiguas por DNI o nombre.
- Si la guía no aparece en las planillas del perfil exacto, SmartPost consulta todos los perfiles alternativos que comparten el mismo DNI y prueba sus planillas antes de recurrir al fallback de Rendición.
- Si ningún perfil del mismo DNI contiene la guía, recién entonces usa `confirmarRecepcionados` como sonda para extraer el recorrido real desde el mensaje de Epresis.
- Se agregaron pruebas de regresión para códigos de perfil con sufijos APP/P.

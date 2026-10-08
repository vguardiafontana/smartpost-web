# SmartPost Desktop v2.2.27 — Parche

## Denuncias Provincia

- Corregida la selección de direcciones alternativas cuando Provincia muestra el aviso **"Se encontró más de una opción, por favor elija una"**.
- El sitio actual renderiza esas alternativas en línea dentro de `app-form-datos-domicilio`, bajo una lista `ul > li > a`; ya no se buscan solamente dentro de diálogos/overlays.
- SmartPost elige automáticamente la primera alternativa visible y luego, si aparece el cuadro de verificación, pulsa **"Ignorar y continuar"**.
- Se agregó un diagnóstico específico del bloque de domicilio si Provincia vuelve a cambiar el HTML.

## Validación

- 22 tests automáticos aprobados.

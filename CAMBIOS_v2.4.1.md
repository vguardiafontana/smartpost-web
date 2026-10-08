# Parche v2.4.1

## Archivar / desarchivar WhatsApp

- La decisión ahora se toma por el estado real de WhatsApp:
  - si `Archivados` contiene chats, los desarchiva;
  - si `Archivados` está vacío o no aparece, abre la lista `Smart Post` y archiva sus chats.
- Corrige el falso positivo de v2.4.0: ya no alcanza con que exista la entrada `Archivados`.
- El menú contextual se abre primero con el desplegable propio de WhatsApp; el clic derecho queda como fallback.
- Se agregaron selectores de acción rápida y búsquedas más tolerantes para `Archivar`/`Desarchivar` en español e inglés.
- Si falla la detección por cambios de interfaz, se usa el horario solo como fallback:
  - 17:00 a 19:00: desarchivar;
  - 22:00 a 01:00: archivar.
- Los errores ahora incluyen las etiquetas visibles del menú para facilitar un siguiente ajuste sin adivinar.

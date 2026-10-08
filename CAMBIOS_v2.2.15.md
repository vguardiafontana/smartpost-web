# Parche v2.2.16

- Corrige el bloqueo visual en la selección de Género del formulario de denuncias.
- Evita el auto-scroll repetido de Playwright al seleccionar radios de Angular/Material.
- La selección de radio ahora usa click DOM directo y prioriza el grupo asociado a la pregunta.
- Mantiene la selección de violencia/daños en el grupo correcto aunque existan otros radios Sí/No en la página.

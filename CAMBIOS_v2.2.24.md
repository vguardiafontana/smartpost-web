# Parche v2.2.24

- Corrige el bloqueo en la verificación de dirección de Provincia.
- Espera hasta 8 segundos a que aparezca el modal "Por favor verifique si la dirección es correcta".
- Pulsa "Ignorar y continuar" dentro del diálogo/overlay con varios fallbacks para Angular Material.
- Verifica que el modal haya desaparecido antes de continuar.
- Vuelve a intentar limpiar ese modal justo antes de avanzar a "Características del hecho" por si aparece con retraso.
- Mantiene la selección automática de la primera sugerencia de Localidad/Barrio.
- 22 tests pasan correctamente.

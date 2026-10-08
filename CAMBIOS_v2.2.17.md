# Parche v2.2.17

- Corrige la selección de Sí/No en “violencia física o daños materiales” con búsqueda DOM tolerante a cambios de Angular/Material, acentos y estructura.
- Agrega diagnóstico detallado si la opción no puede localizarse.
- Denuncias intenta reutilizar un perfil dedicado de Provincia para conservar cookies/estado normal del navegador y hacer menos pesado el CAPTCHA manual.
- Si ese perfil está bloqueado después de una ejecución interrumpida, usa automáticamente un navegador temporal en lugar de quedar colgado.
- El CAPTCHA sigue siendo completamente manual; no se intenta resolverlo ni eludirlo.

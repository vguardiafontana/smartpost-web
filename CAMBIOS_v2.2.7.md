# Parche v2.2.7

- Corrige la detección de campos del formulario de denuncias de Provincia.
- Ya no depende únicamente de `get_by_label()`: soporta etiquetas flotantes de Angular/Material, placeholders, wrappers y atributos de formulario.
- Reintenta durante la carga de la SPA y también revisa frames secundarios.
- Si vuelve a fallar, el error ahora incluye URL, título y texto visible de la página para diagnosticar qué pantalla se abrió realmente.
- No modifica Reportes, Visitas ni el envío de WhatsApp.

Clasificación: **Parche**, porque es una corrección menor de compatibilidad del módulo Denuncias.

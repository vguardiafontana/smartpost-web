# SmartPost Desktop 2.2.0

## Interfaz principal modular
- Nueva pantalla de inicio con módulos independientes.
- **Reportes y Visitas** conserva el flujo existente.
- Nuevo módulo **Denuncias** preparado para sumar futuras funciones sin mezclar pantallas.

## Denuncias
- Carga de múltiples guías/remitos + seller.
- Búsqueda autenticada en Epresis y lectura best-effort de `/guias/filter` y `show/{guia}`.
- Detección del distribuidor/chofer y búsqueda complementaria en Distribuidores.
- Datos faltantes del chofer editables y reutilizables por DNI.
- Relato aleatorio de "circunstancias no determinadas" con múltiples combinaciones de redacción, sin inventar hechos concretos.
- Automatización del formulario `seguridad.gba.gob.ar/#/robo-otros` con pausa para CAPTCHA manual.
- Modo **Probar sin finalizar**: no presenta la denuncia ni envía WhatsApp.
- Tras obtener el PDF oficial: envío sin mensaje a `CONSULTAS / Operación nocturna` y envío por seller con plantilla singular/plural configurable.
- El envío de documentos de WhatsApp ahora admite `.xlsx` y `.pdf` con validación previa.

## Configuración
Nueva pestaña **Denuncias** para cambiar grupo general, hora, URL GBA, ruta de Distribuidores y textos de WhatsApp.

## Nota de validación
La lógica y tests locales pasan en el entorno de desarrollo. La web de Provincia y el endpoint de Distribuidores deben validarse una vez en Windows con sesión real, porque sus selectores/respuestas pueden variar.

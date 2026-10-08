# SmartPost Desktop v2.2.30

Parche para la resolución de direcciones ambiguas en Denuncias GBA.

- Localiza la advertencia real `mat-error` de múltiples opciones.
- Selecciona el primer enlace de dirección visible que aparece debajo de la advertencia, reproduciendo el click manual.
- La detección de la ventana de verificación ahora se limita a diálogos/overlays realmente visibles, evitando falsos positivos por texto residual del formulario.
- Si el usuario resuelve manualmente la dirección mientras SmartPost espera, el flujo continúa en vez de terminar en error.

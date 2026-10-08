# SmartPost v2.9.3 — Memoria de visitas Web y tabla de guías

## Problema confirmado

El usuario confirmó que Windows funciona y aportó el registro de Render: «Ran out of memory (used over 512MB) while running your code», después de varios minutos consultando. El reinicio de la instancia explica el HTTP 502 observado durante el seguimiento.

## Corrección en Web

- Un motor de consulta exclusivo para Web procesa páginas de 50 guías, sin conservar el export crudo completo en memoria.
- Cada respuesta de la API se libera después de leer su JSON, incluso cuando falla. Playwright conserva esos cuerpos hasta llamar a dispose o cerrar el contexto: https://playwright.dev/python/docs/api/class-apiresponse#api-response-dispose
- Bloqueo de descargas de imágenes, video/audio y fuentes: la detección utiliza los elementos y enlaces de la foto, sin descargar sus píxeles. HTML, scripts, estilos y datos JSON permanecen disponibles.
- Navegador temporal y secuencial; cada 25 guías se cierra el navegador completo antes de abrir el siguiente, conservando cookies y almacenamiento de la sesión en memoria. No se acumulan navegadores paralelos.
- Como máximo se conservan dos consultas en memoria, en lugar de veinte. Los resultados siguen siendo temporales y no sobreviven a un reinicio del servidor.
- Seguimiento Web con reintentos limitados ante 502/503/504 transitorios. Si el servidor perdió la consulta, se informa que hay que iniciarla nuevamente.
- Los registros de Render indican cada renovación de navegador y el avance por páginas.

La función de Windows y sus reglas de detección de fotos no se modifican. Web usa el mismo lector de datos y clasificación, con un ciclo de recursos independiente.

## Tabla Web

Visitas muestra este orden, igual que Windows: Nro Guía, Guía Agente, Remito, Cliente, Servicio, Destinatario, Domicilio, Localidad, Provincia, Código postal, Teléfono, Foto, Estado y Distribuidor. Los campos vacíos muestran «—».

Desplazamiento horizontal, primera columna fija, botón para abrir la guía y copia de filas separadas por tabulaciones. Se muestran 100 filas por página y se puede avanzar hasta el final del resultado. «Copiar guías» incluye todo el filtro seleccionado, no solamente la página visible. Búsqueda de guías utiliza la misma tabla y conserva también DNI y teléfono del distribuidor.

## Pruebas

119 pruebas locales aprobadas. Incluyen filtros existentes, Windows, tabla móvil con las 14 columnas del ejemplo, copia exacta por tabulaciones, paginación, escape de HTML y reconexión ante un 502 simulado.

La prueba prolongada procesó 60 guías contra un servidor local simulado: 30 con foto y 30 sin foto, tres navegadores sucesivos cerrados correctamente y ninguna descarga de imágenes. No se usaron credenciales ni se consultó Epresis real.

No se midió el pico real de RAM en Render ni se desplegó desde esta tarea. La validación final es repetir la consulta real después de desplegar y revisar que no aparezca otro evento de falta de memoria. Esta prueba local no garantiza un consumo máximo de 512 MB para cualquier contenido de Epresis.

## Actualización de la página

Aplicar el parche sobre la versión 2.9.2, respetando las carpetas, subir los cambios al repositorio conectado a Render y desplegar el último commit del servicio smartpost-web. No hay nuevas dependencias ni variables de entorno. El caché Web pasa a v7; cerrar todas las pestañas de la PWA y volver a abrir después del despliegue.

No es necesario recompilar Windows para esta corrección, porque sus archivos no cambian.

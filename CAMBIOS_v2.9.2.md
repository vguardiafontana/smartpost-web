# SmartPost v2.9.2 — Visitas sin foto

Nuevo módulo independiente disponible en Web y Windows.

- Pedidos de hoy según la fecha de ingreso a planta, como el filtro de VISITAS existente. El día se calcula en UTC-3 (Uruguay), aunque Render use UTC.
- Estados incluidos: primera visita (127), segunda visita (119), tercera visita (183) y reprogramación (117).
- Selector «Visitas con foto»: Sí muestra las guías con foto; No muestra las guías sin foto. Por defecto se selecciona No.
- La consulta recorre todas las páginas de Epresis. Alternar el selector filtra los resultados ya consultados; para actualizar las fotos, volver a consultar.
- Se consultan los campos de foto del resultado y, si no muestran una foto, la ficha de la guía. Se excluyen botones de carga vacíos e imágenes decorativas reconocibles.
- Las fichas que no puedan leerse se muestran aparte como «Sin verificar», nunca como «No».
- La consulta Web corre en segundo plano y usa el mismo bloqueo de Epresis que los demás módulos. Puede recuperarse al volver al módulo mientras el proceso del servidor continúe activo. Los resultados de esta consulta se guardan en memoria, hasta 20 consultas y con purga a las 24 horas al iniciar otra; si el servidor reinicia, hay que consultar nuevamente.
- Se conserva el acceso por PIN. No se modifican las funciones de cambio de estado, reportes ni WhatsApp.

## Instalación

Cerrar SmartPost antes de aplicar archivos. El ZIP de actualización contiene únicamente archivos nuevos o modificados: extraer su contenido sobre la raíz del proyecto SMARTPOST, conservando las carpetas.

Web: subir los archivos del parche al repositorio usado por Render y realizar el despliegue habitual. No hay nuevas variables de entorno ni dependencias de aplicación. Cerrar y reabrir la PWA después de que finalice el despliegue; se actualizó la versión del caché.

Windows desde código fuente: iniciar como siempre con ABRIR_SMARTPOST.bat. Si se usa un SmartPost.exe compilado, hay que recompilarlo con el proceso de packaging existente: este ZIP no contiene un ejecutable nuevo.

## Verificación

Pruebas automatizadas locales de filtros, paginación, manejo de errores, zona horaria, acceso por PIN, selector de Windows y navegador móvil con datos ficticios. No se consultó Epresis ni se desplegó en Render durante la preparación. La detección debe confirmarse con guías reales con/sin foto; no se dispone de una captura real del HTML de las fotos en esta tarea.

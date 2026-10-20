# SmartPost Web v2.9.5

Actualización del 19/10/2026 sobre el commit b8fe22c.

- Fecha de planilla y cambio seleccionable. El día predeterminado usa America/Montevideo y se conserva en la vista previa, ejecución, reintentos y auditoría, incluso al cruzar medianoche.
- Resolución de identificadores en paralelo con máximo tres consultas activas, orden estable y errores individuales. Reutilización de lecturas de guías y perfiles dentro de cada operación.
- Búsquedas sin descargar el padrón de distribuidores cuando la ficha tiene el teléfono. En Linux se evita la exportación que requiere Excel COM y se conservan los fallbacks de ficha/API.
- Menos lecturas repetidas de progreso, escrituras de avance limitadas y almacenamiento fuera del hilo que atiende peticiones.
- Lectura de XLSX con menos objetos intermedios. Se declara Pillow para conservar el logo de los reportes.
- Caché PWA actualizado a smartpost-shell-v295. Cerrar y reabrir todas las ventanas de SmartPost para activar la nueva versión.

No cambia las variables privadas, el acceso por PIN, el esquema de almacenamiento ni los módulos de escritorio. No incorpora WhatsApp o Denuncias a la web.

Validación local sobre el repositorio: 136 pruebas aprobadas en la batería inicial y una prueba de integridad de un recurso afectada por la conversión automática de saltos de línea de Windows. Restaurados los bytes originales del recurso sin cambiar su contenido versionado, las pruebas de configuración y regresiones web se volvieron a ejecutar correctamente. Se incluyeron pruebas del horario nocturno, día seleccionado en la confirmación, reintentos, consultas acotadas y selector móvil.

No se realizaron cambios de estado reales, exportaciones de Epresis ni envíos de WhatsApp durante las pruebas. La velocidad completa depende también de Epresis, Render y la conexión.

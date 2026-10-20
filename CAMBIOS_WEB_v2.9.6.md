# SmartPost Web v2.9.6 — inicio con un toque

Desde Cambio de estado v2, el botón «Iniciar cambio de estado» envía los números, el estado y la fecha directamente al servidor. Se elimina de la interfaz la vista previa con la segunda confirmación.

El servidor primero guarda el lote y lo incorpora a la cola existente. La búsqueda de guías, resolución de distribuidores, validación de planillas, cambios y verificaciones siguen ejecutándose en el trabajador del servidor, aunque se cierre o bloquee el celular.

La pantalla indica «Lote recibido en el servidor» después de que el lote se guardó. Si la conexión se interrumpe antes de recibir esa respuesta, se conserva el envío pendiente en el navegador y se reintenta al volver a abrir SmartPost. Cada envío tiene un identificador estable: repetirlo devuelve el mismo trabajo, sin volver a encolarlo. Una reutilización del identificador con otro contenido se rechaza.

Se mantienen el PIN, el límite de 250 identificadores, las validaciones de estado y fecha y la fecha elegida en los reintentos. Los endpoints anteriores se conservan para compatibilidad con ventanas que todavía tengan el código anterior. No se modifican las funciones de escritorio ni las credenciales o tablas del servidor.

Validación: **147 pruebas aprobadas**. Incluyen envío directo sin ejecutar la vista previa; persistencia previa a la respuesta; rechazos de entradas inválidas; reintentos simultáneos sin duplicados; errores de almacenamiento; finalización del trabajo sin consultas del celular; fecha nocturna y elegida; navegador móvil que reabre después de perder la respuesta. Se usan datos simulados, sin cambios de estado reales en Epresis.

Después del despliegue, cerrar todas las ventanas de SmartPost y volver a abrir la PWA para activar el caché smartpost-shell-v296.

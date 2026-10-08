# SmartPost: optimización interna v2.9.4

Entrega sobre la copia inspeccionada de Desktop/SMARTPOST, con los cambios v2.9.3 presentes. Esta etiqueta identifica el paquete; no se modificaron rótulos de la interfaz.

## Base y alcance confirmado

Se leyó SMARTPOST_CONTEXT0_MAESTRO.md antes de intervenir. Sus referencias a v2.9.0 y a cantidades históricas de pruebas no se tomaron como descripción vigente. Ningún dato marcado NO CONFIRMADO se usó para reconstruir reglas. La implementación actual confirmó Desktop con Excel COM, Web con openpyxl, trabajos Web en segundo plano y almacenamiento local o PostgreSQL según configuración. La copia actual también tiene Visitas sin foto: se conserva.

Sólo se editaron tres módulos productivos: app/core/config.py, app/procesamiento/io_sources.py y app/reportes/portable_report.py. No cambiaron dependencias, interfaz, PIN, acceso privado, endpoints, autenticación, selectores, acciones, esperas ni frecuencia/concurrencia de pedidos a Presis. Cambio de estado v2 quedó byte por byte intacto. La auditoría de alcance está en docs/performance_v294/scope_audit.json. No se editaron sources/ ni referencias sincronizadas.

## Cambios por etapas

1. El mapeo de encabezados calcula una vez por archivo las posiciones de las 75 columnas. Antes repetía su normalización por cada fila. Conserva columnas duplicadas, filas vacías, orden y valores.
2. El generador Web reutiliza la normalización de estilos dentro del mismo libro. Cada celda recibe una copia independiente. La primera fila normaliza fuente y alineación y las siguientes la copian. Se conserva exactamente la transformación anterior de openpyxl, sin reemplazar el motor.
3. La configuración interpreta una sola vez el contenido idéntico del archivo de valores predeterminados. Sigue leyendo ambos archivos en cada llamada, interpreta siempre la configuración del usuario, copia los valores y conserva validaciones y errores. La caché admite un solo contenido y detecta cambios aunque tengan igual fecha/tamaño. No guarda guías, consultas ni datos de sesiones.

No se agregó concurrencia productiva ni se tocaron las esperas de Excel/Presis. ZIP, persistencia, descarga y VISITAS se midieron, pero no justificaron cambios seguros adicionales.

## Rendimiento

Medianas de cinco repeticiones por versión, en el mismo Windows/Python 3.12.14 y entorno de dependencias. Datos sintéticos iguales: 5.000 filas para CSV/procesamiento y 500 para archivos. Excel COM: tres repeticiones con Excel real, sin caché de reportes. Pruebas secuenciales; no se llamó a producción. Los valores son tiempos internos locales, no tiempos totales de una consulta a Presis.

| Proceso | Antes (s) | Después (s) | Resultado medido |
|---|---:|---:|---|
| Inicio Desktop (ventana local) | 0.404996 | 0.364511 | 10.0% menos; no atribuido como mejora |
| Inicio Web (importación del servidor) | 0.422285 | 0.361215 | 14.5% menos; no atribuido como mejora |
| Lectura de configuración repetida | 0.015081 | 0.010317 | 31.6% menos tiempo |
| Lectura CSV, 5.000 filas | 0.023118 | 0.025663 | Sin mejora; variación de medición |
| Asignación de columnas, 5.000 filas | 0.891355 | 0.028872 | 96.8% menos tiempo |
| Identificación de seller, 5.000 filas | 0.040624 | 0.051048 | Sin mejora; variación de medición |
| Normalización de datos, 5.000 filas | 0.356040 | 0.421381 | Sin mejora; variación de medición |
| Reporte Web, 500 filas | 6.970282 | 0.489949 | 93.0% menos tiempo |
| VISITAS Web, 500 filas | 0.258732 | 0.306479 | Sin mejora; variación de medición |
| ZIP de 20 reportes | 0.064306 | 0.072297 | Sin mejora; variación de medición |
| Almacenamiento local del ZIP | 0.000880 | 0.001033 | Sin mejora; variación de medición |
| Lectura local para descarga | 0.000608 | 0.000785 | Sin mejora; variación de medición |
| Proceso de reporte Desktop COM, 500 filas | 3.303411 | 3.026645 | 8.4% menos en esta muestra; incluye variación de Excel |
| VISITAS Desktop COM, 500 filas | 0.804898 | 0.834443 | Sin mejora |

El arranque Desktop mide importación, construcción de ventana y primer procesamiento de eventos con Qt sin pantalla, omitiendo sólo el diálogo interactivo inicial. Web mide importación del servidor, no despliegue ni primera conexión remota. No se atribuyen sus pequeñas diferencias a una aceleración garantizada: influyen el disco y las cachés del sistema. Los procesos no modificados que resultaron algo más lentos muestran esa variabilidad. No se suman estas medianas para prometer un tiempo total.

Confirmación adicional: tres pares alternados de procesos nuevos para generar el reporte Web dieron aproximadamente 6,88 s antes y 0,40 s después. Pico de memoria del proceso Windows: mediana 53.74 MiB antes y 53.60 MiB después. No aumentó en esta muestra. Esto no mide el navegador, Excel ni el servicio Render completo y no garantiza que cualquier volumen quepa en 512 MB. Datos crudos en memory.json.

## Integridad y pruebas

La suite actualizada terminó con **129 pruebas aprobadas, ninguna omitida**, incluido Chromium local. La base tenía 119 pruebas existentes; se añadieron 10 casos de regresión para mapeo, estilos, configuración fresca/aislada y XLSX de 0, 1, 37 y 210 filas. Los fallos iniciales de ejecución desde una carpeta equivocada se corrigieron ejecutando desde la raíz del proyecto. También se corrigió una expectativa del test: openpyxl normaliza algunos identificadores de estilo aun en el código anterior.

Comparación de salidas con los mismos datos:

- Reporte Web de 500 filas y VISITAS Web de 500 filas: todos los componentes descomprimidos del XLSX coinciden, excluyendo únicamente fecha de creación/modificación. Incluye datos, orden, fórmulas, estilos, logo, tablas y validaciones presentes en el archivo anterior.
- Desktop COM: se compararon reporte y VISITAS de 500 filas. Coinciden datos, fórmulas, resultados calculados, estilos y demás componentes, normalizando fecha, ruta absoluta de salida e identificadores que Excel genera. Excel también varió el orden interno de calcChain; se verificó que contiene las mismas celdas/hojas. Las hojas con fórmulas y valores calculados coinciden sin esa normalización. No se afirma identidad binaria del ZIP ni equivalencia entre los motores Web y Desktop.
- Las pruebas existentes validaron trabajos, acceso, resultados, descargas y Visitas sin foto con servicios simulados. El caso de 60 guías utiliza navegador real y servidor local: no descargó fotos, no superpuso navegadores y devolvió 30 con foto y 30 sin foto.
- Se mantienen las advertencias previas de openpyxl sobre una extensión de validación y de Starlette sobre TestClient. No se alteraron dependencias para silenciarlas. La comparación demuestra que no se añadieron diferencias a los archivos Web anteriores.

## Reglas preservadas y límites externos

Las reglas provienen del código/configuración, no de una reconstrucción del documento: APOLLO conserva month_to_selected (primero del mes hasta día seleccionado), los demás modos configurados se respetan, así como filtros y sellers de sábado. config.default.yaml, core/dates.py, reglas de normalización, validaciones y generadores COM no se modificaron.

Búsqueda de guías, Visitas sin foto y Cambio de estado v2 dependen principalmente del navegador y servicios externos: no se midió su latencia real porque requería producción. No se redujeron timeouts ni esperas, ni se cambiaron sus secuencias. Tampoco se midió red de descarga, PostgreSQL/Neon real, suspensión de Render o un iPhone bloqueado. Se conserva el trabajo Web en segundo plano y su seguimiento/archivos mediante los módulos sin cambios; no se afirma una prueba real con iPhone bloqueado. El almacenamiento/descarga de la tabla es sólo el backend de archivos local, no una medición HTTP o de base remota.

No hubo cambios reales de estado, envíos de WhatsApp ni solicitudes a Presis. La aceleración comprobada corresponde al procesamiento interno. Las demoras externas quedan fuera de esta implementación.

## Reproducibilidad

En docs/performance_v294 se incluyen tiempos individuales, fixture de 500 filas, XLSX comparados y scripts. bench.py genera las 5.000 filas determinísticas y acepta --root, --out y --repeats. bench_com.py utiliza before/visits.csv junto a su script. validate_outputs.py compara los archivos incluidos. Para reproducir antes/después: usar dos copias completas con el mismo entorno, aplicar el ZIP de reversión a una, ejecutar secuencialmente los scripts con --root correspondiente y diferentes carpetas --out. Excel COM necesita Windows y Excel instalado. No usar datos ni endpoints de producción.

Actualización y reversión: ver ACTUALIZAR_Y_VOLVER_v2.9.4.md en la raíz.

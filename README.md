> Versión actual: v3.0.0 — Desktop y Web

## Descargar SmartPost Desktop

[Abrir la página de descarga para Windows](https://github.com/vguardiafontana/smartpost-web/releases/latest). En la sección Assets, seleccionar **SmartPost_Instalador.exe** para empezar la descarga. Abrir la página no descarga archivos automáticamente.

El instalador incluye Python, las bibliotecas y Chromium. En la PC de uso no hace falta instalar dependencias. Los reportes oficiales existentes requieren Microsoft Excel de escritorio. Si el repositorio es privado, iniciar sesión en GitHub con una cuenta que tenga acceso.

Cada cambio de Desktop subido a main genera una compilación, pruebas del ejecutable y de una instalación limpia, y un Release nuevo. El enlace de descarga se conserva entre versiones. Ver `AGENTS.md` y `packaging/README_BUILD.md`.

## v2.6.2

Parche de robustez para Cambio de estado v2: detección del distribuidor desde enlace, campos estructurados y texto visible.

# SmartPost Desktop

SmartPost es una aplicación de escritorio para Windows que ejecuta el flujo completo:

**Epresis → validación de crudos → generación/auditoría de reportes Excel → WhatsApp Web**

La aplicación usa una única fecha operativa elegida desde un calendario. Esa misma fecha se utiliza para la descarga, el nombre del reporte y el mensaje de WhatsApp. APOLLO conserva su regla especial: desde el primer día del mes hasta la fecha seleccionada.

## Uso del usuario final

El usuario recibe únicamente `SmartPost_Instalador.exe`, instala el programa y lo abre desde el Escritorio o menú Inicio. No necesita instalar ni configurar componentes técnicos por separado.

En el primer inicio aparece un asistente que solicita:

- usuario y contraseña de Epresis;
- grupos de WhatsApp de cada seller;
- confirmación de la configuración inicial.

Luego, en la ventana principal:

1. elegir la fecha;
2. elegir `Ejecutar` o `Probar sin enviar`;
3. seguir el progreso Epresis → Reportes → WhatsApp;
4. revisar el resumen por seller.

Los logs también se muestran en vivo dentro de la aplicación. Los logs técnicos persistentes se guardan en `%APPDATA%\SmartPost\runtime\logs`.

## Requisito externo: Microsoft Excel

La PC destino **debe tener Microsoft Excel de escritorio instalado y activado**. El motor de reportes usa automatización COM de Excel real para preservar la plantilla oficial, tablas, fórmulas, formatos y validaciones con la misma fidelidad del flujo actual.

Excel no se puede redistribuir dentro del instalador de SmartPost por razones técnicas y de licencia.

Una alternativa sin Excel (por ejemplo, reescribir la generación con una librería de archivos XLSX o con LibreOffice) es técnicamente posible, pero **no es equivalente**: puede cambiar tablas estructuradas, cálculo, fórmulas, formatos, validaciones y otros detalles que ya fueron críticos en este proyecto. Por eso no se usa en esta versión.

## Datos y configuración

La aplicación instalada es de solo lectura. Todo lo modificable vive en:

`%APPDATA%\SmartPost\`

Incluye configuración, perfiles de Epresis/WhatsApp, base SQLite, logs, temporales e históricos. El usuario modifica la configuración únicamente desde la pantalla `Configuración` de la GUI.

La contraseña de Epresis se guarda con `keyring` en el Administrador de credenciales de Windows.

## Empaquetado

La estrategia elegida es:

- PySide6 para GUI;
- PyInstaller **onedir + windowed** para la aplicación;
- Chromium de Playwright embebido en la distribución;
- Inno Setup para producir un único `SmartPost_Instalador.exe`.

Se eligió `onedir` en vez de `onefile` para PyInstaller porque Chromium agrega cientos de MB: un `onefile` tendría que extraerlos al iniciar, empeorando el tiempo de arranque y aumentando el riesgo de falsos positivos. Para el usuario final no cambia nada: recibe un único instalador `.exe`.

La instalación por defecto es por usuario en `%LOCALAPPDATA%\Programs\SmartPost`, por lo que normalmente no requiere permisos de administrador. Instalar en `Program Files` exigiría elevación de permisos.

## Build del instalador

Ver `packaging/README_BUILD.md`.

## Firma y SmartScreen

Ver `docs/FIRMA_Y_SMARTSCREEN.md`.

## Pruebas antes de distribuir

Ver `docs/PLAN_PRUEBAS_WINDOWS.md`.

## Excel de VISITAS

Desde la versión 2.1, SmartPost también genera un Excel global de visitas usando la misma fecha elegida en la pantalla principal.

La configuración se encuentra en **Configuración → Visitas**. Desde ahí se puede cambiar:

- si la función está habilitada;
- el grupo de WhatsApp;
- el mensaje del adjunto (puede quedar vacío para enviar solo el archivo);
- el nombre del XLSX;
- los IDs y nombres de los estados incluidos.

Por defecto, VISITAS se envía a `CONSULTAS / Operación nocturna` **sin mensaje**.

Si Epresis no devuelve visitas para el día elegido, SmartPost lo muestra como `Sin registros` y continúa normalmente sin generar ni enviar un archivo vacío.

## SmartPost 2.2 - módulos
La pantalla principal ahora separa **Reportes y Visitas** de **Denuncias**. El módulo Denuncias busca datos en Epresis, permite revisar/completar datos reales del chofer, genera una redacción aleatoria de circunstancias no determinadas, completa el formulario de Provincia con CAPTCHA manual y, una vez obtenido el PDF oficial, lo distribuye por WhatsApp según la configuración.

Antes del primer uso real de Denuncias se recomienda **Probar sin finalizar**, porque los selectores de la web externa pueden cambiar.

## Cambio de estado masivo (v2.3.0)
Desde Inicio → **Cambio de estado** se pueden pegar N° de guía, Remito y Guía Agente mezclados. El flujo exige primero **ANALIZAR SIN CAMBIAR** y una confirmación explícita antes de enviar cambios reales a Epresis. Los cambios se procesan uno por uno y los errores individuales no detienen el lote.

## Cambio de estado directo (v2.4.0)

La pestaña **Cambio de estado** ya no requiere un análisis manual previo. Pegá los identificadores, elegí el estado y tocá **CAMBIAR ESTADO**. La resolución, deduplicación y validación se realizan internamente antes de cada lote.

## Archivar / desarchivar chats (v2.4.0)

En el menú principal hay un botón pequeño **Archivar / desarchivar**. Si hay chats archivados, SmartPost los desarchiva todos. Si no los hay, abre la lista de WhatsApp configurada como `Smart Post` y archiva todos sus chats.


## Parche v2.4.1

El botón Archivar / desarchivar ahora revisa si Archivados tiene chats. Si está vacío, archiva la lista Smart Post; si contiene chats, los desarchiva. El horario 17-19 / 22-01 queda solo como fallback ante cambios de interfaz de WhatsApp Web.


## Parche v2.4.2

Mejora la apertura de la lista de WhatsApp `Smart Post`: la usa directamente si está visible o abre `Más listas` mediante la flecha de WhatsApp y la busca allí.


## Parche v2.4.3
Corrige el botón **Más listas** de WhatsApp Web y valida que el desplegable se abra antes de buscar la lista `Smart Post`.

## Búsqueda de guías (v2.5.0)

La pantalla principal incluye **Búsqueda de guías** para pegar múltiples números de guía, remitos o Guías Agente. La consulta es sólo lectura y muestra los datos operativos del envío y del distribuidor, con acceso directo al detalle de Epresis en Chrome.

- v2.5.7: enlace directo a ficha de distribuidor y teléfono por ID real.
- v2.5.8: reintentos robustos de WhatsApp, segunda pasada de pendientes y cierre parcial sin reenviar éxitos.

## Parche v2.5.11

El desarchivado de WhatsApp agrega un fallback más estable: si no puede operar el menú de una fila archivada, abre el chat y usa el menú del encabezado para elegir **Desarchivar chat**. El archivado no cambia.


## Parche v2.5.12

Cuando la fecha elegida para Reportes cae en sábado, SmartPost limita los sellers a ZETABURGOS, GIANGIU, G-COMMERCE, PINTURERIAS MM / TIMARO, TECNONUBEL, CLASS y PINTURERIA MILCOLORES. VISITAS queda fuera de esta regla y sigue ejecutándose normalmente.

## Actualización v2.6.0

Se agregó **Cambio de estado v2**, separado del flujo anterior. El nuevo módulo usa **Rendición de Chofer**: identifica el distribuidor de cada guía, busca su planilla del día, valida que cada retiro pertenezca a esa planilla, agrupa por planilla y confirma el estado en lote. Si un chofer tiene varias planillas, revisa desde la más nueva hasta encontrar la correcta. La fecha/hora de recepción se toma de la PC y el flujo v1 permanece disponible.


## Parche v2.6.1

Corrige la consulta de planillas de Cambio de estado v2 enviando `sort=id` a `recorridos/list-route-json`, requisito del backend de Epresis para ordenar los recorridos.

## Parche v2.6.5

Cambio de estado v2 reutiliza automáticamente una rendición de chofer ya abierta. Si Epresis rechaza `habilitarNroRendicion` porque existe una abierta, SmartPost recupera el número desde el encabezado de la pantalla y continúa.


## v2.6.6
Cambio de estado v2 separa los cambios realizados de los pedidos que ya tenían el estado seleccionado.

## v2.6.7 — Base cloud de Cambio de estado v2
La autenticación de Epresis ahora admite secretos por variables de entorno para una futura ejecución en servidor Linux, manteniendo el keyring de Windows como fallback sin modificar el funcionamiento del escritorio.

## v2.7.0 — SmartPost Web (Etapa 2)
Se agregó una interfaz web/PWA privada para ejecutar Cambio de estado v2 desde un servidor Linux. La app de escritorio no cambia. El navegador hace una vista previa, confirma el lote y luego consulta un trabajo que continúa en segundo plano aunque el teléfono se bloquee. El acceso usa Tailscale + PIN. Ver `deploy/SMARTPOST_WEB_UBUNTU.md`.

## Web cloud (v2.7.1)
Para Render Free usar `Dockerfile`/`render.yaml` y configurar `DATABASE_URL` con Neon. La app de escritorio sigue funcionando sin esas variables.

## Web: Reportes y Visitas (v2.9.0)

La web permite generar Reportes y VISITAS por fecha, descargar cada XLSX o un ZIP conjunto y copiar manualmente el mensaje de cada cliente. No envía nada por WhatsApp. En Render/Linux usa un generador XLSX portable sobre el mismo template; el desktop conserva Microsoft Excel/COM sin cambios. Los artefactos web se persisten en PostgreSQL/Neon cuando `DATABASE_URL` está configurado.


## Búsqueda de guías: columna Foto (v2.9.1)
- Agrega `Foto` = `Sí`/`No` a los resultados de Búsqueda de guías.
- La búsqueda conserva el orden original mientras no se toque el control Foto.
- En web, tocar `Foto` agrupa primero `Sí` y al volver a tocar agrupa primero `No`; los errores quedan al final.
- En desktop se agrega la columna Foto a la tabla existente.

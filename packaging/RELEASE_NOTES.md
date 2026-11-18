SmartPost Desktop — corrección del reporte SAMEDAY en ruta

- Se descarga el reporte de hoy en estado en ruta con todos los servicios y luego se filtra por la columna Servicio del archivo, evitando depender del selector de Epresis.
- Si no hay registros SAMEDAY, no se genera ni envía un archivo vacío.

SmartPost Desktop — actualización de reportes

- Al iniciar Reportes y Visitas a cualquier hora, genera un Excel adicional de los envíos SAMEDAY del día en estado EN RUTA PARA SU ENTREGA y lo envía al grupo configurado para VISITAS.
- Se mantiene el reporte de Visitas habitual. La web incorpora el archivo adicional en la descarga individual y en el ZIP; su envío es manual.

SmartPost Desktop 3.0.1

- Se recupera Cambio de estado v2 en el inicio y en la navegación lateral del escritorio, con Rendición de Chofer y fecha seleccionable. Sólo se mantiene fuera el Cambio de estado normal/v1.
- Ver mensajes muestra los mensajes por seller de la última denuncia finalizada, listos para copiar. Los mensajes de esa denuncia siguen disponibles si falla después el envío de WhatsApp.
- Ver denuncias descargadas abre directamente la carpeta con todos los PDF en el Explorador de Windows.
- Se eliminan los archivos CAMBIOS_*.md antiguos del repositorio.
- Instalador con empaquetado más rápido; conserva Python, bibliotecas, Chromium, tipografía y el icono de SmartPost. Abre sin consola.

Descargá SmartPost_Instalador.exe en Assets y ejecutalo sobre tu instalación actual. No necesitás desinstalar ni instalar requisitos. La configuración y los perfiles de sesión se conservan para el mismo usuario de Windows. Para reportes oficiales se necesita Microsoft Excel de escritorio.

Página pública de descarga, sin iniciar sesión ni descarga automática al abrirla:
https://github.com/vguardiafontana/smartpost-web/releases/latest

El instalador y una instalación limpia se prueban antes de publicar.
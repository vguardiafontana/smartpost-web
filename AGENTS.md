# SmartPost — entrega de Desktop

- Cada cambio en Desktop que se suba a GitHub debe producir un Release con `SmartPost_Instalador.exe` completo, listo para instalar sin Python, pip ni descargas de dependencias en la PC del usuario.
- Mantener `.github/workflows/build-installer.yml`: los cambios de Desktop en main disparan las pruebas, empaquetado, instalación de prueba y publicación. La revisión final incluye verificar el Release y su instalador descargable, no sólo subir el código o un ZIP de fuentes.
- Compartir `https://github.com/vguardiafontana/smartpost-web/releases/latest` como página fija de descarga. Abrirla no debe iniciar una descarga; el usuario selecciona `SmartPost_Instalador.exe`. Conservar el nombre del instalador y su enlace directo como destino del botón, no como página de entrada.
- El número de compilación de GitHub se agrega a la versión base de `packaging/SmartPost.iss`, para que cada compilación tenga versión y etiqueta propias. Actualizar las notas del Release con los cambios reales.
- Incluir las dependencias y Chromium dentro del instalador. No incluir credenciales, sesiones ni datos del usuario. Excel de escritorio sigue siendo una dependencia externa para los reportes oficiales existentes.
- Mantener separados los cambios funcionales de Web y Desktop. No reemplazar archivos web con una copia anterior de Desktop.
- Usar el contexto maestro del proyecto cuando esté disponible; conservar la lógica de negocio y ejecutar las pruebas pertinentes.
- Desktop no ofrece Cambio de estado v1 ni v2 en su interfaz; Cambio de estado v2 sigue en Web. Mantener los servicios compartidos necesarios para Web.
- Mantener la interfaz oscura/violeta, el inicio sin consola y el icono de SmartPost en el ejecutable, accesos directos y barra de tareas.
- Visitas sin foto requiere al menos una evidencia por número de visita (segunda: dos fotos; tercera: tres). No dar por completa una visita por una foto anterior ni convertir fallos de consulta en ausencia de foto.
- Archivar/desarchivar es un botón automático: usar el recorrido actual de Archivados, confirmar su vaciado antes de cambiar a archivar y conservar la dirección al recuperarse de una interrupción.

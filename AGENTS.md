# SmartPost — entrega de Desktop

- Cada cambio en Desktop que se suba a GitHub debe producir un Release con `SmartPost_Instalador.exe` completo, listo para instalar sin Python, pip ni descargas de dependencias en la PC del usuario.
- Mantener `.github/workflows/build-installer.yml`: los cambios de Desktop en main disparan las pruebas, empaquetado, instalación de prueba y publicación. La revisión final incluye verificar el Release y su instalador descargable, no sólo subir el código o un ZIP de fuentes.
- Compartir `https://github.com/vguardiafontana/smartpost-web/releases/latest` como página fija de descarga. Abrirla no debe iniciar una descarga; el usuario selecciona `SmartPost_Instalador.exe`. Conservar el nombre del instalador y su enlace directo como destino del botón, no como página de entrada.
- El número de compilación de GitHub se agrega a la versión base de `packaging/SmartPost.iss`, para que cada compilación tenga versión y etiqueta propias. Actualizar las notas del Release con los cambios reales.
- Incluir las dependencias y Chromium dentro del instalador. No incluir credenciales, sesiones ni datos del usuario. Excel de escritorio sigue siendo una dependencia externa para los reportes oficiales existentes.
- Mantener separados los cambios funcionales de Web y Desktop. No reemplazar archivos web con una copia anterior de Desktop.
- Usar el contexto maestro del proyecto cuando esté disponible; conservar la lógica de negocio y ejecutar las pruebas pertinentes.

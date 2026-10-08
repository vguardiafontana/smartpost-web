# SmartPost Desktop v2.2.9 — Parche de compilación

- Cierra una instancia de SmartPost antes de limpiar `dist\SmartPost`, evitando bloqueos de DLL/PYD (`WinError 5`).
- Reintenta la limpieza de `build\SmartPost` y `dist\SmartPost` con un mensaje claro si otro proceso mantiene archivos abiertos.
- Verifica que `playwright\driver\node.exe` exista en el entorno de build antes de ejecutar PyInstaller.
- Detiene el script inmediatamente si PyInstaller devuelve un código de error; ya no continúa con comprobaciones sobre un build incompleto.
- Verifica de nuevo `node.exe` dentro del paquete final antes de crear el instalador.
- Mantiene compatibilidad con Inno Setup 6 y 7.

# Firma, antivirus y SmartScreen

## Recomendación principal

Para distribución habitual, firmar `SmartPost.exe` y `SmartPost_Instalador.exe` con un certificado de firma de código de una autoridad de certificación reconocida. Una firma válida mejora la reputación de SmartScreen con el tiempo y permite comprobar que el binario no fue modificado.

Un certificado self-signed puede servir en una red interna si el certificado raíz se instala como confiable en las PCs de la organización, pero no elimina las advertencias de SmartScreen en equipos externos que no confían en esa raíz.

## Medidas aplicadas para reducir falsos positivos

- PyInstaller `onedir` en lugar de un enorme `onefile` autoextraíble.
- `UPX` desactivado.
- Sin ofuscadores, packers ni inyección de procesos.
- Dependencias estándar y declaradas.
- Chromium se instala como archivo normal dentro de la carpeta del programa; no se descarga ni se desempaqueta silenciosamente en cada inicio.
- Inno Setup estándar como instalador.
- Firma opcional integrada al script de build mediante `signtool.exe`.

Nada de esto garantiza cero falsos positivos: la reputación del certificado/binario y las políticas de cada antivirus siguen influyendo.

## Si no se firma con certificado público

Instrucción corta para un usuario que confía en el origen del instalador:

**Windows protegió su PC → Más información → Ejecutar de todas formas.**

Solo debe hacerse si el archivo proviene del canal interno/esperado y coincide con la versión publicada por la organización.

En PCs corporativas donde esa opción esté bloqueada por política, el área de IT deberá permitir el instalador o desplegar el certificado/aplicación mediante sus herramientas de administración.

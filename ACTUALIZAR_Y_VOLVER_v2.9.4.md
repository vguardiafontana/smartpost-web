# Actualizar SmartPost y volver a la versión anterior

Esta entrega optimiza el código fuente existente. No incluye un ejecutable nuevo ni cambia dependencias. Conservá tus datos y credenciales privados.

## Actualización con parche

1. Cerrá SmartPost y esperá a que no queden trabajos en curso. Detené el servidor local si lo tenés abierto.
2. Guardá una copia de tu carpeta SMARTPOST. Guardá también tus datos de usuario si vas a cambiar de equipo: normalmente están en `%APPDATA%\SmartPost`, o en la ubicación que hayas configurado mediante SMARTPOST_DATA_DIR.
3. Extraé `SmartPost_PARCHE_v2.9.4.zip` sobre la raíz de SMARTPOST, donde están `desktop.py` y `web_server.py`. Aceptá reemplazar los archivos indicados. No borres la carpeta ni extraigas el parche dentro de otra subcarpeta.
4. Abrí Desktop con `ABRIR_SMARTPOST.bat` como siempre. Si usás un ejecutable empaquetado, copiar código fuente no actualiza ese ejecutable: reconstruí con el procedimiento existente de `packaging/build_windows.ps1` y conservá el ejecutable anterior para poder volver atrás.

El parche modifica solamente tres archivos del programa: `app/core/config.py`, `app/procesamiento/io_sources.py` y `app/reportes/portable_report.py`. El resto agregado son pruebas, documentación y evidencia local. No reemplaza tu configuración de usuario ni tu base de datos.

## Proyecto completo

`SmartPost_COMPLETO_v2.9.4.zip` contiene todo el código y recursos del proyecto. Extraelo en una carpeta nueva. No incluye entornos Python, sesiones, datos de usuario ni ejecutables compilados. Utilizá el mismo procedimiento de instalación y ejecución del README; no se cambiaron requisitos. El parche es la opción más simple para una instalación existente.

## Web alojada en Render/GitHub

Estos ZIP no publican cambios automáticamente. En el repositorio conectado a tu servicio, actualizá los tres archivos productivos conservando sus carpetas. Podés hacerlo con GitHub Desktop: abrí la carpeta del repositorio, copiá los archivos, revisá los cambios, hacé un commit y luego Push origin a la rama que usa Render. Si usás GitHub desde el navegador, cargá cada archivo en su carpeta correspondiente.

No subas config.yaml de usuario, claves, sesiones, bases de datos ni entornos virtuales. Dockerfile, render.yaml y los archivos de dependencias no cambiaron. Esperá a que Render termine el despliegue y revisá sus registros. Si tu servicio no despliega automáticamente, usá su despliegue manual. Conservá el PIN y las variables privadas actuales.

La entrega no incluye una prueba contra Presis en producción ni confirma un despliegue remoto. El informe distingue las mediciones locales de lo que falta comprobar en el servidor.

## Volver atrás

1. Cerrá Desktop y detené trabajos/servidor antes de reemplazar archivos.
2. Extraé `SmartPost_REVERTIR_v2.9.4.zip` sobre la misma raíz, aceptando reemplazar los tres módulos. Ese ZIP contiene las copias exactas anteriores a esta optimización.
3. Reiniciá. Los documentos y pruebas nuevos pueden quedar: no intervienen en el funcionamiento. No hay migración de base ni cambios de configuración que deshacer.
4. Para Web, revertí el commit de esta actualización en el repositorio y volvé a desplegar; conservá las variables de entorno. Para un ejecutable, restaurá el ejecutable anterior o reconstruí desde el código revertido.

El ZIP de reversión corresponde a la copia usada en esta entrega. Si ya modificaste esos módulos después, guardá una copia antes de reemplazarlos.

# SmartPost Desktop v2.9.7 — Desarchivar todos

Actualización del 20/10/2026 sobre Desktop v2.9.5. El cambio corresponde a la app de escritorio.

El botón Desarchivar entra directamente a Archivados y opera cada chat desde su propia fila. No utiliza listas de empresa, horarios ni el menú de la conversación. Repite hasta vaciar Archivados, incluyendo chats que aparecen al desplazarse o se cargan después. Se elimina el corte anterior en 250 chats.

Cada chat se cuenta sólo después de comprobar que salió de la lista. Se reintenta una vez si el control falla y se detiene con un error si no puede confirmar el resultado. Una lista que sigue cargando o con filas desconocidas no se presenta como vacía.

Se agrupan las lecturas del navegador. En una lista simulada de 40 chats, la lectura pasó de 122 consultas a 2; la mediana medida pasó de 186,68 ms a 3,50 ms. Es una medición de esa etapa, no una garantía del tiempo total en WhatsApp real. El panel identificado se reutiliza mientras continúa visible.

Pasaron **149 pruebas**. Se probaron listas fuera del panel principal, menús de fila, iconos, carga progresiva, desplazamiento previo, clics sin efecto, listas vacías, más de 250 chats y filas desconocidas. Las pruebas no utilizaron la sesión real de WhatsApp.

Los módulos de operación modificados son `app/delivery/chat_archive.py` y el nuevo `app/delivery/unarchive_all.py`. La función Archivar conserva su flujo anterior. Los datos y las sesiones guardadas siguen en sus ubicaciones habituales.

## Uso de la copia actualizada

La corrección se aplica a `C:\Users\valen\Desktop\SMARTPOST`. Cerrá esa app y abrila nuevamente desde `ABRIR_SMARTPOST.bat`; luego tocá Desarchivar chats.

Copiar este parche no modifica un SmartPost.exe instalado por separado. El proyecto completo incluye los fuentes para reconstruir ese ejecutable mediante el procedimiento de packaging. Esta entrega no incluye un instalador nuevo.

## Paquetes y respaldo

`SmartPost_DESKTOP_PARCHE_v2.9.7.zip` contiene los cambios; extraer sobre la raíz del proyecto de escritorio con la app cerrada. `SmartPost_DESKTOP_COMPLETO_v2.9.7.zip` contiene el proyecto completo de escritorio. No usar estos paquetes para reemplazar la web: el despliegue web conserva su versión independiente.

Para revertir, cerrar la app y reponer `app/delivery/chat_archive.py` desde `SmartPost_DESKTOP_REVERTIR_v2.9.7.zip`. El módulo nuevo puede quedar en su carpeta: la versión anterior no lo importa. El respaldo no incluye ni reemplaza datos privados.

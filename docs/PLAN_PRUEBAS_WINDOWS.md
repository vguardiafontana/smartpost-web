# Plan obligatorio de validación en Windows limpio

Estas pruebas deben ejecutarse sobre el **instalador final compilado en Windows** antes de distribuirlo.

## PC de prueba

- Windows 10 u 11 x64 limpio.
- Sin Python instalado.
- Sin Playwright instalado.
- Sin Chrome requerido para SmartPost.
- Microsoft Excel de escritorio instalado, activado y capaz de abrir un `.xlsx`.
- Acceso de red a Epresis y WhatsApp Web.

## Casos

1. Instalar `SmartPost_Instalador.exe` con usuario estándar y confirmar que no pide herramientas adicionales.
2. Confirmar accesos directos de Escritorio e Inicio y entrada de desinstalación en Aplicaciones instaladas.
3. Primer inicio: completar el wizard, cerrar y volver a abrir; confirmar persistencia de configuración.
4. Vincular WhatsApp desde la GUI; verificar que Chromium empaquetado abre el QR sin Chrome instalado.
5. Cerrar/reabrir SmartPost y verificar que la sesión de WhatsApp persiste.
6. Ejecutar `Probar sin enviar` con una fecha conocida; verificar descarga, generación de todos los reportes y preparación de mensajes sin envío.
7. Comparar al menos un reporte generado con el reporte de referencia normal: estructura, fórmulas, tipos, fechas, `ReporteTable`, formato y datos largos.
8. Ejecutar flujo real con una fecha controlada y confirmar mensaje: `Buenas noches, adjunto el reporte del día DD/MM.`
9. Probar seller sin guías (por ejemplo CLASS cuando corresponda) y confirmar que no queda bloqueado esperando export.
10. Probar APOLLO y confirmar rango `01/MM/YYYY - DD/MM/YYYY`.
11. Desconectar Internet durante descarga y verificar error amigable + detalle técnico.
12. Probar credenciales Epresis incorrectas y sesión expirada.
13. Probar Excel cerrado/abierto y reiniciar Windows; confirmar generación COM estable.
14. Desinstalar y confirmar que la app desaparece. Los datos de `%APPDATA%\SmartPost` se conservan intencionalmente para no borrar configuración/historial sin permiso.

## Criterio de aprobación

No distribuir hasta completar estas pruebas en una PC distinta de la máquina de desarrollo. La prueba en una PC limpia no puede sustituirse por tests unitarios o por ejecutar el código fuente.

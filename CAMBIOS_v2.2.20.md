# Parche v2.2.20

- Corrige el cierre prematuro durante el CAPTCHA final de Provincia.
- La página permanece abierta hasta 10 minutos mientras el operador completa el CAPTCHA y llega al botón de descarga.
- SmartPost escucha también las descargas hechas manualmente por el operador.
- Cuando aparece el botón/link PDF, intenta descargarlo automáticamente sin cerrar la página antes.
- Se evita repetir el click de finalización mientras el CAPTCHA está activo.
- Nuevo ajuste: `denuncias.final_pdf_timeout_seconds` (600 por defecto).

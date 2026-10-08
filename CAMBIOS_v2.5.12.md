# Parche v2.5.12

- Los lotes de **Reportes** cuya fecha seleccionada cae en sábado procesan únicamente: ZETABURGOS, GIANGIU, G-COMMERCE, PINTURERIAS MM / TIMARO, TECNONUBEL, CLASS y PINTURERIA MILCOLORES.
- La regla usa la fecha elegida en el calendario, no el día actual de la PC.
- **VISITAS no se filtra** por esta regla y conserva su funcionamiento habitual.
- La lista queda declarada en `reportes.saturday_sellers` para que la configuración existente se migre automáticamente sin pisar preferencias del usuario.

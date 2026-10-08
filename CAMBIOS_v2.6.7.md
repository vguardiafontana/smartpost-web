# Parche v2.6.7 — Base para migración web/cloud

- No cambia el flujo ni la interfaz de Cambio de estado v2.
- Agrega una fuente de credenciales portable para el futuro servidor web:
  - `SMARTPOST_EPRESIS_USER`
  - `SMARTPOST_EPRESIS_PASSWORD`
- Si esas variables no existen, Windows sigue usando el keyring actual exactamente como antes.
- No se realizan pruebas contra producción.

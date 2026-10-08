# Parche v2.6.5

Corrige Cambio de estado v2 cuando Epresis ya tiene una rendición de chofer abierta.

- Antes de crear una nueva rendición, SmartPost lee el encabezado de `Generar rendición de chofer` y reutiliza el `Nro de Rendición` activo.
- Si Epresis responde `Existe una rendicion abierta`, SmartPost recarga la pantalla, recupera el número abierto y continúa en lugar de detenerse.
- Se evita crear una segunda rendición innecesaria y se conserva el lote abierto por el usuario.

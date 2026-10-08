# SmartPost v2.2.25 — Parche

- Corrige el modal de verificación de dirección de Provincia.
- Detecta el texto visible **Ignorar y continuar** aunque Angular Material lo renderice dentro de un `span`/`div`.
- Pulsa el ancestro clickeable real y agrega fallback por coordenadas con mouse.
- Verifica que el modal haya desaparecido antes de avanzar a Características del hecho.
- Si el modal no se cierra al primer intento, reintenta en lugar de fallar inmediatamente.
- Si vuelve a fallar, el error incluye las acciones visibles del modal para diagnóstico.

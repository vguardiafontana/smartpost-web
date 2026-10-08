# SmartPost Desktop v2.1.1 — Hotfix VISITAS

Corrige el error `run_pipeline.<locals>.emit() got multiple values for argument 'status'` que podía ocurrir al completar la etapa VISITAS (generada, sin datos o deshabilitada).

La causa era una colisión entre el parámetro `status` del estado visual de la etapa y el campo `status` propio del resultado de VISITAS. El emisor ahora usa `stage_status`, manteniendo ambos valores separados.

# SmartPost v2.6.1 — Parche

- Corrige Cambio de estado v2 al consultar Recorridos.
- `/recorridos/list-route-json` ahora recibe `sort=id` junto con `order=desc`, evitando el HTTP 500 `Unknown column '' in 'order clause'`.
- Mantiene la búsqueda por distribuidor y fecha actual, revisando las planillas de la más nueva a la más antigua hasta encontrar cada retiro.
- No modifica Cambio de estado v1 ni el resto de módulos.

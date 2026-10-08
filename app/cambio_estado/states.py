from __future__ import annotations

# Copiado del selector #estado_id de Epresis /guias/arribo_paquetes.
# Mantener el texto visible para que el operador vea exactamente lo mismo que en Epresis.
STATES: list[tuple[int, str]] = [
    (135, "135 - EN PROCESO DE DEVOLUCION"),
    (136, "136 - DEVUELTO"),
    (127, "1RVT - 1° VISITA"),
    (119, "2DAV - 2° VISITA"),
    (183, "3DAV - 3° VISITA"),
    (123, "ANULADO - ANULADO"),
    (200, "ARMADO - ARMADO"),
    (134, "ARRIBADO - ARRIBADO"),
    (204, "ATD - EN LA PUERTA"),
    (97, "CA - CANCELADO"),
    (48, "DI - DIRECCIÓN INCORRECTA"),
    (201, "LDPOD - ENTREGADO LEJOS DEL DOMICILO"),
    (131, "PDR - PENDIENTE DE RETIRO"),
    (41, "PEND - SOLICITUD CONFIRMADA"),
    (39, "POD - ENTREGADA"),
    (51, "R - RECHAZADO POR DESTINATARIO"),
    (70, "RC - EN RUTA PARA SU ENTREGA"),
    (129, "RECM - RECIBIDO EN CASA MATRIZ"),
    (117, "REPRO - REPROGRAMACIÓN"),
    (196, "SINI - ENVÍO SINIESTRADO"),
    (203, "SSD - SIN STOCK DISPONIBLE"),
    (187, "STOCK RESERVADO - STOCK RESERVADO"),
    (184, "TLG - TELEGESTION"),
    (63, "ZP - ZONA PELIGROSA - DIFICIL ACCESO"),
]

STATE_BY_ID = {state_id: label for state_id, label in STATES}

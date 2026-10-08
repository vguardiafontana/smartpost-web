from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ShipmentLine:
    seller: str
    remito: str
    sale_number: str = ""


_OPENINGS = [
    "Durante el recorrido de distribución correspondiente a la jornada,",
    "Mientras realizaba las entregas asignadas a mi recorrido,",
    "En el transcurso de las tareas de reparto del día,",
    "Encontrándome realizando las entregas correspondientes a mi recorrido,",
    "Durante la jornada de distribución y mientras efectuaba las entregas previstas,",
]

_ARMED_APPROACH = [
    "fui interceptado por una persona que exhibió un arma de fuego y me amenazó",
    "fui abordado por un individuo que, mediante la exhibición de un arma de fuego, me intimidó",
    "una persona se aproximó y, bajo amenaza con un arma de fuego, me obligó a detener la actividad",
    "fui sorprendido por un sujeto que me amenazó mostrando un arma de fuego",
    "fui interceptado por un individuo que me intimidó exhibiendo un arma de fuego para sustraer pertenencias y carga",
]

_THEFT = [
    "y sustrajo distintos paquetes que se encontraban pendientes de entrega",
    "y se llevó varios envíos correspondientes al recorrido que aún estaban pendientes",
    "y sustrajo paquetes de la carga asignada para las entregas del día",
    "y se apoderó de diversos envíos que permanecían pendientes de distribución",
    "y sustrajo varios de los paquetes que formaban parte de la carga del recorrido",
]

_ENDING = [
    "Luego del hecho, la persona se dio a la fuga.",
    "Tras concretar la sustracción, el agresor se retiró del lugar.",
    "Posteriormente, el individuo se dio a la fuga con los elementos sustraídos.",
    "Luego de la amenaza y la sustracción, el autor se alejó del lugar.",
    "Finalizado el hecho, el agresor huyó con los paquetes sustraídos.",
]

_CLOSINGS = [
    "Los envíos siniestrados fueron:",
    "Los paquetes sustraídos fueron identificados como:",
    "Los envíos afectados por el robo fueron:",
    "A continuación se detallan los envíos sustraídos:",
    "Los paquetes involucrados en el hecho fueron:",
]


def _line(item: ShipmentLine) -> str:
    remito = item.remito.strip()
    seller = item.seller.strip()
    return f"{remito} - Seller: {seller}"


def generate_unknown_circumstances(shipments: list[ShipmentLine], rng: random.Random | None = None) -> str:
    """Genera una redacción aleatoria de robo armado.

    Este módulo se usa únicamente para denuncias que el operador confirmó que
    corresponden a hechos con violencia/amenaza armada. La redacción varía,
    pero siempre conserva ese hecho y lista exactamente los remitos/sellers
    suministrados.
    """
    if not shipments:
        raise ValueError("Se necesita al menos un envío para generar el relato")
    rnd = rng or random.SystemRandom()
    body = f"{rnd.choice(_OPENINGS)} {rnd.choice(_ARMED_APPROACH)} {rnd.choice(_THEFT)}. {rnd.choice(_ENDING)}"
    closing = rnd.choice(_CLOSINGS)
    lines = "\n".join(_line(s) for s in shipments)
    return f"{body}\n\n{closing}\n{lines}"

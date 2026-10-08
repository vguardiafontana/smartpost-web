from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Shipment:
    query: str
    guia: str = ""
    seller: str = ""
    remito: str = ""
    sale_number: str = ""
    distributor: str = ""
    address: str = ""
    locality: str = ""
    province: str = ""
    postal_code: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Driver:
    name: str = ""
    surname: str = ""
    dni: str = ""
    birth_date: str = ""  # DD/MM/YYYY
    gender: str = ""  # Masculino/Femenino
    phone_prefix: str = ""
    phone_number: str = ""
    email: str = ""

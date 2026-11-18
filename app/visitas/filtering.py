"""Filtra el reporte global usando exclusivamente la columna Servicio."""
from app.procesamiento.rules import SERVICE_ALIASES, normalize_key, normalize_spaces


def filter_sameday_rows(headers, rows):
    indexes = [i for i, h in enumerate(headers) if normalize_key(h) == normalize_key("Servicio")]
    if len(indexes) != 1:
        raise RuntimeError("El archivo de Epresis no tiene una columna Servicio identificable de forma única.")
    index = indexes[0]
    filtered = []
    for row in rows:
        if len(row) != len(headers):
            raise RuntimeError("El archivo de Epresis contiene una fila con cantidad incorrecta de columnas.")
        value = normalize_spaces(row[index]).upper()
        if SERVICE_ALIASES.get(value, value) == "SAMEDAY":
            filtered.append(row)
    return filtered

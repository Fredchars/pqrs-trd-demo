"""Estados de la solicitud y transiciones permitidas (sección 9 de la especificación)."""
from __future__ import annotations

ESTADOS = {
    "RECIBIDA": "Recibida, en revisión inicial",
    "ASIGNADA": "Asignada a un abogado",
    "EN_TRAMITE": "En estudio por el área jurídica",
    "PENDIENTE_INFO": "Esperando información del ciudadano",
    "EN_REVISION": "Respuesta en revisión y aprobación",
    "APROBADA": "Respuesta aprobada, a punto de enviarse",
    "ENVIADA": "Respuesta enviada al ciudadano",
    "CERRADA": "Caso cerrado",
    "REABIERTA": "Caso reabierto para revisión",
    "ANULADA": "Anulada (duplicado o spam)",
    "TRASLADADA": "Trasladada a la entidad competente",
    "DESISTIDA": "Cerrada por desistimiento (no se aportó la información)",
}

ABIERTOS = {"RECIBIDA", "ASIGNADA", "EN_TRAMITE", "PENDIENTE_INFO", "EN_REVISION", "APROBADA", "REABIERTA"}
FINALES = {"CERRADA", "ANULADA", "TRASLADADA", "DESISTIDA"}

# (origen, destino) -> roles que pueden ejecutar la transición
TRANSICIONES: dict[tuple[str, str], set[str]] = {
    ("RECIBIDA", "ANULADA"): {"radicador", "supervisor", "admin"},
    ("RECIBIDA", "ASIGNADA"): {"sistema", "supervisor", "admin", "radicador"},
    ("ASIGNADA", "EN_TRAMITE"): {"abogado", "supervisor", "sistema"},
    ("ASIGNADA", "TRASLADADA"): {"abogado", "supervisor"},
    # Desviación documentada: también se permite trasladar desde EN_TRAMITE porque el caso
    # pasa a EN_TRAMITE en cuanto el abogado lo abre.
    ("EN_TRAMITE", "TRASLADADA"): {"abogado", "supervisor"},
    ("EN_TRAMITE", "PENDIENTE_INFO"): {"abogado", "supervisor"},
    ("PENDIENTE_INFO", "EN_TRAMITE"): {"ciudadano", "abogado", "supervisor", "sistema"},
    ("PENDIENTE_INFO", "DESISTIDA"): {"sistema", "supervisor"},
    ("EN_TRAMITE", "EN_REVISION"): {"abogado", "supervisor"},
    ("EN_REVISION", "EN_TRAMITE"): {"supervisor", "director", "sistema"},
    ("EN_REVISION", "APROBADA"): {"supervisor", "director", "sistema", "abogado"},
    ("APROBADA", "ENVIADA"): {"abogado", "supervisor", "director", "radicador"},
    ("ENVIADA", "CERRADA"): {"sistema", "abogado", "supervisor", "radicador"},
    ("CERRADA", "REABIERTA"): {"supervisor", "director", "admin"},
    ("REABIERTA", "EN_TRAMITE"): {"abogado", "supervisor", "sistema"},
    # Respuesta parcial: el caso sigue abierto tras enviarla (marca, no estado).
    ("APROBADA", "EN_TRAMITE"): {"sistema"},
}


class TransicionInvalida(Exception):
    pass


def destinos(origen: str) -> list[str]:
    return [d for (o, d) in TRANSICIONES if o == origen]


def puede(origen: str, destino: str, rol: str) -> bool:
    roles = TRANSICIONES.get((origen, destino))
    return bool(roles) and (rol in roles or rol == "admin" and destino != "APROBADA")


def validar(origen: str, destino: str, rol: str) -> None:
    if (origen, destino) not in TRANSICIONES:
        raise TransicionInvalida(f"No se puede pasar de {origen} a {destino}.")
    if not puede(origen, destino, rol):
        raise TransicionInvalida(f"El rol «{rol}» no puede pasar el caso de {origen} a {destino}.")


def explicar(estado: str) -> str:
    return ESTADOS.get(estado, estado)

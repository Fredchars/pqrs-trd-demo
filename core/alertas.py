"""Reglas de alerta por umbral de plazo y matriz de destinatarios (sección 10.3)."""
from __future__ import annotations

from datetime import date

from core.plazos import VACIO, dias_habiles_entre

# tipo -> (roles destinatarios, ¿se repite cada día?)
MATRIZ = {
    "radicada": (["ciudadano"], False),
    "asignada": (["abogado"], False),
    "sin_candidato": (["supervisor"], False),
    "solicitud_info": (["ciudadano"], False),
    "info_aportada": (["ciudadano", "abogado"], False),
    "plazo_50": (["abogado"], False),
    "plazo_80": (["abogado", "supervisor"], False),
    "aprobacion_pendiente": (["aprobador"], True),
    "vence_hoy": (["abogado", "supervisor", "director"], False),
    "vencida": (["abogado", "supervisor", "director"], True),
    "prorroga": (["ciudadano", "supervisor"], False),
    "devuelta": (["abogado"], False),
    "enviada": (["ciudadano", "abogado"], False),
    "rebote": (["abogado", "supervisor"], False),
    "posible_duplicado": (["radicador"], False),
}

TEXTOS = {
    "plazo_50": "Recordatorio: se consumió el 50 % del plazo",
    "plazo_80": "Alerta: se consumió el 80 % del plazo",
    "vence_hoy": "Urgente: el caso vence hoy",
    "vencida": "Caso vencido",
    "aprobacion_pendiente": "Respuesta pendiente de su aprobación hace más de 1 día hábil",
    "asignada": "Nuevo caso asignado",
    "sin_candidato": "Caso sin abogado disponible: asígnelo desde Supervisión",
    "devuelta": "Respuesta devuelta con comentarios",
    "info_aportada": "El ciudadano aportó la información solicitada",
    "prorroga": "Prórroga registrada",
    "rebote": "El correo de respuesta rebotó",
    "posible_duplicado": "Posible duplicado para revisar",
}


def alerta_umbral(radicacion: date, vencimiento: date, hoy: date, umbral_1: float = 50,
                  umbral_2: float = 80, extra=VACIO) -> str | None:
    """Devuelve el tipo de alerta de umbral más alto que corresponde hoy (o None)."""
    if hoy > vencimiento:
        return "vencida"
    if hoy == vencimiento:
        return "vence_hoy"
    total = max(1, dias_habiles_entre(radicacion, vencimiento, extra))
    pct = 100.0 * max(0, dias_habiles_entre(radicacion, hoy, extra)) / total
    if pct >= umbral_2:
        return "plazo_80"
    if pct >= umbral_1:
        return "plazo_50"
    return None


def destinatarios(tipo: str) -> list[str]:
    return MATRIZ.get(tipo, ([], False))[0]


def es_diaria(tipo: str) -> bool:
    return MATRIZ.get(tipo, ([], False))[1]


def clave(tipo: str, solicitud_id: int | None, destinatario: str, hoy: date) -> str:
    """Clave de idempotencia: las alertas diarias se repiten una vez por día."""
    base = f"{tipo}|{solicitud_id}|{destinatario}"
    return f"{base}|{hoy.isoformat()}" if es_diaria(tipo) else base

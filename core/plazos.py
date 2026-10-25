"""Días hábiles, vencimientos, suspensiones, prórrogas y semáforo (Colombia).

Validar los criterios jurídicos con el área legal antes de cualquier uso real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import holidays

FESTIVOS_CO = holidays.country_holidays("CO", years=range(2024, 2033))
VACIO: frozenset[date] = frozenset()


def es_habil(d: date, extra=VACIO) -> bool:
    return d.weekday() < 5 and d not in FESTIVOS_CO and d not in extra


def siguiente_habil(d: date, extra=VACIO) -> date:
    d += timedelta(days=1)
    while not es_habil(d, extra):
        d += timedelta(days=1)
    return d


def fecha_radicacion(recibido: datetime, hora_corte: time = time(17, 0), extra=VACIO) -> date:
    """Fuera de horario o en día no hábil se entiende radicada el siguiente día hábil."""
    d = recibido.date()
    if not es_habil(d, extra) or recibido.time() > hora_corte:
        d = siguiente_habil(d, extra)
    return d


def sumar_habiles(desde: date, dias: int, extra=VACIO) -> date:
    """El término se cuenta a partir del día hábil siguiente a `desde`."""
    d = desde
    for _ in range(dias):
        d = siguiente_habil(d, extra)
    return d


def fecha_vencimiento(radicacion: date, dias_habiles: int, extra=VACIO) -> date:
    return sumar_habiles(radicacion, dias_habiles, extra)


def dias_habiles_entre(desde: date, hasta: date, extra=VACIO) -> int:
    """Días hábiles en (desde, hasta]. Negativo si `hasta` es anterior a `desde`."""
    if hasta == desde:
        return 0
    signo = 1
    if hasta < desde:
        desde, hasta, signo = hasta, desde, -1
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if es_habil(d, extra):
            n += 1
    return n * signo


# ---------------- Suspensión (solicitud de información) ----------------

def reanudar_tras_suspension(radicacion: date, vencimiento: date, suspendida_desde: date,
                             aporte: date, dias_habiles_tipo: int, criterio: str = "reiniciar",
                             extra=VACIO) -> tuple[date, int]:
    """Devuelve (nueva_fecha_vencimiento, dias_habiles_suspendidos).

    - 'reiniciar' (por defecto en la especificación): el término completo se cuenta de nuevo
      a partir del día hábil siguiente al aporte.
    - 'reanudar': se conservan los días hábiles que quedaban al suspender y se cuentan desde el
      día siguiente al aporte (Ley 1755, art. 17: "se reactivará el término").
    """
    if not es_habil(aporte, extra):  # aporte en día no hábil: se entiende recibido el siguiente día hábil
        aporte = siguiente_habil(aporte, extra)
    suspendidos = max(0, dias_habiles_entre(suspendida_desde, aporte, extra))
    if criterio == "reanudar":
        restantes = max(0, dias_habiles_entre(suspendida_desde, vencimiento, extra))
        return sumar_habiles(aporte, restantes, extra), suspendidos
    return sumar_habiles(aporte, dias_habiles_tipo, extra), suspendidos


# ---------------- Prórroga ----------------

def max_fecha_prorroga(radicacion: date, dias_habiles_tipo: int, dias_prorroga_max: int | None,
                       extra=VACIO) -> date:
    """Máximo: plazo + prórroga legal del tipo; si no está definida, el doble del plazo inicial."""
    extra_dias = dias_prorroga_max if dias_prorroga_max else dias_habiles_tipo
    return sumar_habiles(radicacion, dias_habiles_tipo + extra_dias, extra)


def validar_prorroga(hoy: date, vencimiento: date, nueva: date, maximo: date) -> str | None:
    """Devuelve un mensaje de error comprensible o None si es válida."""
    if hoy > vencimiento:
        return "La prórroga debe registrarse antes del vencimiento, y este caso ya venció."
    if nueva <= vencimiento:
        return "La nueva fecha debe ser posterior a la fecha de vencimiento actual."
    if nueva > maximo:
        return f"La nueva fecha supera el máximo permitido para este tipo ({maximo:%d/%m/%Y})."
    return None


# ---------------- Semáforo ----------------

@dataclass
class Semaforo:
    nivel: str        # verde | amarillo | rojo | negro | pausa | cerrado
    icono: str
    texto: str
    porcentaje: float  # % del plazo consumido
    restantes: int     # días hábiles restantes (negativo si vencido)

    @property
    def etiqueta(self) -> str:
        return f"{self.icono} {self.texto}"


ESTADOS_CERRADOS = {"ENVIADA", "CERRADA", "ANULADA", "TRASLADADA", "DESISTIDA"}


def semaforo(radicacion: date, vencimiento: date, hoy: date, estado: str = "EN_TRAMITE",
             umbral_amarillo: float = 50, umbral_rojo: float = 80, extra=VACIO) -> Semaforo:
    """Color + ícono + texto (nunca solo color). Umbrales en % del plazo consumido."""
    if estado in ESTADOS_CERRADOS:
        return Semaforo("cerrado", "✔️", "Gestionada", 100.0, 0)
    total = max(1, dias_habiles_entre(radicacion, vencimiento, extra))
    usados = dias_habiles_entre(radicacion, hoy, extra)
    pct = round(100.0 * max(0, usados) / total, 1)
    restantes = dias_habiles_entre(hoy, vencimiento, extra)
    if estado == "PENDIENTE_INFO":
        return Semaforo("pausa", "⏸️", "Plazo suspendido (esperando al ciudadano)", pct, restantes)
    if hoy > vencimiento:
        n = dias_habiles_entre(vencimiento, hoy, extra)
        return Semaforo("negro", "⛔", f"Vencida hace {n} día{'s' if n != 1 else ''} hábil{'es' if n != 1 else ''}", pct, -n)
    if hoy == vencimiento:
        return Semaforo("rojo", "🔴", "Vence hoy", pct, 0)
    txt = f"Vence en {restantes} día{'s' if restantes != 1 else ''} hábil{'es' if restantes != 1 else ''}"
    if pct > umbral_rojo:
        return Semaforo("rojo", "🔴", txt, pct, restantes)
    if pct >= umbral_amarillo:
        return Semaforo("amarillo", "🟡", txt, pct, restantes)
    return Semaforo("verde", "🟢", txt, pct, restantes)

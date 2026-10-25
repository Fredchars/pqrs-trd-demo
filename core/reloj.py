"""Reloj del sistema en hora de Colombia. PQRS_AHORA permite fijar la fecha (pruebas y demos)."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")


def ahora() -> datetime:
    fijo = os.environ.get("PQRS_AHORA")
    if fijo:
        d = datetime.fromisoformat(fijo)
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    return datetime.now(TZ)


def hoy() -> date:
    return ahora().date()


def a_fecha(v) -> date | None:
    if _vacio(v):
        return None
    if isinstance(v, datetime):
        return v.astimezone(TZ).date() if v.tzinfo else v.date()
    if isinstance(v, date):
        return v
    if _vacio(v):
        return None
    s = str(v)
    if len(s) == 10:
        return date.fromisoformat(s)
    return a_fechahora(s).date()


def _vacio(v) -> bool:
    return v is None or v == "" or str(v) in ("nan", "NaT", "None") or (isinstance(v, float) and v != v)


def a_fechahora(v) -> datetime | None:
    if _vacio(v) or str(v) == "NaT":
        return None
    if isinstance(v, datetime):
        return v.astimezone(TZ) if v.tzinfo else v.replace(tzinfo=TZ)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=TZ)
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=TZ)


def fmt_fecha(v) -> str:
    d = a_fecha(v)
    return d.strftime("%d/%m/%Y") if d else "—"


def fmt_fechahora(v) -> str:
    d = a_fechahora(v)
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"

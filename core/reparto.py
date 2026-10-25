"""Reparto automático de casos (estrategias A, B, C, D y E híbrida)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from core.plazos import VACIO, dias_habiles_entre

ESTRATEGIAS = {
    "A": "Menor carga ponderada",
    "B": "Turno rotativo",
    "C": "Por especialidad (y menor carga)",
    "D": "Manual (cola del supervisor)",
    "E": "Híbrida: especialidad + menor carga; si no hay candidatos, cola del supervisor",
}


@dataclass
class CasoAbierto:
    peso: float
    vencimiento: date


@dataclass
class Abogado:
    id: int
    nombre: str = ""
    disponible: bool = True
    ausente_desde: date | None = None
    ausente_hasta: date | None = None
    capacidad_max: int = 40
    especialidades: list[str] = field(default_factory=list)
    casos: list[CasoAbierto] = field(default_factory=list)
    asignados_hoy: int = 0
    ultima_asignacion: datetime | None = None

    def ausente(self, hoy: date) -> bool:
        if self.ausente_desde and self.ausente_hasta:
            return self.ausente_desde <= hoy <= self.ausente_hasta
        if self.ausente_desde and not self.ausente_hasta:
            return self.ausente_desde <= hoy
        return False

    def puede_recibir(self, hoy: date) -> bool:
        return self.disponible and not self.ausente(hoy) and self.tiene_cupo()

    def tiene_cupo(self) -> bool:
        """Tope de casos abiertos del abogado (configurable por abogado; 0 = no recibe casos nuevos)."""
        return len(self.casos) < int(self.capacidad_max or 0)


def carga_ponderada(casos: list[CasoAbierto], hoy: date, extra=VACIO) -> float:
    total = 0.0
    for c in casos:
        restantes = dias_habiles_entre(hoy, c.vencimiento, extra)
        urgencia = 2.0 if restantes <= 2 else 1.0  # los casos por vencer pesan más
        total += c.peso * urgencia
    return total


def _clave_carga(a: Abogado, hoy: date, extra):
    ua = a.ultima_asignacion.timestamp() if a.ultima_asignacion else 0.0
    return (carga_ponderada(a.casos, hoy, extra), a.asignados_hoy, ua, a.id)


def elegir_abogado(candidatos: list[Abogado], hoy: date, estrategia: str = "E",
                   especialidad: str | None = None, extra=VACIO) -> Abogado | None:
    """Devuelve el abogado elegido o None (el caso va a la cola del supervisor)."""
    estrategia = (estrategia or "E").upper()
    if estrategia == "D":
        return None
    disponibles = [a for a in candidatos if a.puede_recibir(hoy)]
    if estrategia in ("C", "E") and especialidad:
        disponibles = [a for a in disponibles if especialidad in (a.especialidades or [])]
    if not disponibles:
        return None
    if estrategia == "B":
        return min(disponibles, key=lambda a: (a.ultima_asignacion.timestamp() if a.ultima_asignacion else 0.0, a.id))
    return min(disponibles, key=lambda a: _clave_carga(a, hoy, extra))


def repartir(casos: list[CasoAbierto], abogados: list[Abogado], hoy: date, estrategia: str = "E",
             especialidad: str | None = None, ahora: datetime | None = None, extra=VACIO) -> list[int | None]:
    """Simula el reparto secuencial de varios casos; devuelve el id elegido para cada uno."""
    from core.reloj import ahora as _ahora
    t = ahora or _ahora()
    res: list[int | None] = []
    for i, c in enumerate(casos):
        a = elegir_abogado(abogados, hoy, estrategia, especialidad, extra)
        res.append(a.id if a else None)
        if a:
            a.casos.append(c)
            a.asignados_hoy += 1
            a.ultima_asignacion = t.replace(microsecond=0) if i == 0 else datetime.fromtimestamp(t.timestamp() + i, t.tzinfo)
    return res

"""Cadena de aprobación configurable (0, 1 o 2 niveles), versiones y diferencias."""
from __future__ import annotations

import difflib
import html

ROL_POR_NIVEL = {1: "supervisor", 2: "director"}


def niveles_requeridos(niveles_tipo: int, tema_sensible: bool = False) -> int:
    """Esquemas A (0), B (1) y C (2). Un tema sensible agrega un nivel (máximo 2)."""
    n = int(niveles_tipo or 0) + (1 if tema_sensible else 0)
    return max(0, min(2, n))


def nivel_pendiente(aprobaciones: list[dict], requeridos: int) -> int | None:
    """Siguiente nivel que debe aprobar la versión, o None si ya está completa."""
    aprobados = {int(a["nivel"]) for a in aprobaciones if a.get("decision") == "aprobada"}
    for n in range(1, requeridos + 1):
        if n not in aprobados:
            return n
    return None


def rol_para_nivel(nivel: int) -> str:
    return ROL_POR_NIVEL.get(nivel, "director")


def diff_html(anterior: str, nueva: str) -> str:
    """Diferencias por palabra: verde lo agregado, rojo tachado lo eliminado."""
    a, b = (anterior or "").split(), (nueva or "").split()
    sm = difflib.SequenceMatcher(a=a, b=b)
    partes = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            partes.append(html.escape(" ".join(a[i1:i2])))
        if op in ("delete", "replace"):
            partes.append(f"<del style='background:#fde2e1;color:#8a1c1c'>{html.escape(' '.join(a[i1:i2]))}</del>")
        if op in ("insert", "replace"):
            partes.append(f"<ins style='background:#dcfce7;color:#14532d;text-decoration:none'>{html.escape(' '.join(b[j1:j2]))}</ins>")
    return " ".join(p for p in partes if p)


def resumen_diff(anterior: str, nueva: str) -> dict:
    a, b = (anterior or "").split(), (nueva or "").split()
    sm = difflib.SequenceMatcher(a=a, b=b)
    ag = sum(j2 - j1 for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("insert", "replace"))
    el = sum(i2 - i1 for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("delete", "replace"))
    return {"agregadas": ag, "eliminadas": el, "similitud": round(sm.ratio() * 100, 1)}

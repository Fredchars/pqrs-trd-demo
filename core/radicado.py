"""Formato del radicado y del código de consulta."""
from __future__ import annotations

import hashlib
import re
import secrets

PATRON = re.compile(r"\b(EMP\d{2})-(\d{4})-([A-Z]{1,3})-(\d{6})\b")
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para evitar confusiones


def formatear(empresa: str, anio: int, tipo: str, consecutivo: int) -> str:
    """{EMPRESA}-{AÑO}-{TIPO}-{CONSECUTIVO}, p. ej. EMP03-2026-R-000123."""
    return f"{empresa.upper()}-{anio:04d}-{tipo.upper()}-{consecutivo:06d}"


def extraer(texto: str | None) -> str | None:
    """Encuentra un radicado dentro de un texto (por ejemplo el asunto de un correo)."""
    m = PATRON.search((texto or "").upper())
    return m.group(0) if m else None


def es_radicado(texto: str) -> bool:
    return bool(PATRON.fullmatch((texto or "").strip().upper()))


def nuevo_codigo(n: int = 8) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(n))


def hash_codigo(radicado: str, codigo: str) -> str:
    return hashlib.sha256(f"{radicado.upper()}|{codigo.strip().upper()}".encode()).hexdigest()


def verificar_codigo(radicado: str, codigo: str, guardado: str | None) -> bool:
    return bool(guardado) and secrets.compare_digest(hash_codigo(radicado, codigo), guardado)

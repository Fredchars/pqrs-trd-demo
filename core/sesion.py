"""Token de sesión firmado (HMAC) para que recargar la página no cierre la sesión.

Streamlit pierde st.session_state al recargar; el token viaja en el parámetro ?s= de la URL, caduca en
PQRS_SESION_HORAS (8 h por defecto) y solo contiene el id del usuario y la expiración (sin datos personales).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from core import config

PARAM = "s"


def _horas() -> float:
    try:
        return float(config.obtener("PQRS_SESION_HORAS") or 8)
    except ValueError:
        return 8.0


def _firma(cuerpo: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(config.secreto_sesion(), cuerpo.encode(), hashlib.sha256).digest()[:18]).decode()


def emitir(usuario_id: int, ahora: float | None = None) -> str:
    exp = int((ahora or time.time()) + _horas() * 3600)
    cuerpo = f"{int(usuario_id)}.{exp}"
    return f"{cuerpo}.{_firma(cuerpo)}"


def validar(token: str | None, ahora: float | None = None) -> int | None:
    """Devuelve el id de usuario si el token es auténtico y vigente; si no, None."""
    try:
        uid, exp, firma = (token or "").split(".")
        cuerpo = f"{int(uid)}.{int(exp)}"
    except ValueError:
        return None
    if not hmac.compare_digest(firma, _firma(cuerpo)):
        return None
    if int(exp) < (ahora or time.time()):
        return None
    return int(uid)

"""Configuración: lee secretos desde variables de entorno (Streamlit copia st.secrets aquí).

Nunca se guardan secretos en el repositorio.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def obtener(clave: str, defecto: str | None = None) -> str | None:
    v = os.environ.get(clave)
    return v if v not in (None, "") else defecto


def backend() -> str:
    """'postgres' (Supabase) si hay DATABASE_URL; si no, 'sqlite' (modo demo)."""
    forzado = (obtener("PQRS_BACKEND") or "").lower()
    if forzado in ("sqlite", "postgres"):
        return forzado
    return "postgres" if obtener("DATABASE_URL") else "sqlite"


def supabase_storage_activo() -> bool:
    return backend() == "postgres" and bool(obtener("SUPABASE_URL")) and bool(obtener("SUPABASE_SERVICE_KEY"))


def supabase_auth_activo() -> bool:
    if (obtener("PQRS_LOGIN_DEMO") or "").lower() in ("1", "true", "si", "sí"):
        return False
    return backend() == "postgres" and bool(obtener("SUPABASE_URL")) and bool(
        obtener("SUPABASE_ANON_KEY") or obtener("SUPABASE_PUBLISHABLE_KEY"))


def login_demo_permitido() -> tuple[bool, str]:
    """El selector de usuarios ficticios solo se ofrece si:
    - hay clave de acceso demo (PQRS_DEMO_CLAVE en secretos): se pide antes de mostrar el selector, o
    - se trabaja en local con SQLite (sin base de datos real).
    Con base de datos real y sin clave demo, el acceso por selector queda cerrado."""
    if obtener("PQRS_DEMO_CLAVE"):
        return True, "clave"
    if backend() == "sqlite":
        return True, "local"
    return False, "cerrado"


def secreto_sesion() -> bytes:
    """Llave HMAC para el token de sesión que sobrevive a la recarga. PQRS_SESION_SECRETO si existe; si no, se
    deriva de un secreto del servidor (nunca se expone); en local, una llave aleatoria guardada en la carpeta de datos."""
    import hashlib
    base = obtener("PQRS_SESION_SECRETO") or obtener("SUPABASE_SERVICE_KEY") or obtener("DATABASE_URL")
    if base:
        return hashlib.sha256(("pqrs-sesion|" + base).encode()).digest()
    f = dir_datos() / ".sesion.key"
    if not f.exists():
        import secrets as _s
        f.write_bytes(_s.token_bytes(32))
    return f.read_bytes()


def correo_real_activo() -> bool:
    """Envío real si hay credenciales (MAIL_USER + MAIL_APP_PASSWORD) y no se fuerza MAIL_MODO = "simulado"."""
    if (obtener("MAIL_MODO") or "").lower() == "simulado":
        return False
    return bool(obtener("MAIL_USER")) and bool(obtener("MAIL_APP_PASSWORD"))


def correo_servidor() -> dict:
    """Servidor de correo configurable por secretos (por defecto Gmail con contraseña de aplicación)."""
    def _int(clave, defecto):
        try:
            return int(obtener(clave) or defecto)
        except ValueError:
            return defecto
    return {"smtp_host": obtener("MAIL_SMTP_HOST", "smtp.gmail.com"), "smtp_port": _int("MAIL_SMTP_PORT", 465),
            "smtp_starttls": (obtener("MAIL_SMTP_STARTTLS") or "").lower() in ("1", "true", "si", "sí"),
            "imap_host": obtener("MAIL_IMAP_HOST", "imap.gmail.com"), "imap_port": _int("MAIL_IMAP_PORT", 993),
            "remitente": obtener("MAIL_FROM") or obtener("MAIL_USER")}


def dir_datos() -> Path:
    d = Path(obtener("PQRS_DATA_DIR") or (RAIZ / ".datos"))
    d.mkdir(parents=True, exist_ok=True)
    return d


URL_PUBLICA = "https://pqrs-beta.streamlit.app"


def app_url() -> str:
    """URL para enlaces en correos y PDF. Orden: APP_URL; si no está, la URL pública cuando se trabaja con
    Supabase o dentro de GitHub Actions; si no, la local (modo demo en el computador)."""
    v = obtener("APP_URL")
    if v:
        return v.rstrip("/")
    if backend() == "postgres" or obtener("GITHUB_ACTIONS") == "true":
        return URL_PUBLICA
    return "http://localhost:8502"

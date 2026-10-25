"""Configuración común: cada módulo de pruebas usa una base nueva (SQLite, o PostgreSQL con PQRS_TEST_PG_URL) con datos ficticios."""
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Las pruebas nunca usan credenciales reales: forzamos modo demo y correo simulado.
for k in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY",
          "MAIL_USER", "MAIL_APP_PASSWORD"):
    os.environ.pop(k, None)
# Las pantallas (AppTest) leen .streamlit/secrets.toml y exportan esos secretos al entorno: eso activaría Supabase Storage
# real en pruebas posteriores. PQRS_IGNORAR_SECRETS hace que app/Inicio.py los retire en cada ejecución.
os.environ["PQRS_IGNORAR_SECRETS"] = "1"
# Con PQRS_TEST_PG_URL (un PostgreSQL local o de CI, NUNCA el de producción) toda la suite corre sobre PostgreSQL:
# cada fixture borra y vuelve a crear el esquema (db/*.sql) con los roles de Supabase simulados.
PG_URL = os.environ.pop("PQRS_TEST_PG_URL", None)
os.environ["PQRS_BACKEND"] = "postgres" if PG_URL else "sqlite"
if PG_URL and not any(h in PG_URL for h in ("@127.0.0.1", "@localhost", "@[::1]")) and not os.environ.get("PQRS_TEST_PG_PERMITIR_REMOTO"):
    raise pytest.UsageError("PQRS_TEST_PG_URL debe apuntar a un PostgreSQL local (las pruebas borran el esquema).")


# PQRS_TEST_PG_ROL_SERVICIO=1: la aplicación (y sus pruebas) se conectan como pqrs_servicio (db/05_rol_servicio.sql).
ROL_SERVICIO = bool(PG_URL and os.environ.get("PQRS_TEST_PG_ROL_SERVICIO"))


CLAVE_PRUEBAS = "solo-pruebas"  # clave desechable de roles creados únicamente en la base de pruebas


def url_rol_servicio(url: str, usuario: str = "pqrs_servicio") -> str:
    """Misma base de pruebas, otro usuario (con clave de prueba: sirve con «trust» y con autenticación por contraseña)."""
    from urllib.parse import urlsplit, urlunsplit
    u = urlsplit(url)
    host = u.netloc.rsplit("@", 1)[-1]
    return urlunsplit((u.scheme, f"{usuario}:{CLAVE_PRUEBAS}@{host}", u.path, u.query, u.fragment))


@pytest.fixture(autouse=True)
def _nunca_servicios_reales():
    """Red de seguridad: ninguna prueba puede tener activo Supabase (base de datos, auth o Storage reales)."""
    from core import almacenamiento, config

    def revisar():
        assert not config.supabase_storage_activo() and not os.environ.get("SUPABASE_URL"), \
            "Supabase real activo durante una prueba: se aborta para no tocar producción"
        assert not isinstance(almacenamiento._ALMACEN, almacenamiento.AlmacenSupabase)
    revisar()
    yield
    revisar()


def _nuevo_repo(tmp: Path):
    os.environ["PQRS_DATA_DIR"] = str(tmp)
    from core import almacenamiento, consultas
    from core.repositorio import Repositorio, fijar_repo
    almacenamiento.fijar_almacen(None)
    if PG_URL:
        import contextlib
        import io
        sys.path.insert(0, str(RAIZ / "scripts"))
        import setup_supabase
        with contextlib.redirect_stdout(io.StringIO()):
            setup_supabase.aplicar_sql(PG_URL, simulado=True, reset=True, rol_servicio=ROL_SERVICIO)
        if ROL_SERVICIO:  # toda la suite con el rol sin BYPASSRLS ni dueño de las tablas, con FORCE RLS (A7)
            import psycopg
            with psycopg.connect(PG_URL, autocommit=True) as cx:
                cx.execute("alter role pqrs_servicio login password 'solo-pruebas'")
            repo = Repositorio("postgres", url_rol_servicio(PG_URL))
        else:
            repo = Repositorio("postgres", PG_URL)
    else:
        repo = Repositorio("sqlite", ruta_sqlite=tmp / "pqrs.sqlite")
        repo.crear_esquema_sqlite()
    fijar_repo(repo)
    consultas.limpiar_cache()
    return repo


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """Base sembrada (~300 PQRS) compartida por las pruebas del módulo."""
    from core import semilla
    r = _nuevo_repo(tmp_path_factory.mktemp("demo"))
    semilla.cargar(r)
    yield r
    from core.repositorio import fijar_repo
    fijar_repo(None)


@pytest.fixture()
def repo_vacio(tmp_path):
    """Base con catálogos y usuarios, pero sin solicitudes."""
    from core import semilla
    r = _nuevo_repo(tmp_path)
    semilla.cargar(r, n=0, subir_archivos=False, alertas=False)
    yield r
    from core.repositorio import fijar_repo
    fijar_repo(None)


def usuario(email):
    from core import consultas as C
    from core.catalogo_demo import DOMINIO
    return C.usuario_por_email(email if "@" in email else f"{email}@{DOMINIO}")

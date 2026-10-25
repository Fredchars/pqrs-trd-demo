"""Token de sesión firmado: sobrevive a la recarga, caduca y no se puede falsificar."""
import time

from streamlit.testing.v1 import AppTest

from conftest import RAIZ, usuario
from core import sesion


def test_token_valido_expirado_y_falsificado():
    t = sesion.emitir(7)
    assert sesion.validar(t) == 7
    assert sesion.validar(t, ahora=time.time() + 9 * 3600) is None
    uid, exp, firma = t.split(".")
    assert sesion.validar(f"8.{exp}.{firma}") is None
    assert sesion.validar("basura") is None and sesion.validar(None) is None


def test_recarga_restaura_sesion(repo):
    # (la app retira PQRS_SESION_SECRETO del entorno por PQRS_IGNORAR_SECRETS: se usa la llave local de la carpeta de datos)
    u = usuario("supervisor.emp01")
    at = AppTest.from_file(str(RAIZ / "app" / "Inicio.py"), default_timeout=90)
    at.query_params["s"] = sesion.emitir(u["id"])  # simula recargar con el token en la URL (session_state vacío)
    at.run()
    assert not at.exception
    assert at.session_state["usuario"]["id"] == u["id"]
    at2 = AppTest.from_file(str(RAIZ / "app" / "Inicio.py"), default_timeout=90)
    at2.query_params["s"] = "1.9999999999.firmafalsa"
    at2.run()
    assert "usuario" not in at2.session_state

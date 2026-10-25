"""Humo de interfaz: cada pantalla carga sin errores para cada rol (Streamlit AppTest, sin navegador)."""
import pytest
from streamlit.testing.v1 import AppTest

from conftest import RAIZ, usuario
from core import consultas as C

APP = str(RAIZ / "app" / "Inicio.py")


def _correr(email=None, pagina=None, estado=None):
    at = AppTest.from_file(APP, default_timeout=90)
    if email:
        at.session_state["usuario"] = usuario(email)
    for k, v in (estado or {}).items():
        at.session_state[k] = v
    at.run()
    if pagina:
        at.switch_page(f"paginas/{pagina}.py")
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_publicas(repo):
    at = _correr()
    assert any("PROTOTIPO BETA" in m.value for m in at.markdown)
    _correr(None, "consultar_estado")
    _correr(None, "ingresar")


@pytest.mark.parametrize("email,paginas", [
    ("abogado1.emp01", ["mi_bandeja", "busqueda", "reportes"]),
    ("supervisor.emp01", ["supervision", "mi_bandeja", "aprobaciones", "busqueda", "reportes", "buzon_simulado"]),
    ("director", ["aprobaciones", "supervision", "reportes"]),
    ("admin", ["administracion", "bitacora", "buzon_simulado", "busqueda"]),
    ("radicador.emp01", ["mi_bandeja", "buzon_simulado"]),
    ("auditor", ["bitacora", "reportes"]),
])
def test_paginas_por_rol(repo, email, paginas):
    for p in paginas:
        _correr(email, p)


def test_detalle_de_caso_en_cada_estado(repo):
    for estado in ("EN_TRAMITE", "EN_REVISION", "APROBADA", "PENDIENTE_INFO", "CERRADA"):
        filas = C.listar_solicitudes(None, {"estado": [estado]}, sin_alcance=True)
        if not filas:
            continue
        s = filas[0]
        quien = C.usuario(s["abogado_id"])["email"] if s.get("abogado_id") else "admin"
        _correr(quien, "detalle_caso", {"caso_id": s["id"]})
        _correr(C.usuarios("supervisor", s["empresa_id"])[0]["email"], "detalle_caso", {"caso_id": s["id"]})


def test_modo_formulario_solo_muestra_el_formulario(repo):
    """?modo=formulario&empresa=EMP01: formulario de la empresa, sin barra lateral ni menú (para <iframe>)."""
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["modo"] = "formulario"
    at.query_params["empresa"] = "EMP01"
    at.run()
    assert not at.exception
    assert not any("PQRS Consorcio" in m.value for m in at.sidebar.markdown)
    html = " ".join(m.value for m in at.markdown)
    assert C.empresa_por_codigo("EMP01")["nombre"] in html and "stSidebar" in html  # encabezado + CSS que oculta
    assert len(at.text_input) >= 3 and len(at.text_area) >= 1  # campos del formulario de radicación


def test_url_publica_por_defecto(monkeypatch):
    from core import config
    monkeypatch.delenv("APP_URL", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert config.app_url() == config.URL_PUBLICA
    monkeypatch.setenv("APP_URL", "https://otra.example.com/")
    assert config.app_url() == "https://otra.example.com"


def test_login_demo_restringido(monkeypatch):
    from core import config
    monkeypatch.delenv("PQRS_DEMO_CLAVE", raising=False)
    monkeypatch.setenv("PQRS_BACKEND", "postgres")
    assert config.login_demo_permitido() == (False, "cerrado")
    monkeypatch.setenv("PQRS_DEMO_CLAVE", "x")
    assert config.login_demo_permitido() == (True, "clave")
    monkeypatch.delenv("PQRS_DEMO_CLAVE")
    monkeypatch.setenv("PQRS_BACKEND", "sqlite")
    assert config.login_demo_permitido() == (True, "local")


def test_radicador_ve_reclasificar(repo_vacio):
    from core import servicios as S
    e = C.empresa_por_codigo("EMP01")
    r = S.radicar({"empresa_id": e["id"], "tipo_id": C.tipo_por_codigo("P")["id"], "asunto": "Cobro doble",
                   "descripcion": "Me cobraron dos veces (dato ficticio).", "nombre": "Ana Prueba",
                   "email": "ana@correo.example.com", "autoriza_datos": True}, asignar_ya=False)
    at = _correr(f"radicador.emp01@{__import__('core.catalogo_demo').catalogo_demo.DOMINIO}", "detalle_caso",
                 {"caso_id": r["solicitud"]["id"]})
    assert any("Corregir clasificación" in e.label for e in at.expander)


def test_bug01_consultar_estado_envia_formulario(repo_vacio):
    from core import servicios as S
    e = C.empresa_por_codigo("EMP01")
    r = S.radicar({"empresa_id": e["id"], "tipo_id": C.tipo_por_codigo("P")["id"], "asunto": "Consulta de estado",
                   "descripcion": "Solicitud ficticia para probar la consulta.", "nombre": "Ana Prueba",
                   "email": "ana@correo.example.com", "autoriza_datos": True})
    at = _correr(None, "consultar_estado")
    at.text_input[0].input(r["solicitud"]["radicado"])
    at.text_input[1].input(r["codigo"])
    at.button[0].click()
    at.run()
    assert not at.exception, [x.value for x in at.exception]
    assert any("Estado:" in m.value for m in at.markdown)
    at.run()  # segundo rerun (antes fallaba por la clave 'consulta')
    assert not at.exception

"""A3 · Lectura de `usuarios` / `usuario_empresa` acotada por empresa (RLS en PostgreSQL) y filtro por empresa en la Bitácora."""
import json

import pytest
from conftest import PG_URL, RAIZ, usuario
from streamlit.testing.v1 import AppTest

from core import consultas as C


def _como(cx, email=None, rol="authenticated"):
    claims = {"role": rol, **({"email": email} if email else {})}
    cx.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps(claims)])
    cx.execute(f"set local role {rol}")


@pytest.fixture()
def cx(repo):
    if not PG_URL:
        pytest.skip("requiere PQRS_TEST_PG_URL")
    import psycopg
    with psycopg.connect(PG_URL) as c:
        yield c
        c.rollback()


def _emails(cx):
    return {r[0] for r in cx.execute("select email from usuarios").fetchall()}


def test_abogado_solo_ve_usuarios_de_su_empresa(repo, cx):
    _como(cx, usuario("abogado1.emp01")["email"])
    emails = _emails(cx)
    assert any(e.startswith("abogado1.emp01@") for e in emails)                      # a sí mismo
    assert any(e.startswith("supervisor.emp01@") for e in emails)                    # su supervisor
    assert any(e.startswith("director@") for e in emails)                            # roles transversales (pertenecen a todas)
    assert not any(".emp02@" in e or ".emp03@" in e for e in emails)                 # ninguna otra empresa
    # ni siquiera conociendo el correo exacto
    assert cx.execute("select count(*) from usuarios where email like %s", ["%emp02@%"]).fetchone()[0] == 0
    assert cx.execute("select count(*) from usuarios where auth_id is not null and rol = 'abogado' "
                      "and id not in (select usuario_id from usuario_empresa where empresa_id = "
                      "(select id from empresas where codigo = 'EMP01'))").fetchone()[0] == 0


def test_membresias_solo_de_empresas_propias(repo, cx):
    _como(cx, usuario("supervisor.emp02")["email"])
    codigos = {r[0] for r in cx.execute("select e.codigo from usuario_empresa ue join empresas e on e.id = ue.empresa_id").fetchall()}
    assert codigos == {"EMP02"}
    assert any(e.startswith("supervisor.emp02@") for e in _emails(cx))
    assert not any(e.startswith("supervisor.emp01@") for e in _emails(cx))


def test_admin_y_auditor_ven_todos_y_anonimo_ninguno(repo, cx):
    total = cx.execute("select count(*) from usuarios").fetchone()[0]
    for quien in ("admin", "auditor"):
        cx.rollback()
        _como(cx, usuario(quien)["email"])
        assert cx.execute("select count(*) from usuarios").fetchone()[0] == total
        assert cx.execute("select count(distinct empresa_id) from usuario_empresa").fetchone()[0] == 10
    cx.rollback()
    _como(cx, rol="anon")
    with pytest.raises(Exception):  # anon no tiene ni el privilegio de lectura
        cx.execute("select count(*) from usuarios").fetchone()
    cx.rollback()
    _como(cx, "nadie@desconocido.example.com")
    assert cx.execute("select count(*) from usuarios").fetchone()[0] == 0


def test_la_app_con_rls_sigue_mostrando_nombres(repo):
    """Las pantallas que unen con usuarios (abogado de un caso) siguen funcionando con el alcance del usuario."""
    sup = usuario("supervisor.emp01")
    filas = C.listar_solicitudes(sup, {})
    assert filas and any(f.get("abogado_nombre") or f.get("abogado") for f in filas)


# ------------------------------------------------------------------ Bitácora por empresa
def test_consulta_eventos_por_empresa(repo):
    emp1, emp2 = (C.empresa_por_codigo(c)["id"] for c in ("EMP01", "EMP02"))
    todos = C.eventos(None, 100000)
    e1 = C.eventos(None, 100000, empresa_id=emp1)
    assert e1 and {e["empresa_id"] for e in e1} == {emp1}
    assert len(e1) < len(todos)
    assert {e["empresa_id"] for e in C.eventos(None, 100000, empresa_id=emp2)} == {emp2}
    sin = C.eventos(None, 100000, empresa_id=C.SIN_EMPRESA)
    assert all(e["empresa_id"] is None and e["solicitud_id"] is None for e in sin)
    assert len(e1) + len(C.eventos(None, 100000, empresa_id=emp2)) + len(sin) <= len(todos)


def test_pantalla_bitacora_filtra_por_empresa(repo):
    at = AppTest.from_file(str(RAIZ / "app" / "Inicio.py"), default_timeout=90)
    at.session_state["usuario"] = usuario("auditor")
    at.run()
    at.switch_page("paginas/bitacora.py")
    at.run()
    assert not at.exception
    sel = next(s for s in at.selectbox if s.label == "Empresa")
    assert sel.options[0] == "Todas las empresas"
    sel.select_index(2)  # primera empresa
    at.run()
    assert not at.exception
    codigo = sel.options[2].split(" · ")[0]
    frames = [d.value for d in at.dataframe]
    assert frames and "Empresa" in frames[0].columns
    assert set(frames[0]["Empresa"]) <= {sel.options[2]}
    assert codigo in sel.options[2]

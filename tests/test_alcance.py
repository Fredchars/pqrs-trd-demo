"""Criterio 11 (capa de aplicación): un abogado de EMP01 no ve ni encuentra casos de EMP02.
La misma regla está en PostgreSQL con RLS (tests/test_postgres.py)."""
from conftest import usuario
from core import consultas as C


def test_abogado_solo_ve_sus_casos(repo):
    ab = usuario("abogado1.emp01")
    vis = C.listar_solicitudes(ab)
    assert vis and all(s["abogado_id"] == ab["id"] for s in vis)
    emp2 = C.empresa_por_codigo("EMP02")
    caso2 = C.listar_solicitudes(None, {"empresa_id": emp2["id"]}, sin_alcance=True)[0]
    assert C.obtener_solicitud(caso2["id"], ab) is None
    assert C.solicitud_por_radicado(caso2["radicado"], ab) is None
    assert C.buscar(ab, caso2["radicado"]) == []
    palabra = caso2["asunto"].split()[0]
    assert all(r["empresa_id"] != emp2["id"] for r in C.buscar(ab, palabra))


def test_supervisor_solo_su_empresa_y_admin_todo(repo):
    sup = usuario("supervisor.emp02")
    emp2 = C.empresa_por_codigo("EMP02")
    vis = C.listar_solicitudes(sup)
    assert vis and {s["empresa_id"] for s in vis} == {emp2["id"]}
    assert len(C.listar_solicitudes(usuario("admin"))) == len(C.listar_solicitudes(None, sin_alcance=True))
    assert len(C.listar_solicitudes(usuario("auditor"))) == len(C.listar_solicitudes(None, sin_alcance=True))


def test_radicador_solo_recibidas(repo):
    r = usuario("radicador.emp01")
    assert all(s["estado"] == "RECIBIDA" for s in C.listar_solicitudes(r))


def test_ciudadano_sin_sesion_no_ve_nada(repo):
    assert C.listar_solicitudes({"rol": "ciudadano", "id": -1, "empresas": []}) == []

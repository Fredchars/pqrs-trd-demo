"""Supervisor único: si quien debe aprobar redactó la respuesta, la aprobación se escala o se avisa; nadie aprueba lo suyo."""
import pytest

from conftest import usuario
from core import consultas as C
from core import servicios as S
from core.repositorio import obtener_repo
from test_e2e import _caso_en_tramite


def _alertas(sid, tipo):
    return [a for a in obtener_repo().q("select * from alertas where solicitud_id = ? and tipo = ?", [sid, tipo])]


def _enviar_por_supervisor(emp="EMP06", tipo="R"):
    s, _ = _caso_en_tramite(emp, tipo)
    sups = C.usuarios("supervisor", s["empresa_id"])
    assert len(sups) == 1, "el escenario requiere un único supervisor"
    S.enviar_a_revision(s["id"], "Respuesta redactada por el único supervisor (ficticia).", sups[0])
    return C.obtener_solicitud(s["id"], sin_alcance=True), sups[0]


def test_unico_supervisor_escala_al_director_y_la_alerta_no_va_al_autor(repo_vacio):
    s, sup = _enviar_por_supervisor()
    directores = C.usuarios("director", s["empresa_id"])
    assert directores
    est = S.estado_aprobacion(s)
    assert est["escalado"] and not est["sin_aprobador"] and est["nivel"] == 1
    assert {u["id"] for u in est["posibles"]} == {d["id"] for d in directores}
    # la alerta de aprobación no le llega al autor; sí al director
    dest = {a["destinatario_id"] for a in _alertas(s["id"], "aprobacion_pendiente")}
    assert sup["id"] not in dest and dest == {d["id"] for d in directores}
    assert not _alertas(s["id"], "aprobacion_sin_aprobador")
    # el autor sigue sin poder aprobar ni devolver
    ok, _, nota = S.puede_aprobar(s, sup)
    assert not ok and "usted mismo" in nota
    with pytest.raises(S.ErrorNegocio):
        S.aprobar(s["id"], sup)
    # el administrador tampoco
    assert not S.puede_aprobar(s, usuario("admin"))[0]
    # el director sí, con nota de escalamiento
    d = directores[0]
    ok, n, nota = S.puede_aprobar(s, d)
    assert ok and n == 1 and "escalamiento" in nota
    r = S.aprobar(s["id"], d, "Revisada")
    assert r["estado"] == "APROBADA"


def test_sin_aprobador_disponible_avisa_al_autor_y_a_administracion(repo_vacio):
    s, _ = _caso_en_tramite("EMP06", "R")
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    for d in C.usuarios("director", s["empresa_id"]):
        obtener_repo().actualizar("usuarios", d["id"], {"activo": False})
    C.limpiar_cache()
    S.enviar_a_revision(s["id"], "Respuesta del único supervisor (ficticia).", sup)
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    est = S.estado_aprobacion(s)
    assert est["sin_aprobador"] and not est["posibles"]
    assert not _alertas(s["id"], "aprobacion_pendiente")
    dest = {a["destinatario_id"] for a in _alertas(s["id"], "aprobacion_sin_aprobador")}
    assert sup["id"] in dest and usuario("admin")["id"] in dest
    ok, _, nota = S.puede_aprobar(s, sup)
    assert not ok
    ok, _, nota = S.puede_aprobar(s, usuario("admin"))
    assert not ok and "Nadie puede aprobar" in nota


def test_dos_niveles_el_mismo_director_no_aprueba_ambos(repo_vacio):
    s, _ = _caso_en_tramite("EMP06", "R")
    obtener_repo().actualizar("tipos_pqrs", s["tipo_id"], {"niveles_aprobacion": 2})
    C.limpiar_cache()
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    S.enviar_a_revision(s["id"], "Respuesta del supervisor (ficticia).", sup)
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    d = C.usuarios("director", s["empresa_id"])[0]
    assert S.aprobar(s["id"], d)["estado"] == "EN_REVISION"
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    est = S.estado_aprobacion(s)
    assert est["nivel"] == 2
    ok, _, nota = S.puede_aprobar(s, d)
    assert not ok  # el mismo director no aprueba también el nivel 2
    if len(C.usuarios("director", s["empresa_id"])) == 1:
        assert est["sin_aprobador"]


def test_con_dos_supervisores_no_se_escala(repo_vacio):
    s, ab = _caso_en_tramite("EMP06", "R")
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    otro = C.usuarios("supervisor", C.empresa_por_codigo("EMP01")["id"])[0]
    S.crear_config("usuario_empresa", {"usuario_id": otro["id"], "empresa_id": s["empresa_id"]}, usuario("admin"))
    C.limpiar_cache()
    S.enviar_a_revision(s["id"], "Respuesta del supervisor (ficticia).", sup)
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    est = S.estado_aprobacion(s)
    assert not est["escalado"] and [u["id"] for u in est["posibles"]] == [otro["id"]]
    assert S.puede_aprobar(s, C.usuario(otro["id"]))[0]
    assert not S.puede_aprobar(s, C.usuarios("director", s["empresa_id"])[0])[0]

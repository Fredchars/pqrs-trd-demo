import pytest

from core import aprobacion, flujo


def test_transiciones_validas_por_rol():
    assert flujo.puede("RECIBIDA", "ASIGNADA", "sistema")
    assert flujo.puede("ASIGNADA", "EN_TRAMITE", "abogado")
    assert flujo.puede("EN_TRAMITE", "EN_REVISION", "abogado")
    assert flujo.puede("EN_REVISION", "APROBADA", "sistema")
    assert flujo.puede("APROBADA", "ENVIADA", "abogado")


def test_transiciones_invalidas():
    assert not flujo.puede("RECIBIDA", "ENVIADA", "abogado")
    assert not flujo.puede("CERRADA", "EN_TRAMITE", "abogado")
    assert not flujo.puede("EN_TRAMITE", "APROBADA", "abogado")  # el abogado no se aprueba a sí mismo
    with pytest.raises(flujo.TransicionInvalida):
        flujo.validar("ANULADA", "ASIGNADA", "supervisor")


def test_admin_no_puede_aprobar_por_atajo():
    assert not flujo.puede("EN_REVISION", "APROBADA", "admin")


def test_estados_tienen_explicacion():
    for e in flujo.ESTADOS:
        assert len(flujo.explicar(e)) > 5
    assert flujo.ABIERTOS.isdisjoint(flujo.FINALES)


def test_niveles_de_aprobacion():
    assert aprobacion.niveles_requeridos(0) == 0
    assert aprobacion.niveles_requeridos(1) == 1
    assert aprobacion.niveles_requeridos(1, tema_sensible=True) == 2
    assert aprobacion.niveles_requeridos(2, tema_sensible=True) == 2
    aps = [{"nivel": 1, "decision": "aprobada"}]
    assert aprobacion.nivel_pendiente([], 2) == 1
    assert aprobacion.nivel_pendiente(aps, 2) == 2
    assert aprobacion.nivel_pendiente(aps, 1) is None
    assert aprobacion.rol_para_nivel(1) == "supervisor" and aprobacion.rol_para_nivel(2) == "director"


def test_diff_entre_versiones():
    d = aprobacion.resumen_diff("Le informamos que no procede.", "Le informamos que sí procede el reintegro.")
    assert d["agregadas"] >= 2 and d["eliminadas"] >= 1
    h = aprobacion.diff_html("hola mundo", "hola mundo cruel")
    assert "cruel" in h


def test_correo_registra_consentimiento_o_aviso(repo):
    from core import correo
    from core import servicios as S
    from core.repositorio import obtener_repo
    R = obtener_repo()
    sin = correo.construir("ana.ficticia@correo.example.com", "pqrs@emp01.example.com", "Reclamo por cobro",
                           "Me cobraron dos veces la factura de este mes, solicito revisión.")
    r1 = S.procesar_correo(sin.as_bytes())
    s1 = S.C.solicitud_por_radicado(r1["radicado"], sin_alcance=True)
    assert not R.q("select autoriza_datos from solicitantes where id = ?", [s1["solicitante_id"]])[0]["autoriza_datos"]
    assert R.valor("select count(*) from eventos where solicitud_id = ? and accion = 'consentimiento_pendiente'", [s1["id"]])
    acuse = R.q("select cuerpo from correos where solicitud_id = ? and direccion = 'salida' order by id limit 1", [s1["id"]])
    assert "AUTORIZO el tratamiento" in acuse[0]["cuerpo"]
    resp = correo.construir("ana.ficticia@correo.example.com", "pqrs@emp01.example.com", f"RE: {r1['radicado']}",
                            "AUTORIZO el tratamiento de mis datos personales.")
    S.procesar_correo(resp.as_bytes())
    fila = R.q("select autoriza_datos, fecha_autorizacion from solicitantes where id = ?", [s1["solicitante_id"]])[0]
    assert fila["autoriza_datos"] and fila["fecha_autorizacion"]
    con = correo.construir("luis.ficticio@correo.example.com", "pqrs@emp01.example.com", "Petición de copia",
                           "Solicito copia de mi contrato. Autorizo el tratamiento de mis datos personales.")
    r2 = S.procesar_correo(con.as_bytes())
    s2 = S.C.solicitud_por_radicado(r2["radicado"], sin_alcance=True)
    assert R.q("select autoriza_datos from solicitantes where id = ?", [s2["solicitante_id"]])[0]["autoriza_datos"]

"""Criterio 6: alertas del 50 %, 80 %, «vence hoy» y «vencida» a los destinatarios correctos."""
from datetime import date

from core import alertas, plazos

RAD = date(2026, 9, 1)
VEN = plazos.fecha_vencimiento(RAD, 10)


def test_umbral():
    assert alertas.alerta_umbral(RAD, VEN, RAD) is None
    assert alertas.alerta_umbral(RAD, VEN, plazos.sumar_habiles(RAD, 5)) == "plazo_50"
    assert alertas.alerta_umbral(RAD, VEN, plazos.sumar_habiles(RAD, 8)) == "plazo_80"
    assert alertas.alerta_umbral(RAD, VEN, VEN) == "vence_hoy"
    assert alertas.alerta_umbral(RAD, VEN, plazos.sumar_habiles(VEN, 1)) == "vencida"


def test_matriz_destinatarios():
    assert alertas.destinatarios("plazo_50") == ["abogado"]
    assert set(alertas.destinatarios("plazo_80")) == {"abogado", "supervisor"}
    assert set(alertas.destinatarios("vence_hoy")) == {"abogado", "supervisor", "director"}
    assert set(alertas.destinatarios("vencida")) == {"abogado", "supervisor", "director"}
    assert alertas.es_diaria("vencida") and not alertas.es_diaria("plazo_50")


def test_alertas_en_base_llegan_a_quien_corresponde(repo_vacio):
    from conftest import usuario
    from core import consultas as C
    from core import servicios as S
    emp = C.empresa_por_codigo("EMP03")
    tp = C.tipo_por_codigo("D")  # 10 días
    s = S.radicar({"empresa_id": emp["id"], "tipo_id": tp["id"], "asunto": "Documento de prueba",
                   "descripcion": "Solicito copia de documento ficticio.", "nombre": "Ana Prueba",
                   "email": "ana@correo.example.com", "autoriza_datos": True})["solicitud"]
    ab = C.usuario(s["abogado_id"])
    sup = usuario("supervisor.emp03")
    dire = usuario("director")
    rad, ven = date.fromisoformat(s["fecha_radicacion"]), date.fromisoformat(s["fecha_vencimiento"])

    def recibidas(u, tipo):
        return [a for a in C.alertas_usuario(u["id"], limite=500) if a["tipo"] == tipo and a["solicitud_id"] == s["id"]]

    S.generar_alertas(plazos.sumar_habiles(rad, 5))
    assert recibidas(ab, "plazo_50") and not recibidas(sup, "plazo_50")
    S.generar_alertas(plazos.sumar_habiles(rad, 9))
    assert recibidas(ab, "plazo_80") and recibidas(sup, "plazo_80") and not recibidas(dire, "plazo_80")
    S.generar_alertas(ven)
    assert all(recibidas(u, "vence_hoy") for u in (ab, sup, dire))
    S.generar_alertas(plazos.sumar_habiles(ven, 1))
    S.generar_alertas(plazos.sumar_habiles(ven, 1))  # idempotente el mismo día
    assert all(len(recibidas(u, "vencida")) == 1 for u in (ab, sup, dire))
    S.generar_alertas(plazos.sumar_habiles(ven, 2))  # la «vencida» se repite cada día
    assert len(recibidas(ab, "vencida")) == 2
    # y además se escribió el correo (simulado)
    assert any(c["para"] == ab["email"] and "[Alerta PQRS]" in c["asunto"] for c in C.correos(None, "salida", 1000, sin_alcance=True))


def test_correo_alerta_trae_enlace_al_caso(repo):
    from core import servicios as S
    from core.repositorio import obtener_repo
    s = obtener_repo().q("select * from solicitudes order by id limit 1")[0]
    s = S._sol(s["id"])
    S.alertar("asignada", s, clave_extra="|prueba-enlace")
    fila = obtener_repo().q("select cuerpo from correos where asunto like ? order by id desc limit 1", ["%Alerta PQRS%"])
    assert fila and f"/detalle_caso?caso={s['radicado']}" in fila[0]["cuerpo"]


def test_correo_configurable_y_fallback_simulado(monkeypatch):
    from core import config, correo
    for k in ("MAIL_USER", "MAIL_APP_PASSWORD", "MAIL_MODO", "MAIL_SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert correo.modo() == "simulado"
    monkeypatch.setenv("MAIL_USER", "u@x.example.com")
    monkeypatch.setenv("MAIL_APP_PASSWORD", "x")
    assert correo.modo() == "real"
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.office365.com")
    assert config.correo_servidor()["smtp_host"] == "smtp.office365.com"
    monkeypatch.setenv("MAIL_MODO", "simulado")
    assert correo.modo() == "simulado"

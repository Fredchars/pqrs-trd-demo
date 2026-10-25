"""Pruebas de punta a punta de los criterios de aceptación 1, 2, 3, 7, 8, 10 y 12 (sección 13), en modo demo."""
from datetime import date, timedelta

import pytest

from conftest import usuario
from core import consultas as C
from core import correo, plantillas
from core import reportes as RP
from core import servicios as S
from core.reloj import ahora


def _pdf(texto):
    return plantillas.pdf_texto("Soporte ficticio", [texto])


def _radicar(emp="EMP04", tipo="P", **kw):
    e = C.empresa_por_codigo(emp)
    t = C.tipo_por_codigo(tipo)
    datos = {"empresa_id": e["id"], "tipo_id": t["id"], "asunto": "Solicitud de copia de contrato",
             "descripcion": "Solicito copia del contrato de condiciones uniformes (dato ficticio).",
             "nombre": "Pedro Prueba", "email": "pedro.prueba@correo.example.com", "num_doc": "99887766",
             "autoriza_datos": True}
    datos.update(kw)
    return S.radicar(datos, archivos=[("factura.pdf", _pdf("Factura número 123 ficticia"), "application/pdf")])


def test_1_radicacion_web_con_adjunto_y_acuse(repo_vacio):
    t0 = ahora()
    r = _radicar()
    s = r["solicitud"]
    assert s["radicado"].startswith("EMP04-") and s["estado"] in ("RECIBIDA", "ASIGNADA")
    docs = C.documentos(s["id"])
    assert [d["categoria"] for d in docs] == ["entrada"] and docs[0]["nombre"].startswith(s["radicado"] + "_entrada_")
    acuse = [c for c in C.correos(None, "salida", sin_alcance=True) if c["solicitud_id"] == s["id"] and c["para"] == "pedro.prueba@correo.example.com"]
    assert acuse and s["radicado"] in acuse[-1]["asunto"]
    assert r["codigo"] in acuse[-1]["cuerpo"]
    assert (ahora() - t0).total_seconds() < 60
    # el ciudadano consulta con radicado + código
    assert S.consultar_estado(s["radicado"], r["codigo"])["solicitud"]["id"] == s["id"]
    with pytest.raises(S.ErrorNegocio):
        S.consultar_estado(s["radicado"], "ZZZZZZZZ")


def test_validaciones_del_formulario(repo_vacio):
    with pytest.raises(S.ErrorNegocio, match="autorizar"):
        _radicar(autoriza_datos=False)
    with pytest.raises(S.ErrorNegocio, match="correo"):
        _radicar(email="no-es-correo")
    e = C.empresa_por_codigo("EMP04")
    with pytest.raises(S.ErrorNegocio):
        S.radicar({"empresa_id": e["id"], "tipo_codigo": "P", "asunto": "Hola", "descripcion": "Descripción larga",
                   "nombre": "X", "email": "x@correo.example.com", "autoriza_datos": True},
                  archivos=[("virus.exe", b"MZ", "application/octet-stream")])


def test_2_y_3_correo_entrante_y_respuesta_con_radicado(repo_vacio):
    emp = C.empresa_por_codigo("EMP05")
    correo.simular_entrante(repo_vacio, "maria.prueba@correo.example.com", emp["buzon_correo"], "Queja por mala atención",
                            "Me atendieron mal en la oficina. Adjunto soporte.",
                            [("soporte.pdf", _pdf("soporte ficticio de queja"), "application/pdf")])
    res = S.ejecutar_tareas()["correos"]
    assert res[0]["resultado"] == "radicada" and res[0]["empresa"] == "EMP05" and res[0]["tipo"] == "Q"
    s = C.solicitud_por_radicado(res[0]["radicado"], sin_alcance=True)
    assert s["canal"] == "correo"
    entrada = [d["nombre_original"] for d in C.documentos(s["id"]) if d["categoria"] == "entrada"]
    assert "correo-original.eml" in entrada and "soporte.pdf" in entrada
    total = repo_vacio.valor("select count(*) from solicitudes")
    # 3: el ciudadano responde con el radicado en el asunto
    correo.simular_entrante(repo_vacio, "maria.prueba@correo.example.com", emp["buzon_correo"],
                            f"RE: {s['radicado']} información adicional", "Agrego más datos.",
                            [("foto.png", b"\x89PNG\r\n\x1a\nficticio", "image/png")])
    res = S.leer_correo()
    assert res[0]["resultado"] == "agregado_a_expediente" and res[0]["radicado"] == s["radicado"]
    assert repo_vacio.valor("select count(*) from solicitudes") == total
    assert any(d["nombre_original"] == "foto.png" for d in C.documentos(s["id"]))
    # idempotencia: volver a leer no duplica
    assert S.leer_correo() == []


def test_correo_spam_a_cuarentena_y_liberacion(repo_vacio):
    emp = C.empresa_por_codigo("EMP01")
    cid = correo.simular_entrante(repo_vacio, "promo@spam.example.com", emp["buzon_correo"], "Gana dinero rápido",
                                  "Haz clic aquí, gana dinero rápido con este premio.")
    assert S.leer_correo()[0]["resultado"] == "cuarentena"
    r = S.liberar_cuarentena(cid, usuario("radicador.emp01"))
    assert r["resultado"] == "radicada"


def _caso_en_tramite(emp="EMP06", tipo="R"):
    s = _radicar(emp, tipo)["solicitud"]
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    ab = C.usuario(s["abogado_id"])
    S.abrir_caso(s["id"], ab)
    return C.obtener_solicitud(s["id"], sin_alcance=True), ab


def test_7_devolucion_nueva_version_y_8_envio(repo_vacio):
    s, ab = _caso_en_tramite()
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    p = C.plantillas("respuesta", s["empresa_id"], s["tipo_id"])[0]
    texto = S.texto_plantilla(s["id"], p["id"], ab)
    assert s["radicado"] in texto and "{{" not in texto
    S.enviar_a_revision(s["id"], texto, ab)
    with pytest.raises(S.ErrorNegocio):
        S.aprobar(s["id"], ab)  # el abogado no aprueba
    S.devolver(s["id"], sup, "Falta citar la norma aplicable.")
    s2 = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert s2["estado"] == "EN_TRAMITE"
    S.enviar_a_revision(s["id"], texto + "\n\nNorma: Ley 142 de 1994 (cita ficticia).", ab)
    rs = C.respuestas(s["id"])
    assert [r["version"] for r in rs] == [1, 2] and rs[0]["estado"] == "devuelta"
    aps = C.aprobaciones_de([r["id"] for r in rs])
    assert aps[0]["comentario"] == "Falta citar la norma aplicable."
    assert S.aprobar(s["id"], sup)["estado"] == "APROBADA"
    r = S.enviar_respuesta(s["id"], ab)
    s3 = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert s3["estado"] == "ENVIADA" and r["codigo_verificacion"]
    pdfs = [d for d in C.documentos(s["id"]) if d["categoria"] == "respuesta"]
    assert pdfs and pdfs[0]["ruta"].split("/")[4] == "03_respuesta"
    datos, _, integro = S.descargar(pdfs[0]["id"], ab)
    assert datos.startswith(b"%PDF") and integro
    acciones = [e["accion"] for e in C.eventos(s["id"])]
    assert "respuesta_enviada" in acciones or any("enviad" in a for a in acciones)
    assert any(e["accion"] == "cambio_estado" and (e["detalle"] or {}).get("a") == "ENVIADA" for e in C.eventos(s["id"]))


def test_dos_niveles_tema_sensible_y_bitacora_inmutable(repo_vacio):
    tema = next(t for t in C.temas() if t["sensible"])
    s = _radicar("EMP07", "P", tema_id=tema["id"])["solicitud"]
    s = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert S.niveles_caso(s) == 2
    ab = C.usuario(s["abogado_id"]) if s.get("abogado_id") else None
    if ab is None:  # sin especialista: el supervisor lo asigna
        sup = C.usuarios("supervisor", s["empresa_id"])[0]
        S.reasignar(s["id"], C.usuarios("abogado", s["empresa_id"])[0]["id"], "prueba", sup)
        s = C.obtener_solicitud(s["id"], sin_alcance=True)
        ab = C.usuario(s["abogado_id"])
    S.enviar_a_revision(s["id"], "Respuesta de fondo ficticia para tema sensible.", ab)
    S.aprobar(s["id"], C.usuarios("supervisor", s["empresa_id"])[0])
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["estado"] == "EN_REVISION"
    assert S.aprobar(s["id"], usuario("director"))["estado"] == "APROBADA"
    with pytest.raises(Exception):
        repo_vacio.ex("update eventos set accion = 'x'")
    with pytest.raises(Exception):
        repo_vacio.ex("delete from eventos")


def test_pedir_informacion_suspende_y_reinicia(repo_vacio):
    s, ab = _caso_en_tramite("EMP08", "P")
    S.pedir_informacion(s["id"], "Envíe copia de la factura.", ab)
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["sem_nivel"] == "pausa"
    S.aportar_informacion(s["id"], "Adjunto la factura", [("f.pdf", _pdf("factura"), "application/pdf")], "ciudadano")
    s2 = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert s2["estado"] == "EN_TRAMITE" and s2["fecha_vencimiento"] >= s["fecha_vencimiento"]


def test_prorroga_y_traslado(repo_vacio):
    s, ab = _caso_en_tramite("EMP09", "P")
    nueva = date.fromisoformat(s["fecha_vencimiento"]) + timedelta(days=7)
    S.prorrogar(s["id"], nueva, "Se requiere concepto técnico (ficticio).", ab)
    s2 = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert s2["prorrogada"] and s2["fecha_vencimiento"] == nueva.isoformat()
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    S.trasladar_empresa(s["id"], C.empresa_por_codigo("EMP10")["id"], "Competencia de otra empresa", sup)
    s3 = C.obtener_solicitud(s["id"], sin_alcance=True)
    assert s3["empresa_codigo"] == "EMP10" and s3["radicado"] == s["radicado"]


def test_10_excel_r1_coincide_con_tablero(repo):
    import io

    import pandas as pd
    admin = usuario("admin")
    df = RP.marco(C.listar_solicitudes(admin))
    r1 = RP.r1_tablero(df)
    leido = pd.read_excel(io.BytesIO(RP.a_excel({"R1": r1})), sheet_name="R1")
    pd.testing.assert_frame_equal(r1.reset_index(drop=True), leido, check_dtype=False)
    assert int(r1[r1["Empresa"] == "CONSOLIDADO"]["Recibidas"].iloc[0]) == len(df)


def test_12_radicacion_por_api_se_completa_y_asigna(repo_vacio):
    """La API REST (rpc radicar_pqrs en Supabase) deja la fila con pendiente_completar; la tarea la completa."""
    emp, tp = C.empresa_por_codigo("EMP02"), C.tipo_por_codigo("P")
    from core import radicado as rad
    from core.reloj import hoy
    n = rad.formatear("EMP02", hoy().year, "P", repo_vacio.siguiente_consecutivo(emp["id"], hoy().year))
    sol = repo_vacio.insertar("solicitantes", {"tipo_doc": "CC", "nombre": "Integración Prueba", "email": "api@correo.example.com",
                                               "anonimo": False, "autoriza_datos": True})
    sid = repo_vacio.insertar("solicitudes", {"radicado": n, "empresa_id": emp["id"], "tipo_id": tp["id"], "solicitante_id": sol,
                                              "canal": "api", "asunto": "Radicada por API", "descripcion": "Prueba de API ficticia",
                                              "estado": "RECIBIDA", "prioridad": "normal", "fecha_recepcion": ahora(),
                                              "pendiente_completar": True, "revisar_duplicado": False})
    out = S.ejecutar_tareas()
    assert out["api_completadas"] == 1
    s = C.obtener_solicitud(sid, sin_alcance=True)
    assert s["fecha_vencimiento"] and s["abogado_id"] and s["estado"] == "ASIGNADA"


def test_duplicado_se_detecta(repo_vacio):
    _radicar("EMP03", "Q", asunto="Cobro doble en factura de agosto")
    r = _radicar("EMP03", "Q", asunto="Cobro doble en la factura de agosto")
    assert r["duplicado_de"]
    assert C.obtener_solicitud(r["solicitud"]["id"], sin_alcance=True)["revisar_duplicado"]


def test_ausencia_reasigna_casos(repo_vacio):
    s, ab = _caso_en_tramite("EMP01", "P")
    sup = usuario("supervisor.emp01")
    r = S.marcar_ausencia(ab["id"], date.today(), date.today() + timedelta(days=3), True, sup)
    assert s["radicado"] in [x[0] for x in r["reasignados"]]
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["abogado_id"] != ab["id"]


def test_supervisor_no_aprueba_su_propia_respuesta(repo_vacio):
    s, ab = _caso_en_tramite()
    sups = C.usuarios("supervisor", s["empresa_id"])
    sup = sups[0]
    S.enviar_a_revision(s["id"], "Respuesta redactada por el supervisor (ficticia).", sup)
    ok, _, nota = S.puede_aprobar(C.obtener_solicitud(s["id"], sin_alcance=True), sup)
    assert not ok and "usted mismo" in nota
    with pytest.raises(S.ErrorNegocio):
        S.aprobar(s["id"], sup)
    with pytest.raises(S.ErrorNegocio):
        S.devolver(s["id"], sup, "autodevolución")


def test_radicador_reclasifica(repo_vacio):
    r = _radicar("EMP04", "P", asunto="Cobro doble en la factura")
    s = C.obtener_solicitud(r["solicitud"]["id"], sin_alcance=True)
    if s["estado"] != "RECIBIDA":  # el reparto inmediato pudo asignarlo: se prueba con uno sin repartir
        e = C.empresa_por_codigo("EMP04")
        r = S.radicar({"empresa_id": e["id"], "tipo_id": C.tipo_por_codigo("P")["id"], "asunto": "Otro cobro",
                       "descripcion": "Solicitud ficticia para reclasificar.", "nombre": "Ana Prueba",
                       "email": "ana2@correo.example.com", "autoriza_datos": True}, asignar_ya=False)
        s = C.obtener_solicitud(r["solicitud"]["id"], sin_alcance=True)
    rad_ = C.usuarios("radicador", s["empresa_id"])[0]
    nuevo = C.tipo_por_codigo("Q")
    S.cambiar_clasificacion(s["id"], nuevo["id"], None, rad_, "Era una queja")
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["tipo_id"] == nuevo["id"]
    otro = next(x for x in C.usuarios("radicador") if s["empresa_id"] not in x["empresas"])
    with pytest.raises(S.ErrorNegocio):
        S.cambiar_clasificacion(s["id"], nuevo["id"], None, otro)  # otra empresa
    t, _ = _caso_en_tramite()
    with pytest.raises(S.ErrorNegocio):
        S.cambiar_clasificacion(t["id"], nuevo["id"], None, C.usuarios("radicador", t["empresa_id"])[0])  # ya repartido


def test_informacion_faltante_vacia_se_rechaza(repo_vacio):
    s, ab = _caso_en_tramite()
    for malo in ("", "   ", "falta"):
        with pytest.raises(S.ErrorNegocio):
            S.pedir_informacion(s["id"], malo, ab)
    S.pedir_informacion(s["id"], "Envíe copia de la factura de marzo.", ab)
    with pytest.raises(S.ErrorNegocio):
        S.aportar_informacion(s["id"], "   ", [])
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["estado"] == "PENDIENTE_INFO"
    S.aportar_informacion(s["id"], "Adjunto la factura (ficticia).", [])
    assert C.obtener_solicitud(s["id"], sin_alcance=True)["estado"] == "EN_TRAMITE"

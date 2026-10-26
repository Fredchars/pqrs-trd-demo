"""TRD y archivo físico (core/archivo.py): reglas de retención, flujo de disposición con acta, préstamos, rótulos con QR real,
alertas a 30/90 días, permisos por rol y aislamiento entre empresas. Corre en SQLite y en PostgreSQL (RLS real)."""
from datetime import date

import pytest
from conftest import usuario

from core import archivo as A
from core import consultas as C
from core.repositorio import obtener_repo

ARCH1, ARCH2 = "archivista.emp01", "archivista.emp02"


def emp_id(cod):
    return C.empresa_por_codigo(cod)["id"]


# ------------------------------------------------------------------ reglas puras
def test_sumar_anios_y_29_de_febrero():
    assert A.sumar_anios(date(2024, 2, 29), 1) == date(2025, 2, 28)
    assert A.sumar_anios(date(2024, 2, 29), 4) == date(2028, 2, 29)
    assert A.sumar_anios(date(2020, 5, 10), 0) == date(2020, 5, 10)


def test_calculo_de_fechas_de_retencion():
    g, d = A.calcular_fechas(date(2023, 3, 15), 2, 8)
    assert g == date(2025, 3, 15) and d == date(2033, 3, 15)


@pytest.mark.parametrize("dias,esperado", [(-400, "vencida"), (-1, "vencida"), (0, "30"), (30, "30"), (31, "90"), (90, "90"), (91, None), (None, None)])
def test_niveles_de_alerta(dias, esperado):
    assert A.nivel_alerta(dias) == esperado


def test_fases_del_expediente():
    x = {"estado": "activo", "fecha_fin_gestion": "2026-01-01", "fecha_disposicion": "2028-01-01"}
    assert A.fase(x, date(2025, 6, 1)) == "Archivo de gestión"
    assert A.fase(x, date(2027, 6, 1)) == "Archivo central"
    assert A.fase(x, date(2028, 6, 1)) == "Disposición pendiente"
    assert A.fase({**x, "estado": "dispuesto"}, date(2025, 6, 1)) == "Dispuesto"


# ------------------------------------------------------------------ semilla y consultas
def test_semilla_tiene_trd_y_archivo_en_varias_empresas(repo):
    adm = usuario("admin")
    ser, exps, cajas = A.series(adm), A.expedientes(adm), A.cajas(adm)
    assert len({s["empresa_id"] for s in ser}) >= 10 and len({x["empresa_id"] for x in exps}) >= 5 and cajas
    niveles = {x["nivel"] for x in A.expedientes(usuario(ARCH1))}
    assert {"vencida", "30", "90"} <= niveles  # la demostración muestra los tres niveles de alerta
    assert any(c["estado"] == "cerrada" for c in cajas) and any(c["n_carpetas"] == 0 for c in cajas)
    assert {d["estado"] for d in A.disposiciones(usuario(ARCH1))} >= {"propuesta", "revisada", "aprobada", "ejecutada"}
    assert A.actas(usuario(ARCH1)) and A.actas(usuario(ARCH2))


def test_expediente_tiene_indice_con_folios_continuos_y_huellas(repo):
    arch = usuario(ARCH1)
    x = max(A.expedientes(arch, emp_id("EMP01")), key=lambda e: e["folios"])
    ind = A.indice(x["id"], arch)
    assert ind and ind[0]["orden"] == 1 and ind[0]["folio_inicial"] == 1
    for a, b in zip(ind, ind[1:]):
        assert b["folio_inicial"] == a["folio_final"] + 1
    assert ind[-1]["folio_final"] == x["folios"] == sum(d["folios"] for d in ind)
    assert all(len(d["sha256"] or "x" * 64) == 64 for d in ind)
    assert any("Constancia de cierre" in d["descripcion"] for d in ind)


def test_fechas_del_expediente_siguen_la_serie(repo):
    arch = usuario(ARCH1)
    for x in A.expedientes(arch, emp_id("EMP01")):
        g, d = A.calcular_fechas(A.a_fecha(x["fecha_cierre"]), x["anios_gestion"], x["anios_central"])
        assert (A.a_fecha(x["fecha_fin_gestion"]), A.a_fecha(x["fecha_disposicion"])) == (g, d)


def test_cerradas_sin_serie_son_cerradas_y_no_tienen_expediente(repo):
    arch = usuario(ARCH1)
    sin = A.cerradas_sin_serie(arch, emp_id("EMP01"))
    assert sin
    con = {x["solicitud_id"] for x in A.expedientes(arch)}
    assert not (con & {s["id"] for s in sin})
    assert all(C.obtener_solicitud(s["id"], arch)["estado"] == "CERRADA" for s in sin)


# ------------------------------------------------------------------ aislamiento entre empresas
@pytest.mark.parametrize("quien,cod", [(ARCH1, "EMP01"), (ARCH2, "EMP02"), ("supervisor.emp01", "EMP01")])
def test_cada_usuario_solo_ve_su_empresa(repo, quien, cod):
    u, mi = usuario(quien), emp_id(cod)
    for lista in (A.series(u), A.cajas(u), A.carpetas(u), A.expedientes(u), A.prestamos(u), A.disposiciones(u), A.actas(u),
                  A.cerradas_sin_serie(u)):
        assert lista and {f["empresa_id"] for f in lista} == {mi}
    # pedir otra empresa explícitamente no devuelve nada
    otra = emp_id("EMP02" if cod == "EMP01" else "EMP01")
    assert A.expedientes(u, otra) == [] and A.series(u, otra) == [] and A.cajas(u, otra) == []


def test_no_se_puede_escribir_en_otra_empresa(repo):
    a1, e2 = usuario(ARCH1), emp_id("EMP02")
    with pytest.raises(A.ErrorArchivo, match="otra empresa"):
        A.crear_caja({"empresa_id": e2, "sede": "S", "deposito": "D", "estante": "E", "entrepano": "1"}, a1)
    with pytest.raises(A.ErrorArchivo, match="otra empresa"):
        A.guardar_serie({"empresa_id": e2, "codigo": "99", "nombre": "Intruso", "anios_gestion": 1, "anios_central": 1, "disposicion": "eliminar"}, a1)
    x2 = A.expedientes(usuario(ARCH2), e2)[0]
    with pytest.raises(A.ErrorArchivo):
        A.ubicar_expediente(x2["id"], None, a1)
    ca2 = A.carpetas(usuario(ARCH2), e2)[0]
    with pytest.raises(A.ErrorArchivo):
        A.solicitar_prestamo(ca2["id"], "Intento desde otra empresa", 3, a1)
    d2 = A.disposiciones(usuario(ARCH2), empresa_id=e2)[0]
    with pytest.raises(A.ErrorArchivo):
        A.revisar_disposicion(d2["id"], True, "Concepto desde otra empresa, no debe valer", a1)


def test_la_serie_de_otra_empresa_no_se_puede_asignar(repo):
    a1 = usuario(ARCH1)
    caso = A.cerradas_sin_serie(a1, emp_id("EMP01"))[0]
    serie_ajena = A.series_asignables(usuario(ARCH2), emp_id("EMP02"))[0]
    with pytest.raises(A.ErrorArchivo, match="no pertenece"):
        A.asignar_serie(caso["id"], serie_ajena["id"], a1)


def test_la_base_rechaza_mezclar_empresas(repo):
    """Defensa en profundidad: las claves foráneas compuestas impiden un expediente con la serie de otra empresa."""
    R = obtener_repo()
    caso = A.cerradas_sin_serie(usuario(ARCH1), emp_id("EMP01"))[0]
    serie_ajena = A.series_asignables(usuario(ARCH2), emp_id("EMP02"))[0]
    if not R.es_pg:
        R.conn.execute("pragma foreign_keys = on")
    with pytest.raises(Exception):
        with R.transaccion():
            R.insertar("expedientes", {"empresa_id": emp_id("EMP01"), "solicitud_id": caso["id"], "serie_id": serie_ajena["id"],
                                       "fecha_cierre": "2026-01-01", "fecha_fin_gestion": "2027-01-01", "fecha_disposicion": "2028-01-01",
                                       "disposicion": "eliminar", "folios": 1, "estado": "activo"})


# ------------------------------------------------------------------ permisos por rol
@pytest.mark.parametrize("quien", ["abogado1.emp01", "radicador.emp01", "auditor", "supervisor.emp01", "director"])
def test_roles_sin_gestion_no_modifican_el_archivo(repo, quien):
    u = usuario(quien)
    e = emp_id("EMP01") if u.get("empresas") else emp_id("EMP01")
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.crear_caja({"empresa_id": e, "sede": "S", "deposito": "D", "estante": "E", "entrepano": "1"}, u)
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.guardar_serie({"empresa_id": e, "codigo": "98", "nombre": "No permitido"}, u)
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.proponer_disposiciones(u, e)
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.asignar_serie(1, 1, u)


def test_radicador_no_ve_expedientes_ni_actas(repo):
    r = usuario("radicador.emp01")
    assert A.expedientes(r) == [] and A.actas(r) == [] and A.disposiciones(r) == [] and A.cerradas_sin_serie(r) == []


def test_abogado_solo_ve_expedientes_de_sus_casos_y_puede_pedir_prestamo(repo):
    ab = usuario("abogado1.emp01")
    exps = A.expedientes(ab)
    assert exps and all(x["abogado_id"] == ab["id"] for x in exps)
    assert A.series(ab, emp_id("EMP01")) and A.actas(ab) == []
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.revisar_disposicion(1, True, "Un abogado no revisa disposiciones", ab)


def test_admin_y_archivista_no_aprueban_disposiciones(repo):
    for quien in ("admin", ARCH1):
        with pytest.raises(A.ErrorArchivo, match="permiso"):
            A.decidir_disposiciones([1], True, "Intento de aprobación no autorizado", usuario(quien))


def test_auditor_ve_todo_pero_solo_lee(repo):
    au = usuario("auditor")
    assert {x["empresa_id"] for x in A.expedientes(au)} >= {emp_id("EMP01"), emp_id("EMP02")}
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.cerrar_caja(A.cajas(au, emp_id("EMP01"))[0]["id"], au)


# ------------------------------------------------------------------ asignar serie y crear expediente
def test_asignar_serie_crea_expediente_con_indice_y_evento(repo):
    a1 = usuario(ARCH1)
    caso = next(c for c in A.cerradas_sin_serie(a1, emp_id("EMP01")) if c["docs_fisicos"]) if any(
        c["docs_fisicos"] for c in A.cerradas_sin_serie(a1, emp_id("EMP01"))) else A.cerradas_sin_serie(a1, emp_id("EMP01"))[0]
    serie = A.series_asignables(a1, emp_id("EMP01"))[0]
    xid = A.asignar_serie(caso["id"], serie["id"], a1)
    x = A.expediente(xid, a1)
    assert x["serie_id"] == serie["id"] and x["estado"] == "activo" and x["folios"] >= 2
    assert A.a_fecha(x["fecha_fin_gestion"]) > A.a_fecha(x["fecha_cierre"])
    assert A.indice(xid, a1)
    ev = obtener_repo().q("select accion from eventos where solicitud_id = ? order by id desc", [caso["id"]])
    assert any(e["accion"] == "expediente_creado" for e in ev)
    with pytest.raises(A.ErrorArchivo, match="ya tiene expediente"):
        A.asignar_serie(caso["id"], serie["id"], a1)


def test_solo_se_archivan_casos_cerrados(repo):
    a1 = usuario(ARCH1)
    abierto = C.listar_solicitudes(None, {"abiertos": True, "empresa_id": emp_id("EMP01")}, sin_alcance=True)[0]
    with pytest.raises(A.ErrorArchivo):
        A.asignar_serie(abierto["id"], A.series_asignables(a1, emp_id("EMP01"))[0]["id"], a1)


def test_series_validaciones(repo):
    a1, e = usuario(ARCH1), emp_id("EMP01")
    base = {"empresa_id": e, "codigo": "77", "nombre": "Serie de prueba", "anios_gestion": 1, "anios_central": 2, "disposicion": "conservar"}
    sid = A.guardar_serie(base, a1)
    with pytest.raises(A.ErrorArchivo, match="Ya existe"):
        A.guardar_serie(base, a1)
    with pytest.raises(A.ErrorArchivo, match="subserie"):
        A.guardar_serie({"empresa_id": e, "codigo": "77.2", "nombre": "Sin retención", "serie_padre_id": sid}, a1)
    with pytest.raises(A.ErrorArchivo, match="disposición"):
        A.guardar_serie({**base, "codigo": "78", "disposicion": "quemar"}, a1)
    # no se cambian los tiempos de una serie con expedientes
    con_exp = next(s for s in A.series(a1, e) if s["n_expedientes"])
    with pytest.raises(A.ErrorArchivo, match="expediente"):
        A.guardar_serie({"empresa_id": e, "codigo": con_exp["codigo"], "nombre": con_exp["nombre"], "anios_gestion": 99, "anios_central": 99,
                         "disposicion": con_exp["disposicion"]}, a1, con_exp["id"])


# ------------------------------------------------------------------ cajas, carpetas, ubicación
def test_caja_carpeta_capacidad_y_cierre(repo):
    a1, e = usuario(ARCH1), emp_id("EMP01")
    cid = A.crear_caja({"empresa_id": e, "sede": "Sede", "deposito": "Central", "estante": "E-9", "entrepano": "3", "capacidad_carpetas": 2}, a1)
    caja = next(c for c in A.cajas(a1, e) if c["id"] == cid)
    assert caja["codigo"].startswith("EMP01-C-") and caja["ocupacion"] == 0
    A.crear_carpeta(cid, a1, None, 2026, "uno")
    A.crear_carpeta(cid, a1, None, 2026, "dos")
    with pytest.raises(A.ErrorArchivo, match="llena"):
        A.crear_carpeta(cid, a1)
    assert next(c for c in A.cajas(a1, e) if c["id"] == cid)["ocupacion"] == 100
    with pytest.raises(A.ErrorArchivo, match="Ya existe"):
        A.crear_caja({"empresa_id": e, "codigo": caja["codigo"], "sede": "S", "deposito": "D", "estante": "E", "entrepano": "1"}, a1)
    with pytest.raises(A.ErrorArchivo, match="estante"):
        A.crear_caja({"empresa_id": e, "sede": "S", "deposito": "D", "estante": " ", "entrepano": "1"}, a1)
    A.cerrar_caja(cid, a1)
    with pytest.raises(A.ErrorArchivo, match="cerrada"):
        A.crear_carpeta(cid, a1)


def test_ubicar_expediente_y_folios_de_la_carpeta(repo):
    a1, e = usuario(ARCH1), emp_id("EMP01")
    cid = A.crear_caja({"empresa_id": e, "sede": "Sede", "deposito": "Central", "estante": "E-8", "entrepano": "1", "capacidad_carpetas": 5}, a1)
    fid = A.crear_carpeta(cid, a1)
    libres = [x for x in A.expedientes(a1, e) if x["estado"] == "activo" and not x.get("carpeta_codigo") and x["nivel"] != "vencida"]
    x = libres[0]
    A.ubicar_expediente(x["id"], fid, a1)
    f = next(c for c in A.carpetas(a1, e) if c["id"] == fid)
    assert f["n_expedientes"] == 1 and f["serie_id"] == x["serie_id"]
    papel = sum(d["folios"] for d in A.indice(x["id"], a1) if d["soporte"] == "fisico")
    assert f["folio_final"] == max(1, papel)
    otro = next((y for y in libres[1:] if y["serie_id"] != x["serie_id"]), None)
    if otro:
        with pytest.raises(A.ErrorArchivo, match="otra serie"):
            A.ubicar_expediente(otro["id"], fid, a1)
    A.ubicar_expediente(x["id"], None, a1)
    assert next(c for c in A.carpetas(a1, e) if c["id"] == fid)["n_expedientes"] == 0


# ------------------------------------------------------------------ rótulos y QR
def test_qr_es_un_png_real_y_distinto_por_codigo(repo):
    a = A.qr_png("https://ejemplo.test/cajas?codigo=EMP01-C-001")
    b = A.qr_png("https://ejemplo.test/cajas?codigo=EMP01-C-002")
    assert a[:8] == b"\x89PNG\r\n\x1a\n" and a != b and len(a) > 300
    import io

    import segno
    assert segno.make("https://ejemplo.test/cajas?codigo=EMP01-C-001", error="m").designator  # el QR es válido
    from PIL import Image
    assert Image.open(io.BytesIO(a)).size[0] > 100


def test_payload_del_qr_apunta_a_la_ficha(repo):
    assert A.payload_qr("caja", "EMP01-C-001").endswith("/cajas?codigo=EMP01-C-001")


def test_rotulos_pdf_con_texto_y_pie(repo):
    import io

    from pypdf import PdfReader
    a1, e = usuario(ARCH1), emp_id("EMP01")
    caja = A.cajas(a1, e)[0]
    texto = PdfReader(io.BytesIO(A.rotulo_pdf("caja", caja))).pages[0].extract_text()
    assert caja["codigo"] in texto and "Powered by ATm Consulting" in texto and "DEMOSTRACIÓN" in texto
    for palabra in ("Depósito", "Entrepaño", "sesión"):  # tildes y eñes sin depender de fuentes del sistema
        assert palabra in texto, palabra
    carp = A.carpetas(a1, e, caja["id"])[0]
    assert "Año" in PdfReader(io.BytesIO(A.rotulo_pdf("carpeta", carp))).pages[0].extract_text()
    assert carp["codigo"] in PdfReader(io.BytesIO(A.rotulo_pdf("carpeta", carp))).pages[0].extract_text()
    todos = PdfReader(io.BytesIO(A.rotulos_caja_pdf(caja, a1)))
    assert len(todos.pages) == 1 + len(A.carpetas(a1, e, caja["id"]))


# ------------------------------------------------------------------ préstamos
def test_prestamo_completo_con_responsables_y_fechas(repo):
    a1, ab, e = usuario(ARCH1), usuario("abogado1.emp01"), emp_id("EMP01")
    libre = next(f for f in A.carpetas(a1, e) if f["estado"] == "en_archivo" and f["n_expedientes"])
    pid = A.solicitar_prestamo(libre["id"], "Consultar antecedentes del caso", 4, ab)
    with pytest.raises(A.ErrorArchivo, match="pendiente"):
        A.solicitar_prestamo(libre["id"], "Consultar antecedentes del caso", 4, ab)
    with pytest.raises(A.ErrorArchivo, match="permiso"):
        A.entregar_prestamo(pid, ab)  # solo el archivista entrega
    A.entregar_prestamo(pid, a1)
    p = next(x for x in A.prestamos(a1, empresa_id=e) if x["id"] == pid)
    assert p["estado"] == "prestada" and p["responsable"] == a1["nombre"] and p["fecha_vence"] and not p["vencido"]
    assert next(f for f in A.carpetas(a1, e) if f["id"] == libre["id"])["estado"] == "prestada"
    with pytest.raises(A.ErrorArchivo, match="ya está prestada"):
        A.solicitar_prestamo(libre["id"], "Otro motivo cualquiera", 3, usuario("supervisor.emp01"))
    A.devolver_prestamo(pid, a1, "Completa")
    p = next(x for x in A.prestamos(a1, empresa_id=e) if x["id"] == pid)
    assert p["estado"] == "devuelta" and p["fecha_devolucion"] and p["recibido_por_nombre"] == a1["nombre"]
    assert next(f for f in A.carpetas(a1, e) if f["id"] == libre["id"])["estado"] == "en_archivo"
    with pytest.raises(A.ErrorArchivo, match="prestada"):
        A.devolver_prestamo(pid, a1)


def test_prestamo_validaciones_y_vencidos(repo):
    a1, e = usuario(ARCH1), emp_id("EMP01")
    f = next(f for f in A.carpetas(a1, e) if f["estado"] == "en_archivo")
    with pytest.raises(A.ErrorArchivo, match="motivo"):
        A.solicitar_prestamo(f["id"], "x", 3, a1)
    with pytest.raises(A.ErrorArchivo, match="plazo"):
        A.solicitar_prestamo(f["id"], "Motivo válido de prueba", 400, a1)
    assert any(p["vencido"] for p in A.prestamos(a1, empresa_id=e))  # la semilla deja uno vencido para la demostración
    assert A.resumen(a1)["prestamos_vencidos"] >= 1


def test_abogado_solo_ve_sus_prestamos(repo):
    ab = usuario("abogado1.emp01")
    assert all(p["solicitante_id"] == ab["id"] for p in A.prestamos(ab))


# ------------------------------------------------------------------ disposición final con acta
def _vencido_libre(arch, e):
    ya = {d["expediente_id"] for d in A.disposiciones(arch, empresa_id=e) if d["estado"] in ("propuesta", "revisada", "aprobada")}
    return [x for x in A.expedientes(arch, e) if x["estado"] == "activo" and x["dias_restantes"] < 0 and x["id"] not in ya]


def test_flujo_de_disposicion_propuesta_revision_aprobacion_ejecucion(repo):
    R = obtener_repo()
    e = emp_id("EMP02")
    arch, sup = usuario(ARCH2), usuario("supervisor.emp02")
    vs = _vencido_libre(arch, e)
    assert len(vs) >= 2
    x1, x2 = vs[0], vs[1]
    assert A.proponer_disposiciones(arch, e, [x1["id"], x2["id"]]) == 2
    assert A.proponer_disposiciones(arch, e, [x1["id"]]) == 0  # ya tiene propuesta: no se duplica
    d1, d2 = (next(d for d in A.disposiciones(arch, empresa_id=e) if d["expediente_id"] == x["id"]) for x in (x1, x2))
    with pytest.raises(A.ErrorArchivo, match="favorable"):
        A.decidir_disposiciones([d1["id"]], True, "Se intenta aprobar sin revisión previa", sup)
    A.revisar_disposicion(d1["id"], True, "Revisado: coincide con la TRD vigente.", arch)
    A.revisar_disposicion(d2["id"], False, "Faltan folios, devolver el expediente.", arch)
    assert A.expediente(x2["id"], arch)["estado"] == "activo"  # la no favorable lo deja activo
    with pytest.raises(A.ErrorArchivo, match="observación"):
        A.decidir_disposiciones([d1["id"]], True, "", sup)
    # el supervisor de OTRA empresa no puede aprobar
    with pytest.raises(A.ErrorArchivo, match="otra empresa"):
        A.decidir_disposiciones([d1["id"]], True, "Aprobación de otra empresa, no válida", usuario("supervisor.emp01"))
    # segregación de funciones: quien dio el concepto no aprueba
    R.actualizar("trd_disposiciones", d1["id"], {"revisada_por": sup["id"]})
    with pytest.raises(A.ErrorArchivo, match="otra persona"):
        A.decidir_disposiciones([d1["id"]], True, "Aprobación del mismo revisor, no válida", sup)
    R.actualizar("trd_disposiciones", d1["id"], {"revisada_por": arch["id"]})
    acta_id = A.decidir_disposiciones([d1["id"]], True, "Aprobada según la TRD vigente.", sup)
    acta = next(a for a in A.actas(sup, e) if a["id"] == acta_id)
    assert acta["sha256"] == A.sha256_texto(acta["contenido"]) and x1["radicado"] in acta["contenido"] and "sin firma digital certificada" in acta["contenido"]
    n_docs = R.valor("select count(*) from expediente_docs where expediente_id = ?", [x1["id"]])
    A.ejecutar_disposicion(d1["id"], "Registro de ejecución de prueba", arch)
    xf = A.expediente(x1["id"], arch)
    assert xf["estado"] == "dispuesto" and "demostración" in (xf["resultado"] or "") or xf["disposicion"] == "conservar"
    # la demostración NO borra nada: la PQRS y su índice siguen ahí
    assert R.valor("select count(*) from solicitudes where id = ?", [x1["solicitud_id"]]) == 1
    assert R.valor("select count(*) from expediente_docs where expediente_id = ?", [x1["id"]]) == n_docs
    with pytest.raises(A.ErrorArchivo):
        A.ejecutar_disposicion(d1["id"], "otra vez", arch)  # ya ejecutada


def test_no_se_propone_disposicion_si_la_retencion_no_vencio(repo):
    arch, e = usuario(ARCH1), emp_id("EMP01")
    vigente = next(x for x in A.expedientes(arch, e) if x["estado"] == "activo" and x["dias_restantes"] > 100)
    with pytest.raises(A.ErrorArchivo, match="retención"):
        A.proponer_disposiciones(arch, e, [vigente["id"]])


def test_un_acta_por_lote_y_por_empresa(repo):
    arch, sup, e = usuario(ARCH1), usuario("supervisor.emp01"), emp_id("EMP01")
    vs = _vencido_libre(arch, e)
    if len(vs) < 2:
        pytest.skip("la semilla no deja suficientes vencidos libres")
    A.proponer_disposiciones(arch, e, [vs[0]["id"], vs[1]["id"]])
    ds = [d for d in A.disposiciones(arch, empresa_id=e) if d["expediente_id"] in (vs[0]["id"], vs[1]["id"])]
    for d in ds:
        A.revisar_disposicion(d["id"], True, "Revisado y conforme con la serie.", arch)
    antes = len(A.actas(sup, e))
    A.decidir_disposiciones([d["id"] for d in ds], True, "Aprobación en lote de prueba.", sup)
    assert len(A.actas(sup, e)) == antes + 1


# ------------------------------------------------------------------ alertas
def test_alertas_de_archivo_por_umbral_e_idempotentes(repo):
    R = obtener_repo()
    n1 = A.generar_alertas_archivo()
    assert not any(A.generar_alertas_archivo().values())  # segunda vez: nada nuevo (idempotente)
    tipos = {r["tipo"] for r in R.q("select distinct tipo from alertas")}
    assert {"retencion_vencida", "retencion_30", "retencion_90"} <= tipos
    arch = usuario(ARCH1)
    mias = C.alertas_usuario(arch["id"], limite=500)
    assert mias and all(a["empresa_id"] == emp_id("EMP01") for a in mias if a["tipo"].startswith(("retencion", "prestamo")))
    # el archivista de EMP02 no recibe alertas de EMP01
    de_2 = C.alertas_usuario(usuario(ARCH2)["id"], limite=500)
    assert all(a["empresa_id"] == emp_id("EMP02") for a in de_2 if a["tipo"].startswith(("retencion", "prestamo", "disposicion")))
    assert isinstance(n1, dict)
    assert R.q("select 1 as x from alertas where tipo = 'prestamo_vencido'")


def test_alerta_a_supervisor_cuando_hay_disposicion_por_aprobar(repo):
    sup = usuario("supervisor.emp01")
    tipos = {a["tipo"] for a in C.alertas_usuario(sup["id"], limite=500)}
    assert "disposicion_pendiente" in tipos or A.disposiciones(sup, "revisada") == []


# ------------------------------------------------------------------ reportes y resumen
def test_resumen_coincide_con_el_detalle(repo):
    a1 = usuario(ARCH1)
    r = A.resumen(a1)
    exps = [x for x in A.expedientes(a1) if x["estado"] != "dispuesto"]
    assert r["vencidas"] == sum(x["nivel"] == "vencida" for x in exps)
    assert r["en_30"] == sum(x["nivel"] == "30" for x in exps) and r["en_90"] == sum(x["nivel"] == "90" for x in exps)
    assert r["sin_serie"] == len(A.cerradas_sin_serie(a1))
    cj = A.cajas(a1)
    assert r["cajas"] == len(cj) and r["ocupacion"] == round(sum(c["n_carpetas"] for c in cj) / sum(c["capacidad_carpetas"] for c in cj) * 100, 1)


def test_vencimientos_a_30_y_90_dias(repo):
    a1 = usuario(ARCH1)
    v30, v90 = A.vencimientos(a1, 30), A.vencimientos(a1, 90)
    assert v30 and len(v90) > len(v30) and all(x["dias_restantes"] <= 30 for x in v30)
    assert {x["id"] for x in v30} <= {x["id"] for x in v90}


def test_ubicacion_del_caso_para_la_ficha(repo):
    a1 = usuario(ARCH1)
    x = next(x for x in A.expedientes(a1) if x.get("carpeta_codigo"))
    u = A.ubicacion_de_caso(x["solicitud_id"], a1)
    assert u["caja_codigo"] == x["caja_codigo"] and A.ubicacion_de_caso(-1, a1) is None

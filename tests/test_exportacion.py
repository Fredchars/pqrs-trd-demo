"""A6 · Exportación por empresa con manifiesto SHA-256 (core/exportacion.py, scripts/exportar_empresa.py, pantalla «Exportar empresa»)."""
import io
import json
import zipfile

import pytest
from conftest import RAIZ, usuario
from streamlit.testing.v1 import AppTest

from core import consultas as C
from core import exportacion as X
from core import servicios as S
from core.repositorio import obtener_repo


def _abrir(datos: bytes):
    z = zipfile.ZipFile(io.BytesIO(datos))
    raiz = z.namelist()[0].split("/")[0]
    return z, raiz


def test_paquete_integro_y_solo_de_la_empresa(repo):
    R = obtener_repo()
    emp = C.empresa_por_codigo("EMP02")
    nombre, datos, man = X.generar_bytes("EMP02", usuario("admin"))
    assert nombre.startswith("EMP02_exportacion_") and nombre.endswith(".zip")
    assert X.verificar(io.BytesIO(datos)) == []
    z, raiz = _abrir(datos)
    # conteos = lo que hay en la base para esa empresa
    por_tabla = {t["tabla"]: t["filas"] for t in man["tablas"]}
    assert por_tabla["solicitudes"] == R.valor("select count(*) from solicitudes where empresa_id = ?", [emp["id"]]) > 0
    assert por_tabla["eventos"] == R.valor("select count(*) from eventos where empresa_id = ? and accion <> 'exportacion_empresa'", [emp["id"]]) > 0
    assert por_tabla["correos"] == R.valor("select count(*) from correos where empresa_id = ?", [emp["id"]])
    assert por_tabla["documentos"] == R.valor("select count(*) from documentos d join solicitudes s on s.id = d.solicitud_id "
                                              "where s.empresa_id = ?", [emp["id"]]) > 0
    # nada de otras empresas
    sol = json.loads(z.read(f"{raiz}/datos/solicitudes.json"))
    assert sol and all(s["empresa_id"] == emp["id"] and s["radicado"].startswith("EMP02-") for s in sol)
    texto = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith(f"{raiz}/datos/") and "tipos_pqrs" not in n)
    for otro in ("EMP01", "EMP03", "EMP10"):
        assert f'"{otro}-' not in texto, f"aparece un radicado de {otro}"
    assert {e["empresa_id"] for e in json.loads(z.read(f"{raiz}/datos/eventos.json"))} == {emp["id"]}
    assert {e["codigo"] for e in json.loads(z.read(f"{raiz}/datos/empresas.json"))} == {"EMP02"}
    assert all("auth_id" not in u for u in json.loads(z.read(f"{raiz}/datos/usuarios.json")))
    # archivos del bucket: solo el prefijo EMP02/, y con el hash registrado
    assert man["archivos"] and all(a["ruta"].startswith("archivos/EMP02/") and a["coincide_con_registro"] for a in man["archivos"])
    assert man["archivos_faltantes_en_almacen"] == []
    assert man["verificaciones"] == {"filas_de_otra_empresa": 0, "archivos_con_hash_distinto_al_registrado": 0}
    # la bitácora registra la exportación con el hash del manifiesto
    ev = R.q("select * from eventos where accion = 'exportacion_empresa' order by id desc", uno=True)
    assert ev["empresa_id"] == emp["id"] and ev["usuario_id"] == usuario("admin")["id"]
    detalle = ev["detalle"] if isinstance(ev["detalle"], dict) else json.loads(ev["detalle"])
    assert detalle["sha256_manifiesto"] == man["sha256_manifiesto"]


def test_paquete_incluye_trd_y_archivo_fisico_solo_de_la_empresa(repo):
    R = obtener_repo()
    emp = C.empresa_por_codigo("EMP01")
    _, datos, man = X.generar_bytes("EMP01", usuario("admin"), con_archivos=False)
    assert X.verificar(io.BytesIO(datos)) == [] and man["version"] == 2
    z, raiz = _abrir(datos)
    por_tabla = {t["tabla"]: t["filas"] for t in man["tablas"]}
    for t in ("trd_series", "archivo_cajas", "archivo_carpetas", "expedientes", "expediente_docs", "trd_actas", "trd_disposiciones",
              "archivo_prestamos"):
        assert por_tabla[t] == R.valor(f"select count(*) from {t} where empresa_id = ?", [emp["id"]]) > 0, t
        assert {f["empresa_id"] for f in json.loads(z.read(f"{raiz}/datos/{t}.json"))} == {emp["id"]}
    assert any("TRD" in a for a in man["avisos"])


def test_manifiesto_detecta_alteraciones(repo):
    _, datos, _ = X.generar_bytes("EMP05", usuario("auditor"), con_archivos=True)
    z, raiz = _abrir(datos)
    ok = {n: z.read(n) for n in z.namelist()}

    def con(cambios, quitar=()):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as w:
            for n, c in ok.items():
                if n not in quitar:
                    w.writestr(n, cambios.get(n, c))
            for n in set(cambios) - set(ok):
                w.writestr(n, cambios[n])
        return X.verificar(b)

    assert con({}) == []
    assert any("solicitudes.json" in p for p in con({f"{raiz}/datos/solicitudes.json": b"[]"}))
    assert any("MANIFIESTO" in p for p in con({f"{raiz}/MANIFIESTO.json": ok[f"{raiz}/MANIFIESTO.json"] + b" "}))
    pdf = next(n for n in ok if "/archivos/" in n)
    assert any("cambió" in p for p in con({pdf: b"alterado"}))
    assert any("falta" in p for p in con({}, quitar=(pdf,)))
    assert any("no está en el manifiesto" in p for p in con({f"{raiz}/datos/extra.json": b"[]"}))


@pytest.mark.parametrize("quien,permitido", [("admin", True), ("auditor", True), ("supervisor.emp01", False),
                                             ("abogado1.emp01", False), ("director", False)])
def test_quien_puede_exportar(repo, quien, permitido):
    if permitido:
        assert X.generar_bytes("EMP01", usuario(quien), con_archivos=False)[1]
    else:
        with pytest.raises(X.ErrorExportacion):
            X.generar_bytes("EMP01", usuario(quien), con_archivos=False)
    with pytest.raises(X.ErrorExportacion):
        X.generar_bytes("EMP99", usuario("admin"))


def test_pantalla_exportar_empresa(repo):
    for quien, ve in (("admin", True), ("auditor", True), ("supervisor.emp01", False)):
        at = AppTest.from_file(str(RAIZ / "app" / "Inicio.py"), default_timeout=90)
        at.session_state["usuario"] = usuario(quien)
        at.run()
        if not ve:  # la pantalla ni siquiera está en su menú
            with pytest.raises(ValueError):
                at.switch_page("paginas/exportacion.py")
            continue
        at.switch_page("paginas/exportacion.py")
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        next(b for b in at.button if b.label == "Preparar paquete").click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert any("Paquete listo" in s.value for s in at.success)


# (al final: usa repo_vacio, que en PostgreSQL recrea el esquema y deja sin datos al `repo` del módulo)
def test_caso_trasladado_viaja_y_el_prefijo_antiguo_se_informa(repo_vacio):
    R = obtener_repo()
    s = S.radicar({"empresa_id": C.empresa_por_codigo("EMP03")["id"], "tipo_id": C.tipo_por_codigo("D")["id"],
                   "asunto": "Documento de prueba", "descripcion": "Solicito copia.", "nombre": "Ana Prueba",
                   "email": "ana@correo.example.com", "autoriza_datos": True},
                  archivos=[("soporte.pdf", b"%PDF-1.4 prueba", "application/pdf")])["solicitud"]
    assert R.valor("select count(*) from documentos where solicitud_id = ?", [s["id"]]) >= 1
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    S.trasladar_empresa(s["id"], C.empresa_por_codigo("EMP05")["id"], "Competencia de otra empresa", sup)
    _, d3, m3 = X.generar_bytes("EMP03", usuario("admin"))
    _, d5, m5 = X.generar_bytes("EMP05", usuario("admin"))
    z3, r3 = _abrir(d3)
    z5, r5 = _abrir(d5)
    assert s["radicado"] not in z3.read(f"{r3}/datos/solicitudes.json").decode()
    assert s["radicado"] in z5.read(f"{r5}/datos/solicitudes.json").decode()
    # el archivo sigue guardado bajo EMP03/…: viaja con el caso (EMP05) y EMP03 lo ve listado como no suyo
    assert any(a["ruta"].startswith("archivos/EMP03/") for a in m5["archivos"])
    assert not any(a["ruta"].startswith("archivos/EMP03/") for a in m3["archivos"])
    assert any(r.startswith("EMP03/") for r in m3["archivos_bajo_el_prefijo_que_no_son_de_casos_actuales"])
    assert X.verificar(io.BytesIO(d3)) == [] and X.verificar(io.BytesIO(d5)) == []

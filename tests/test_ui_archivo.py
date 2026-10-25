"""Interfaz: páginas nuevas (inicio, TRD, expedientes, cajas, préstamos, vencimientos, reportes) por rol y pie de página
«Powered by ATm Consulting» en todas las pantallas."""
import pytest
from conftest import usuario
from test_ui import _correr

PIE = "Powered by ATm Consulting"
ARCHIVO = ["inicio", "trd_series", "expedientes", "cajas_rotulos", "prestamos", "vencimientos", "reportes_archivo"]


def _html(at):
    """Texto visible de todos los bloques (sin etiquetas HTML)."""
    import re
    return re.sub(r"<[^>]+>", "", " ".join(m.value for m in at.markdown))


@pytest.mark.parametrize("email", ["archivista.emp01", "archivista.emp02", "supervisor.emp01", "admin", "auditor", "director", "abogado1.emp01"])
def test_paginas_de_archivo_cargan_con_pie(repo, email):
    for p in ARCHIVO:
        if email.startswith("abogado") and p in ("vencimientos", "reportes_archivo"):
            continue  # el abogado consulta expedientes y pide préstamos, pero esas pantallas no están en su menú
        at = _correr(email, p)
        assert PIE in _html(at), f"falta el pie en {p} para {email}"


@pytest.mark.parametrize("email", ["radicador.emp01", "abogado1.emp01"])
def test_paginas_que_tampoco_deben_romperse_con_roles_sin_archivo(repo, email):
    for p in ("mi_bandeja", "inicio"):
        assert PIE in _html(_correr(email, p))


def test_pie_en_pantallas_publicas_y_modo_formulario(repo):
    for p in (None, "consultar_estado", "ingresar", "radicar"):
        assert PIE in _html(_correr(None, p))
    from streamlit.testing.v1 import AppTest

    from conftest import RAIZ
    at = AppTest.from_file(str(RAIZ / "app" / "Inicio.py"), default_timeout=90)
    at.query_params["modo"] = "formulario"
    at.query_params["empresa"] = "EMP01"
    at.run()
    assert not at.exception and PIE in _html(at)


def test_pie_en_pantallas_internas_existentes(repo):
    for email, p in (("supervisor.emp01", "supervision"), ("admin", "administracion"), ("auditor", "bitacora"), ("abogado1.emp01", "reportes")):
        assert PIE in _html(_correr(email, p))


def test_inicio_del_archivista_muestra_indicadores_y_accesos(repo):
    at = _correr("archivista.emp01", "inicio")
    html = _html(at)
    assert "retención" in html.lower() and "Expedientes" in html


def test_indice_tabla_tolera_valores_vacios():
    """Regresión: pandas convierte None en NaN y el índice del expediente fallaba al mostrarse."""
    import sys

    from conftest import RAIZ
    sys.path.insert(0, str(RAIZ / "app"))
    import ui_archivo
    filas = [
        {"orden": 1, "descripcion": "Radicación", "fecha_doc": "2026-01-02", "folio_inicial": 1, "folio_final": 3, "folios": 3, "soporte": "electronico", "sha256": "a" * 64},
        {"orden": 2, "descripcion": "Papel sin huella", "fecha_doc": None, "folio_inicial": None, "folio_final": None, "folios": 4, "soporte": "fisico", "sha256": None},
    ]
    t = ui_archivo.indice_tabla(filas)
    assert list(t["Folios"]) == ["1–3", "4"] and t["Huella SHA-256"].iloc[1] == "—" and t["Fecha"].iloc[1] == "—"
    assert ui_archivo.indice_tabla([]).empty


def test_ficha_del_caso_cerrado_muestra_la_serie_y_la_ubicacion(repo):
    from core import archivo as A
    arch = usuario("archivista.emp01")
    x = next(x for x in A.expedientes(arch) if x.get("carpeta_codigo"))
    at = _correr("archivista.emp01", "detalle_caso", {"caso_id": x["solicitud_id"]})
    txt = " ".join(i.value for i in at.info)
    assert x["serie_codigo"] in txt and x["caja_codigo"] in txt and PIE in _html(at)
    sin = A.cerradas_sin_serie(arch)[0]
    at = _correr("archivista.emp01", "detalle_caso", {"caso_id": sin["id"]})
    assert any("serie documental" in w.value for w in at.warning)

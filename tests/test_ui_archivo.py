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


# ---------------------------------------------------------------- QR de caja sin sesión (se conserva el destino)
def _qr_caja(repo):
    from core import archivo as A
    from core import consultas as C
    u = C.usuario_por_email(f"archivista.emp01@{__import__('core.catalogo_demo').catalogo_demo.DOMINIO}")
    e = C.empresa_por_codigo("EMP01")
    return next(c for c in A.cajas(u, e["id"]))["codigo"]


def test_qr_de_caja_sin_sesion_lleva_al_ingreso_y_conserva_la_caja(repo):
    from streamlit.testing.v1 import AppTest
    from core import catalogo_demo
    from test_ui import APP
    cod = _qr_caja(repo)
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["codigo"] = cod
    at.run()
    at.switch_page("paginas/cajas_rotulos.py")  # como al escanear /cajas?codigo=... sin sesión
    at.run()
    at.switch_page("paginas/ingresar.py")  # AppTest no sigue el switch_page de la página: se simula el salto
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    # sin sesión: aterriza en «Ingresar» con aviso claro de la caja
    assert any(cod in i.value and "Ingrese" in i.value for i in at.info)
    # ingresa como archivista -> se abre la ficha de la caja del QR
    for b in at.button:
        if "Archivista" in b.label:
            b.click()
            break
    else:
        raise AssertionError("no hay botón de acceso rápido de archivista")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(f"Abierto desde el QR: **{cod}**" in s.value for s in at.success), [s.value for s in at.success]
    assert catalogo_demo  # silencia import no usado


def test_qr_de_caja_con_rol_sin_acceso_avisa_en_el_inicio(repo):
    from streamlit.testing.v1 import AppTest
    from test_ui import APP
    cod = _qr_caja(repo)
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["codigo"] = cod
    at.run()
    at.switch_page("paginas/cajas_rotulos.py")
    at.run()
    at.switch_page("paginas/ingresar.py")
    at.run()
    for b in at.button:
        if "Radicador" in b.label:
            b.click()
            break
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("no tiene acceso a las cajas" in w.value for w in at.warning), [w.value for w in at.warning]


# ---------------------------------------------------------------- hallazgos de la verificación de la guía v2
def test_login_demo_texto_veraz_y_clave_opcional(repo, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_ui import APP
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.switch_page("paginas/ingresar.py")
    at.run()
    assert not at.exception
    txt = " ".join(c.value for c in at.caption)
    assert "datos ficticios" in txt and "PQRS_DEMO_CLAVE" in txt and "corre en local" not in txt
    assert any("Archivista" in b.label for b in at.button)
    # con PQRS_DEMO_CLAVE definida se pide la clave y NO se ofrecen los botones
    from core import config  # (la app retira PQRS_DEMO_CLAVE del entorno en pruebas: se simula con el lector de configuración)
    original = config.obtener
    monkeypatch.setattr(config, "obtener", lambda k, d=None: "clave-de-prueba" if k == "PQRS_DEMO_CLAVE" else original(k, d))
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.switch_page("paginas/ingresar.py")
    at.run()
    assert not at.exception
    assert any("Clave de acceso" in t.label for t in at.text_input)
    assert not any("Archivista" in b.label for b in at.button)
    at.text_input[0].input("incorrecta")
    at.button[0].click()
    at.run()
    assert any("Clave incorrecta" in e.value for e in at.error)
    at.text_input[0].input("clave-de-prueba")
    at.button[0].click()
    at.run()
    assert any("Archivista" in b.label for b in at.button)


def test_anios_en_singular_y_plural():
    from conftest import RAIZ
    import sys
    sys.path.insert(0, str(RAIZ / "app"))
    import ui_archivo
    assert ui_archivo.anios(1) == "1 año" and ui_archivo.anios(0) == "0 años" and ui_archivo.anios(5) == "5 años"
    assert ui_archivo.anios(None) == "—"


def test_administracion_en_demo_no_menciona_github_actions_ni_supabase(repo):
    at = _correr("admin", "administracion")
    txt = " ".join(m.value for m in at.markdown)
    assert "GitHub Actions" not in txt and "esta demostración no corren solas" in txt


def test_detalle_en_revision_no_muestra_none_y_el_director_aprueba_por_escalamiento(repo_vacio):
    from core import consultas as C
    from core import servicios as S
    from test_e2e import _caso_en_tramite
    s, _ = _caso_en_tramite("EMP06", "R")
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    S.enviar_a_revision(s["id"], "Respuesta redactada por el único supervisor (ficticia).", sup)
    at = _correr(sup["email"], "detalle_caso", {"caso_id": s["id"]})
    txt = " ".join(c.value for c in at.caption)
    assert not any("None" in c.value for c in at.caption) and "usted mismo" in txt
    assert not any(b.label.startswith("✅ Aprobar") for b in at.button)  # el autor no puede aprobar
    d = C.usuarios("director", s["empresa_id"])[0]
    at = _correr(d["email"], "detalle_caso", {"caso_id": s["id"]})
    assert any(b.label.startswith("✅ Aprobar") for b in at.button)
    capt = " ".join(c.value for c in at.caption)
    assert "Nivel pendiente: 1 (supervisor)" in capt and "escalamiento" in capt and "None" not in capt


def test_asignar_series_sugeridas_refresca_la_tabla(repo):
    from core import archivo as A
    arch = usuario("archivista.emp01")
    e = A.cerradas_sin_serie(arch)
    assert e, "la semilla debe dejar cerradas sin serie"
    at = _correr("archivista.emp01", "expedientes")
    btn = next(b for b in at.button if "Asignar las series sugeridas" in b.label)
    btn.click()
    at.run()
    assert not at.exception, [x.value for x in at.exception]
    quedan = A.cerradas_sin_serie(arch)
    assert len(quedan) < len(e)
    # la pestaña refleja el nuevo número (sin necesidad de recargar a mano)
    assert any(f"Cerradas sin serie ({len(quedan)})" in t.label for t in at.tabs)
    assert any("expediente(s) creados" in s.value for s in at.success)

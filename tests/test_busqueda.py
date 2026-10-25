"""Criterio 9: una palabra que solo aparece dentro de un PDF adjunto encuentra el caso (sin importar tildes)."""
from conftest import usuario
from core import consultas as C
from core import semilla


def test_palabra_solo_en_pdf(repo):
    admin = usuario("admin")
    for consulta in ("hidrómetro ultrasónico", "hidrometro ultrasonico", "HIDROMETRO"):
        res = C.buscar(admin, consulta)
        assert len(res) == 1, consulta
        assert res[0]["coincidencia_en"].startswith("documento")
    s = res[0]
    assert "hidr" not in (s["asunto"] + (s["descripcion"] or "")).lower()


def test_busqueda_por_radicado_y_documento(repo):
    admin = usuario("admin")
    s = C.listar_solicitudes(None, {}, sin_alcance=True)[10]
    assert [x["id"] for x in C.buscar(admin, s["radicado"].lower())] == [s["id"]]
    doc = repo.valor("select num_doc from solicitantes where id = ?", [s["solicitante_id"]])
    if doc:
        assert s["id"] in [x["id"] for x in C.buscar(admin, doc)]


def test_busqueda_en_respuestas_y_filtros(repo):
    admin = usuario("admin")
    res = C.buscar(admin, "en atención a su solicitud")
    assert res and all("coincidencia_en" in r for r in res)
    emp = C.empresa_por_codigo("EMP02")
    res2 = C.buscar(admin, "en atención a su solicitud", {"empresa_id": [emp["id"]]})
    assert res2 and all(r["empresa_id"] == emp["id"] for r in res2)
    rojos = C.buscar(admin, "", {"semaforo": ["rojo", "negro"]})
    assert all(r["sem_nivel"] in ("rojo", "negro") for r in rojos)

"""Criterio 4: 30 casos entre 3 abogados con cargas distintas; el ausente no recibe."""
from datetime import date, datetime, timedelta

from core import reparto
from core.reloj import TZ

HOY = date(2026, 10, 15)


def _abogados(ausente_id=None):
    lejos = HOY + timedelta(days=40)
    ab = [reparto.Abogado(1, "A", casos=[reparto.CasoAbierto(1.0, lejos)] * 10),
          reparto.Abogado(2, "B", casos=[reparto.CasoAbierto(1.0, lejos)] * 4),
          reparto.Abogado(3, "C", casos=[]),
          reparto.Abogado(4, "Ausente", ausente_desde=HOY - timedelta(days=1), ausente_hasta=HOY + timedelta(days=5))]
    return ab


def test_30_casos_equilibrados_y_ausente_sin_casos():
    ab = _abogados()
    casos = [reparto.CasoAbierto(1.0, HOY + timedelta(days=30)) for _ in range(30)]
    res = reparto.repartir(casos, ab, HOY, "E", ahora=datetime(2026, 10, 15, 9, tzinfo=TZ))
    assert None not in res
    assert 4 not in res
    cargas = [reparto.carga_ponderada(a.casos, HOY) for a in ab[:3]]
    assert max(cargas) - min(cargas) <= 1.0
    assert sum(len(a.casos) for a in ab[:3]) == 14 + 30


def test_carga_ponderada_pesos_y_urgencia():
    casos = [reparto.CasoAbierto(2.0, HOY + timedelta(days=30)), reparto.CasoAbierto(1.0, HOY + timedelta(days=1))]
    assert reparto.carga_ponderada(casos, HOY) == 2.0 + 2.0


def test_especialidad_y_cola_del_supervisor():
    ab = _abogados()
    ab[1].especialidades = ["datos_personales"]
    assert reparto.elegir_abogado(ab, HOY, "E", "datos_personales").id == 2
    assert reparto.elegir_abogado(ab, HOY, "E", "tributario") is None  # nadie: cola
    assert reparto.elegir_abogado(ab, HOY, "D") is None


def test_capacidad_maxima_y_no_disponible():
    ab = _abogados()
    ab[2].capacidad_max = 0
    ab[1].disponible = False
    assert reparto.elegir_abogado(ab, HOY, "A").id == 1


def test_turno_rotativo():
    ab = _abogados()[:3]
    res = reparto.repartir([reparto.CasoAbierto(1.0, HOY)] * 6, ab, HOY, "B", ahora=datetime(2026, 10, 15, 9, tzinfo=TZ))
    assert sorted(res) == [1, 1, 2, 2, 3, 3]


def test_reparto_real_en_base_de_datos(repo_vacio):
    """Con la base: 30 radicaciones en EMP02; el abogado ausente no recibe ninguna."""
    from core import consultas as C
    from core import servicios as S
    emp = C.empresa_por_codigo("EMP02")
    abogs = C.usuarios("abogado", emp["id"])
    ausente = abogs[2]
    S.marcar_ausencia(ausente["id"], HOY - timedelta(days=400), HOY + timedelta(days=400), True,
                      C.usuarios("supervisor", emp["id"])[0])
    tp = C.tipo_por_codigo("P")
    for i in range(30):
        S.radicar({"empresa_id": emp["id"], "tipo_id": tp["id"], "asunto": f"Petición de prueba {i}",
                   "descripcion": f"Descripción ficticia número {i} para el reparto.", "nombre": "Ciudadana Prueba",
                   "email": f"c{i}@correo.example.com", "num_doc": str(10000 + i), "autoriza_datos": True})
    carga = {c["abogado_id"]: c for c in C.carga_equipo(emp["id"])}
    assert carga[ausente["id"]]["casos_abiertos"] == 0
    activos = [carga[a["id"]]["casos_abiertos"] for a in abogs[:2]]
    assert sum(activos) == 30 and abs(activos[0] - activos[1]) <= 1


def test_capacidad_configurable_por_abogado():
    from datetime import date
    h = date(2026, 3, 2)
    casos = [reparto.CasoAbierto(1.0, date(2026, 4, 1))] * 60
    assert not reparto.Abogado(2, capacidad_max=40, casos=list(casos)).puede_recibir(h)
    assert reparto.Abogado(3, capacidad_max=80, casos=list(casos)).puede_recibir(h)


def test_capacidad_por_defecto_parametrizable(repo_vacio):
    from core import servicios as S
    from core.repositorio import obtener_repo
    from core import consultas as C
    assert S.capacidad_defecto() == 40
    obtener_repo().ex("update parametros set valor = ? where clave = ?", ["55", "capacidad_max_defecto"])
    C.limpiar_cache()
    assert S.capacidad_defecto() == 55

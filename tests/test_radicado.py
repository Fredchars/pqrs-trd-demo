from core import radicado as rad


def test_formato_y_extraccion():
    n = rad.formatear("EMP01", 2026, "Q", 12)
    assert n == "EMP01-2026-Q-000012"
    assert rad.es_radicado(n)
    assert rad.extraer("RE: respuesta al radicado emp01-2026-q-000012 gracias") == n
    assert rad.extraer("sin número") is None
    assert rad.formatear("EMP10", 2026, "CD", 1) == "EMP10-2026-CD-000001"


def test_codigo_consulta_se_guarda_como_hash():
    c = rad.nuevo_codigo()
    assert len(c) == 8
    h = rad.hash_codigo("EMP01-2026-Q-000012", c)
    assert c not in h
    assert rad.verificar_codigo("EMP01-2026-Q-000012", c.lower(), h) or rad.verificar_codigo("EMP01-2026-Q-000012", c, h)
    assert not rad.verificar_codigo("EMP01-2026-Q-000012", "XXXXXXXX", h)


def test_consecutivo_por_empresa_y_anio_sin_huecos(repo_vacio):
    a = [repo_vacio.siguiente_consecutivo(1, 2026) for _ in range(5)]
    b = repo_vacio.siguiente_consecutivo(2, 2026)
    c = repo_vacio.siguiente_consecutivo(1, 2027)
    assert a == [1, 2, 3, 4, 5] and b == 1 and c == 1


def test_consecutivo_concurrente(repo_vacio):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda _: repo_vacio.siguiente_consecutivo(3, 2026), range(40)))
    assert sorted(res) == list(range(1, 41))

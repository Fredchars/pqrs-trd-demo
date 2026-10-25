"""A2 · empresa_id en correos, alertas y eventos: se deriva del caso (o del buzón), la clave foránea compuesta impide
mezclar empresas y el traslado de un caso mueve sus registros. Corre en SQLite y, con PQRS_TEST_PG_URL, en PostgreSQL."""
import pytest
from conftest import usuario

from core import consultas as C
from core import correo
from core import servicios as S
from core.repositorio import obtener_repo

TABLAS = ("correos", "alertas", "eventos")


def _radicar(emp="EMP03", tipo="D"):
    return S.radicar({"empresa_id": C.empresa_por_codigo(emp)["id"], "tipo_id": C.tipo_por_codigo(tipo)["id"],
                      "asunto": "Documento de prueba", "descripcion": "Solicito copia de documento ficticio.",
                      "nombre": "Ana Prueba", "email": "ana@correo.example.com", "autoriza_datos": True})["solicitud"]


def test_todo_registro_con_caso_hereda_la_empresa_del_caso(repo):
    R = obtener_repo()
    for t in TABLAS:
        n = R.valor(f"select count(*) from {t} x where x.solicitud_id is not null")
        assert n > 0, t
        malos = R.valor(f"select count(*) from {t} x join solicitudes s on s.id = x.solicitud_id "
                        "where x.empresa_id is null or x.empresa_id <> s.empresa_id")
        assert malos == 0, f"{t}: filas con empresa distinta de la de su caso"


def test_empresa_no_se_confia_al_cliente(repo_vacio):
    """Aunque quien inserta indique otra empresa, manda la del caso."""
    s = _radicar("EMP03")
    otra = C.empresa_por_codigo("EMP04")["id"]
    obtener_repo().insertar("alertas", {"solicitud_id": s["id"], "empresa_id": otra, "tipo": "info", "programada_para": "2026-01-01",
                                        "clave": "prueba-empresa-cliente"})
    fila = obtener_repo().q("select empresa_id from alertas where clave = ?", ["prueba-empresa-cliente"], uno=True)
    assert fila["empresa_id"] == s["empresa_id"]


@pytest.mark.parametrize("tabla", ["correos", "alertas"])
def test_clave_foranea_compuesta_rechaza_empresa_distinta(repo_vacio, tabla):
    """Cambiar empresa_id a mano (sin pasar por el caso) viola (solicitud_id, empresa_id) -> solicitudes(id, empresa_id)."""
    R = obtener_repo()
    s = _radicar("EMP03")
    otra = C.empresa_por_codigo("EMP04")["id"]
    fila = R.q(f"select id from {tabla} where solicitud_id = ? limit 1", [s["id"]], uno=True)
    assert fila, f"el radicado debe dejar al menos una fila en {tabla}"
    with pytest.raises(Exception):
        R.ex(f"update {tabla} set empresa_id = ? where id = ?", [otra, fila["id"]])


def test_evento_con_caso_exige_empresa_en_sqlite_y_pg(repo_vacio):
    """El CHECK: un registro con caso no puede quedar sin empresa (MATCH SIMPLE no validaría la clave compuesta)."""
    R = obtener_repo()
    s = _radicar("EMP03")
    if R.es_pg:  # en PG el disparador siempre la rellena: se prueba el CHECK con el disparador de bitácora aparte
        pytest.skip("en PostgreSQL el disparador rellena empresa_id antes del CHECK (cubierto en test_aislamiento_pg)")
    with pytest.raises(Exception):
        R.ex("insert into eventos (solicitud_id, empresa_id, origen, accion, fecha) values (?, NULL, 'app', 'x', '2026-01-01')",
             [s["id"]])


def test_cuarentena_toma_la_empresa_del_buzon_de_destino(repo_vacio):
    R = obtener_repo()
    emp2 = C.empresa_por_codigo("EMP02")
    cid = correo.simular_entrante(R, "promo@spam.example.com", emp2["buzon_correo"], "Gana dinero rápido", "Gana dinero rápido ya.")
    assert S.leer_correo()[0]["resultado"] == "cuarentena"
    assert R.valor("select empresa_id from correos where id = ?", [cid]) == emp2["id"]
    ev = R.q("select empresa_id from eventos where accion = 'correo_cuarentena'", uno=True)
    assert ev["empresa_id"] == emp2["id"]


def test_cuarentena_buzon_desconocido_queda_sin_empresa(repo_vacio):
    R = obtener_repo()
    cid = correo.simular_entrante(R, "promo@spam.example.com", "nadie@desconocido.example.com", "Gana dinero rápido",
                                  "Gana dinero rápido ya.")
    S.leer_correo()
    assert R.valor("select empresa_id from correos where id = ?", [cid]) is None
    assert R.valor("select empresa_id from eventos where accion = 'correo_cuarentena'") is None
    # solo el administrador puede liberarlo; el radicador de una empresa no
    with pytest.raises(S.ErrorNegocio):
        S.liberar_cuarentena(cid, usuario("radicador.emp01"))
    assert S.liberar_cuarentena(cid, usuario("admin"))["resultado"] == "radicada"


def test_liberar_cuarentena_de_otra_empresa_se_rechaza(repo_vacio):
    R = obtener_repo()
    emp2 = C.empresa_por_codigo("EMP02")
    cid = correo.simular_entrante(R, "promo@spam.example.com", emp2["buzon_correo"], "Gana dinero rápido", "Gana dinero rápido ya.")
    S.leer_correo()
    with pytest.raises(S.ErrorNegocio):
        S.liberar_cuarentena(cid, usuario("radicador.emp01"))
    assert S.liberar_cuarentena(cid, usuario("radicador.emp02"))["resultado"] == "radicada"
    # al radicarse, el correo queda con la empresa del caso creado
    assert R.valor("select empresa_id from correos where id = ?", [cid]) == emp2["id"]


def test_buzon_solo_muestra_correos_de_la_empresa(repo_vacio):
    R = obtener_repo()
    for cod in ("EMP01", "EMP02"):
        correo.simular_entrante(R, f"ciudadano.{cod}@correo.example.com", C.empresa_por_codigo(cod)["buzon_correo"],
                                "Consulta", "Buenos días, ¿cómo va mi trámite?")
    S.leer_correo()
    emp1, emp2 = C.empresa_por_codigo("EMP01")["id"], C.empresa_por_codigo("EMP02")["id"]
    r1 = C.correos(usuario("radicador.emp01"))
    assert r1 and {c["empresa_id"] for c in r1} == {emp1}
    assert {c["empresa_id"] for c in C.correos(usuario("supervisor.emp02"))} == {emp2}
    assert {c["empresa_id"] for c in C.correos(usuario("admin"))} >= {emp1, emp2}
    assert C.correos(usuario("abogado1.emp01")) == []
    assert C.correos(None) == []


def test_traslado_mueve_correos_alertas_y_eventos_con_el_caso(repo_vacio):
    R = obtener_repo()
    s = _radicar("EMP03")
    antes = {t: R.valor(f"select count(*) from {t} where solicitud_id = ?", [s["id"]]) for t in TABLAS}
    assert antes["eventos"] > 0
    destino = C.empresa_por_codigo("EMP05")
    sup = C.usuarios("supervisor", s["empresa_id"])[0]
    S.trasladar_empresa(s["id"], destino["id"], "Competencia de otra empresa", sup)
    for t in TABLAS:
        filas = R.q(f"select empresa_id from {t} where solicitud_id = ?", [s["id"]])
        assert len(filas) >= antes[t], f"{t}: no se debe perder historia"
        assert {f["empresa_id"] for f in filas} == {destino["id"]}, f"{t}: debe viajar con el caso"
    # la bitácora sigue siendo inmutable
    with pytest.raises(Exception):
        R.ex("update eventos set accion = 'alterada' where solicitud_id = ?", [s["id"]])
    with pytest.raises(Exception):
        R.ex("delete from eventos where solicitud_id = ?", [s["id"]])


def test_evento_sin_caso_conserva_empresa_indicada(repo_vacio):
    S.evento(None, None, "prueba_sin_caso", {"x": 1}, empresa_id=C.empresa_por_codigo("EMP02")["id"])
    S.evento(None, None, "prueba_sin_empresa", {"x": 1})
    R = obtener_repo()
    assert R.valor("select empresa_id from eventos where accion = 'prueba_sin_caso'") == C.empresa_por_codigo("EMP02")["id"]
    assert R.valor("select empresa_id from eventos where accion = 'prueba_sin_empresa'") is None


def test_migracion_04_es_idempotente_y_rellena_datos_antiguos(repo_vacio):
    """PostgreSQL: reaplicar db/04 no falla ni cambia nada, y sobre una base «antigua» (sin empresa_id) la rellena."""
    from core import config
    R = obtener_repo()
    if not R.es_pg:
        pytest.skip("migración SQL: solo PostgreSQL")
    sql = (config.RAIZ / "db" / "04_aislamiento_empresa.sql").read_text(encoding="utf-8")
    _radicar("EMP03")
    _radicar("EMP05")
    import conftest
    if conftest.ROL_SERVICIO:  # migrar el esquema es trabajo del dueño, no del rol de servicio (sin DDL)
        R.cerrar()
        R.url = conftest.PG_URL
        R._conectar_pg()
    # Los eventos SIN caso (p. ej. «caja_creada» del archivo físico) llevan su empresa de origen y no se pueden derivar de un
    # caso: pertenecen a una base posterior a la migración 04, así que no entran en la foto de «datos antiguos».
    def _foto():
        return {t: R.valor(f"select count(*) from {t} where empresa_id is not null"
                           + (" and solicitud_id is not null" if t == "eventos" else "")) for t in TABLAS}
    foto = _foto()
    R.conn.execute(sql)
    R.conn.execute(sql)
    assert foto == _foto()
    # base «antigua»: se quita la protección y se borran los valores
    for t in TABLAS:
        R.ex(f"alter table {t} drop constraint fk_{t}_solicitud_empresa")
        R.ex(f"alter table {t} drop constraint ck_{t}_empresa_con_caso")
    R.ex("alter table eventos disable trigger tr_eventos_inmutables")
    for t in TABLAS:
        R.ex(f"update {t} set empresa_id = null")
    R.ex("alter table eventos enable trigger tr_eventos_inmutables")
    R.conn.execute(sql)
    assert foto == _foto()
    for t in TABLAS:
        assert R.valor(f"select count(*) from {t} x join solicitudes s on s.id = x.solicitud_id "
                       "where x.empresa_id <> s.empresa_id") == 0
    assert R.valor("select count(*) from pg_trigger where tgname = 'tr_eventos_inmutables' and tgenabled = 'O'") == 1


def test_migracion_sqlite_de_base_antigua(tmp_path):
    """SQLite: una base creada antes de la migración 04 se actualiza sola al abrirla y conserva la bitácora inmutable."""
    import sqlite3

    from core.repositorio import Repositorio
    ruta = tmp_path / "vieja.sqlite"
    cx = sqlite3.connect(ruta)
    cx.executescript("""
      create table empresas (id integer primary key, buzon_correo text);
      create table solicitudes (id integer primary key, empresa_id integer not null);
      create table usuarios (id integer primary key);
      create table alertas (id integer primary key, solicitud_id integer, tipo text);
      create table correos (id integer primary key, direccion text, para text, solicitud_id integer);
      create table eventos (id integer primary key, solicitud_id integer, usuario_id integer, origen text, accion text,
                            detalle text, fecha text);
      create trigger tr_eventos_no_update before update on eventos
        begin select raise(abort, 'inmutable'); end;
      insert into empresas values (1, 'a@x.com'), (2, 'b@x.com');
      insert into solicitudes values (10, 2);
      insert into alertas values (1, 10, 'x');
      insert into eventos values (1, 10, null, 'app', 'creada', '{}', '2026-01-01');
      insert into correos values (1, 'entrada', 'b@x.com', null), (2, 'entrada', 'zzz@x.com', null), (3, 'salida', 'q@x.com', 10);
    """)
    cx.close()
    r = Repositorio("sqlite", ruta_sqlite=ruta)
    assert r.valor("select empresa_id from alertas where id = 1") == 2
    assert r.valor("select empresa_id from eventos where id = 1") == 2
    assert r.valor("select empresa_id from correos where id = 1") == 2     # por buzón de destino
    assert r.valor("select empresa_id from correos where id = 2") is None  # buzón desconocido
    assert r.valor("select empresa_id from correos where id = 3") == 2     # por caso
    with pytest.raises(Exception):
        r.ex("update eventos set accion = 'alterada' where id = 1")
    r.ex("update eventos set empresa_id = 1 where id = 1")                 # único cambio permitido (traslado)
    assert not r.fk_compuesta()
    r.propagar_empresa(10, 1)
    assert r.valor("select empresa_id from alertas where id = 1") == 1
    Repositorio("sqlite", ruta_sqlite=ruta)  # reabrir no falla (idempotente)

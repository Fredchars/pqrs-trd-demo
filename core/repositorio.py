"""Acceso a datos con dos motores intercambiables.

- **postgres** (Supabase): se activa con DATABASE_URL. Las lecturas por usuario corren con
  `SET LOCAL ROLE authenticated` + claims JWT, así que las políticas RLS de db/02_rls.sql
  se aplican de verdad dentro de la base de datos.
- **sqlite** (modo demo, por defecto): archivo local que se crea y se llena con datos
  ficticios la primera vez. La visibilidad por empresa se aplica en la capa de servicios
  (la misma regla que RLS).

Las consultas se escriben con marcadores `?`; el adaptador los convierte para psycopg.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from core import config
from core.reloj import TZ

BOOL_COLS = {"activo", "acepta_anonimas", "disponible", "anonimo", "autoriza_datos", "prorrogada", "revisar_duplicado",
             "respuesta_parcial", "reabierta", "es_parcial", "urgente", "leida", "sensible", "pendiente_completar", "activa",
             "docs_fisicos"}
JSON_COLS = {"detalle", "filtros"}
LIST_COLS = {"especialidades"}
TABLAS = ["empresas", "usuarios", "usuario_empresa", "tipos_pqrs", "temas", "solicitantes", "solicitudes", "asignaciones",
          "respuestas", "aprobaciones", "documentos", "alertas", "plantillas", "eventos", "consecutivos", "festivos_extra",
          "correos_procesados", "parametros", "correos", "filtros_guardados", "encuestas",
          # módulos TRD y archivo físico (db/06_trd_archivo.sql)
          "trd_series", "archivo_cajas", "archivo_carpetas", "expedientes", "expediente_docs", "trd_actas",
          "trd_disposiciones", "archivo_prestamos"]
TABLAS_ARCHIVO = TABLAS[21:]
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(x: str) -> str:
    if not _IDENT.match(x):
        raise ValueError(f"Identificador inválido: {x}")
    return x


def _fts_consulta(texto: str) -> str | None:
    toks = re.findall(r"\w+", texto or "", flags=re.UNICODE)
    toks = [t for t in toks if len(t) >= 2]
    if not toks:
        return None
    return " ".join(f'"{t}"*' for t in toks)


# Tablas con empresa_id derivado: del caso (solicitud_id) o, en correos entrantes sin caso, del buzón de destino.
# En PostgreSQL lo rellenan disparadores (db/04_aislamiento_empresa.sql); en SQLite, estos métodos.
TABLAS_EMPRESA_DERIVADA = ("correos", "alertas", "eventos")


def _direcciones(texto) -> set[str]:
    return {x.strip(" <>").lower() for x in re.split(r"[,;\s]+", texto or "") if x.strip(" <>")}


class Repositorio:
    def __init__(self, tipo: str | None = None, url: str | None = None, ruta_sqlite: str | Path | None = None):
        self.tipo = tipo or config.backend()
        self._lock = threading.RLock()
        self._prof = 0
        if self.tipo == "postgres":
            self.url = url or config.obtener("DATABASE_URL")
            self._conectar_pg()
        else:
            self.ruta = Path(ruta_sqlite or (config.dir_datos() / "pqrs_demo.sqlite"))
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.ruta), check_same_thread=False, isolation_level=None, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.migrar_sqlite()

    # ------------------------------------------------------------------ conexión
    def _conectar_pg(self):
        import psycopg
        from psycopg.rows import dict_row
        self.conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                                    connect_timeout=15)

    @property
    def es_pg(self) -> bool:
        return self.tipo == "postgres"

    def cerrar(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ conversión
    def _param(self, v):
        if self.es_pg:
            if isinstance(v, dict):
                from psycopg.types.json import Jsonb
                return Jsonb(v)
            return v
        if isinstance(v, datetime):
            v = v if v.tzinfo else v.replace(tzinfo=TZ)
            return v.astimezone(TZ).isoformat(timespec="seconds")
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, default=str)
        return v

    def _fila(self, r) -> dict:
        d = dict(r)
        for k, v in d.items():
            if v is None:
                continue
            if isinstance(v, datetime):
                d[k] = v.astimezone(TZ).isoformat(timespec="seconds") if v.tzinfo else v.isoformat(timespec="seconds")
            elif isinstance(v, date):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
            elif k in BOOL_COLS and isinstance(v, int):
                d[k] = bool(v)
            elif (k in JSON_COLS or k in LIST_COLS) and isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except ValueError:
                    pass
            elif k == "auth_id" and not isinstance(v, str):
                d[k] = str(v)
        return d

    def _sql(self, sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s") if self.es_pg else sql

    def _ejecutar(self, sql, params):
        ps = tuple(self._param(p) for p in params)
        if self.es_pg:
            import psycopg
            try:
                cur = self.conn.cursor()
                cur.execute(self._sql(sql), ps)
                return cur
            except (psycopg.OperationalError, psycopg.InterfaceError):
                if self._prof:
                    raise
                self.cerrar()
                self._conectar_pg()
                cur = self.conn.cursor()
                cur.execute(self._sql(sql), ps)
                return cur
        return self.conn.execute(sql, ps)

    # ------------------------------------------------------------------ API genérica
    def q(self, sql: str, params=(), uno: bool = False):
        with self._lock:
            cur = self._ejecutar(sql, params)
            if cur.description is None:
                return None if uno else []
            filas = [self._fila(r) for r in cur.fetchall()]
        return (filas[0] if filas else None) if uno else filas

    def valor(self, sql: str, params=()):
        f = self.q(sql, params, uno=True)
        return next(iter(f.values())) if f else None

    def ex(self, sql: str, params=()) -> int:
        with self._lock:
            cur = self._ejecutar(sql, params)
            return cur.rowcount

    # ------------------------------------------------------------------ empresa derivada (solo SQLite)
    def empresa_por_buzon(self, para) -> int | None:
        """Empresa dueña del buzón de destino; None si no hay exactamente una (cuarentena sin empresa conocida)."""
        dest = _direcciones(para)
        ids = {r["id"] for r in self.q("select id, buzon_correo from empresas where coalesce(buzon_correo, '') <> ''")
               if r["buzon_correo"].strip().lower() in dest}
        return ids.pop() if len(ids) == 1 else None

    def _con_empresa(self, tabla: str, filas: list[dict]) -> list[dict]:
        """Copia de las filas con empresa_id (la del caso manda; en correos entrantes sin caso, la del buzón)."""
        if self.es_pg or tabla not in TABLAS_EMPRESA_DERIVADA or not filas:
            return filas
        sids = sorted({f["solicitud_id"] for f in filas if f.get("solicitud_id") is not None})
        emp: dict[int, int] = {}
        for i in range(0, len(sids), 500):
            lote = sids[i:i + 500]
            for r in self.q(f"select id, empresa_id from solicitudes where id in ({', '.join('?' for _ in lote)})", lote):
                emp[r["id"]] = r["empresa_id"]
        buzones: dict[str, int | None] = {}
        res = []
        for f in filas:
            g = dict(f)
            if g.get("solicitud_id") is not None:
                g["empresa_id"] = emp.get(g["solicitud_id"])
            elif g.get("empresa_id") is None and tabla == "correos" and g.get("direccion") == "entrada":
                clave = g.get("para") or ""
                if clave not in buzones:
                    buzones[clave] = self.empresa_por_buzon(clave)
                g["empresa_id"] = buzones[clave]
            else:
                g.setdefault("empresa_id", None)
            res.append(g)
        return res

    def migrar_sqlite(self):
        """Pone al día una base SQLite creada antes de la migración 04 (empresa_id en correos, alertas y eventos).
        Sin clave foránea compuesta (SQLite no permite agregarla con ALTER): el CHECK de las bases nuevas tampoco existe aquí;
        servicios.trasladar_empresa propaga empresa_id a mano en ese caso (ver propagar_empresa)."""
        if self.es_pg:
            return
        existentes = {r[0] for r in self.conn.execute("select name from sqlite_master where type = 'table'")}
        if "eventos" not in existentes:
            return
        with self._lock:
            for t in TABLAS_EMPRESA_DERIVADA:
                cols = {r[1] for r in self.conn.execute(f"pragma table_info({t})")}
                if "empresa_id" not in cols:
                    self.conn.execute(f"alter table {t} add column empresa_id integer references empresas(id)")
                    if t == "eventos":
                        self.conn.execute("drop trigger if exists tr_eventos_no_update")
                    self.conn.execute(f"update {t} set empresa_id = (select s.empresa_id from solicitudes s "
                                      f"where s.id = {t}.solicitud_id) where solicitud_id is not null")
                    self.conn.execute(f"create index if not exists ix_{t}_empresa on {t} (empresa_id)")
            for r in self.q("select id, para from correos where solicitud_id is null and direccion = 'entrada' "
                            "and empresa_id is null"):
                self.conn.execute("update correos set empresa_id = ? where id = ?", [self.empresa_por_buzon(r["para"]), r["id"]])
            self.conn.execute(_SQL_TRIGGER_EVENTOS_SQLITE)
            self.conn.execute("create unique index if not exists uq_solicitudes_id_empresa on solicitudes (id, empresa_id)")
            self._migrar_archivo_sqlite()

    def _migrar_archivo_sqlite(self):
        """Pone al día una base SQLite anterior a db/06 (módulos TRD y archivo físico): rol «archivista», columnas de papel
        en solicitudes y tablas nuevas. Idempotente."""
        cols = {r[1] for r in self.conn.execute("pragma table_info(solicitudes)")}
        for c in ("docs_fisicos", "hojas_fisicas"):
            if c not in cols:
                self.conn.execute(f"alter table solicitudes add column {c} integer not null default 0")
        ddl = self.conn.execute("select sql from sqlite_master where type = 'table' and name = 'usuarios'").fetchone()
        if ddl and "'archivista'" not in ddl[0] and "'integracion')" in ddl[0]:
            # SQLite no permite cambiar un CHECK con ALTER: se relaja la definición guardada (solo agrega un valor permitido).
            nuevo = ddl[0].replace("'integracion')", "'integracion','archivista')", 1)
            version = self.conn.execute("pragma schema_version").fetchone()[0]
            self.conn.execute("pragma writable_schema = on")
            self.conn.execute("update sqlite_master set sql = ? where type = 'table' and name = 'usuarios'", [nuevo])
            self.conn.execute(f"pragma schema_version = {version + 1}")
            self.conn.execute("pragma writable_schema = off")
        self.conn.executescript((config.RAIZ / "core" / "esquema_sqlite_archivo.sql").read_text(encoding="utf-8"))

    def fk_compuesta(self) -> bool:
        """True si empresa_id viaja por clave foránea compuesta (ON UPDATE CASCADE); False en bases SQLite antiguas migradas."""
        if self.es_pg:
            return True
        return any(r[2] == "solicitudes" and r[3] == "empresa_id" for r in self.conn.execute("pragma foreign_key_list(correos)"))

    def propagar_empresa(self, solicitud_id: int, empresa_id: int):
        """Mueve empresa_id de correos, alertas y eventos de un caso trasladado. Solo hace falta si no hay FK compuesta."""
        if self.fk_compuesta():
            return
        for t in TABLAS_EMPRESA_DERIVADA:
            self.ex(f"update {t} set empresa_id = ? where solicitud_id = ?", [empresa_id, solicitud_id])

    def insertar(self, tabla: str, datos: dict, devolver_id: bool = True):
        datos = self._con_empresa(tabla, [datos])[0]
        cols = [_ident(c) for c in datos]
        marc = ", ".join("?" for _ in cols)
        sql = f"insert into {_ident(tabla)} ({', '.join(cols)}) values ({marc})"
        if devolver_id:
            sql += " returning id"
            return self.valor(sql, list(datos.values()))
        self.ex(sql, list(datos.values()))
        return None

    def actualizar(self, tabla: str, id_, cambios: dict, clave: str = "id") -> int:
        if not cambios:
            return 0
        if tabla == "correos" and cambios.get("solicitud_id") is not None and not self.es_pg:
            cambios = self._con_empresa(tabla, [cambios])[0]
        sets = ", ".join(f"{_ident(c)} = ?" for c in cambios)
        return self.ex(f"update {_ident(tabla)} set {sets} where {_ident(clave)} = ?", [*cambios.values(), id_])

    def carga_masiva(self, tabla: str, filas: list[dict]):
        if not filas:
            return
        filas = self._con_empresa(tabla, filas)
        cols = list(filas[0].keys())
        sql = f"insert into {_ident(tabla)} ({', '.join(_ident(c) for c in cols)}) values ({', '.join('?' for _ in cols)})"
        with self._lock:
            if self.es_pg:
                with self.conn.cursor() as cur:
                    cur.executemany(self._sql(sql), [tuple(self._param(f.get(c)) for c in cols) for f in filas])
            else:
                self.conn.executemany(sql, [tuple(self._param(f.get(c)) for c in cols) for f in filas])

    @contextmanager
    def transaccion(self):
        with self._lock:
            if self.es_pg:
                self._prof += 1
                try:
                    with self.conn.transaction():
                        yield self
                finally:
                    self._prof -= 1
                return
            if self._prof == 0:
                self.conn.execute("BEGIN IMMEDIATE")
                self._prof += 1
                try:
                    yield self
                    self.conn.execute("COMMIT")
                except BaseException:
                    self.conn.execute("ROLLBACK")
                    raise
                finally:
                    self._prof -= 1
            else:
                n = self._prof
                self.conn.execute(f"SAVEPOINT sp{n}")
                self._prof += 1
                try:
                    yield self
                    self.conn.execute(f"RELEASE sp{n}")
                except BaseException:
                    self.conn.execute(f"ROLLBACK TO sp{n}")
                    self.conn.execute(f"RELEASE sp{n}")
                    raise
                finally:
                    self._prof -= 1

    @contextmanager
    def como_usuario(self, usuario: dict | None):
        """Lecturas con los permisos del usuario. En PostgreSQL aplica RLS real."""
        if not self.es_pg or not usuario or not (usuario.get("auth_id") or usuario.get("email")):
            yield self
            return
        with self.transaccion():
            claims = {"email": usuario.get("email") or "", "role": "authenticated"}
            if usuario.get("auth_id"):  # auth.uid() convierte 'sub' a uuid: no enviar cadenas vacías
                claims["sub"] = str(usuario["auth_id"])
            self.q("select set_config('request.jwt.claims', ?, true)", [json.dumps(claims)])
            self.ex("set local role authenticated")
            ok = False
            try:
                yield self
                ok = True
            finally:
                if ok:  # si se anida en otra transacción, el rol no debe "contagiar" las escrituras siguientes
                    self.ex("reset role")
                    self.q("select set_config('request.jwt.claims', '', true)")

    # ------------------------------------------------------------------ específicos
    def siguiente_consecutivo(self, empresa_id: int, anio: int) -> int:
        """UPSERT atómico (misma sentencia en ambos motores; en PG está también como función SQL)."""
        if self.es_pg:
            return int(self.valor("select siguiente_consecutivo(?, ?)", [empresa_id, anio]))
        with self.transaccion():
            return int(self.valor(
                "insert into consecutivos (empresa_id, anio, ultimo) values (?, ?, 1) "
                "on conflict (empresa_id, anio) do update set ultimo = consecutivos.ultimo + 1 returning ultimo",
                [empresa_id, anio]))

    def indexar(self, solicitud_id: int, origen: str, ref_id: int, texto: str | None):
        """Solo SQLite: en PostgreSQL los triggers de db/03_busqueda.sql mantienen el tsvector."""
        if self.es_pg or not texto:
            return
        self.ex("delete from busqueda_fts where origen = ? and ref_id = ?", [origen.split(":")[0], ref_id])
        self.ex("insert into busqueda_fts (texto, solicitud_id, origen, ref_id) values (?, ?, ?, ?)",
                [texto, solicitud_id, origen, ref_id])

    def reconstruir_indice(self):
        if self.es_pg:
            return
        self.ex("delete from busqueda_fts")
        self.ex("insert into busqueda_fts (texto, solicitud_id, origen, ref_id) "
                "select radicado || ' ' || asunto || ' ' || coalesce(descripcion,''), id, 'solicitud', id from solicitudes")
        self.ex("insert into busqueda_fts (texto, solicitud_id, origen, ref_id) "
                "select contenido, solicitud_id, 'respuesta', id from respuestas")
        self.ex("insert into busqueda_fts (texto, solicitud_id, origen, ref_id) "
                "select coalesce(nombre_original,'') || ' ' || texto_extraido, solicitud_id, "
                "'documento: ' || coalesce(nombre_original, nombre), id from documentos where texto_extraido is not null")

    def buscar_texto(self, texto: str, limite: int = 200, usuario: dict | None = None) -> list[dict]:
        if self.es_pg:
            with self.como_usuario(usuario):
                return self.q("select * from buscar_pqrs(?, ?)", [texto, limite])
        mq = _fts_consulta(texto)
        if not mq:
            return []
        filas = self.q("select solicitud_id, origen, -bm25(busqueda_fts) as rango, "
                       "snippet(busqueda_fts, 0, '«', '»', '…', 14) as fragmento "
                       "from busqueda_fts where busqueda_fts match ? order by bm25(busqueda_fts) limit ?", [mq, limite])
        for f in filas:
            f["solicitud_id"] = int(f["solicitud_id"])
        return filas

    def reiniciar_secuencias(self):
        if not self.es_pg:
            return
        for t in TABLAS:
            tiene_id = self.valor("select count(*) from information_schema.columns where table_schema='public' "
                                  "and table_name=? and column_name='id'", [t])
            if tiene_id:
                self.ex(f"select setval(pg_get_serial_sequence('{t}', 'id'), coalesce((select max(id) from {t}), 0) + 1, false)")

    # ------------------------------------------------------------------ esquema
    def esta_vacio(self) -> bool:
        try:
            return not self.valor("select count(*) from empresas")
        except Exception:
            if self.es_pg:
                self.conn.rollback() if not self.conn.autocommit else None
            return True

    def crear_esquema_sqlite(self):
        sql = (config.RAIZ / "core" / "esquema_sqlite.sql").read_text(encoding="utf-8")
        sql += "\n" + (config.RAIZ / "core" / "esquema_sqlite_archivo.sql").read_text(encoding="utf-8")
        with self._lock:
            self.conn.executescript(sql)

    def borrar_todo(self):
        """Reinicio de la demo. En SQLite elimina el archivo; en PG borra las tablas (requiere dueño)."""
        with self._lock:
            if self.es_pg:
                self.ex("drop table if exists " + ", ".join(reversed(TABLAS)) + " cascade")
            else:
                self.conn.close()
                for suf in ("", "-wal", "-shm"):
                    p = Path(str(self.ruta) + suf)
                    if p.exists():
                        p.unlink()
                self.conn = sqlite3.connect(str(self.ruta), check_same_thread=False, isolation_level=None, timeout=30)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA foreign_keys = ON")


_SQL_TRIGGER_EVENTOS_SQLITE = """create trigger if not exists tr_eventos_no_update before update on eventos
  when new.id is not old.id or new.solicitud_id is not old.solicitud_id or new.usuario_id is not old.usuario_id
    or new.origen is not old.origen or new.accion is not old.accion or new.detalle is not old.detalle or new.fecha is not old.fecha
  begin select raise(abort, 'La bitácora (eventos) es de solo inserción: no se puede modificar ni borrar.'); end"""

_REPO: Repositorio | None = None
_REPO_LOCK = threading.RLock()


def obtener_repo() -> Repositorio:
    """Repositorio único del proceso. En modo demo crea y siembra la base si está vacía."""
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            repo = Repositorio()
            _REPO = repo
            if not repo.es_pg and repo.esta_vacio():
                repo.crear_esquema_sqlite()
                from core import semilla
                semilla.cargar(repo)
        return _REPO


def fijar_repo(repo: Repositorio | None):
    global _REPO
    with _REPO_LOCK:
        _REPO = repo

"""Lecturas: catálogos, alcance por rol (equivalente a RLS), listados, búsqueda y consultas para el MCP."""
from __future__ import annotations

import time
import unicodedata
from datetime import date, timedelta

from core import flujo, plazos
from core.reloj import a_fecha, ahora, hoy as _hoy
from core.repositorio import obtener_repo

ROLES = {
    "abogado": "Abogado", "supervisor": "Supervisor", "director": "Director / aprobador final",
    "admin": "Administrador", "radicador": "Radicador / ventanilla", "auditor": "Auditor (solo lectura)",
    "integracion": "Integración (API/MCP)", "archivista": "Archivista",
}
CANALES = {"web": "Formulario web", "correo": "Correo electrónico", "presencial": "Presencial",
           "telefonico": "Telefónico", "api": "API", "mcp": "Asistente (MCP)"}

SOL_COLS = ("id, radicado, empresa_id, tipo_id, tema_id, solicitante_id, canal, asunto, descripcion, estado, prioridad, "
            "fecha_recepcion, fecha_radicacion, fecha_vencimiento, dias_suspendidos, suspendida_desde, prorrogada, "
            "fecha_respuesta, abogado_id, solicitud_padre_id, posible_duplicado_de, revisar_duplicado, respuesta_parcial, "
            "reabierta, empresa_origen_id, entidad_traslado, marca, codigo_consulta, message_id, creado_por, pendiente_completar, "
            "docs_fisicos, hojas_fisicas")
BASE = ("select " + ", ".join("s." + c.strip() for c in SOL_COLS.split(",")) + ", "
        "e.codigo as empresa_codigo, e.nombre as empresa_nombre, e.color as empresa_color, "
        "t.codigo as tipo_codigo, t.nombre as tipo_nombre, t.dias_habiles, t.peso_carga, t.niveles_aprobacion, "
        "t.dias_prorroga_max, te.nombre as tema_nombre, te.sensible as tema_sensible, te.especialidad_requerida, "
        "u.nombre as abogado_nombre, so.nombre as solicitante_nombre, so.email as solicitante_email, "
        "so.num_doc as solicitante_doc, so.tipo_doc as solicitante_tipo_doc, so.telefono as solicitante_telefono, "
        "so.anonimo as anonimo "
        "from solicitudes s join empresas e on e.id = s.empresa_id join tipos_pqrs t on t.id = s.tipo_id "
        "left join temas te on te.id = s.tema_id left join usuarios u on u.id = s.abogado_id "
        "left join solicitantes so on so.id = s.solicitante_id")


def R():
    return obtener_repo()


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


# ------------------------------------------------------------------ caché corta de catálogos
_CACHE: dict = {}


def _cache(clave, fn, ttl=30):
    v = _CACHE.get(clave)
    if v and time.time() - v[0] < ttl:
        return v[1]
    r = fn()
    _CACHE[clave] = (time.time(), r)
    return r


def limpiar_cache():
    _CACHE.clear()


def empresas(activas: bool = True) -> list[dict]:
    return _cache(("emp", activas), lambda: R().q(
        "select * from empresas" + (" where activo" if activas else "") + " order by codigo"))


def empresa(empresa_id) -> dict | None:
    return next((e for e in empresas(False) if e["id"] == empresa_id), None)


def empresa_por_codigo(codigo: str) -> dict | None:
    return next((e for e in empresas(False) if e["codigo"] == (codigo or "").upper()), None)


def tipos(activos: bool = True) -> list[dict]:
    return _cache(("tip", activos), lambda: R().q(
        "select * from tipos_pqrs" + (" where activo" if activos else "") + " order by id"))


def tipo(tipo_id) -> dict | None:
    return next((t for t in tipos(False) if t["id"] == tipo_id), None)


def tipo_por_codigo(codigo: str) -> dict | None:
    return next((t for t in tipos(False) if t["codigo"] == (codigo or "").upper()), None)


def temas(empresa_id=None) -> list[dict]:
    todos = _cache("temas", lambda: R().q("select * from temas order by empresa_id, nombre"))
    return [t for t in todos if empresa_id is None or t["empresa_id"] == empresa_id]


def tema(tema_id) -> dict | None:
    return next((t for t in temas() if t["id"] == tema_id), None)


def parametros() -> dict:
    return _cache("par", lambda: {p["clave"]: p["valor"] for p in R().q("select clave, valor from parametros")})


def param(clave: str, defecto=None):
    v = parametros().get(clave)
    return defecto if v in (None, "") else v


def param_num(clave: str, defecto: float) -> float:
    try:
        return float(param(clave, defecto))
    except (TypeError, ValueError):
        return defecto


def param_si(clave: str, defecto: bool = False) -> bool:
    v = param(clave)
    return defecto if v is None else str(v).strip().lower() in ("si", "sí", "true", "1", "yes")


def hora_corte():
    from datetime import time as _t
    h, _, m = str(param("hora_corte", "17:00")).partition(":")
    return _t(int(h), int(m or 0))


def festivos(empresa_id=None) -> frozenset[date]:
    filas = _cache("fest", lambda: R().q("select empresa_id, fecha from festivos_extra"))
    return frozenset(a_fecha(f["fecha"]) for f in filas if f["empresa_id"] is None or f["empresa_id"] == empresa_id)


def usuarios(rol: str | None = None, empresa_id=None, activos=True) -> list[dict]:
    def carga():
        us = R().q("select * from usuarios order by rol, nombre")
        ue = R().q("select usuario_id, empresa_id from usuario_empresa")
        mapa: dict[int, list[int]] = {}
        for r in ue:
            mapa.setdefault(r["usuario_id"], []).append(r["empresa_id"])
        for u in us:
            u["empresas"] = sorted(mapa.get(u["id"], []))
        return us
    todos = _cache("usr", carga)
    return [u for u in todos if (rol is None or u["rol"] == rol) and (empresa_id is None or empresa_id in u["empresas"])
            and (not activos or u["activo"])]


def usuario(uid) -> dict | None:
    return next((u for u in usuarios(activos=False) if u["id"] == uid), None)


def usuario_por_email(email: str) -> dict | None:
    return next((u for u in usuarios(activos=False) if u["email"].lower() == (email or "").lower()), None)


# ------------------------------------------------------------------ alcance (misma regla que RLS)
def alcance(usuario: dict | None) -> tuple[str, list]:
    """Fragmento SQL sobre el alias `s` que replica la política RLS `ver_solicitudes`."""
    if usuario is None:
        return "1 = 0", []
    rol, emps = usuario["rol"], list(usuario.get("empresas") or [])
    if rol in ("admin", "auditor"):
        return "1 = 1", []
    marc = ", ".join("?" for _ in emps) or "NULL"
    if rol in ("supervisor", "director", "integracion"):
        return f"s.empresa_id in ({marc})", emps
    if rol == "radicador":
        return f"s.estado = 'RECIBIDA' and s.empresa_id in ({marc})", emps
    if rol == "archivista":  # casos CERRADOS de sus empresas (necesita sus documentos para armar el expediente)
        return f"s.estado = 'CERRADA' and s.empresa_id in ({marc})", emps
    if rol == "abogado":
        return "s.abogado_id = ?", [usuario["id"]]
    return "1 = 0", []


def puede_ver(usuario: dict | None, sol: dict) -> bool:
    if not usuario or not sol:
        return False
    rol = usuario["rol"]
    if rol in ("admin", "auditor"):
        return True
    if rol in ("supervisor", "director", "integracion"):
        return sol["empresa_id"] in usuario.get("empresas", [])
    if rol == "radicador":
        return sol["estado"] == "RECIBIDA" and sol["empresa_id"] in usuario.get("empresas", [])
    if rol == "archivista":
        return sol["estado"] == "CERRADA" and sol["empresa_id"] in usuario.get("empresas", [])
    if rol == "abogado":
        return sol.get("abogado_id") == usuario["id"]
    return False


def enriquecer(s: dict, hoy: date | None = None) -> dict:
    hoy = hoy or _hoy()
    rad, ven = a_fecha(s.get("fecha_radicacion")), a_fecha(s.get("fecha_vencimiento"))
    if rad and ven:
        sm = plazos.semaforo(rad, ven, hoy, s["estado"], param_num("umbral_amarillo", 50), param_num("umbral_rojo", 80),
                             festivos(s["empresa_id"]))
        s.update(sem_nivel=sm.nivel, sem_icono=sm.icono, sem_texto=sm.texto, sem_etiqueta=sm.etiqueta,
                 pct_plazo=sm.porcentaje, dias_restantes=sm.restantes)
    else:
        s.update(sem_nivel="pendiente", sem_icono="⏳", sem_texto="Plazo por calcular", sem_etiqueta="⏳ Plazo por calcular",
                 pct_plazo=0.0, dias_restantes=None)
    s["estado_texto"] = flujo.explicar(s["estado"])
    return s


def listar_solicitudes(usuario: dict | None, filtros: dict | None = None, enriquecer_: bool = True,
                       sin_alcance: bool = False) -> list[dict]:
    f = filtros or {}
    where, params = (["1 = 1"], []) if sin_alcance else ([alcance(usuario)[0]], list(alcance(usuario)[1]))
    def en(col, vals):
        vals = [v for v in (vals if isinstance(vals, (list, tuple, set)) else [vals]) if v not in (None, "")]
        if vals:
            where.append(f"{col} in ({', '.join('?' for _ in vals)})")
            params.extend(vals)
    en("s.id", f.get("ids"))
    en("s.empresa_id", f.get("empresa_id"))
    en("s.tipo_id", f.get("tipo_id"))
    en("s.tema_id", f.get("tema_id"))
    en("s.estado", f.get("estado"))
    en("s.canal", f.get("canal"))
    en("s.abogado_id", f.get("abogado_id"))
    if f.get("abiertos"):
        en("s.estado", sorted(flujo.ABIERTOS))
    for campo, col in (("recepcion", "s.fecha_recepcion"), ("vencimiento", "s.fecha_vencimiento"),
                       ("respuesta", "s.fecha_respuesta")):
        d, h = f.get(f"{campo}_desde"), f.get(f"{campo}_hasta")
        if d:
            where.append(f"{col} >= ?")
            params.append(d.isoformat() if col == "s.fecha_vencimiento" else _inicio(d))
        if h:
            where.append(f"{col} {'<=' if col == 's.fecha_vencimiento' else '<'} ?")
            params.append(h.isoformat() if col == "s.fecha_vencimiento" else _inicio(h + timedelta(days=1)))
    for marca in ("prorrogada", "respuesta_parcial", "reabierta", "revisar_duplicado"):
        if f.get(marca):
            where.append(f"s.{marca}")
    if f.get("sin_abogado"):
        where.append("s.abogado_id is null")
    if f.get("solicitante"):
        x = f"%{str(f['solicitante']).lower()}%"
        where.append("(lower(so.nombre) like ? or lower(so.email) like ? or lower(so.num_doc) like ?)")
        params += [x, x, x]
    if f.get("radicado"):
        where.append("upper(s.radicado) = ?")
        params.append(str(f["radicado"]).strip().upper())
    sql = BASE + " where " + " and ".join(where) + " order by s.fecha_vencimiento, s.id"
    repo = R()
    with repo.como_usuario(None if sin_alcance else usuario):
        filas = repo.q(sql, params)
    if enriquecer_:
        h = _hoy()
        filas = [enriquecer(x, h) for x in filas]
        if f.get("semaforo"):
            filas = [x for x in filas if x["sem_nivel"] in f["semaforo"]]
        if f.get("aprobador_id"):
            filas = [x for x in filas if x["id"] in _solicitudes_de_aprobador(f["aprobador_id"])]
    return filas


def _solicitudes_de_aprobador(uid) -> set[int]:
    return {r["solicitud_id"] for r in R().q(
        "select distinct r.solicitud_id from aprobaciones a join respuestas r on r.id = a.respuesta_id where a.aprobador_id = ?", [uid])}


def _inicio(d: date):
    from datetime import datetime
    from core.reloj import TZ
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def obtener_solicitud(sid: int, usuario: dict | None = None, sin_alcance: bool = False) -> dict | None:
    filas = listar_solicitudes(usuario, {"ids": [sid]}, sin_alcance=sin_alcance)
    return filas[0] if filas else None


def solicitud_por_radicado(radicado: str, usuario: dict | None = None, sin_alcance: bool = False) -> dict | None:
    filas = listar_solicitudes(usuario, {"radicado": radicado}, sin_alcance=sin_alcance)
    return filas[0] if filas else None


def buscar(usuario: dict, texto: str = "", filtros: dict | None = None, limite: int = 300) -> list[dict]:
    """Filtros combinados + texto completo (solicitud, respuestas y documentos). Respeta el alcance."""
    texto = (texto or "").strip()
    f = dict(filtros or {})
    from core import radicado as _rad
    if texto and _rad.es_radicado(texto):
        f["radicado"] = texto
        return listar_solicitudes(usuario, f)
    if texto and texto.replace(".", "").isdigit() and len(texto) >= 5:
        f["solicitante"] = texto.replace(".", "")
        return listar_solicitudes(usuario, f)
    if not texto:
        return listar_solicitudes(usuario, f)[:limite]
    hits = R().buscar_texto(texto, 1000, usuario)
    if not hits:
        return []
    mejor: dict[int, dict] = {}
    for h in hits:
        sid = int(h["solicitud_id"])
        if sid not in mejor or float(h["rango"] or 0) > float(mejor[sid]["rango"] or 0):
            mejor[sid] = h
    f["ids"] = list(mejor)
    filas = listar_solicitudes(usuario, f)
    for x in filas:
        h = mejor[x["id"]]
        x["coincidencia_en"] = h["origen"]
        x["fragmento"] = h["fragmento"]
        x["relevancia"] = round(float(h["rango"] or 0), 4)
    filas.sort(key=lambda x: -x["relevancia"])
    return filas[:limite]


# ------------------------------------------------------------------ detalle del expediente
def documentos(sid: int) -> list[dict]:
    return R().q("select id, solicitud_id, categoria, nombre, nombre_original, ruta, mime, tamano, sha256, version, "
                 "estado_texto, subido_por, origen, fecha from documentos where solicitud_id = ? order by categoria, fecha", [sid])


def documento(doc_id: int) -> dict | None:
    return R().q("select id, solicitud_id, categoria, nombre, nombre_original, ruta, mime, tamano, sha256, version, "
                 "texto_extraido, estado_texto, origen, fecha from documentos where id = ?", [doc_id], uno=True)


def respuestas(sid: int) -> list[dict]:
    return R().q("select r.id, r.solicitud_id, r.version, r.contenido, r.es_parcial, r.estado, r.autor_id, r.origen, r.fecha, "
                 "r.actualizado, u.nombre as autor from respuestas r left join usuarios u on u.id = r.autor_id "
                 "where r.solicitud_id = ? order by r.version", [sid])


def aprobaciones_de(respuesta_ids: list[int]) -> list[dict]:
    if not respuesta_ids:
        return []
    return R().q("select a.*, u.nombre as aprobador from aprobaciones a left join usuarios u on u.id = a.aprobador_id "
                 f"where a.respuesta_id in ({', '.join('?' for _ in respuesta_ids)}) order by a.fecha", respuesta_ids)


SIN_EMPRESA = 0  # valor de filtro: eventos de sistema sin empresa (p. ej. error_imap, configuración global)


def eventos(sid: int | None = None, limite: int = 500, empresa_id: int | None = None) -> list[dict]:
    """Bitácora. Sin `sid`: los últimos `limite` eventos, de todas las empresas o solo de `empresa_id`
    (`SIN_EMPRESA` = los que no pertenecen a ninguna empresa)."""
    if sid is None:
        where, p = "", []
        if empresa_id == SIN_EMPRESA:
            where = " where ev.empresa_id is null"
        elif empresa_id is not None:
            where, p = " where ev.empresa_id = ?", [empresa_id]
        return R().q("select ev.*, u.nombre as usuario, s.radicado from eventos ev left join usuarios u on u.id = ev.usuario_id "
                     "left join solicitudes s on s.id = ev.solicitud_id" + where + " order by ev.id desc limit ?", p + [limite])
    return R().q("select ev.*, u.nombre as usuario from eventos ev left join usuarios u on u.id = ev.usuario_id "
                 "where ev.solicitud_id = ? order by ev.id", [sid])


def asignaciones(sid: int) -> list[dict]:
    return R().q("select a.*, u.nombre as abogado, p.nombre as asignado_por_nombre from asignaciones a "
                 "left join usuarios u on u.id = a.abogado_id left join usuarios p on p.id = a.asignado_por "
                 "where a.solicitud_id = ? order by a.fecha", [sid])


def alertas_usuario(uid: int, solo_no_leidas: bool = False, limite: int = 50) -> list[dict]:
    return R().q("select al.*, s.radicado from alertas al left join solicitudes s on s.id = al.solicitud_id "
                 "where al.destinatario_id = ?" + (" and not al.leida" if solo_no_leidas else "") +
                 " order by al.id desc limit ?", [uid, limite])


def vinculados(sid: int) -> list[dict]:
    return R().q("select id, radicado, estado from solicitudes where solicitud_padre_id = ? order by id", [sid])


def plantillas(clave: str | None = None, empresa_id=None, tipo_id=None) -> list[dict]:
    filas = R().q("select * from plantillas where activo order by clave, nombre")
    res = [p for p in filas if (clave is None or p["clave"] == clave)
           and (p["empresa_id"] in (None, empresa_id) or empresa_id is None)
           and (p["tipo_id"] in (None, tipo_id) or tipo_id is None)]
    # Las más específicas primero
    res.sort(key=lambda p: (p["empresa_id"] is None, p["tipo_id"] is None))
    return res


def empresas_alcance(usuario: dict | None) -> list[int] | None:
    """Empresas cuyos datos auxiliares (correos, bitácora) puede ver el usuario. None = todas (admin, auditor); [] = ninguna."""
    if not usuario:
        return []
    if usuario["rol"] in ("admin", "auditor"):
        return None
    return list(usuario.get("empresas") or [])


def correos(usuario: dict | None, direccion: str | None = None, limite: int = 200, sin_alcance: bool = False) -> list[dict]:
    """Buzón. Réplica de la política RLS ver_correos: admin/auditor ven todo (incluido lo de empresa desconocida);
    supervisor, director y radicador solo los correos de sus empresas; los demás roles, ninguno."""
    sql = ("select id, direccion, modo, message_id, de, para, asunto, cuerpo, solicitud_id, empresa_id, estado, error, fecha "
           "from correos where 1 = 1")
    p: list = []
    if not sin_alcance:
        emps = empresas_alcance(usuario)
        if emps is not None:
            if not usuario or usuario["rol"] not in ("supervisor", "director", "radicador") or not emps:
                return []
            sql += f" and empresa_id in ({', '.join('?' for _ in emps)})"
            p += emps
    if direccion:
        sql += " and direccion = ?"
        p.append(direccion)
    return R().q(sql + " order by id desc limit ?", p + [limite])


def correo_eml(cid: int) -> str | None:
    return R().valor("select eml from correos where id = ?", [cid])


# ------------------------------------------------------------------ para el MCP y reportes
def por_vencer(usuario: dict | None = None, empresa: str | None = None, dias: int = 3) -> list[dict]:
    f: dict = {"abiertos": True}
    if empresa:
        e = empresa_por_codigo(empresa)
        f["empresa_id"] = e["id"] if e else -1
    filas = listar_solicitudes(usuario, f, sin_alcance=usuario is None)
    return [x for x in filas if x.get("dias_restantes") is not None and x["dias_restantes"] <= dias
            and x["estado"] != "PENDIENTE_INFO"]


def carga_equipo(empresa_id=None) -> list[dict]:
    from core import reparto
    h = _hoy()
    abogados = usuarios("abogado", empresa_id)
    abiertos = R().q("select s.abogado_id, s.fecha_vencimiento, t.peso_carga, s.empresa_id from solicitudes s "
                     "join tipos_pqrs t on t.id = s.tipo_id where s.abogado_id is not null and s.estado in (" +
                     ", ".join(f"'{e}'" for e in sorted(flujo.ABIERTOS)) + ")")
    res = []
    for a in abogados:
        casos = [reparto.CasoAbierto(float(x["peso_carga"]), a_fecha(x["fecha_vencimiento"]) or h)
                 for x in abiertos if x["abogado_id"] == a["id"]]
        ab = reparto.Abogado(a["id"], a["nombre"], a["disponible"], a_fecha(a["ausente_desde"]),
                             a_fecha(a["ausente_hasta"]), a["capacidad_max"])
        res.append({"abogado_id": a["id"], "abogado": a["nombre"], "empresas": a["empresas"],
                    "casos_abiertos": len(casos), "carga_ponderada": round(reparto.carga_ponderada(casos, h), 2),
                    "capacidad_max": a["capacidad_max"], "disponible": a["disponible"] and not ab.ausente(h),
                    "ausente": ab.ausente(h), "especialidades": ", ".join(a.get("especialidades") or [])})
    return res

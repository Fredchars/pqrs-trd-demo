"""Módulos TRD (tablas de retención documental) y archivo físico. [DEMOSTRACIÓN]

Reglas de este módulo (resumen; el detalle está en el Anexo de funcionamiento y en el Manual de uso):
  * Cada PQRS CERRADA se asigna a una serie/subserie de la TRD de su empresa y forma un expediente electrónico con índice
    (documentos, fechas, folios). La serie define los años en archivo de gestión y en archivo central y la disposición final
    (conservar, eliminar, digitalizar). Fecha de transferencia = cierre + años de gestión; fecha de disposición = transferencia
    + años de central.
  * La disposición se PROPONE, la REVISA el archivista y la APRUEBA el supervisor (otra persona), con acta con huella SHA-256.
    Ejecutarla solo registra la decisión: en esta demostración no se borra ningún documento ni se firma digitalmente.
  * Archivo físico: cajas → carpetas (con rango de folios) → expedientes en papel; rótulos con QR real; préstamos con responsable.
  * Aislamiento: toda fila lleva empresa_id y las consultas replican la política RLS de db/06_trd_archivo.sql.
"""
from __future__ import annotations

import hashlib
import io
from datetime import date, timedelta

from core import consultas as C
from core.config import app_url
from core.reloj import a_fecha, ahora, fmt_fecha, hoy as _hoy
from core.repositorio import obtener_repo

DISPOSICIONES = {"conservar": "Conservar", "eliminar": "Eliminar", "digitalizar": "Digitalizar"}
DISPOSICION_ICONO = {"conservar": "🛡️", "eliminar": "🗑️", "digitalizar": "💾"}
DISPOSICION_AYUDA = {
    "conservar": "Se conserva de forma permanente (valor histórico o probatorio).",
    "eliminar": "Se elimina al vencer la retención, con acta y autorización.",
    "digitalizar": "Se conserva en soporte electrónico y se elimina el papel.",
}
ESTADOS_DISPOSICION = {"propuesta": "Propuesta (falta revisión)", "revisada": "Revisada (falta aprobación)", "rechazada": "Rechazada",
                       "aprobada": "Aprobada (falta ejecutar)", "ejecutada": "Ejecutada"}
ESTADOS_EXPEDIENTE = {"activo": "Activo", "con_propuesta": "Con propuesta de disposición", "dispuesto": "Dispuesto"}
ESTADOS_PRESTAMO = {"solicitada": "Solicitada", "prestada": "Prestada", "devuelta": "Devuelta"}

# Quién puede hacer qué (los mismos nombres de rol de core/consultas.py)
ROLES_GESTION = ("archivista", "admin")                 # catálogo, expedientes, cajas, préstamos, propuestas, ejecución
ROLES_APRUEBAN = ("supervisor", "director")             # aprobación de la disposición final (otra persona distinta del revisor)
ROLES_ARCHIVO_VE = ("archivista", "admin", "supervisor", "director", "auditor")  # menú de archivo completo
ROLES_CONSULTA = ("abogado",)                            # consultan catálogo, ubicación de sus casos y piden préstamos
ROLES_LECTURA = ("auditor",)                             # solo lectura


class ErrorArchivo(Exception):
    """Error comprensible para mostrar al usuario."""


def R():
    return obtener_repo()


# ====================================================================== utilidades puras
def sumar_anios(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + int(n))
    except ValueError:  # 29 de febrero
        return d.replace(year=d.year + int(n), day=28)


def calcular_fechas(fecha_cierre: date, anios_gestion: int, anios_central: int) -> tuple[date, date]:
    """(fecha de transferencia a archivo central, fecha de disposición final)."""
    fin_gestion = sumar_anios(fecha_cierre, anios_gestion)
    return fin_gestion, sumar_anios(fin_gestion, anios_central)


def dias_para(fecha, hoy: date | None = None) -> int | None:
    f = a_fecha(fecha)
    return None if f is None else (f - (hoy or _hoy())).days


def nivel_alerta(dias: int | None) -> str | None:
    """None si falta más de 90 días; '90', '30' o 'vencida'."""
    if dias is None:
        return None
    if dias < 0:
        return "vencida"
    if dias <= 30:
        return "30"
    if dias <= 90:
        return "90"
    return None


NIVELES = {"vencida": ("Vencida", "🔴"), "30": ("≤ 30 días", "🟠"), "90": ("≤ 90 días", "🟡"), None: ("Vigente", "🟢")}


def fase(exp: dict, hoy: date | None = None) -> str:
    hoy = hoy or _hoy()
    if exp["estado"] == "dispuesto":
        return "Dispuesto"
    if hoy < a_fecha(exp["fecha_fin_gestion"]):
        return "Archivo de gestión"
    if hoy < a_fecha(exp["fecha_disposicion"]):
        return "Archivo central"
    return "Disposición pendiente"


def sha256_texto(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _alcance_emp(usuario: dict | None) -> list[int] | None:
    """None = todas las empresas (admin, auditor); lista (posiblemente vacía) = solo esas."""
    if not usuario:
        return []
    if usuario["rol"] in ("admin", "auditor"):
        return None
    return list(usuario.get("empresas") or [])


def _filtro_emp(usuario, col="empresa_id", empresa_id=None) -> tuple[str, list]:
    emps = _alcance_emp(usuario)
    where, p = [], []
    if emps is not None:
        where.append(f"{col} in ({', '.join('?' for _ in emps) or 'NULL'})")
        p += emps
    if empresa_id is not None:
        where.append(f"{col} = ?")
        p.append(empresa_id)
    return (" and ".join(where) or "1 = 1"), p


def puede_gestionar(usuario) -> bool:
    return bool(usuario) and usuario["rol"] in ROLES_GESTION


def puede_aprobar(usuario) -> bool:
    return bool(usuario) and usuario["rol"] in ROLES_APRUEBAN


def _exigir(usuario, roles, accion: str):
    if not usuario or usuario["rol"] not in roles:
        nombres = ", ".join(C.ROLES.get(r, r) for r in roles)
        raise ErrorArchivo(f"No tiene permiso para {accion}. Lo hace: {nombres}.")


def _exigir_empresa(usuario, empresa_id: int):
    emps = _alcance_emp(usuario)
    if emps is not None and empresa_id not in emps:
        raise ErrorArchivo("Esa información pertenece a otra empresa y no está dentro de su alcance.")


def _evento(usuario, accion: str, detalle: dict, empresa_id: int, sid: int | None = None):
    from core import servicios as S
    S.evento(sid, usuario, accion, {**detalle, "modulo": "archivo"}, empresa_id=empresa_id)


# ====================================================================== lecturas (alcance = política RLS de db/06)
def series(usuario, empresa_id=None, solo_activas=False) -> list[dict]:
    w, p = _filtro_emp(usuario, "t.empresa_id", empresa_id)
    with R().como_usuario(usuario):
        filas = R().q(
            "select t.*, e.codigo as empresa_codigo, pa.codigo as padre_codigo, pa.nombre as padre_nombre, "
            "(select count(*) from expedientes x where x.serie_id = t.id and x.empresa_id = t.empresa_id) as n_expedientes, "
            "(select count(*) from trd_series h where h.serie_padre_id = t.id) as n_hijas "
            "from trd_series t join empresas e on e.id = t.empresa_id left join trd_series pa on pa.id = t.serie_padre_id "
            f"where {w}" + (" and t.activa" if solo_activas else "") + " order by e.codigo, t.codigo", p)
    return filas


def serie(serie_id: int, usuario=None) -> dict | None:
    w, p = _filtro_emp(usuario) if usuario else ("1 = 1", [])
    return R().q(f"select * from trd_series where id = ? and {w}", [serie_id] + p, uno=True)


def retencion_total(s: dict) -> int | None:
    if s.get("anios_gestion") is None or s.get("anios_central") is None:
        return None
    return int(s["anios_gestion"]) + int(s["anios_central"])


def series_asignables(usuario, empresa_id) -> list[dict]:
    """Series/subseries con retención definida (las que se pueden asignar a un expediente)."""
    return [s for s in series(usuario, empresa_id, solo_activas=True) if s["disposicion"] and s["anios_gestion"] is not None]


def sugerir_serie(solicitud: dict, usuario=None) -> dict | None:
    cod = solicitud.get("tipo_codigo")
    for s in series_asignables(usuario, solicitud["empresa_id"]):
        if cod and cod in [x.strip() for x in (s.get("tipos_sugeridos") or "").split(",") if x.strip()]:
            return s
    return None


def cajas(usuario, empresa_id=None) -> list[dict]:
    w, p = _filtro_emp(usuario, "c.empresa_id", empresa_id)
    with R().como_usuario(usuario):
        filas = R().q(
            "select c.*, e.codigo as empresa_codigo, e.nombre as empresa_nombre, "
            "(select count(*) from archivo_carpetas f where f.caja_id = c.id) as n_carpetas "
            f"from archivo_cajas c join empresas e on e.id = c.empresa_id where {w} order by e.codigo, c.codigo", p)
    for f in filas:
        f["ocupacion"] = round(100.0 * f["n_carpetas"] / f["capacidad_carpetas"], 1)
        f["ubicacion"] = f"{f['sede']} · {f['deposito']} · Estante {f['estante']} · Entrepaño {f['entrepano']}"
    return filas


def carpetas(usuario, empresa_id=None, caja_id=None) -> list[dict]:
    w, p = _filtro_emp(usuario, "f.empresa_id", empresa_id)
    if caja_id is not None:
        w += " and f.caja_id = ?"
        p.append(caja_id)
    with R().como_usuario(usuario):
        filas = R().q(
            "select f.*, c.codigo as caja_codigo, c.sede, c.deposito, c.estante, c.entrepano, e.codigo as empresa_codigo, "
            "t.codigo as serie_codigo, t.nombre as serie_nombre, "
            "(select count(*) from expedientes x where x.carpeta_id = f.id) as n_expedientes "
            "from archivo_carpetas f join archivo_cajas c on c.id = f.caja_id join empresas e on e.id = f.empresa_id "
            f"left join trd_series t on t.id = f.serie_id where {w} order by e.codigo, c.codigo, f.numero", p)
    for f in filas:
        f["ubicacion"] = f"{f['sede']} · {f['deposito']} · Estante {f['estante']} · Entrepaño {f['entrepano']} · Caja {f['caja_codigo']}"
        f["folios"] = max(0, int(f["folio_final"]) - int(f["folio_inicial"]) + 1) if f["n_expedientes"] else 0
    return filas


def _decorar_exp(f: dict, hoy: date) -> dict:
    f["dias_restantes"] = dias_para(f["fecha_disposicion"], hoy)
    f["nivel"] = nivel_alerta(f["dias_restantes"]) if f["estado"] != "dispuesto" else None
    f["nivel_texto"] = NIVELES[f["nivel"]][0] if f["estado"] != "dispuesto" else "Dispuesto"
    f["nivel_icono"] = NIVELES[f["nivel"]][1] if f["estado"] != "dispuesto" else "✅"
    f["fase"] = fase(f, hoy)
    return f


def expedientes(usuario, empresa_id=None, estado=None, serie_id=None, hoy=None) -> list[dict]:
    hoy = hoy or _hoy()
    w, p = _filtro_emp(usuario, "x.empresa_id", empresa_id)
    if usuario and usuario["rol"] == "abogado":
        w += " and s.abogado_id = ?"
        p.append(usuario["id"])
    elif not usuario or usuario["rol"] not in ROLES_ARCHIVO_VE:
        return []
    if estado:
        w += " and x.estado = ?"
        p.append(estado)
    if serie_id:
        w += " and x.serie_id = ?"
        p.append(serie_id)
    with R().como_usuario(usuario):
        filas = R().q(
            "select x.*, s.radicado, s.asunto, s.abogado_id, s.docs_fisicos, s.hojas_fisicas, e.codigo as empresa_codigo, "
            "t.codigo as serie_codigo, t.nombre as serie_nombre, t.anios_gestion, t.anios_central, pa.nombre as serie_padre_nombre, "
            "f.codigo as carpeta_codigo, "
            "c.codigo as caja_codigo, c.estante, c.entrepano, f.estado as carpeta_estado "
            "from expedientes x join solicitudes s on s.id = x.solicitud_id join empresas e on e.id = x.empresa_id "
            "join trd_series t on t.id = x.serie_id left join trd_series pa on pa.id = t.serie_padre_id "
            "left join archivo_carpetas f on f.id = x.carpeta_id left join archivo_cajas c on c.id = f.caja_id "
            f"where {w} order by x.fecha_disposicion, x.id", p)
    return [_decorar_exp(f, hoy) for f in filas]


def expediente(exp_id: int, usuario) -> dict | None:
    w, p = _filtro_emp(usuario, "x.empresa_id")
    filas = [f for f in expedientes(usuario) if f["id"] == exp_id]
    return filas[0] if filas else None


def indice(exp_id: int, usuario) -> list[dict]:
    if not expediente(exp_id, usuario):
        return []
    with R().como_usuario(usuario):
        return R().q("select * from expediente_docs where expediente_id = ? order by orden", [exp_id])


def cerradas_sin_serie(usuario, empresa_id=None) -> list[dict]:
    """PQRS CERRADAS que aún no tienen serie TRD (no se les puede calcular la retención)."""
    if not usuario or usuario["rol"] not in ROLES_ARCHIVO_VE:
        return []
    w, p = _filtro_emp(usuario, "s.empresa_id", empresa_id)
    with R().como_usuario(usuario):
        filas = R().q(
            "select s.id, s.radicado, s.empresa_id, s.asunto, s.docs_fisicos, s.hojas_fisicas, e.codigo as empresa_codigo, "
            "t.codigo as tipo_codigo, t.nombre as tipo_nombre, s.fecha_respuesta "
            "from solicitudes s join empresas e on e.id = s.empresa_id join tipos_pqrs t on t.id = s.tipo_id "
            f"where s.estado = 'CERRADA' and {w} and not exists (select 1 from expedientes x where x.solicitud_id = s.id) "
            "order by s.empresa_id, s.radicado", p)
    return filas


def vencimientos(usuario, dias: int = 90, empresa_id=None, hoy=None) -> list[dict]:
    """Expedientes sin disponer cuya disposición vence en `dias` días o ya venció."""
    return [x for x in expedientes(usuario, empresa_id, hoy=hoy) if x["estado"] != "dispuesto"
            and x["dias_restantes"] is not None and x["dias_restantes"] <= dias]


def disposiciones(usuario, estado=None, empresa_id=None) -> list[dict]:
    if not usuario or usuario["rol"] not in ROLES_ARCHIVO_VE:
        return []
    w, p = _filtro_emp(usuario, "d.empresa_id", empresa_id)
    if estado:
        estados = [estado] if isinstance(estado, str) else list(estado)
        w += f" and d.estado in ({', '.join('?' for _ in estados)})"
        p += estados
    with R().como_usuario(usuario):
        return R().q(
            "select d.*, x.serie_id, x.fecha_disposicion, x.folios, x.solicitud_id, s.radicado, s.asunto, e.codigo as empresa_codigo, "
            "t.codigo as serie_codigo, t.nombre as serie_nombre, a.numero as acta_numero, ur.nombre as revisor, ua.nombre as aprobador "
            "from trd_disposiciones d join expedientes x on x.id = d.expediente_id join solicitudes s on s.id = x.solicitud_id "
            "join empresas e on e.id = d.empresa_id join trd_series t on t.id = x.serie_id "
            "left join trd_actas a on a.id = d.acta_id left join usuarios ur on ur.id = d.revisada_por "
            f"left join usuarios ua on ua.id = d.aprobada_por where {w} order by d.id desc", p)


def actas(usuario, empresa_id=None) -> list[dict]:
    if not usuario or usuario["rol"] not in ROLES_ARCHIVO_VE:
        return []
    w, p = _filtro_emp(usuario, "a.empresa_id", empresa_id)
    with R().como_usuario(usuario):
        return R().q("select a.*, e.codigo as empresa_codigo, u.nombre as aprobada_por_nombre from trd_actas a "
                     "join empresas e on e.id = a.empresa_id left join usuarios u on u.id = a.aprobada_por "
                     f"where {w} order by a.id desc", p)


def prestamos(usuario, estado=None, empresa_id=None, hoy=None) -> list[dict]:
    hoy = hoy or _hoy()
    if not usuario:
        return []
    w, p = _filtro_emp(usuario, "p.empresa_id", empresa_id)
    if usuario["rol"] not in ("archivista", "admin", "supervisor", "director", "auditor"):
        w += " and p.solicitante_id = ?"
        p.append(usuario["id"])
    if estado:
        w += " and p.estado = ?"
        p.append(estado)
    with R().como_usuario(usuario):
        filas = R().q(
            "select p.*, f.codigo as carpeta_codigo, f.descripcion as carpeta_descripcion, c.codigo as caja_codigo, "
            "c.estante, c.entrepano, e.codigo as empresa_codigo, us.nombre as solicitante, ur.nombre as responsable, "
            "ud.nombre as recibido_por_nombre from archivo_prestamos p join archivo_carpetas f on f.id = p.carpeta_id "
            "join archivo_cajas c on c.id = f.caja_id join empresas e on e.id = p.empresa_id "
            "join usuarios us on us.id = p.solicitante_id left join usuarios ur on ur.id = p.responsable_id "
            f"left join usuarios ud on ud.id = p.recibido_por where {w} order by p.id desc", p)
    for f in filas:
        f["vencido"] = f["estado"] == "prestada" and bool(f["fecha_vence"]) and a_fecha(f["fecha_vence"]) < hoy
    return filas


def resumen(usuario, hoy=None) -> dict:
    """Indicadores para el inicio y el panel de archivo."""
    hoy = hoy or _hoy()
    exps = expedientes(usuario, hoy=hoy)
    activos = [x for x in exps if x["estado"] != "dispuesto"]
    cj = cajas(usuario)
    pr = prestamos(usuario, hoy=hoy)
    return {
        "expedientes": len(exps), "activos": len(activos),
        "vencidas": sum(1 for x in activos if x["nivel"] == "vencida"),
        "en_30": sum(1 for x in activos if x["nivel"] == "30"),
        "en_90": sum(1 for x in activos if x["nivel"] == "90"),
        "sin_serie": len(cerradas_sin_serie(usuario)),
        "cajas": len(cj), "carpetas": sum(c["n_carpetas"] for c in cj),
        "ocupacion": round(sum(c["n_carpetas"] for c in cj) / max(1, sum(c["capacidad_carpetas"] for c in cj)) * 100, 1) if cj else 0.0,
        "prestadas": sum(1 for x in pr if x["estado"] == "prestada"),
        "prestamos_vencidos": sum(1 for x in pr if x["vencido"]),
        "por_aprobar": len(disposiciones(usuario, "revisada")),
        "por_revisar": len(disposiciones(usuario, "propuesta")),
        "por_ejecutar": len(disposiciones(usuario, "aprobada")),
    }


def ubicacion_de_caso(solicitud_id: int, usuario) -> dict | None:
    """Dónde está el papel de un caso (para la ficha del caso). None si no tiene expediente."""
    for x in expedientes(usuario):
        if x["solicitud_id"] == solicitud_id:
            return x
    return None


# ====================================================================== escrituras: catálogo TRD
def guardar_serie(datos: dict, usuario, serie_id: int | None = None) -> int:
    """Crea o actualiza una serie/subserie. Una serie «madre» (con subseries) puede quedar sin retención."""
    _exigir(usuario, ROLES_GESTION, "administrar la TRD")
    emp = int(datos["empresa_id"])
    _exigir_empresa(usuario, emp)
    codigo = (datos.get("codigo") or "").strip()
    nombre = (datos.get("nombre") or "").strip()
    if not codigo or len(nombre) < 3:
        raise ErrorArchivo("Escriba el código y el nombre de la serie (mínimo 3 letras).")
    padre = datos.get("serie_padre_id")
    if padre:
        sp = R().q("select * from trd_series where id = ? and empresa_id = ?", [padre, emp], uno=True)
        if not sp:
            raise ErrorArchivo("La serie madre no existe en esta empresa.")
        if sp["serie_padre_id"]:
            raise ErrorArchivo("Solo hay dos niveles: serie y subserie. Elija una serie como madre.")
    g, c, disp = datos.get("anios_gestion"), datos.get("anios_central"), datos.get("disposicion")
    con_ret = g is not None or c is not None or disp
    if con_ret:
        if g is None or c is None or int(g) < 0 or int(c) < 0:
            raise ErrorArchivo("Indique los años en archivo de gestión y en archivo central (0 o más).")
        if disp not in DISPOSICIONES:
            raise ErrorArchivo("Elija la disposición final: conservar, eliminar o digitalizar.")
    elif padre:
        raise ErrorArchivo("Una subserie debe tener tiempos de retención y disposición final.")
    fila = {"empresa_id": emp, "codigo": codigo, "nombre": nombre, "descripcion": datos.get("descripcion") or None,
            "serie_padre_id": padre or None, "anios_gestion": int(g) if con_ret else None,
            "anios_central": int(c) if con_ret else None, "disposicion": disp if con_ret else None,
            "tipos_sugeridos": ",".join(sorted({x.strip().upper() for x in (datos.get("tipos_sugeridos") or "").split(",") if x.strip()})),
            "procedimiento": datos.get("procedimiento") or None, "acto_aprobacion": datos.get("acto_aprobacion") or None,
            "activa": bool(datos.get("activa", True))}
    dup = R().q("select id from trd_series where empresa_id = ? and codigo = ?", [emp, codigo], uno=True)
    if dup and dup["id"] != serie_id:
        raise ErrorArchivo(f"Ya existe una serie con el código {codigo} en esta empresa.")
    if serie_id:
        antes = R().q("select * from trd_series where id = ? and empresa_id = ?", [serie_id, emp], uno=True)
        if not antes:
            raise ErrorArchivo("No se encontró la serie en esta empresa.")
        n = R().valor("select count(*) from expedientes where serie_id = ?", [serie_id])
        if n and con_ret and (antes["anios_gestion"], antes["anios_central"], antes["disposicion"]) != (
                fila["anios_gestion"], fila["anios_central"], fila["disposicion"]):
            raise ErrorArchivo(f"Esta serie ya tiene {n} expediente(s): cambiar los tiempos exigiría recalcular fechas con acta de "
                               "modificación de la TRD. En esta demostración cree una subserie nueva.")
        R().actualizar("trd_series", serie_id, {k: v for k, v in fila.items() if k != "empresa_id"})
        _evento(usuario, "trd_serie_editada", {"serie": codigo}, emp)
        return serie_id
    fila["creado_por"] = usuario["id"]
    sid = R().insertar("trd_series", fila)
    _evento(usuario, "trd_serie_creada", {"serie": codigo, "nombre": nombre}, emp)
    return sid


# ====================================================================== expedientes
def _fecha_cierre(sol: dict) -> date:
    for e in sorted(C.eventos(sol["id"]), key=lambda e: e["id"], reverse=True):
        d = e.get("detalle") or {}
        if e["accion"] == "cambio_estado" and isinstance(d, dict) and d.get("a") == "CERRADA":
            return a_fecha(e["fecha"])
    return a_fecha(sol.get("fecha_respuesta")) or a_fecha(sol.get("fecha_vencimiento")) or _hoy()


def _paginas(doc: dict) -> int:
    if (doc.get("mime") or "").endswith("pdf"):
        try:
            from pypdf import PdfReader
            from core.almacenamiento import obtener_almacen
            return max(1, len(PdfReader(io.BytesIO(obtener_almacen().leer(doc["ruta"]))).pages))
        except Exception:
            return 1
    return 1


def _armar_indice(sol: dict, exp_id: int, empresa_id: int, contar_paginas: bool = True) -> int:
    """Escribe el índice del expediente y devuelve el total de folios. Los documentos del caso van con su huella SHA-256; los
    registros (solicitud, respuesta, cierre) con la huella del texto del registro. Los folios del papel se numeran aparte."""
    from core import documentos as docs
    filas: list[dict] = []
    filas.append({"descripcion": f"Solicitud radicada {sol['radicado']}: {sol['asunto']}", "soporte": "electronico",
                  "fecha_doc": a_fecha(sol["fecha_radicacion"]), "folios": 1, "sha256": sha256_texto(
                      f"{sol['radicado']}|{sol['asunto']}|{sol.get('descripcion')}"), "documento_id": None})
    for d in C.documentos(sol["id"]):
        filas.append({"descripcion": f"{docs.CATEGORIAS.get(d['categoria'], d['categoria'])} · {d.get('nombre_original') or d['nombre']}",
                      "soporte": "electronico", "fecha_doc": a_fecha(d["fecha"]),
                      "folios": _paginas(d) if contar_paginas else 1, "sha256": d.get("sha256"), "documento_id": d["id"]})
    for r in C.respuestas(sol["id"]):
        if r["estado"] == "enviada":
            filas.append({"descripcion": f"Respuesta v{r['version']} enviada al ciudadano", "soporte": "electronico",
                          "fecha_doc": a_fecha(sol.get("fecha_respuesta") or r["fecha"]), "folios": 1,
                          "sha256": sha256_texto(r["contenido"] or ""), "documento_id": None})
    filas.append({"descripcion": "Constancia de cierre del caso", "soporte": "electronico", "fecha_doc": _fecha_cierre(sol), "folios": 1,
                  "sha256": sha256_texto(f"cierre|{sol['radicado']}|{_fecha_cierre(sol)}"), "documento_id": None})
    if sol.get("docs_fisicos") and int(sol.get("hojas_fisicas") or 0) > 0:
        filas.append({"descripcion": "Documentos físicos aportados en ventanilla (papel)", "soporte": "fisico",
                      "fecha_doc": a_fecha(sol["fecha_radicacion"]), "folios": int(sol["hojas_fisicas"]), "sha256": None,
                      "documento_id": None})
    filas.sort(key=lambda f: (f["soporte"] == "fisico", f["fecha_doc"] or date.max))
    folio, orden, total = 1, 1, 0
    for f in filas:
        f.update(empresa_id=empresa_id, expediente_id=exp_id, orden=orden, folio_inicial=folio, folio_final=folio + f["folios"] - 1)
        folio += f["folios"]
        orden += 1
        total += f["folios"]
    R().carga_masiva("expediente_docs", filas)
    return total


def _crear_expediente(sol: dict, s_trd: dict, usuario, fecha_cierre: date, observacion: str | None = None,
                      contar_paginas: bool = True) -> int:
    fin_g, disp = calcular_fechas(fecha_cierre, s_trd["anios_gestion"], s_trd["anios_central"])
    with R().transaccion():
        eid = R().insertar("expedientes", {
            "empresa_id": sol["empresa_id"], "solicitud_id": sol["id"], "serie_id": s_trd["id"], "fecha_cierre": fecha_cierre,
            "fecha_fin_gestion": fin_g, "fecha_disposicion": disp, "disposicion": s_trd["disposicion"], "folios": 0,
            "estado": "activo", "observacion": observacion, "asignado_por": usuario["id"] if usuario else None,
            "fecha_asignacion": ahora()})
        total = _armar_indice(sol, eid, sol["empresa_id"], contar_paginas)
        R().actualizar("expedientes", eid, {"folios": total})
        _evento(usuario, "expediente_creado", {"serie": s_trd["codigo"], "disposicion": s_trd["disposicion"],
                                               "fecha_disposicion": disp.isoformat(), "folios": total}, sol["empresa_id"], sol["id"])
    return eid


def asignar_serie(solicitud_id: int, serie_id: int, usuario, observacion: str | None = None) -> int:
    """Asigna una PQRS cerrada a su serie TRD y crea el expediente electrónico con su índice."""
    _exigir(usuario, ROLES_GESTION, "asignar series a los casos cerrados")
    sol = C.obtener_solicitud(solicitud_id, usuario if usuario["rol"] != "admin" else None, sin_alcance=usuario["rol"] == "admin")
    if not sol:
        raise ErrorArchivo("No se encontró el caso o no está dentro de su alcance.")
    _exigir_empresa(usuario, sol["empresa_id"])
    if sol["estado"] != "CERRADA":
        raise ErrorArchivo("Solo se archivan los casos CERRADOS. Este caso está en estado " + sol["estado"] + ".")
    if R().valor("select count(*) from expedientes where solicitud_id = ?", [sol["id"]]):
        raise ErrorArchivo("Este caso ya tiene expediente y serie asignada.")
    st = R().q("select * from trd_series where id = ? and empresa_id = ?", [serie_id, sol["empresa_id"]], uno=True)
    if not st:
        raise ErrorArchivo("La serie elegida no pertenece a la empresa del caso.")
    if not st["activa"]:
        raise ErrorArchivo("La serie elegida está inactiva.")
    if not st["disposicion"]:
        raise ErrorArchivo("Elija una subserie: la serie madre no define tiempos de retención.")
    return _crear_expediente(sol, st, usuario, _fecha_cierre(sol), observacion)


def asignar_series_sugeridas(usuario, empresa_id=None) -> dict:
    """Asigna en bloque la serie sugerida por tipo de PQRS a los casos cerrados sin serie."""
    _exigir(usuario, ROLES_GESTION, "asignar series a los casos cerrados")
    hechos, sin_sugerencia = 0, 0
    for c in cerradas_sin_serie(usuario, empresa_id):
        sol = C.obtener_solicitud(c["id"], sin_alcance=True)
        sug = sugerir_serie(sol, usuario)
        if not sug:
            sin_sugerencia += 1
            continue
        asignar_serie(c["id"], sug["id"], usuario)
        hechos += 1
    return {"asignados": hechos, "sin_sugerencia": sin_sugerencia}


# ====================================================================== archivo físico
def crear_caja(datos: dict, usuario) -> int:
    _exigir(usuario, ROLES_GESTION, "registrar cajas")
    emp = int(datos["empresa_id"])
    _exigir_empresa(usuario, emp)
    for k, etiqueta in (("sede", "la sede"), ("deposito", "el depósito"), ("estante", "el estante"), ("entrepano", "el entrepaño")):
        if not (datos.get(k) or "").strip():
            raise ErrorArchivo(f"Indique {etiqueta} donde queda la caja.")
    e = C.empresa(emp)
    codigo = (datos.get("codigo") or "").strip()
    if not codigo:
        n = R().valor("select count(*) from archivo_cajas where empresa_id = ?", [emp]) + 1
        codigo = f"{e['codigo']}-C-{n:03d}"
        while R().valor("select count(*) from archivo_cajas where empresa_id = ? and codigo = ?", [emp, codigo]):
            n += 1
            codigo = f"{e['codigo']}-C-{n:03d}"
    elif R().valor("select count(*) from archivo_cajas where empresa_id = ? and codigo = ?", [emp, codigo]):
        raise ErrorArchivo(f"Ya existe la caja {codigo} en esta empresa.")
    cap = int(datos.get("capacidad_carpetas") or 20)
    if cap < 1:
        raise ErrorArchivo("La capacidad debe ser de al menos una carpeta.")
    cid = R().insertar("archivo_cajas", {
        "empresa_id": emp, "codigo": codigo, "sede": datos["sede"].strip(), "deposito": datos["deposito"].strip(),
        "estante": datos["estante"].strip(), "entrepano": datos["entrepano"].strip(), "capacidad_carpetas": cap,
        "estado": "abierta", "observaciones": datos.get("observaciones") or None, "creado_por": usuario["id"]})
    _evento(usuario, "caja_creada", {"caja": codigo, "ubicacion": f"{datos['estante']}/{datos['entrepano']}"}, emp)
    return cid


def crear_carpeta(caja_id: int, usuario, serie_id: int | None = None, anio: int | None = None, descripcion: str | None = None) -> int:
    _exigir(usuario, ROLES_GESTION, "registrar carpetas")
    caja = R().q("select * from archivo_cajas where id = ?", [caja_id], uno=True)
    if not caja:
        raise ErrorArchivo("No se encontró la caja.")
    _exigir_empresa(usuario, caja["empresa_id"])
    if caja["estado"] == "cerrada":
        raise ErrorArchivo(f"La caja {caja['codigo']} está cerrada. Elija otra caja o registre una nueva.")
    n = R().valor("select count(*) from archivo_carpetas where caja_id = ?", [caja_id])
    if n >= caja["capacidad_carpetas"]:
        raise ErrorArchivo(f"La caja {caja['codigo']} está llena ({n} de {caja['capacidad_carpetas']} carpetas). Registre otra caja.")
    if serie_id and not R().q("select id from trd_series where id = ? and empresa_id = ?", [serie_id, caja["empresa_id"]], uno=True):
        raise ErrorArchivo("La serie elegida no pertenece a la empresa de la caja.")
    numero = (R().valor("select max(numero) from archivo_carpetas where caja_id = ?", [caja_id]) or 0) + 1
    codigo = f"{caja['codigo']}-F{numero:02d}"
    fid = R().insertar("archivo_carpetas", {
        "empresa_id": caja["empresa_id"], "caja_id": caja_id, "numero": numero, "codigo": codigo, "serie_id": serie_id,
        "anio": anio, "descripcion": descripcion or None, "folio_inicial": 1, "folio_final": 1, "creado_por": usuario["id"]})
    _evento(usuario, "carpeta_creada", {"carpeta": codigo}, caja["empresa_id"])
    return fid


def _recalcular_folios(carpeta_id: int):
    total = R().valor(
        "select coalesce(sum(d.folios), 0) from expediente_docs d join expedientes x on x.id = d.expediente_id "
        "where x.carpeta_id = ? and d.soporte = 'fisico'", [carpeta_id])
    R().actualizar("archivo_carpetas", carpeta_id, {"folio_inicial": 1, "folio_final": max(1, int(total))})


def ubicar_expediente(exp_id: int, carpeta_id: int | None, usuario) -> None:
    """Guarda el papel de un expediente en una carpeta (o lo saca de ella con carpeta_id = None)."""
    _exigir(usuario, ROLES_GESTION, "ubicar expedientes en carpetas")
    x = R().q("select * from expedientes where id = ?", [exp_id], uno=True)
    if not x:
        raise ErrorArchivo("No se encontró el expediente.")
    _exigir_empresa(usuario, x["empresa_id"])
    if x["estado"] == "dispuesto":
        raise ErrorArchivo("El expediente ya tuvo disposición final.")
    anterior = x["carpeta_id"]
    if carpeta_id is not None:
        f = R().q("select * from archivo_carpetas where id = ?", [carpeta_id], uno=True)
        if not f or f["empresa_id"] != x["empresa_id"]:
            raise ErrorArchivo("La carpeta no existe en la empresa del expediente.")
        if f["serie_id"] and f["serie_id"] != x["serie_id"]:
            raise ErrorArchivo("La carpeta es de otra serie documental. Cree una carpeta para esta serie.")
        if f["estado"] == "prestada":
            raise ErrorArchivo("La carpeta está prestada: espere su devolución para guardar documentos en ella.")
    with R().transaccion():
        R().actualizar("expedientes", exp_id, {"carpeta_id": carpeta_id})
        if carpeta_id is not None and not f["serie_id"]:
            R().actualizar("archivo_carpetas", carpeta_id, {"serie_id": x["serie_id"]})
        for cid in {anterior, carpeta_id} - {None}:
            _recalcular_folios(cid)
        _evento(usuario, "expediente_ubicado", {"carpeta_id": carpeta_id}, x["empresa_id"], x["solicitud_id"])


def cerrar_caja(caja_id: int, usuario) -> None:
    _exigir(usuario, ROLES_GESTION, "cerrar cajas")
    caja = R().q("select * from archivo_cajas where id = ?", [caja_id], uno=True)
    if not caja:
        raise ErrorArchivo("No se encontró la caja.")
    _exigir_empresa(usuario, caja["empresa_id"])
    R().actualizar("archivo_cajas", caja_id, {"estado": "cerrada"})
    _evento(usuario, "caja_cerrada", {"caja": caja["codigo"]}, caja["empresa_id"])


# ---------------------------------------------------------------------- rótulos y QR
def payload_qr(tipo: str, codigo: str) -> str:
    """Contenido del QR: enlace a la pantalla de cajas con el código (pide inicio de sesión)."""
    return f"{app_url()}/cajas?codigo={codigo}"


def qr_png(texto: str, escala: int = 8) -> bytes:
    import segno
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="png", scale=escala, border=2)
    return buf.getvalue()


def rotulo_pdf(tipo: str, objeto: dict, usuario=None) -> bytes:
    """Rótulo imprimible (A6 horizontal) con QR REAL. tipo = 'caja' o 'carpeta'."""
    from fpdf import FPDF
    from core.plantillas import _latin1
    pdf = FPDF(orientation="L", format=(105, 148))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    codigo = objeto["codigo"]
    pdf.set_draw_color(20, 60, 110)
    pdf.set_line_width(0.8)
    pdf.rect(4, 4, 140.5, 97)
    pdf.set_fill_color(20, 60, 110)
    pdf.rect(4, 4, 140.5, 14, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(8, 7)
    emp = C.empresa(objeto["empresa_id"]) or {}
    pdf.cell(0, 8, _latin1(f"{emp.get('nombre', '')} - {'CAJA' if tipo == 'caja' else 'CARPETA'}"))
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_xy(8, 24)
    pdf.cell(95, 12, _latin1(codigo))
    pdf.set_font("Helvetica", "", 10)
    if tipo == "caja":
        lineas = [f"Sede: {objeto['sede']}", f"Deposito: {objeto['deposito']}", f"Estante: {objeto['estante']}   Entrepano: {objeto['entrepano']}",
                  f"Capacidad: {objeto['capacidad_carpetas']} carpetas", f"Estado: {objeto['estado']}"]
    else:
        lineas = [f"Caja: {objeto.get('caja_codigo', '')}", f"Serie: {(objeto.get('serie_codigo') or '-')} {(objeto.get('serie_nombre') or '')}",
                  f"Anio: {objeto.get('anio') or '-'}", f"Folios: {objeto.get('folio_inicial')} a {objeto.get('folio_final')}",
                  f"Ubicacion: Estante {objeto.get('estante')} / Entrepano {objeto.get('entrepano')}"]
        if objeto.get("descripcion"):
            lineas.append(str(objeto["descripcion"])[:70])
    y = 40
    for ln in lineas:
        pdf.set_xy(8, y)
        pdf.multi_cell(95, 5.5, _latin1(ln))
        y = pdf.get_y() + 1
    png = qr_png(payload_qr(tipo, codigo))
    pdf.image(io.BytesIO(png), x=108, y=26, w=34, h=34)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(104, 62)
    pdf.multi_cell(42, 3.5, _latin1("Escanee con el celular para abrir la ficha en el sistema (requiere inicio de sesion)."), align="C")
    pdf.set_text_color(170, 30, 30)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(8, 93)
    pdf.cell(0, 4, _latin1("DEMOSTRACION - DATOS FICTICIOS  |  Powered by ATm Consulting"))
    return bytes(pdf.output())


def rotulos_caja_pdf(caja: dict, usuario=None) -> bytes:
    """Un PDF con el rótulo de la caja y el de cada una de sus carpetas."""
    from fpdf import FPDF  # noqa: F401  (se concatena página a página con pypdf)
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    partes = [rotulo_pdf("caja", caja)] + [rotulo_pdf("carpeta", f) for f in carpetas(usuario, caja["empresa_id"], caja["id"])]
    for b in partes:
        for pg in PdfReader(io.BytesIO(b)).pages:
            w.add_page(pg)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# ---------------------------------------------------------------------- préstamos
def solicitar_prestamo(carpeta_id: int, motivo: str, dias: int, usuario) -> int:
    if not usuario or usuario["rol"] not in ("archivista", "admin", "abogado", "supervisor", "director"):
        raise ErrorArchivo("Su rol no puede solicitar préstamos de carpetas físicas.")
    f = R().q("select * from archivo_carpetas where id = ?", [carpeta_id], uno=True)
    if not f:
        raise ErrorArchivo("No se encontró la carpeta.")
    _exigir_empresa(usuario, f["empresa_id"])
    if len((motivo or "").strip()) < 5:
        raise ErrorArchivo("Escriba el motivo del préstamo (mínimo 5 caracteres).")
    if not 1 <= int(dias) <= 60:
        raise ErrorArchivo("El plazo del préstamo es de 1 a 60 días.")
    if f["estado"] == "prestada":
        raise ErrorArchivo("La carpeta ya está prestada. Pida que se registre su devolución.")
    if f["estado"] == "dispuesta":
        raise ErrorArchivo("La carpeta ya tuvo disposición final.")
    if R().valor("select count(*) from archivo_prestamos where carpeta_id = ? and solicitante_id = ? and estado = 'solicitada'",
                 [carpeta_id, usuario["id"]]):
        raise ErrorArchivo("Ya tiene una solicitud pendiente para esta carpeta.")
    pid = R().insertar("archivo_prestamos", {
        "empresa_id": f["empresa_id"], "carpeta_id": carpeta_id, "solicitante_id": usuario["id"], "motivo": motivo.strip(),
        "dias": int(dias), "fecha_solicitud": ahora(), "estado": "solicitada"})
    _evento(usuario, "prestamo_solicitado", {"carpeta": f["codigo"], "dias": int(dias)}, f["empresa_id"])
    return pid


def entregar_prestamo(prestamo_id: int, usuario) -> None:
    """El archivista entrega el papel: queda registrado quién lo recibe (el solicitante) y hasta cuándo."""
    _exigir(usuario, ROLES_GESTION, "entregar carpetas en préstamo")
    p = R().q("select * from archivo_prestamos where id = ?", [prestamo_id], uno=True)
    if not p:
        raise ErrorArchivo("No se encontró el préstamo.")
    _exigir_empresa(usuario, p["empresa_id"])
    if p["estado"] != "solicitada":
        raise ErrorArchivo("Solo se entregan préstamos en estado «solicitada».")
    f = R().q("select * from archivo_carpetas where id = ?", [p["carpeta_id"]], uno=True)
    if f["estado"] != "en_archivo":
        raise ErrorArchivo("La carpeta no está disponible en el archivo (prestada o dispuesta).")
    with R().transaccion():
        R().actualizar("archivo_prestamos", prestamo_id, {
            "estado": "prestada", "responsable_id": usuario["id"], "fecha_prestamo": ahora(),
            "fecha_vence": _hoy() + timedelta(days=int(p["dias"]))})
        R().actualizar("archivo_carpetas", p["carpeta_id"], {"estado": "prestada"})
        _evento(usuario, "prestamo_entregado", {"carpeta": f["codigo"], "solicitante_id": p["solicitante_id"]}, p["empresa_id"])


def devolver_prestamo(prestamo_id: int, usuario, observaciones: str | None = None) -> None:
    _exigir(usuario, ROLES_GESTION, "registrar devoluciones")
    p = R().q("select * from archivo_prestamos where id = ?", [prestamo_id], uno=True)
    if not p:
        raise ErrorArchivo("No se encontró el préstamo.")
    _exigir_empresa(usuario, p["empresa_id"])
    if p["estado"] != "prestada":
        raise ErrorArchivo("Solo se devuelven préstamos en estado «prestada».")
    with R().transaccion():
        R().actualizar("archivo_prestamos", prestamo_id, {
            "estado": "devuelta", "fecha_devolucion": ahora(), "recibido_por": usuario["id"], "observaciones": observaciones or None})
        R().actualizar("archivo_carpetas", p["carpeta_id"], {"estado": "en_archivo"})
        _evento(usuario, "prestamo_devuelto", {"carpeta_id": p["carpeta_id"]}, p["empresa_id"])


# ====================================================================== disposición final
def proponer_disposiciones(usuario, empresa_id=None, expediente_ids=None) -> int:
    """Crea la propuesta de disposición para los expedientes cuya retención ya venció (o para los indicados)."""
    _exigir(usuario, ROLES_GESTION, "proponer la disposición final")
    n = 0
    for x in expedientes(usuario, empresa_id):
        if expediente_ids is not None and x["id"] not in expediente_ids:
            continue
        if x["estado"] != "activo" or (expediente_ids is None and x["dias_restantes"] is not None and x["dias_restantes"] >= 0):
            continue
        if expediente_ids is not None and x["dias_restantes"] is not None and x["dias_restantes"] > 0:
            raise ErrorArchivo(f"El expediente {x['radicado']} aún está en retención ({fmt_fecha(x['fecha_disposicion'])}).")
        with R().transaccion():
            R().insertar("trd_disposiciones", {
                "empresa_id": x["empresa_id"], "expediente_id": x["id"], "disposicion": x["disposicion"], "estado": "propuesta",
                "propuesta_en": ahora()})
            R().actualizar("expedientes", x["id"], {"estado": "con_propuesta"})
            _evento(usuario, "disposicion_propuesta", {"disposicion": x["disposicion"], "serie": x["serie_codigo"]},
                    x["empresa_id"], x["solicitud_id"])
        n += 1
    return n


def _disp(disp_id: int, usuario) -> dict:
    d = R().q("select * from trd_disposiciones where id = ?", [disp_id], uno=True)
    if not d:
        raise ErrorArchivo("No se encontró la propuesta de disposición.")
    _exigir_empresa(usuario, d["empresa_id"])
    return d


def revisar_disposicion(disp_id: int, favorable: bool, concepto: str, usuario) -> None:
    """Concepto del archivista: favorable (pasa a aprobación) o no favorable (se rechaza y el expediente sigue activo)."""
    _exigir(usuario, ROLES_GESTION, "emitir el concepto del archivista")
    d = _disp(disp_id, usuario)
    if d["estado"] != "propuesta":
        raise ErrorArchivo("Solo se revisan propuestas pendientes de revisión.")
    if len((concepto or "").strip()) < 10:
        raise ErrorArchivo("Escriba el concepto del archivista (mínimo 10 caracteres).")
    x = R().q("select * from expedientes where id = ?", [d["expediente_id"]], uno=True)
    with R().transaccion():
        R().actualizar("trd_disposiciones", disp_id, {
            "estado": "revisada" if favorable else "rechazada", "revisada_por": usuario["id"], "revisada_en": ahora(),
            "concepto_archivista": concepto.strip()})
        if not favorable:
            R().actualizar("expedientes", d["expediente_id"], {"estado": "activo"})
        _evento(usuario, "disposicion_revisada", {"favorable": bool(favorable)}, d["empresa_id"], x["solicitud_id"])


def _numero_acta(empresa_id: int) -> str:
    e = C.empresa(empresa_id)
    n = R().valor("select count(*) from trd_actas where empresa_id = ?", [empresa_id]) + 1
    return f"ACTA-{e['codigo']}-{_hoy().year}-{n:03d}"


def decidir_disposiciones(disp_ids: list[int], aprobar: bool, observacion: str, usuario) -> int | None:
    """Aprobación del supervisor (o director) de la empresa. Aprobar genera UN acta con huella SHA-256; rechazar deja el
    expediente activo. El aprobador no puede ser quien emitió el concepto del archivista."""
    _exigir(usuario, ROLES_APRUEBAN, "aprobar la disposición final")
    if not disp_ids:
        raise ErrorArchivo("Elija al menos una propuesta.")
    if len((observacion or "").strip()) < 5:
        raise ErrorArchivo("Escriba una observación para el acta (mínimo 5 caracteres).")
    ds = [_disp(i, usuario) for i in disp_ids]
    if len({d["empresa_id"] for d in ds}) != 1:
        raise ErrorArchivo("Cada acta corresponde a una sola empresa. Apruebe por separado las propuestas de cada empresa.")
    for d in ds:
        if d["estado"] != "revisada":
            raise ErrorArchivo("Solo se aprueban propuestas con concepto favorable del archivista.")
        if d["revisada_por"] == usuario["id"]:
            raise ErrorArchivo("Usted emitió el concepto de una de estas propuestas: la aprobación debe hacerla otra persona.")
    emp = ds[0]["empresa_id"]
    with R().transaccion():
        acta_id = None
        if aprobar:
            lineas = []
            for d in ds:
                x = next(e for e in expedientes(usuario, emp) if e["id"] == d["expediente_id"])
                lineas.append(f"- {x['radicado']} | serie {x['serie_codigo']} {x['serie_nombre']} | cierre {fmt_fecha(x['fecha_cierre'])} | "
                              f"folios {x['folios']} | disposición: {DISPOSICIONES[d['disposicion']]}")
            numero = _numero_acta(emp)
            contenido = (f"{numero}\nEmpresa: {C.empresa(emp)['nombre']}\nFecha: {ahora():%Y-%m-%d %H:%M}\n"
                         f"Aprueba: {usuario['nombre']} ({C.ROLES.get(usuario['rol'])})\nObservación: {observacion.strip()}\n"
                         f"Expedientes ({len(ds)}):\n" + "\n".join(lineas) +
                         "\n\nActa de demostración: sin firma digital certificada.")
            acta_id = R().insertar("trd_actas", {"empresa_id": emp, "numero": numero, "fecha": ahora(), "aprobada_por": usuario["id"],
                                                 "contenido": contenido, "sha256": sha256_texto(contenido)})
        for d in ds:
            x = R().q("select * from expedientes where id = ?", [d["expediente_id"]], uno=True)
            R().actualizar("trd_disposiciones", d["id"], {
                "estado": "aprobada" if aprobar else "rechazada", "aprobada_por": usuario["id"], "aprobada_en": ahora(),
                "observacion_aprobacion": observacion.strip(), "acta_id": acta_id})
            if not aprobar:
                R().actualizar("expedientes", d["expediente_id"], {"estado": "activo"})
            _evento(usuario, "disposicion_aprobada" if aprobar else "disposicion_rechazada",
                    {"acta_id": acta_id}, emp, x["solicitud_id"])
    return acta_id


def ejecutar_disposicion(disp_id: int, detalle: str, usuario) -> None:
    """Registra que la disposición aprobada se llevó a cabo. En la demostración NO borra ni mueve ningún archivo."""
    _exigir(usuario, ROLES_GESTION, "registrar la ejecución de la disposición")
    d = _disp(disp_id, usuario)
    if d["estado"] != "aprobada" or not d["acta_id"]:
        raise ErrorArchivo("Solo se ejecutan disposiciones aprobadas con acta.")
    x = R().q("select * from expedientes where id = ?", [d["expediente_id"]], uno=True)
    if x["carpeta_id"] and R().valor("select count(*) from archivo_prestamos where carpeta_id = ? and estado = 'prestada'", [x["carpeta_id"]]):
        raise ErrorArchivo("La carpeta del expediente está prestada: registre primero su devolución.")
    resultado = {"conservar": "Conservado de forma permanente", "eliminar": "Eliminación registrada (demostración: no se borró nada)",
                 "digitalizar": "Digitalizado; papel marcado para eliminación (demostración)"}[d["disposicion"]]
    with R().transaccion():
        R().actualizar("trd_disposiciones", disp_id, {"estado": "ejecutada", "ejecutada_por": usuario["id"], "ejecutada_en": ahora(),
                                                     "detalle_ejecucion": (detalle or "").strip() or None})
        R().actualizar("expedientes", d["expediente_id"], {"estado": "dispuesto", "resultado": resultado})
        if x["carpeta_id"] and not R().valor("select count(*) from expedientes where carpeta_id = ? and estado <> 'dispuesto'", [x["carpeta_id"]]):
            R().actualizar("archivo_carpetas", x["carpeta_id"], {"estado": "dispuesta"})
        _evento(usuario, "disposicion_ejecutada", {"resultado": resultado}, d["empresa_id"], x["solicitud_id"])


# ====================================================================== alertas (se llaman desde servicios.generar_alertas)
def _destinatarios(roles: tuple[str, ...], empresa_id: int) -> list[dict]:
    res = []
    for r in roles:
        res += C.usuarios(r, empresa_id)
    return res


def _alertar(tipo: str, empresa_id: int, solicitud_id: int | None, clave_base: str, mensaje: str, roles: tuple[str, ...],
             existentes: set[str]) -> int:
    nuevas = []
    for u in _destinatarios(roles, empresa_id):
        clave = f"{tipo}|{clave_base}|u{u['id']}"
        if clave in existentes:
            continue
        existentes.add(clave)
        nuevas.append({"solicitud_id": solicitud_id, "empresa_id": empresa_id, "destinatario": u["email"], "destinatario_id": u["id"],
                       "rol_destino": u["rol"], "canal": "app", "tipo": tipo, "mensaje": mensaje, "clave": clave,
                       "programada_para": ahora(), "enviada_en": ahora(), "leida": False, "estado": "enviada"})
    R().carga_masiva("alertas", nuevas)
    return len(nuevas)


TEXTOS_ALERTA = {
    "retencion_90": "Retención por vencer en 90 días o menos",
    "retencion_30": "Retención por vencer en 30 días o menos",
    "retencion_vencida": "Retención vencida: falta proponer la disposición final",
    "disposicion_pendiente": "Disposición final revisada: pendiente de su aprobación",
    "prestamo_vencido": "Préstamo de carpeta vencido: reclame la devolución",
}


def generar_alertas_archivo(hoy: date | None = None) -> dict:
    """Alertas de TRD y archivo físico para archivista y supervisor. Idempotentes por clave (una vez por umbral)."""
    hoy = hoy or _hoy()
    existentes = {r["clave"] for r in R().q("select clave from alertas where clave is not null")}
    cuenta: dict[str, int] = {}
    for x in _expedientes_sistema(hoy):
        if x["estado"] == "dispuesto":
            continue
        niv = x["nivel"]
        if niv == "vencida":
            tipo, roles = "retencion_vencida", ("archivista", "supervisor")
        elif niv == "30":
            tipo, roles = "retencion_30", ("archivista", "supervisor")
        elif niv == "90":
            tipo, roles = "retencion_90", ("archivista",)
        else:
            continue
        cuenta[tipo] = cuenta.get(tipo, 0) + _alertar(
            tipo, x["empresa_id"], x["solicitud_id"], f"{x['id']}", f"{x['radicado']}: {TEXTOS_ALERTA[tipo]} ({fmt_fecha(x['fecha_disposicion'])})",
            roles, existentes)
    for d in R().q("select d.id, d.empresa_id, x.solicitud_id, s.radicado from trd_disposiciones d join expedientes x on x.id = d.expediente_id "
                   "join solicitudes s on s.id = x.solicitud_id where d.estado = 'revisada'"):
        cuenta["disposicion_pendiente"] = cuenta.get("disposicion_pendiente", 0) + _alertar(
            "disposicion_pendiente", d["empresa_id"], d["solicitud_id"], f"{d['id']}",
            f"{d['radicado']}: {TEXTOS_ALERTA['disposicion_pendiente']}", ("supervisor",), existentes)
    for p in R().q("select p.id, p.empresa_id, p.fecha_vence, f.codigo from archivo_prestamos p join archivo_carpetas f on f.id = p.carpeta_id "
                   "where p.estado = 'prestada'"):
        if p["fecha_vence"] and a_fecha(p["fecha_vence"]) < hoy:
            cuenta["prestamo_vencido"] = cuenta.get("prestamo_vencido", 0) + _alertar(
                "prestamo_vencido", p["empresa_id"], None, f"{p['id']}",
                f"Carpeta {p['codigo']}: {TEXTOS_ALERTA['prestamo_vencido']} (vencía el {fmt_fecha(p['fecha_vence'])})",
                ("archivista",), existentes)
    return cuenta


def _expedientes_sistema(hoy: date) -> list[dict]:
    """Todos los expedientes (tareas del sistema: sin alcance de usuario)."""
    filas = R().q("select x.*, s.radicado from expedientes x join solicitudes s on s.id = x.solicitud_id order by x.id")
    return [_decorar_exp(f, hoy) for f in filas]

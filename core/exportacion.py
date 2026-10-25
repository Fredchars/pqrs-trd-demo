"""Exportación de los datos de UNA empresa (entrega a una autoridad, portabilidad, cierre de contrato).

Paquete ZIP:
  <EMPnn>_exportacion_<fecha>/
      LEEME.txt            qué contiene y cómo verificarlo
      MANIFIESTO.json      empresa, fecha, quién lo generó, y por cada archivo del paquete: tamaño y SHA-256
      MANIFIESTO.sha256    SHA-256 del propio MANIFIESTO.json (formato `sha256sum`)
      datos/<tabla>.json   filas filtradas por empresa_id (o por el caso que pertenece a la empresa)
      archivos/<ruta>      los documentos del expediente de los casos de la empresa (prefijo EMPnn/ del bucket)
Al terminar se deja un evento `exportacion_empresa` en la bitácora (con el SHA-256 del manifiesto). Ese evento queda en la
plataforma, no dentro del paquete, porque contiene el hash del manifiesto.
Solo lectura sobre los datos: se usa la conexión de servicio, y el filtro por empresa es explícito en cada consulta."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import IO

from core import consultas as C
from core.reloj import ahora

VERSION = 2  # 2: incluye las tablas de TRD y archivo físico
# (tabla, SQL con un único parámetro: el id de la empresa, columnas a omitir). Todo se ordena para que el hash sea estable.
TABLAS: list[tuple[str, str, tuple[str, ...]]] = [
    ("empresas", "select * from empresas where id = ? order by id", ()),
    ("usuario_empresa", "select * from usuario_empresa where empresa_id = ? order by usuario_id", ()),
    ("usuarios", "select * from usuarios where id in (select usuario_id from usuario_empresa where empresa_id = ?) order by id",
     ("auth_id",)),
    ("temas", "select * from temas where empresa_id = ? order by id", ()),
    ("plantillas", "select * from plantillas where empresa_id = ? order by id", ()),
    ("festivos_extra", "select * from festivos_extra where empresa_id = ? order by id", ()),
    ("solicitantes", "select * from solicitantes where id in (select solicitante_id from solicitudes where empresa_id = ?) order by id",
     ()),
    ("solicitudes", "select * from solicitudes where empresa_id = ? order by id", ("tsv",)),
    ("asignaciones", "select a.* from asignaciones a join solicitudes s on s.id = a.solicitud_id where s.empresa_id = ? order by a.id", ()),
    ("respuestas", "select r.* from respuestas r join solicitudes s on s.id = r.solicitud_id where s.empresa_id = ? order by r.id",
     ("tsv",)),
    ("aprobaciones", "select a.* from aprobaciones a join respuestas r on r.id = a.respuesta_id "
                     "join solicitudes s on s.id = r.solicitud_id where s.empresa_id = ? order by a.id", ()),
    ("documentos", "select d.* from documentos d join solicitudes s on s.id = d.solicitud_id where s.empresa_id = ? order by d.id",
     ("texto_extraido", "tsv")),
    ("encuestas", "select e.* from encuestas e join solicitudes s on s.id = e.solicitud_id where s.empresa_id = ? order by e.id", ()),
    ("alertas", "select * from alertas where empresa_id = ? order by id", ()),
    ("eventos", "select * from eventos where empresa_id = ? order by id", ()),
    ("correos", "select * from correos where empresa_id = ? order by id", ()),
    ("correos_procesados", "select c.* from correos_procesados c join solicitudes s on s.id = c.solicitud_id "
                           "where s.empresa_id = ? order by c.message_id", ()),
    ("consecutivos", "select * from consecutivos where empresa_id = ? order by anio", ()),
    # TRD y archivo físico (db/06): todo por empresa_id
    ("trd_series", "select * from trd_series where empresa_id = ? order by id", ()),
    ("archivo_cajas", "select * from archivo_cajas where empresa_id = ? order by id", ()),
    ("archivo_carpetas", "select * from archivo_carpetas where empresa_id = ? order by id", ()),
    ("expedientes", "select * from expedientes where empresa_id = ? order by id", ()),
    ("expediente_docs", "select * from expediente_docs where empresa_id = ? order by id", ()),
    ("trd_actas", "select * from trd_actas where empresa_id = ? order by id", ()),
    ("trd_disposiciones", "select * from trd_disposiciones where empresa_id = ? order by id", ()),
    ("archivo_prestamos", "select * from archivo_prestamos where empresa_id = ? order by id", ()),
]
# Catálogo global (igual para todas las empresas): se incluye solo para poder interpretar tipo_id.
GLOBALES = [("tipos_pqrs", "select * from tipos_pqrs order by id", ("tsv",))]
OMITIDO = ("filtros_guardados (preferencias personales de cada usuario)", "parametros (configuración global de la plataforma)",
           "columnas derivadas: tsv y documentos.texto_extraido (se regeneran al indexar)", "usuarios.auth_id (identificador de Supabase Auth)")


class ErrorExportacion(Exception):
    pass


def _json(x):
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (bytes, memoryview)):
        return bytes(x).hex()
    return str(x)


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _filas(R, sql, emp_id, omitir):
    return [{k: v for k, v in f.items() if k not in omitir} for f in R.q(sql, [emp_id] if "?" in sql else [])]


def generar(codigo_empresa: str, destino: IO[bytes], usuario: dict | None = None, con_archivos: bool = True,
            operador: str | None = None) -> dict:
    """Escribe el paquete ZIP en `destino` y devuelve el manifiesto (más `nombre` y `sha256_manifiesto`).
    `usuario`: quien lo pide en la aplicación (solo admin o auditor). Sin usuario (script de operación) se anota `operador`."""
    from core import servicios as S
    from core.almacenamiento import obtener_almacen
    from core.repositorio import obtener_repo
    if usuario is not None and usuario["rol"] not in ("admin", "auditor"):
        raise ErrorExportacion("Solo el administrador o el auditor pueden exportar los datos de una empresa.")
    R = obtener_repo()
    emp = C.empresa_por_codigo(codigo_empresa)
    if not emp:
        raise ErrorExportacion(f"La empresa {codigo_empresa} no existe.")
    cod, eid = emp["codigo"], emp["id"]
    t0 = ahora()
    carpeta = f"{cod}_exportacion_{t0.strftime('%Y%m%d-%H%M%S')}"
    miembros: dict[str, bytes] = {}
    tablas = []
    for tabla, sql, omitir in [*TABLAS, *GLOBALES]:
        filas = _filas(R, sql, eid, omitir)
        datos = json.dumps(filas, ensure_ascii=False, indent=1, default=_json).encode("utf-8")
        ruta = f"datos/{tabla}.json"
        miembros[ruta] = datos
        tablas.append({"tabla": tabla, "filas": len(filas), "archivo": ruta, "bytes": len(datos), "sha256": _sha(datos),
                       "global": (tabla, sql, omitir) in GLOBALES, "columnas_omitidas": list(omitir)})
    # --- archivos del expediente (los de los casos que HOY pertenecen a la empresa) ---
    archivos, faltantes, ajenos_al_prefijo = [], [], []
    if con_archivos:
        alm = obtener_almacen()
        docs = [d for d in R.q("select d.id, d.ruta, d.sha256 from documentos d join solicitudes s on s.id = d.solicitud_id "
                               "where s.empresa_id = ? order by d.id", [eid])]
        incluidas = set()
        for d in docs:
            try:
                datos = alm.leer(d["ruta"])
            except Exception as e:  # archivo ausente o ilegible: se informa, no se inventa
                faltantes.append({"documento_id": d["id"], "ruta": d["ruta"], "error": type(e).__name__})
                continue
            incluidas.add(d["ruta"])
            h = _sha(datos)
            miembros[f"archivos/{d['ruta']}"] = datos
            archivos.append({"documento_id": d["id"], "ruta": f"archivos/{d['ruta']}", "bytes": len(datos), "sha256": h,
                             "sha256_registrado": d["sha256"], "coincide_con_registro": h == d["sha256"]})
        try:  # objetos bajo EMPnn/ que NO son de casos actuales de la empresa (p. ej. casos trasladados a otra empresa)
            ajenos_al_prefijo = [r for r in alm.listar(f"{cod}/") if r not in incluidas]
        except Exception:
            ajenos_al_prefijo = None
    # --- verificación: ninguna fila de una solicitud de otra empresa ---
    ids_sol = {f["id"] for f in json.loads(miembros["datos/solicitudes.json"])}
    cruces = 0
    for tabla in ("asignaciones", "respuestas", "documentos", "encuestas", "alertas", "eventos", "correos", "trd_series", "archivo_cajas",
                  "archivo_carpetas", "expedientes", "expediente_docs", "trd_actas", "trd_disposiciones", "archivo_prestamos"):
        for f in json.loads(miembros[f"datos/{tabla}.json"]):
            if f.get("solicitud_id") is not None and f["solicitud_id"] not in ids_sol:
                cruces += 1
            if f.get("empresa_id") is not None and f["empresa_id"] != eid:
                cruces += 1
    if cruces:
        raise ErrorExportacion(f"Verificación fallida: {cruces} fila(s) no pertenecen a la empresa. No se genera el paquete.")
    manifiesto = {
        "version": VERSION, "empresa": {"id": eid, "codigo": cod, "nombre": emp["nombre"]}, "generado_en": t0.isoformat(),
        "generado_por": ({"id": usuario["id"], "email": usuario["email"], "rol": usuario["rol"]} if usuario
                         else {"operador": operador or "script"}),
        "criterio": "Filas con empresa_id = la empresa, o hijas de casos (solicitudes) que hoy pertenecen a la empresa.",
        "tablas": tablas, "archivos": archivos, "con_archivos": con_archivos,
        "archivos_faltantes_en_almacen": faltantes,
        "archivos_bajo_el_prefijo_que_no_son_de_casos_actuales": ajenos_al_prefijo,
        "no_incluido": list(OMITIDO),
        "verificaciones": {"filas_de_otra_empresa": cruces,
                           "archivos_con_hash_distinto_al_registrado": sum(not a["coincide_con_registro"] for a in archivos)},
        "avisos": ["Eventos de sistema sin empresa (empresa_id NULL) y correos sin buzón identificable no pertenecen a ninguna "
                   "empresa y no se incluyen.",
                   "Un caso trasladado a otra empresa viaja con su historial: aparece en la exportación de la empresa actual.",
                  "TRD y archivo físico: se exportan las series, cajas, carpetas, expedientes (con su índice), préstamos, propuestas de "
                  "disposición y actas. El papel no se exporta (solo su registro y ubicación)."],
    }
    mbytes = json.dumps(manifiesto, ensure_ascii=False, indent=1).encode("utf-8")
    mhash = _sha(mbytes)
    leeme = (f"Exportación de datos · {emp['nombre']} ({cod})\nGenerada: {t0.isoformat()}\n\n"
             "Contenido: datos/*.json (tablas filtradas por empresa), archivos/ (expediente), MANIFIESTO.json (lista de todo con "
             "SHA-256).\nVerificación: `sha256sum -c MANIFIESTO.sha256` valida el manifiesto; cada archivo se valida contra el "
             "SHA-256 del manifiesto (o con `python scripts/exportar_empresa.py --verificar PAQUETE.zip`).\n"
             "Separación lógica por empresa (modelo pool con RLS); el paquete no prueba separación física de las bases.\n").encode("utf-8")
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{carpeta}/LEEME.txt", leeme)
        z.writestr(f"{carpeta}/MANIFIESTO.json", mbytes)
        z.writestr(f"{carpeta}/MANIFIESTO.sha256", f"{mhash}  MANIFIESTO.json\n")
        for ruta, datos in miembros.items():
            z.writestr(f"{carpeta}/{ruta}", datos)
    S.evento(None, usuario, "exportacion_empresa",
             {"empresa": cod, "sha256_manifiesto": mhash, "tablas": {t["tabla"]: t["filas"] for t in tablas if not t["global"]},
              "archivos": len(archivos), "operador": None if usuario else (operador or "script"), "paquete": carpeta},
             origen="app" if usuario else "script", empresa_id=eid)
    return {**manifiesto, "nombre": f"{carpeta}.zip", "sha256_manifiesto": mhash}


def generar_bytes(codigo_empresa: str, usuario: dict | None = None, con_archivos: bool = True) -> tuple[str, bytes, dict]:
    buf = io.BytesIO()
    man = generar(codigo_empresa, buf, usuario, con_archivos)
    return man["nombre"], buf.getvalue(), man


def verificar(origen: str | IO[bytes]) -> list[str]:
    """Recalcula los SHA-256 de un paquete y los compara con el manifiesto. Devuelve la lista de problemas (vacía = íntegro)."""
    problemas = []
    with zipfile.ZipFile(origen) as z:
        nombres = z.namelist()
        raiz = nombres[0].split("/")[0]
        man_b = z.read(f"{raiz}/MANIFIESTO.json")
        esperado = z.read(f"{raiz}/MANIFIESTO.sha256").decode().split()[0]
        if _sha(man_b) != esperado:
            problemas.append("MANIFIESTO.json no coincide con MANIFIESTO.sha256")
        man = json.loads(man_b)
        listados = {t["archivo"]: t["sha256"] for t in man["tablas"]} | {a["ruta"]: a["sha256"] for a in man["archivos"]}
        for ruta, h in listados.items():
            try:
                if _sha(z.read(f"{raiz}/{ruta}")) != h:
                    problemas.append(f"{ruta}: el contenido cambió")
            except KeyError:
                problemas.append(f"{ruta}: falta en el paquete")
        sobrantes = set(nombres) - {f"{raiz}/{r}" for r in listados} - {f"{raiz}/{x}" for x in ("LEEME.txt", "MANIFIESTO.json", "MANIFIESTO.sha256")}
        problemas += [f"{n}: no está en el manifiesto" for n in sorted(sobrantes) if not n.endswith("/")]
    return problemas

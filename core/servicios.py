"""Casos de uso del sistema (radicar, repartir, tramitar, aprobar, enviar, alertar...).

Toda acción valida el rol, respeta las transiciones de core/flujo.py y deja un evento en la bitácora.
"""
from __future__ import annotations

import difflib
import mimetypes
import re
from datetime import date, datetime, timedelta

from core import alertas as reglas
from core import aprobacion, correo, documentos as docs, flujo, plantillas, plazos, radicado as rad, reparto
from core import consultas as C
from core.almacenamiento import obtener_almacen
from core.config import app_url
from core.reloj import a_fecha, a_fechahora, ahora, fmt_fecha, hoy as _hoy
from core.repositorio import obtener_repo


class ErrorNegocio(Exception):
    """Error comprensible para mostrar al usuario: dice qué pasó y qué hacer."""


def R():
    return obtener_repo()


def _rol(usuario):
    return usuario["rol"] if usuario else "sistema"


def _uid(usuario):
    return usuario["id"] if usuario else None


def evento(sid, usuario, accion, detalle=None, origen=None, empresa_id=None):
    """Bitácora. Con caso, la empresa es la del caso (la fija la BD); sin caso, `empresa_id` si se conoce (si no, NULL)."""
    R().insertar("eventos", {"solicitud_id": sid, "usuario_id": _uid(usuario), "empresa_id": None if sid else empresa_id,
                             "origen": origen or (usuario.get("origen", "app") if usuario else "sistema"),
                             "accion": accion, "detalle": detalle or {}, "fecha": ahora()})


def _sol(sid):
    s = C.obtener_solicitud(sid, sin_alcance=True)
    if not s:
        raise ErrorNegocio("No se encontró la solicitud. Verifique el número de radicado.")
    return s


def _transicion(s, destino, usuario, detalle=None, rol=None, extra=None):
    rol = rol or _rol(usuario)
    try:
        flujo.validar(s["estado"], destino, rol)
    except flujo.TransicionInvalida as e:
        raise ErrorNegocio(str(e)) from e
    R().actualizar("solicitudes", s["id"], {"estado": destino, **(extra or {})})
    evento(s["id"], usuario, "cambio_estado", {"de": s["estado"], "a": destino, **(detalle or {})})
    s["estado"] = destino


def _vars(s, usuario=None, **extra):
    abogado = C.usuario(s.get("abogado_id")) if s.get("abogado_id") else None
    firmante = usuario if usuario and usuario.get("rol") in ("abogado", "supervisor", "director") else abogado
    return {"radicado": s["radicado"], "nombre": s.get("solicitante_nombre") or "ciudadano(a)",
            "fecha_radicacion": fmt_fecha(s.get("fecha_radicacion")), "fecha_vencimiento": fmt_fecha(s.get("fecha_vencimiento")),
            "empresa": s.get("empresa_nombre"), "abogado": (firmante or {}).get("nombre", "Equipo jurídico"),
            "cargo": (firmante or {}).get("cargo", "Área jurídica"), "asunto": s.get("asunto"), "tipo": s.get("tipo_nombre"),
            "enlace_consulta": f"{app_url()}/consultar_estado?radicado={s['radicado']}", **extra}


def _plantilla(clave, s):
    ps = C.plantillas(clave, s["empresa_id"], s["tipo_id"])
    return ps[0] if ps else None


def _notificar_ciudadano(s, clave, usuario=None, adjuntos=None, **extra):
    """Envía al ciudadano el correo de la plantilla `clave` (si tiene correo)."""
    email = s.get("solicitante_email")
    p = _plantilla(clave, s)
    if not email or not p:
        return None
    v = _vars(s, usuario, **extra)
    asunto = f"[{s['radicado']}] " + plantillas.render(p["asunto"] or p["nombre"], v)
    r = correo.enviar(R(), email, asunto, plantillas.render(p["cuerpo"], v), adjuntos, s["id"])
    evento(s["id"], usuario, "correo_ciudadano", {"plantilla": clave, "estado": r["estado"], "para": email})
    return r


# ====================================================================== ALERTAS
def _resolver_destinatarios(rol_dest, s):
    if rol_dest == "abogado":
        u = C.usuario(s.get("abogado_id")) if s.get("abogado_id") else None
        return [u] if u else []
    if rol_dest in ("supervisor", "director", "radicador", "archivista"):
        return C.usuarios(rol_dest, s["empresa_id"])
    if rol_dest == "aprobador":
        return estado_aprobacion(s)["posibles"]
    if rol_dest == "autor":  # quien redactó la respuesta en revisión
        r = _respuesta_actual(s["id"])
        u = C.usuario(r["autor_id"]) if r and r.get("autor_id") else None
        return [u] if u else []
    if rol_dest == "admin":
        return C.usuarios("admin", s["empresa_id"]) or C.usuarios("admin")
    return []


def _alertar_aprobacion(s, mensaje=None, **kw):
    """Avisa a quien puede aprobar. Si nadie puede (p. ej. el único supervisor redactó la respuesta), avisa al autor y a
    administración en lugar de dejar la alerta de aprobación en manos del propio autor."""
    if estado_aprobacion(s)["sin_aprobador"]:
        return alertar("aprobacion_sin_aprobador", s, None, **kw)
    return alertar("aprobacion_pendiente", s, mensaje, **kw)


def alertar(tipo, s, mensaje=None, hoy=None, existentes=None, enviar_correo=True, clave_extra=""):
    """Crea alertas internas según la matriz (idempotentes por clave). Devuelve cuántas creó."""
    hoy = hoy or _hoy()
    texto = f"{s['radicado']}: {mensaje or reglas.TEXTOS.get(tipo, tipo)}"
    nuevas, correos_ = [], []
    for rol_dest in reglas.destinatarios(tipo):
        if rol_dest == "ciudadano":
            continue  # al ciudadano se le escribe con plantillas en cada flujo
        for u in _resolver_destinatarios(rol_dest, s):
            clave = reglas.clave(tipo, s["id"], f"u{u['id']}", hoy) + clave_extra
            if existentes is not None:
                if clave in existentes:
                    continue
                existentes.add(clave)
            elif R().valor("select count(*) from alertas where clave = ?", [clave]):
                continue
            nuevas.append({"solicitud_id": s["id"], "destinatario": u["email"], "destinatario_id": u["id"],
                           "rol_destino": rol_dest, "canal": "app+correo", "tipo": tipo, "mensaje": texto, "clave": clave,
                           "programada_para": ahora(), "enviada_en": ahora(), "leida": False, "estado": "enviada"})
            if enviar_correo and C.param_si("alertas_por_correo", True):
                correos_.append(u["email"])
    if nuevas:
        R().carga_masiva("alertas", nuevas)
        filas = []
        enlace = f"{app_url()}/detalle_caso?caso={s['radicado']}"
        cuerpo_alerta = f"{texto}\n\nAbra el caso directamente: {enlace}\n(Si no ha iniciado sesión, ingrese primero y vuelva a abrir el enlace.)"
        for email in correos_:
            if correo.modo() == "real":
                if not email.endswith("example.com"):  # usuarios ficticios: en modo real solo queda la campana
                    correo.enviar(R(), email, f"[Alerta PQRS] {texto}", cuerpo_alerta, None, s["id"])
                continue
            filas.append({"direccion": "salida", "modo": "simulado", "message_id": None, "de": correo.remitente(),
                          "para": email, "asunto": f"[Alerta PQRS] {texto}",
                          "cuerpo": cuerpo_alerta, "eml": None,
                          "solicitud_id": s["id"], "estado": "simulado", "error": None, "fecha": ahora()})
        R().carga_masiva("correos", filas)
    return len(nuevas)


def marcar_alerta_leida(alerta_id, usuario):
    R().ex("update alertas set leida = ? where id = ? and destinatario_id = ?", [True, alerta_id, usuario["id"]])


def marcar_todas_leidas(usuario):
    R().ex("update alertas set leida = ? where destinatario_id = ?", [True, usuario["id"]])


# ====================================================================== RADICACIÓN
def _similar(a, b):
    return difflib.SequenceMatcher(a=C.sin_tildes(a), b=C.sin_tildes(b)).ratio()


def detectar_duplicado(empresa_id, email, num_doc, asunto, excluir_id=None, cuando=None):
    """Mismo correo o documento, misma empresa y asunto similar en los últimos N días."""
    if not email and not num_doc:
        return None
    dias = int(C.param_num("ventana_duplicados_dias", 5))
    desde = (cuando or ahora()) - timedelta(days=dias)
    filas = R().q("select s.id, s.radicado, s.asunto, so.email, so.num_doc from solicitudes s "
                  "left join solicitantes so on so.id = s.solicitante_id where s.empresa_id = ? and s.fecha_recepcion >= ? "
                  "and s.estado <> 'ANULADA'", [empresa_id, desde])
    for f in filas:
        if f["id"] == excluir_id:
            continue
        mismo = (email and (f["email"] or "").lower() == email.lower()) or (num_doc and f["num_doc"] == num_doc)
        if mismo and _similar(f["asunto"], asunto) >= 0.6:
            return f
    return None


AVISO_PRIVACIDAD_CORREO = (
    "\n\nTratamiento de datos personales (Ley 1581 de 2012): usaremos sus datos solo para tramitar y responder "
    "esta solicitud. Para dejar constancia de su autorización, responda a este correo conservando el número de "
    "radicado en el asunto e incluya la frase «AUTORIZO el tratamiento de mis datos». Su solicitud se tramita "
    "igualmente dentro del plazo legal.")
FRASE_AUTORIZA = re.compile(r"autorizo\s+(el\s+)?tratamiento", re.IGNORECASE)


def registrar_consentimiento(sid, origen="correo", detalle=None):
    """Marca la autorización de datos del solicitante del caso (Ley 1581) con fecha y deja evento."""
    s = _sol(sid)
    sol = R().q("select id, autoriza_datos from solicitantes where id = ?", [s["solicitante_id"]])
    if not sol or sol[0]["autoriza_datos"]:
        return False
    R().actualizar("solicitantes", sol[0]["id"], {"autoriza_datos": True, "fecha_autorizacion": ahora()})
    evento(sid, None, "consentimiento_registrado", {"canal": origen, **(detalle or {})}, origen=origen)
    return True


def radicar(datos, canal="web", archivos=(), usuario=None, recibido=None, message_id=None, omitir_invalidos=False,
            origen=None, asignar_ya=None):
    """Crea la solicitud, calcula plazos, guarda adjuntos en 01_entrada, envía el acuse y la reparte."""
    emp = C.empresa(datos.get("empresa_id")) or C.empresa_por_codigo(datos.get("empresa_codigo", ""))
    if not emp:
        raise ErrorNegocio("Seleccione la empresa a la que dirige su solicitud.")
    tp = C.tipo(datos.get("tipo_id")) or C.tipo_por_codigo(datos.get("tipo_codigo", ""))
    if not tp:
        raise ErrorNegocio("Seleccione el tipo de solicitud (petición, queja, reclamo...).")
    asunto = (datos.get("asunto") or "").strip()
    descripcion = (datos.get("descripcion") or "").strip()
    if len(asunto) < 4:
        raise ErrorNegocio("Escriba un asunto corto que resuma su solicitud (mínimo 4 caracteres).")
    if len(descripcion) < 10:
        raise ErrorNegocio("Describa su solicitud con un poco más de detalle (mínimo 10 caracteres).")
    anonimo = bool(datos.get("anonimo"))
    email = (datos.get("email") or "").strip().lower() or None
    if anonimo:
        if not emp.get("acepta_anonimas"):
            raise ErrorNegocio(f"{emp['nombre']} no recibe solicitudes anónimas. Escriba su nombre y correo.")
        if C.param_si("anonimas_solo_quejas", True) and tp["codigo"] != "Q":
            raise ErrorNegocio("Las solicitudes anónimas solo se aceptan para quejas.")
    else:
        if not (datos.get("nombre") or "").strip():
            raise ErrorNegocio("Escriba su nombre completo.")
        if canal in ("web", "api") and not email:
            raise ErrorNegocio("Escriba un correo electrónico para enviarle el acuse y la respuesta.")
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise ErrorNegocio("El correo electrónico no parece válido. Revíselo (ejemplo: nombre@correo.com).")
    if canal == "web" and not datos.get("autoriza_datos"):
        raise ErrorNegocio("Para radicar debe autorizar el tratamiento de sus datos personales (Ley 1581 de 2012).")

    max_mb, max_total = C.param_num("max_mb_archivo", 10), C.param_num("max_mb_solicitud", 25)
    validos, rechazados, total = [], [], 0
    for nombre, contenido, mime in archivos or []:
        try:
            docs.validar(nombre, len(contenido), total, max_mb, max_total)
            validos.append((nombre, contenido, mime or mimetypes.guess_type(nombre)[0] or "application/octet-stream"))
            total += len(contenido)
        except docs.ErrorDocumento as e:
            if not omitir_invalidos:
                raise ErrorNegocio(str(e)) from e
            rechazados.append(str(e))

    recibido = recibido or ahora()
    extra = C.festivos(emp["id"])
    f_rad = plazos.fecha_radicacion(recibido, C.hora_corte(), extra)
    f_ven = plazos.fecha_vencimiento(f_rad, int(tp["dias_habiles"]), extra)
    codigo = rad.nuevo_codigo()
    repo = R()
    with repo.transaccion():
        sol_id = repo.insertar("solicitantes", {
            "tipo_doc": datos.get("tipo_doc") or ("NA" if anonimo else "CC"),
            "num_doc": (datos.get("num_doc") or "").strip() or None,
            "nombre": "Anónimo" if anonimo else datos.get("nombre").strip(), "email": email,
            "telefono": datos.get("telefono"), "direccion": datos.get("direccion"), "anonimo": anonimo,
            "autoriza_datos": bool(datos.get("autoriza_datos")),
            "fecha_autorizacion": recibido if datos.get("autoriza_datos") else None})
        consecutivo = repo.siguiente_consecutivo(emp["id"], f_rad.year)
        numero = rad.formatear(emp["codigo"], f_rad.year, tp["codigo"], consecutivo)
        dup = detectar_duplicado(emp["id"], email, datos.get("num_doc"), asunto, cuando=recibido)
        sid = repo.insertar("solicitudes", {
            "radicado": numero, "empresa_id": emp["id"], "tipo_id": tp["id"], "tema_id": datos.get("tema_id"),
            "solicitante_id": sol_id, "canal": canal, "asunto": asunto, "descripcion": descripcion, "estado": "RECIBIDA",
            "prioridad": datos.get("prioridad") or "normal", "fecha_recepcion": recibido, "fecha_radicacion": f_rad,
            "fecha_vencimiento": f_ven, "codigo_consulta": rad.hash_codigo(numero, codigo), "message_id": message_id,
            "posible_duplicado_de": dup["id"] if dup else None, "revisar_duplicado": bool(dup), "creado_por": _uid(usuario),
            "marca": datos.get("marca"), "docs_fisicos": bool(datos.get("docs_fisicos")),
            "hojas_fisicas": int(datos.get("hojas_fisicas") or 0) if datos.get("docs_fisicos") else 0})
        repo.indexar(sid, "solicitud", sid, f"{numero} {asunto} {descripcion}")
        evento(sid, usuario, "radicada", {"radicado": numero, "canal": canal, "fecha_radicacion": f_rad.isoformat(),
                                          "fecha_vencimiento": f_ven.isoformat(), "adjuntos": len(validos),
                                          "rechazados": rechazados}, origen=origen or ("ciudadano" if not usuario else None))
        if dup:
            evento(sid, usuario, "posible_duplicado", {"de": dup["radicado"]})
    s = _sol(sid)
    for nombre, contenido, mime in validos:
        adjuntar(s, "entrada", nombre, contenido, mime, usuario, origen=canal, validar=False)
    nota = ("\n\nNo pudimos recibir algunos archivos:\n- " + "\n- ".join(rechazados)) if rechazados else ""
    if canal == "correo" and not anonimo and not datos.get("autoriza_datos"):
        nota += AVISO_PRIVACIDAD_CORREO
        evento(sid, usuario, "consentimiento_pendiente", {"canal": "correo", "aviso_enviado": True}, origen=origen)
    elif datos.get("autoriza_datos"):
        evento(sid, usuario, "consentimiento_registrado", {"canal": canal, "fecha": recibido.isoformat()}, origen=origen)
    acuse = _notificar_ciudadano(s, "acuse", usuario, codigo=codigo, texto=nota)
    if dup:
        alertar("posible_duplicado", s, f"posible duplicado de {dup['radicado']}")
    asignado = None
    if (asignar_ya if asignar_ya is not None else C.param_si("asignar_al_radicar", True)) and not dup:
        asignado = asignar(sid)
    return {"solicitud": _sol(sid), "codigo": codigo, "acuse": acuse, "duplicado_de": dup["radicado"] if dup else None,
            "rechazados": rechazados, "asignado_a": asignado}


def completar_radicaciones_api():
    """Solicitudes creadas por REST (rpc radicar_pqrs): calcula plazos con festivos, acuse y reparto."""
    n = 0
    for fila in R().q("select id from solicitudes where pendiente_completar"):
        x = _sol(fila["id"])
        extra = C.festivos(x["empresa_id"])
        f_rad = plazos.fecha_radicacion(a_fechahora(x["fecha_recepcion"]), C.hora_corte(), extra)
        f_ven = plazos.fecha_vencimiento(f_rad, int(x["dias_habiles"]), extra)
        R().actualizar("solicitudes", x["id"], {"fecha_radicacion": f_rad, "fecha_vencimiento": f_ven,
                                                "pendiente_completar": False})
        R().indexar(x["id"], "solicitud", x["id"], f"{x['radicado']} {x['asunto']} {x['descripcion']}")
        evento(x["id"], None, "plazos_calculados", {"fecha_radicacion": f_rad.isoformat(), "fecha_vencimiento": f_ven.isoformat()})
        x = _sol(x["id"])
        _notificar_ciudadano(x, "acuse", None, codigo="(el entregado al radicar por API)", texto="")
        asignar(x["id"])
        n += 1
    return n


# ====================================================================== DOCUMENTOS
def adjuntar(s, categoria, nombre, contenido, mime, usuario, origen="app", validar=True):
    if categoria not in docs.CATEGORIAS:
        raise ErrorNegocio("Categoría de documento no válida.")
    if validar:
        total = int(R().valor("select coalesce(sum(tamano), 0) from documentos where solicitud_id = ? "
                              "and categoria in ('entrada','soporte')", [s["id"]]) or 0)
        try:
            docs.validar(nombre, len(contenido), total if categoria in ("entrada", "soporte") else 0,
                         C.param_num("max_mb_archivo", 10), C.param_num("max_mb_solicitud", 25))
        except docs.ErrorDocumento as e:
            raise ErrorNegocio(str(e)) from e
    version = int(R().valor("select count(*) from documentos where solicitud_id = ? and categoria = ? and nombre_original = ?",
                            [s["id"], categoria, nombre]) or 0) + 1
    t = ahora()
    nombre_n = docs.nombre_normalizado(s["radicado"], categoria, t, version, nombre)
    ruta = docs.ruta(s["empresa_codigo"], int(s["radicado"].split("-")[1]), s["tipo_codigo"], s["radicado"], categoria, nombre_n)
    huella = docs.sha256(contenido)
    texto, estado_texto = docs.extraer_texto(nombre, contenido)
    obtener_almacen().guardar(ruta, contenido, mime)
    did = R().insertar("documentos", {
        "solicitud_id": s["id"], "categoria": categoria, "nombre": nombre_n, "nombre_original": nombre, "ruta": ruta,
        "mime": mime or mimetypes.guess_type(nombre)[0], "tamano": len(contenido), "sha256": huella, "version": version,
        "texto_extraido": texto, "estado_texto": estado_texto, "subido_por": _uid(usuario), "origen": origen, "fecha": t})
    if texto:
        R().indexar(s["id"], f"documento: {nombre}", did, f"{nombre} {texto}")
    evento(s["id"], usuario, "documento_agregado", {"documento_id": did, "categoria": categoria, "nombre": nombre,
                                                    "sha256": huella, "version": version, "texto": estado_texto})
    return {"id": did, "ruta": ruta, "sha256": huella, "version": version, "estado_texto": estado_texto}


def descargar(doc_id, usuario=None):
    """Devuelve (contenido, documento, íntegro). Verifica el SHA-256 al descargar."""
    d = C.documento(doc_id)
    if not d:
        raise ErrorNegocio("Documento no encontrado.")
    if usuario is not None and not C.puede_ver(usuario, _sol(d["solicitud_id"])):
        raise ErrorNegocio("No tiene permiso para ver este documento.")
    datos = obtener_almacen().leer(d["ruta"])
    integro = docs.sha256(datos) == d["sha256"]
    if not integro:
        evento(d["solicitud_id"], usuario, "integridad_fallida", {"documento_id": doc_id})
    return datos, d, integro


def agregar_nota(sid, texto, usuario, origen="app"):
    if not (texto or "").strip():
        raise ErrorNegocio("La nota está vacía.")
    s = _sol(sid)
    r = adjuntar(s, "trabajo", "nota-interna.txt", texto.strip().encode("utf-8"), "text/plain", usuario, origen, validar=False)
    evento(sid, usuario, "nota", {"documento_id": r["id"], "texto": texto[:300]}, origen=origen)
    return r


# ====================================================================== REPARTO
_ABIERTOS_SQL = ", ".join(f"'{e}'" for e in sorted(flujo.ABIERTOS))


def capacidad_defecto() -> int:
    return int(C.param_num("capacidad_max_defecto", 40))


def _capacidad(a) -> int:
    v = a.get("capacidad_max")
    return capacidad_defecto() if v in (None, "") else int(v)


def _candidatos(empresa_id, excluir=()):
    abogados = [a for a in C.usuarios("abogado", empresa_id) if a["id"] not in set(excluir)]
    if not abogados:
        return []
    ids = [a["id"] for a in abogados]
    marc = ", ".join("?" for _ in ids)
    abiertos = R().q(f"select s.abogado_id, s.fecha_vencimiento, t.peso_carga from solicitudes s join tipos_pqrs t "
                     f"on t.id = s.tipo_id where s.abogado_id in ({marc}) and s.estado in ({_ABIERTOS_SQL})", ids)
    inicio = datetime.combine(_hoy(), datetime.min.time(), tzinfo=ahora().tzinfo)
    hoy_cnt = {r["abogado_id"]: r["n"] for r in R().q(
        f"select abogado_id, count(*) as n from asignaciones where abogado_id in ({marc}) and fecha >= ? group by abogado_id",
        ids + [inicio])}
    ultima = {r["abogado_id"]: r["u"] for r in R().q(
        f"select abogado_id, max(fecha) as u from asignaciones where abogado_id in ({marc}) group by abogado_id", ids)}
    h = _hoy()
    res = []
    for a in abogados:
        casos = [reparto.CasoAbierto(float(x["peso_carga"]), a_fecha(x["fecha_vencimiento"]) or h)
                 for x in abiertos if x["abogado_id"] == a["id"]]
        res.append(reparto.Abogado(a["id"], a["nombre"], bool(a["disponible"]), a_fecha(a["ausente_desde"]),
                                   a_fecha(a["ausente_hasta"]), _capacidad(a), list(a.get("especialidades") or []),
                                   casos, int(hoy_cnt.get(a["id"], 0)), a_fechahora(ultima.get(a["id"]))))
    return res


def asignar(sid, usuario=None, excluir=(), motivo="automatica", detalle=None):
    """Aplica la estrategia de la empresa. Devuelve el nombre del abogado o None (cola del supervisor)."""
    s = _sol(sid)
    emp = C.empresa(s["empresa_id"])
    estrategia = emp.get("estrategia_reparto") or "E"
    elegido = reparto.elegir_abogado(_candidatos(s["empresa_id"], excluir), _hoy(), estrategia,
                                     s.get("especialidad_requerida"), C.festivos(s["empresa_id"]))
    with R().transaccion():
        if elegido is None:
            R().actualizar("solicitudes", sid, {"abogado_id": None})
            R().insertar("asignaciones", {"solicitud_id": sid, "abogado_id": None, "motivo": "cola",
                                          "detalle": detalle or "Sin candidatos disponibles", "asignado_por": _uid(usuario),
                                          "fecha": ahora()})
            evento(sid, usuario, "en_cola_supervisor", {"estrategia": estrategia, "motivo": motivo})
        else:
            R().actualizar("solicitudes", sid, {"abogado_id": elegido.id})
            R().insertar("asignaciones", {"solicitud_id": sid, "abogado_id": elegido.id, "motivo": motivo,
                                          "detalle": detalle, "asignado_por": _uid(usuario), "fecha": ahora()})
            evento(sid, usuario, "asignada", {"abogado_id": elegido.id, "abogado": elegido.nombre, "motivo": motivo,
                                             "estrategia": estrategia})
            if s["estado"] == "RECIBIDA":
                _transicion(s, "ASIGNADA", usuario, rol="sistema")
    s = _sol(sid)
    if elegido is None:
        if estrategia != "D":
            alertar("sin_candidato", s)
        return None
    alertar("asignada", s, clave_extra=f"|{elegido.id}|{ahora().isoformat()}")
    return elegido.nombre


def reasignar(sid, nuevo_abogado_id, motivo, usuario, tipo_motivo="manual"):
    if _rol(usuario) not in ("supervisor", "admin"):
        raise ErrorNegocio("Solo el supervisor puede reasignar casos.")
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo de la reasignación (es obligatorio).")
    s = _sol(sid)
    if _rol(usuario) == "supervisor" and s["empresa_id"] not in usuario["empresas"]:
        raise ErrorNegocio("Este caso no pertenece a su empresa.")
    nuevo = C.usuario(nuevo_abogado_id)
    if not nuevo or nuevo["rol"] != "abogado" or s["empresa_id"] not in nuevo["empresas"]:
        raise ErrorNegocio("El abogado elegido no atiende esta empresa.")
    with R().transaccion():
        R().actualizar("solicitudes", sid, {"abogado_id": nuevo_abogado_id})
        R().insertar("asignaciones", {"solicitud_id": sid, "abogado_id": nuevo_abogado_id, "motivo": tipo_motivo,
                                      "detalle": motivo, "asignado_por": usuario["id"], "fecha": ahora()})
        evento(sid, usuario, "reasignada", {"de": s.get("abogado_nombre"), "a": nuevo["nombre"], "motivo": motivo})
        if s["estado"] == "RECIBIDA":
            _transicion(s, "ASIGNADA", usuario)
    alertar("asignada", _sol(sid), "caso reasignado a usted: " + motivo, clave_extra=f"|{nuevo_abogado_id}|{ahora().isoformat()}")


def rechazar_caso(sid, motivo, usuario):
    """El abogado devuelve un caso (conflicto de interés, tema ajeno). Se reasigna y se informa al supervisor."""
    s = _sol(sid)
    if s.get("abogado_id") != usuario["id"]:
        raise ErrorNegocio("Solo puede devolver casos asignados a usted.")
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo por el que devuelve el caso.")
    evento(sid, usuario, "caso_rechazado_por_abogado", {"motivo": motivo})
    nombre = asignar(sid, usuario, excluir=[usuario["id"]], motivo="rechazo", detalle=motivo)
    filas = [{"solicitud_id": sid, "destinatario": sup["email"], "destinatario_id": sup["id"], "rol_destino": "supervisor",
              "canal": "app", "tipo": "rechazo_abogado",
              "mensaje": f"{s['radicado']}: {usuario['nombre']} devolvió el caso ({motivo}). Nuevo responsable: {nombre or 'cola'}",
              "clave": f"rechazo|{sid}|{usuario['id']}|{sup['id']}|{ahora().isoformat()}", "programada_para": ahora(),
              "enviada_en": ahora(), "leida": False, "estado": "enviada"} for sup in C.usuarios("supervisor", s["empresa_id"])]
    R().carga_masiva("alertas", filas)
    return nombre


def marcar_ausencia(abogado_id, desde, hasta, reasignar_casos, usuario):
    if _rol(usuario) not in ("supervisor", "admin"):
        raise ErrorNegocio("Solo el supervisor puede registrar ausencias.")
    if hasta < desde:
        raise ErrorNegocio("La fecha final de la ausencia no puede ser anterior a la inicial.")
    ab = C.usuario(abogado_id)
    R().actualizar("usuarios", abogado_id, {"ausente_desde": desde, "ausente_hasta": hasta})
    C.limpiar_cache()
    evento(None, usuario, "ausencia_registrada", {"abogado": ab["nombre"], "desde": desde.isoformat(),
                                                  "hasta": hasta.isoformat(), "reasignar": reasignar_casos})
    movidos, conservados = [], []
    for s in C.listar_solicitudes(None, {"abogado_id": abogado_id, "abiertos": True}, sin_alcance=True):
        venc = a_fecha(s["fecha_vencimiento"])
        if reasignar_casos or (venc and venc <= hasta):
            nombre = asignar(s["id"], usuario, excluir=[abogado_id], motivo="ausencia", detalle=f"Ausencia de {ab['nombre']}")
            movidos.append((s["radicado"], nombre or "cola del supervisor"))
        else:
            conservados.append(s["radicado"])
    return {"reasignados": movidos, "conservados": conservados}


def quitar_ausencia(abogado_id, usuario):
    if _rol(usuario) not in ("supervisor", "admin"):
        raise ErrorNegocio("Solo el supervisor puede registrar ausencias.")
    R().actualizar("usuarios", abogado_id, {"ausente_desde": None, "ausente_hasta": None})
    C.limpiar_cache()
    evento(None, usuario, "ausencia_terminada", {"abogado_id": abogado_id})


def trasladar_empresa(sid, empresa_destino_id, motivo, usuario):
    """Traslado dentro del consorcio: conserva el radicado, crea referencia cruzada e informa al ciudadano."""
    if _rol(usuario) not in ("supervisor", "admin", "director"):
        raise ErrorNegocio("Solo el supervisor o el director pueden trasladar entre empresas.")
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo del traslado.")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    destino = C.empresa(empresa_destino_id)
    if not destino or destino["id"] == s["empresa_id"]:
        raise ErrorNegocio("Elija una empresa de destino diferente.")
    tema_dest = next((t for t in C.temas(destino["id"]) if t["nombre"] == s.get("tema_nombre")), None)
    R().actualizar("solicitudes", sid, {"empresa_id": destino["id"], "empresa_origen_id": s["empresa_id"],
                                        "tema_id": tema_dest["id"] if tema_dest else None, "abogado_id": None})
    R().propagar_empresa(sid, destino["id"])  # correos, alertas y eventos del caso viajan con él (en PG lo hace la FK)
    evento(sid, usuario, "trasladada_empresa", {"de": s["empresa_codigo"], "a": destino["codigo"], "motivo": motivo})
    nombre = asignar(sid, usuario, motivo="traslado", detalle=f"Traslado desde {s['empresa_codigo']}")
    _notificar_ciudadano(_sol(sid), "traslado_interno", usuario, entidad=destino["nombre"], motivo=motivo)
    return nombre


def trasladar_externo(sid, entidad, motivo, usuario):
    """Sin competencia: se remite a la entidad competente y se informa al ciudadano (estado TRASLADADA)."""
    if not (entidad or "").strip() or not (motivo or "").strip():
        raise ErrorNegocio("Indique la entidad competente y el motivo del traslado.")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    _transicion(s, "TRASLADADA", usuario, {"entidad": entidad, "motivo": motivo},
                extra={"entidad_traslado": entidad, "fecha_respuesta": ahora()})
    _notificar_ciudadano(s, "traslado", usuario, entidad=entidad, motivo=motivo)


# ====================================================================== TRÁMITE
def _permiso_caso(s, usuario):
    if usuario is None:
        return
    rol = usuario["rol"]
    if rol == "abogado" and s.get("abogado_id") != usuario["id"]:
        raise ErrorNegocio("Este caso no está asignado a usted.")
    if rol in ("supervisor", "director", "radicador") and s["empresa_id"] not in usuario.get("empresas", []):
        raise ErrorNegocio("Este caso no pertenece a su empresa.")
    if rol == "auditor":
        raise ErrorNegocio("El rol auditor es de solo lectura.")


def abrir_caso(sid, usuario):
    """ASIGNADA o REABIERTA -> EN_TRAMITE cuando el abogado asignado abre el caso."""
    s = _sol(sid)
    if usuario and usuario["rol"] == "abogado" and s.get("abogado_id") == usuario["id"] and s["estado"] in ("ASIGNADA", "REABIERTA"):
        _transicion(s, "EN_TRAMITE", usuario, {"motivo": "El abogado abrió el caso"})
    return _sol(sid)


def cambiar_clasificacion(sid, tipo_id, tema_id, usuario, motivo=""):
    """Corrige tipo/tema y recalcula el vencimiento. Lo pueden hacer el abogado asignado, el supervisor, el admin
    y el radicador de la empresa (que es quien clasifica al radicar)."""
    s = _sol(sid)
    _permiso_caso(s, usuario)
    if usuario and usuario["rol"] not in ("abogado", "supervisor", "admin", "radicador", "director"):
        raise ErrorNegocio("Su rol no puede reclasificar casos.")
    if s["estado"] not in flujo.ABIERTOS:
        raise ErrorNegocio("Solo se reclasifican casos abiertos.")
    if usuario and usuario["rol"] == "radicador" and s["estado"] != "RECIBIDA":
        raise ErrorNegocio("El radicador reclasifica casos recibidos (antes del reparto); después lo hace el abogado o el supervisor.")
    tp = C.tipo(tipo_id)
    if not tp:
        raise ErrorNegocio("Seleccione un tipo de solicitud válido.")
    nuevo_ven = plazos.fecha_vencimiento(a_fecha(s["fecha_radicacion"]), int(tp["dias_habiles"]), C.festivos(s["empresa_id"]))
    R().actualizar("solicitudes", sid, {"tipo_id": tipo_id, "tema_id": tema_id, "fecha_vencimiento": nuevo_ven})
    evento(sid, usuario, "reclasificada", {"tipo_antes": s["tipo_codigo"], "tipo_despues": tp["codigo"],
                                           "vencimiento_antes": s["fecha_vencimiento"],
                                           "vencimiento_despues": nuevo_ven.isoformat(), "motivo": motivo})


def marcar(sid, marca, usuario):
    """Marca peticiones irrespetuosas, oscuras o reiterativas (se tratan según la política jurídica)."""
    s = _sol(sid)
    _permiso_caso(s, usuario)
    R().actualizar("solicitudes", sid, {"marca": marca or None})
    evento(sid, usuario, "marca", {"marca": marca})


def pedir_informacion(sid, texto, usuario):
    if len((texto or "").strip()) < 10:
        raise ErrorNegocio("Explique al ciudadano qué información le falta (mínimo 10 caracteres).")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    _transicion(s, "PENDIENTE_INFO", usuario, {"solicitado": texto}, extra={"suspendida_desde": _hoy()})
    limite = _hoy() + timedelta(days=int(C.param_num("dias_desistimiento", 30)))
    _notificar_ciudadano(s, "solicitud_info", usuario, texto=texto, nueva_fecha=fmt_fecha(limite))


def aportar_informacion(sid, texto, archivos=(), origen="ciudadano", usuario=None):
    """El ciudadano completa: el plazo se reanuda o reinicia según el parámetro `criterio_suspension`."""
    if not (texto or "").strip() and not archivos:
        raise ErrorNegocio("Escriba la información solicitada o adjunte al menos un archivo.")
    s = _sol(sid)
    for nombre, contenido, mime in archivos or []:
        adjuntar(s, "soporte", nombre, contenido, mime, usuario, origen=origen)
    if (texto or "").strip():
        adjuntar(s, "soporte", "informacion-aportada.txt", texto.encode("utf-8"), "text/plain", usuario, origen=origen,
                 validar=False)
    evento(sid, usuario, "informacion_aportada", {"texto": (texto or "")[:300], "adjuntos": len(archivos or [])}, origen=origen)
    if s["estado"] == "PENDIENTE_INFO":
        nuevo, susp = plazos.reanudar_tras_suspension(
            a_fecha(s["fecha_radicacion"]), a_fecha(s["fecha_vencimiento"]), a_fecha(s["suspendida_desde"]) or _hoy(), _hoy(),
            int(s["dias_habiles"]), C.param("criterio_suspension", "reiniciar"), C.festivos(s["empresa_id"]))
        _transicion(s, "EN_TRAMITE", usuario, {"vencimiento_antes": s["fecha_vencimiento"], "vencimiento_nuevo": nuevo.isoformat(),
                                               "dias_suspendidos": susp}, rol="ciudadano" if usuario is None else None,
                    extra={"fecha_vencimiento": nuevo, "suspendida_desde": None,
                           "dias_suspendidos": int(s.get("dias_suspendidos") or 0) + susp})
        s = _sol(sid)
        _notificar_ciudadano(s, "info_recibida", usuario)
    alertar("info_aportada", s, clave_extra=f"|{ahora().isoformat()}")
    return _sol(sid)


def prorrogar(sid, nueva_fecha, motivo, usuario):
    if _rol(usuario) not in ("supervisor", "abogado", "admin"):
        raise ErrorNegocio("No tiene permiso para registrar prórrogas.")
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo de la prórroga (se le informará al ciudadano).")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    if s["estado"] not in flujo.ABIERTOS:
        raise ErrorNegocio("Solo se pueden prorrogar casos abiertos.")
    maximo = plazos.max_fecha_prorroga(a_fecha(s["fecha_radicacion"]), int(s["dias_habiles"]), s.get("dias_prorroga_max"),
                                       C.festivos(s["empresa_id"]))
    err = plazos.validar_prorroga(_hoy(), a_fecha(s["fecha_vencimiento"]), nueva_fecha, maximo)
    if err:
        raise ErrorNegocio(err)
    R().actualizar("solicitudes", sid, {"fecha_vencimiento": nueva_fecha, "prorrogada": True})
    evento(sid, usuario, "prorroga", {"antes": s["fecha_vencimiento"], "nueva": nueva_fecha.isoformat(), "motivo": motivo})
    s = _sol(sid)
    _notificar_ciudadano(s, "prorroga", usuario, nueva_fecha=fmt_fecha(nueva_fecha), motivo=motivo)
    alertar("prorroga", s, f"prórroga hasta {fmt_fecha(nueva_fecha)}: {motivo}")


def anular(sid, motivo, usuario):
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo de la anulación (duplicado, spam...).")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    _transicion(s, "ANULADA", usuario, {"motivo": motivo}, extra={"revisar_duplicado": False})


def resolver_duplicado(sid, decision, usuario, motivo=""):
    """decision: 'vincular' (respuesta conjunta con el original), 'no_duplicado' o 'anular'."""
    s = _sol(sid)
    _permiso_caso(s, usuario)
    if decision == "anular":
        return anular(sid, motivo or "Duplicado de otra solicitud", usuario)
    cambios = {"revisar_duplicado": False}
    if decision == "vincular" and s.get("posible_duplicado_de"):
        cambios["solicitud_padre_id"] = s["posible_duplicado_de"]
    R().actualizar("solicitudes", sid, cambios)
    evento(sid, usuario, "duplicado_resuelto", {"decision": decision, "padre": cambios.get("solicitud_padre_id")})
    if s["estado"] == "RECIBIDA" and not s.get("abogado_id"):
        asignar(sid, usuario)


def cerrar(sid, usuario, motivo="Entrega confirmada"):
    s = _sol(sid)
    _transicion(s, "CERRADA", usuario, {"motivo": motivo}, rol=None if usuario else "sistema")


def reabrir(sid, motivo, usuario):
    if not (motivo or "").strip():
        raise ErrorNegocio("Escriba el motivo de la reapertura (inconformidad o error).")
    s = _sol(sid)
    _permiso_caso(s, usuario)
    _transicion(s, "REABIERTA", usuario, {"motivo": motivo}, extra={"reabierta": True})
    alertar("asignada", _sol(sid), "caso reabierto: " + motivo, clave_extra=f"|{ahora().isoformat()}")


# ====================================================================== RESPUESTAS Y APROBACIÓN
def _niveles(s):
    return aprobacion.niveles_requeridos(int(s.get("niveles_aprobacion") or 0), bool(s.get("tema_sensible")))


def niveles_caso(s):
    return _niveles(s)


def _respuesta_actual(sid):
    rs = C.respuestas(sid)
    return rs[-1] if rs else None


def respuesta_actual(sid):
    return _respuesta_actual(sid)


def texto_plantilla(sid, plantilla_id, usuario=None):
    s = _sol(sid)
    p = R().q("select * from plantillas where id = ?", [plantilla_id], uno=True)
    return plantillas.render(p["cuerpo"], _vars(s, usuario)) if p else ""


def guardar_borrador(sid, contenido, usuario, es_parcial=False, origen="app"):
    """Guarda el trabajo sin perderlo. Si la última versión ya se envió a revisión, crea una versión nueva."""
    if not (contenido or "").strip():
        raise ErrorNegocio("La respuesta está vacía. Escriba el texto o use una plantilla.")
    s = _sol(sid)
    if origen == "app":
        _permiso_caso(s, usuario)
    if s["estado"] not in ("ASIGNADA", "EN_TRAMITE", "REABIERTA", "PENDIENTE_INFO", "RECIBIDA"):
        raise ErrorNegocio(f"No se puede editar la respuesta en el estado actual ({flujo.explicar(s['estado'])}).")
    r = _respuesta_actual(sid)
    if r and r["estado"] == "borrador":
        R().actualizar("respuestas", r["id"], {"contenido": contenido, "es_parcial": es_parcial, "actualizado": ahora(),
                                               "origen": origen if origen != "app" else r["origen"]})
        R().indexar(sid, "respuesta", r["id"], contenido)
        evento(sid, usuario, "borrador_guardado", {"version": r["version"], "origen": origen}, origen=origen)
        return {**r, "contenido": contenido}
    version = (r["version"] + 1) if r else 1
    rid = R().insertar("respuestas", {"solicitud_id": sid, "version": version, "contenido": contenido, "es_parcial": es_parcial,
                                      "estado": "borrador", "autor_id": _uid(usuario), "origen": origen, "fecha": ahora(),
                                      "actualizado": ahora()})
    R().indexar(sid, "respuesta", rid, contenido)
    evento(sid, usuario, "borrador_creado", {"version": version, "origen": origen}, origen=origen)
    return R().q("select * from respuestas where id = ?", [rid], uno=True)


def enviar_a_revision(sid, contenido, usuario, es_parcial=False):
    s = _sol(sid)
    _permiso_caso(s, usuario)
    if s["estado"] in ("ASIGNADA", "REABIERTA"):
        _transicion(s, "EN_TRAMITE", usuario)
    if s["estado"] != "EN_TRAMITE":
        raise ErrorNegocio("Solo se envían a revisión casos en trámite.")
    r = guardar_borrador(sid, contenido, usuario, es_parcial)  # guardado automático (RU-07)
    R().actualizar("respuestas", r["id"], {"estado": "en_revision", "actualizado": ahora()})
    _transicion(s, "EN_REVISION", usuario, {"version": r["version"]})
    if _niveles(s) == 0:
        R().actualizar("respuestas", r["id"], {"estado": "aprobada"})
        _transicion(s, "APROBADA", usuario, {"esquema": "A (sin aprobación)"}, rol="sistema")
        return {"version": r["version"], "estado": "APROBADA", "niveles": 0}
    _alertar_aprobacion(_sol(sid), f"respuesta v{r['version']} pendiente de su aprobación", clave_extra=f"|v{r['version']}")
    return {"version": r["version"], "estado": "EN_REVISION", "niveles": _niveles(s)}


def redacto_respuesta(r, usuario) -> bool:
    """True si el usuario es autor de la versión o la editó (eventos de borrador): no puede aprobarla (segregación)."""
    uid = _uid(usuario)
    if not r or uid is None:
        return False
    if r.get("autor_id") == uid:
        return True
    import json
    for ev in R().q("select detalle from eventos where solicitud_id = ? and usuario_id = ? and accion in "
                    "('borrador_creado', 'borrador_guardado')", [r["solicitud_id"], uid]):
        d = ev["detalle"]
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except ValueError:
                d = {}
        if (d or {}).get("version") == r["version"]:
            return True
    return False


# Si nadie del rol titular puede aprobar un nivel (p. ej. el único supervisor redactó la respuesta), el nivel pasa a este rol.
ESCALAMIENTO = {1: ("director",), 2: ()}


def _aprobo_otro_nivel(r, usuario, nivel) -> bool:
    return any(a["aprobador_id"] == usuario["id"] and a["decision"] == "aprobada" and int(a["nivel"]) != int(nivel)
               for a in C.aprobaciones_de([r["id"]]))


def estado_aprobacion(s) -> dict:
    """Quién puede aprobar hoy la respuesta en revisión: {nivel, rol, posibles, escalado, sin_aprobador}.
    Nunca incluye a quien redactó o editó la versión ni a quien ya aprobó otro nivel de ella (segregación)."""
    vacio = {"nivel": None, "rol": None, "posibles": [], "escalado": False, "sin_aprobador": False}
    r = _respuesta_actual(s["id"])
    if not r or r["estado"] != "en_revision":
        return vacio
    n = aprobacion.nivel_pendiente(C.aprobaciones_de([r["id"]]), _niveles(s))
    if not n:
        return vacio
    rol = aprobacion.rol_para_nivel(n)

    def libres(rol_):
        return [u for u in C.usuarios(rol_, s["empresa_id"]) if not redacto_respuesta(r, u) and not _aprobo_otro_nivel(r, u, n)]
    titulares = libres(rol)
    if titulares:
        return {**vacio, "nivel": n, "rol": rol, "posibles": titulares}
    for alterno in ESCALAMIENTO.get(n, ()):
        alt = libres(alterno)
        if alt:
            return {**vacio, "nivel": n, "rol": alterno, "posibles": alt, "escalado": True}
    return {**vacio, "nivel": n, "rol": rol, "sin_aprobador": True}


MSG_SIN_APROBADOR = ("Nadie puede aprobar esta respuesta: quien debería hacerlo la redactó o ya aprobó otro nivel. "
                     "Pida a administración que designe otro aprobador (otro supervisor o director de la empresa).")

MSG_AUTOAPROBACION = "No puede aprobar ni devolver una respuesta que usted mismo redactó o editó; debe revisarla otra persona."


def puede_aprobar(s, usuario):
    r = _respuesta_actual(s["id"])
    if not r or r["estado"] != "en_revision" or s["estado"] != "EN_REVISION":
        return False, None, "No hay una respuesta en revisión."
    if redacto_respuesta(r, usuario):
        return False, None, MSG_AUTOAPROBACION
    n = aprobacion.nivel_pendiente(C.aprobaciones_de([r["id"]]), _niveles(s))
    if n is None:
        return False, None, "La respuesta ya tiene todas las aprobaciones."
    rol_req = aprobacion.rol_para_nivel(n)
    if _aprobo_otro_nivel(r, usuario, n):
        return False, n, "Ya aprobó otro nivel de esta respuesta; el siguiente nivel lo aprueba otra persona."
    if usuario["rol"] == rol_req and s["empresa_id"] in usuario.get("empresas", []):
        return True, n, ""
    h = _hoy()  # Delegación: el suplente aprueba si el titular está ausente
    for titular in C.usuarios(rol_req, s["empresa_id"]):
        aus = reparto.Abogado(titular["id"], ausente_desde=a_fecha(titular["ausente_desde"]),
                              ausente_hasta=a_fecha(titular["ausente_hasta"]))
        if titular.get("suplente_id") == usuario["id"] and (aus.ausente(h) or not titular["disponible"]):
            return True, n, f"como suplente de {titular['nombre']}"
    est = estado_aprobacion(s)  # escalamiento: nadie del rol titular puede aprobar
    if est["escalado"] and any(u["id"] == usuario["id"] for u in est["posibles"]):
        return True, n, f"por escalamiento: ningún {rol_req} de la empresa puede aprobar esta respuesta"
    if est["sin_aprobador"]:
        return False, n, MSG_SIN_APROBADOR
    if est["escalado"]:
        return False, n, f"El nivel {n} lo aprueba el rol «{est['rol']}» de la empresa (escalamiento: el {rol_req} la redactó)."
    return False, n, f"El nivel {n} lo aprueba el rol «{rol_req}» de la empresa."


def aprobar(sid, usuario, comentario="", urgente=False):
    s = _sol(sid)
    ok, n, nota = puede_aprobar(s, usuario)
    if not ok:
        raise ErrorNegocio(nota)
    r = _respuesta_actual(sid)
    R().insertar("aprobaciones", {"respuesta_id": r["id"], "nivel": n, "aprobador_id": usuario["id"], "decision": "aprobada",
                                  "comentario": ((comentario or "") + (f" ({nota})" if nota else "")).strip(),
                                  "urgente": urgente, "fecha": ahora()})
    evento(sid, usuario, "aprobacion", {"version": r["version"], "nivel": n, "urgente": urgente, "nota": nota})
    if aprobacion.nivel_pendiente(C.aprobaciones_de([r["id"]]), _niveles(s)) is None:
        R().actualizar("respuestas", r["id"], {"estado": "aprobada"})
        _transicion(s, "APROBADA", usuario, {"version": r["version"]}, rol="sistema")
        return {"estado": "APROBADA", "nivel": n}
    _alertar_aprobacion(_sol(sid), f"v{r['version']} aprobada en nivel {n}; falta su aprobación (nivel {n + 1})",
                        clave_extra=f"|v{r['version']}|n{n + 1}")
    return {"estado": "EN_REVISION", "nivel": n}


def devolver(sid, usuario, comentario):
    if not (comentario or "").strip():
        raise ErrorNegocio("El comentario de devolución es obligatorio: explique qué debe corregirse.")
    s = _sol(sid)
    ok, n, nota = puede_aprobar(s, usuario)
    if not ok:
        raise ErrorNegocio(nota)
    r = _respuesta_actual(sid)
    R().insertar("aprobaciones", {"respuesta_id": r["id"], "nivel": n, "aprobador_id": usuario["id"], "decision": "devuelta",
                                  "comentario": comentario, "urgente": False, "fecha": ahora()})
    R().actualizar("respuestas", r["id"], {"estado": "devuelta"})
    _transicion(s, "EN_TRAMITE", usuario, {"version": r["version"], "nivel": n, "comentario": comentario}, rol="sistema")
    alertar("devuelta", _sol(sid), f"v{r['version']} devuelta: {comentario[:120]}", clave_extra=f"|v{r['version']}")
    return {"estado": "EN_TRAMITE", "version": r["version"]}


def _pdf_para(s, r, firmante, t):
    emp = C.empresa(s["empresa_id"])
    cod = plantillas.codigo_verificacion(s["radicado"], r["contenido"], t)
    pdf = plantillas.pdf_respuesta(empresa=emp, radicado=s["radicado"], destinatario=s.get("solicitante_nombre") or "",
                                   asunto=s["asunto"], contenido=r["contenido"], firmante=firmante["nombre"],
                                   cargo=firmante.get("cargo") or "", fecha=t, codigo_verif=cod,
                                   enlace=f"{app_url()}/consultar_estado?radicado={s['radicado']}",
                                   es_parcial=bool(r.get("es_parcial")))
    return pdf, cod


def enviar_respuesta(sid, usuario, medio="correo", incluir_vinculados=True):
    """Genera el PDF, lo guarda en 03_respuesta, lo envía y deja el caso ENVIADA (o EN_TRAMITE si es parcial)."""
    s = _sol(sid)
    _permiso_caso(s, usuario)
    if s["estado"] != "APROBADA":
        raise ErrorNegocio("La respuesta debe estar aprobada antes de enviarla.")
    r = _respuesta_actual(sid)
    t = ahora()
    firmante = C.usuario(r["autor_id"]) if r.get("autor_id") else None
    firmante = firmante if firmante and firmante["rol"] != "integracion" else usuario
    pdf, cod = _pdf_para(s, r, firmante, t)
    nombre_pdf = f"respuesta-{s['radicado']}-v{r['version']}.pdf"
    doc = adjuntar(s, "respuesta", nombre_pdf, pdf, "application/pdf", usuario, validar=False)
    envio = None
    if medio == "correo" and s.get("solicitante_email"):
        envio = _notificar_ciudadano(s, "respuesta_enviada", usuario, adjuntos=[(nombre_pdf, pdf, "application/pdf")],
                                     codigo=cod)
        if envio and envio["estado"] == "error":
            alertar("rebote", s, f"no se pudo entregar el correo ({envio['error']}); quedó publicada en la consulta web")
            medio = "publicacion"
    elif medio == "correo":
        medio = "publicacion"
    constancia = (f"Constancia de envío\nRadicado: {s['radicado']}\nFecha: {t:%d/%m/%Y %H:%M}\nMedio: {medio}\n"
                  f"Destinatario: {s.get('solicitante_email') or '(sin correo)'}\n"
                  f"Estado del envío: {(envio or {}).get('estado', 'publicada en la consulta web')}\n"
                  f"Message-ID: {(envio or {}).get('message_id', '-')}\nPDF SHA-256: {doc['sha256']}\n"
                  f"Código de verificación: {cod}\nEnviado por: {usuario['nombre']}")
    adjuntar(s, "respuesta", "constancia-envio.txt", constancia.encode("utf-8"), "text/plain", usuario, validar=False)
    R().actualizar("respuestas", r["id"], {"estado": "enviada", "actualizado": t})
    if r["es_parcial"]:
        _transicion(s, "EN_TRAMITE", usuario, {"respuesta_parcial": True, "version": r["version"]}, rol="sistema",
                    extra={"respuesta_parcial": True})
    else:
        _transicion(s, "ENVIADA", usuario, {"medio": medio, "documento_id": doc["id"], "codigo_verificacion": cod},
                    extra={"fecha_respuesta": t})
    evento(sid, usuario, "respuesta_enviada", {"medio": medio, "pdf": doc["ruta"], "sha256": doc["sha256"],
                                               "parcial": bool(r["es_parcial"])})
    alertar("enviada", _sol(sid), "respuesta enviada (confirmación)", clave_extra=f"|v{r['version']}")
    conjuntos = []
    if incluir_vinculados and not r["es_parcial"]:
        for v in C.vinculados(sid):
            if v["estado"] in flujo.ABIERTOS:
                conjuntos.append(_enviar_copia_conjunta(v["id"], s, r, usuario))
    return {"estado": _sol(sid)["estado"], "medio": medio, "documento_id": doc["id"], "codigo_verificacion": cod,
            "conjuntos": conjuntos}


def _enviar_copia_conjunta(hijo_id, padre, r, usuario):
    """Respuesta conjunta: la misma respuesta aprobada se envía a cada radicado vinculado."""
    h = _sol(hijo_id)
    t = ahora()
    pdf, cod = _pdf_para(h, r, usuario, t)
    nombre = f"respuesta-{h['radicado']}-conjunta.pdf"
    adjuntar(h, "respuesta", nombre, pdf, "application/pdf", usuario, validar=False)
    _notificar_ciudadano(h, "respuesta_enviada", usuario, adjuntos=[(nombre, pdf, "application/pdf")], codigo=cod)
    R().actualizar("solicitudes", hijo_id, {"estado": "ENVIADA", "fecha_respuesta": t})
    evento(hijo_id, usuario, "respuesta_conjunta", {"de": padre["radicado"], "estado_anterior": h["estado"]})
    return h["radicado"]


def aprobar_y_enviar_urgente(sid, usuario, comentario=""):
    """Si el caso vence hoy (o venció), el supervisor aprueba todos los niveles y envía en un solo paso."""
    s = _sol(sid)
    if usuario["rol"] != "supervisor" or s["empresa_id"] not in usuario["empresas"]:
        raise ErrorNegocio("La aprobación urgente solo la puede hacer el supervisor de la empresa.")
    if s.get("dias_restantes") is None or s["dias_restantes"] > 0:
        raise ErrorNegocio("La aprobación urgente solo aplica a casos que vencen hoy o ya vencieron.")
    r = _respuesta_actual(sid)
    if not r or s["estado"] != "EN_REVISION":
        raise ErrorNegocio("No hay una respuesta en revisión.")
    if redacto_respuesta(r, usuario):
        raise ErrorNegocio(MSG_AUTOAPROBACION)
    while (n := aprobacion.nivel_pendiente(C.aprobaciones_de([r["id"]]), _niveles(s))) is not None:
        R().insertar("aprobaciones", {"respuesta_id": r["id"], "nivel": n, "aprobador_id": usuario["id"], "decision": "aprobada",
                                      "comentario": f"APROBACIÓN URGENTE (vence hoy). {comentario}".strip(), "urgente": True,
                                      "fecha": ahora()})
    R().actualizar("respuestas", r["id"], {"estado": "aprobada"})
    _transicion(s, "APROBADA", usuario, {"urgente": True}, rol="sistema")
    evento(sid, usuario, "aprobacion_urgente", {"version": r["version"], "comentario": comentario})
    return enviar_respuesta(sid, usuario)


# ====================================================================== CONSULTA CIUDADANA
def consultar_estado(radicado_txt, codigo):
    s = C.solicitud_por_radicado(radicado_txt, sin_alcance=True)
    if not s or not rad.verificar_codigo(s["radicado"], codigo, s.get("codigo_consulta")):
        raise ErrorNegocio("No encontramos una solicitud con ese radicado y código. Revise que estén bien escritos "
                           "(el código está en el acuse de recibo).")
    enviadas = [r for r in C.respuestas(s["id"]) if r["estado"] == "enviada"]
    pdfs = [d for d in C.documentos(s["id"]) if d["categoria"] == "respuesta" and (d["nombre_original"] or "").endswith(".pdf")]
    encuesta = R().q("select * from encuestas where solicitud_id = ?", [s["id"]], uno=True)
    return {"solicitud": s, "respuesta": enviadas[-1] if enviadas else None, "pdf": pdfs[-1] if pdfs else None,
            "encuesta": encuesta}


def registrar_encuesta(sid, puntaje, comentario=""):
    if not 1 <= int(puntaje) <= 5:
        raise ErrorNegocio("Elija un puntaje de 1 a 5.")
    if R().valor("select count(*) from encuestas where solicitud_id = ?", [sid]):
        raise ErrorNegocio("Ya registró su opinión sobre esta respuesta. ¡Gracias!")
    R().insertar("encuestas", {"solicitud_id": sid, "puntaje": int(puntaje), "comentario": comentario, "fecha": ahora()})
    evento(sid, None, "encuesta", {"puntaje": int(puntaje)}, origen="ciudadano")


# ====================================================================== CORREO ENTRANTE
def _clasificar_tipo(texto):
    t = C.sin_tildes(texto)
    mejor, puntos = C.tipo_por_codigo("P"), 0
    for tp in C.tipos():
        claves = [C.sin_tildes(k.strip()) for k in (tp.get("palabras_clave") or "").split(",") if k.strip()]
        p = sum(1 for k in claves if k in t)
        if p > puntos:
            mejor, puntos = tp, p
    return mejor


def _es_spam(de, texto):
    t = C.sin_tildes(texto)
    palabras = [C.sin_tildes(x.strip()) for x in (C.param("palabras_spam", "") or "").split(",") if x.strip()]
    bloqueados = [x.strip().lower() for x in (C.param("remitentes_bloqueados", "") or "").split(",") if x.strip()]
    return any(p in t for p in palabras) or any(b in de for b in bloqueados)


def procesar_correo(eml, correo_id=None, forzar=False):
    """Convierte un correo en solicitud (o lo agrega al expediente si el asunto trae un radicado). Idempotente."""
    m = correo.parsear(eml)
    if not forzar and R().valor("select count(*) from correos_procesados where message_id = ?", [m["message_id"]]):
        if correo_id:
            R().actualizar("correos", correo_id, {"estado": "procesado"})
        return {"resultado": "duplicado_ignorado", "message_id": m["message_id"]}
    numero = rad.extraer(m["asunto"])
    texto = f"{m['asunto']}\n{m['cuerpo']}"
    if correo_id is None:  # IMAP real: también queda registro en el buzón
        correo_id = R().insertar("correos", {"direccion": "entrada", "modo": "real", "message_id": m["message_id"],
                                             "de": m["de"], "para": ", ".join(m["para"]), "asunto": m["asunto"],
                                             "cuerpo": m["cuerpo"][:20000], "eml": None, "estado": "pendiente",
                                             "fecha": ahora()})
    s = C.solicitud_por_radicado(numero, sin_alcance=True) if numero else None
    if s:
        if FRASE_AUTORIZA.search(m["cuerpo"] or ""):
            registrar_consentimiento(s["id"], "correo", {"message_id": m["message_id"]})
        adjuntar(s, "soporte", "correo-ciudadano.eml", eml, "message/rfc822", None, origen="correo", validar=False)
        validos_ = [a for a in m["adjuntos"] if docs.extension(a[0]) in docs.EXTENSIONES]
        if s["estado"] == "PENDIENTE_INFO" and not (m["cuerpo"] or "").strip() and not validos_:
            evento(s["id"], None, "correo_vacio_ignorado", {"asunto": m["asunto"]}, origen="correo")
        elif s["estado"] == "PENDIENTE_INFO":
            aportar_informacion(s["id"], m["cuerpo"], [a for a in m["adjuntos"] if docs.extension(a[0]) in docs.EXTENSIONES],
                                origen="correo")
        else:
            for nombre, contenido, mime in m["adjuntos"]:
                try:
                    adjuntar(s, "soporte", nombre, contenido, mime, None, origen="correo")
                except ErrorNegocio:
                    pass
            evento(s["id"], None, "correo_ciudadano_recibido", {"asunto": m["asunto"]}, origen="correo")
            alertar("info_aportada", s, "el ciudadano escribió un correo sobre este caso", clave_extra=f"|{m['message_id']}")
        _marcar_procesado(m["message_id"], s["id"], forzar)
        R().actualizar("correos", correo_id, {"estado": "procesado", "solicitud_id": s["id"]})
        return {"resultado": "agregado_a_expediente", "radicado": s["radicado"]}
    if not forzar and _es_spam(m["de"], texto):
        R().actualizar("correos", correo_id, {"estado": "cuarentena"})
        _marcar_procesado(m["message_id"], None, False)
        evento(None, None, "correo_cuarentena", {"de": m["de"], "asunto": m["asunto"]}, origen="correo",
               empresa_id=R().empresa_por_buzon(", ".join(m["para"])))  # NULL si el buzón no identifica una empresa
        return {"resultado": "cuarentena"}
    emp = next((e for e in C.empresas() if (e.get("buzon_correo") or "").lower() in m["para"]), None) \
        or C.empresa_por_codigo(C.param("empresa_por_defecto", "EMP01"))
    tp = _clasificar_tipo(texto)
    archivos = [("correo-original.eml", eml, "message/rfc822")] + list(m["adjuntos"])
    res = radicar({"empresa_id": emp["id"], "tipo_id": tp["id"], "asunto": m["asunto"][:200] or "(sin asunto)",
                   "descripcion": m["cuerpo"] or "(correo sin texto)", "nombre": m["nombre"], "email": m["de"],
                   "autoriza_datos": bool(FRASE_AUTORIZA.search(texto))}, canal="correo", archivos=archivos, message_id=m["message_id"],
                  omitir_invalidos=True, origen="correo")
    sid = res["solicitud"]["id"]
    _marcar_procesado(m["message_id"], sid, forzar)
    R().actualizar("correos", correo_id, {"estado": "procesado", "solicitud_id": sid})
    return {"resultado": "radicada", "radicado": res["solicitud"]["radicado"], "tipo": tp["codigo"], "empresa": emp["codigo"],
            "rechazados": res["rechazados"]}


def _marcar_procesado(message_id, sid, actualizar):
    if actualizar:
        R().ex("delete from correos_procesados where message_id = ?", [message_id])
    R().ex("insert into correos_procesados (message_id, fecha, solicitud_id) values (?, ?, ?) on conflict do nothing",
           [message_id, ahora(), sid])


def liberar_cuarentena(correo_id, usuario):
    """El radicador revisa un correo en cuarentena y decide radicarlo (nunca se borra automáticamente)."""
    if _rol(usuario) not in ("radicador", "admin", "supervisor"):
        raise ErrorNegocio("Solo el radicador, el supervisor o el administrador pueden liberar correos.")
    emp_correo = R().valor("select empresa_id from correos where id = ?", [correo_id])
    if _rol(usuario) != "admin" and emp_correo not in usuario.get("empresas", []):  # NULL (buzón desconocido): solo admin
        raise ErrorNegocio("Este correo no pertenece a su empresa.")
    eml = C.correo_eml(correo_id)
    if not eml:
        raise ErrorNegocio("Este correo no tiene el contenido original guardado.")
    evento(None, usuario, "cuarentena_liberada", {"correo_id": correo_id}, empresa_id=emp_correo)
    return procesar_correo(eml.encode("utf-8"), correo_id, forzar=True)


# ====================================================================== TAREAS PROGRAMADAS
def leer_correo():
    res = []
    for cid, eml in correo.leer_nuevos(R()):
        try:
            res.append(procesar_correo(eml, cid))
        except Exception as e:  # un correo defectuoso no detiene a los demás
            if cid:
                R().actualizar("correos", cid, {"estado": "error", "error": str(e)[:300]})
            res.append({"resultado": "error", "error": str(e)[:200]})
    return res


def asignar_pendientes():
    asignados, cola = 0, 0
    for s in R().q("select id from solicitudes where estado = 'RECIBIDA' and abogado_id is null and not revisar_duplicado "
                   "and not pendiente_completar order by fecha_recepcion"):
        if asignar(s["id"]):
            asignados += 1
        else:
            cola += 1
    return {"asignados": asignados, "en_cola": cola}


def desistimientos():
    dias = int(C.param_num("dias_desistimiento", 30))
    n = 0
    for s in C.listar_solicitudes(None, {"estado": ["PENDIENTE_INFO"]}, sin_alcance=True):
        desde = a_fecha(s.get("suspendida_desde"))
        if desde and _hoy() > desde + timedelta(days=dias):
            _transicion(s, "DESISTIDA", None, {"motivo": f"No aportó la información en {dias} días"}, rol="sistema",
                        extra={"fecha_respuesta": ahora()})
            _notificar_ciudadano(s, "desistimiento", None)
            n += 1
    return n


def cierre_automatico():
    dias = int(C.param_num("dias_cierre_auto", 2))
    n = 0
    for s in C.listar_solicitudes(None, {"estado": ["ENVIADA"]}, sin_alcance=True):
        f = a_fecha(s.get("fecha_respuesta"))
        if f and plazos.dias_habiles_entre(f, _hoy()) >= dias:
            cerrar(s["id"], None, f"Cierre automático tras {dias} días hábiles sin rebote")
            n += 1
    return n


def generar_alertas(hoy=None):
    """Alertas por umbral (50 %, 80 %, vence hoy, vencida) y recordatorio de aprobación pendiente."""
    hoy = hoy or _hoy()
    existentes = {r["clave"] for r in R().q("select clave from alertas where clave is not null")}
    ult_rev = {r["solicitud_id"]: r["u"] for r in R().q(
        "select solicitud_id, max(fecha) as u from eventos where accion in ('cambio_estado','aprobacion') "
        "and solicitud_id is not null group by solicitud_id")}
    cuenta = {}
    u1, u2 = C.param_num("umbral_amarillo", 50), C.param_num("umbral_rojo", 80)
    for s in C.listar_solicitudes(None, {"abiertos": True}, sin_alcance=True):
        if s["estado"] == "PENDIENTE_INFO" or not s.get("fecha_vencimiento"):
            continue
        tipo = reglas.alerta_umbral(a_fecha(s["fecha_radicacion"]), a_fecha(s["fecha_vencimiento"]), hoy, u1, u2,
                                    C.festivos(s["empresa_id"]))
        if tipo:
            cuenta[tipo] = cuenta.get(tipo, 0) + alertar(tipo, s, hoy=hoy, existentes=existentes)
        ult = ult_rev.get(s["id"])
        if s["estado"] == "EN_REVISION" and ult and plazos.dias_habiles_entre(a_fecha(ult), hoy) > 1:
            sin = estado_aprobacion(s)["sin_aprobador"]
            k = "aprobacion_sin_aprobador" if sin else "aprobacion_pendiente"
            cuenta[k] = cuenta.get(k, 0) + alertar(k, s, hoy=hoy, existentes=existentes)
    from core import archivo  # alertas de TRD (retención 90/30 días, vencida) y archivo físico (préstamos vencidos)
    for k, v in archivo.generar_alertas_archivo(hoy).items():
        cuenta[k] = cuenta.get(k, 0) + v
    return cuenta


def ejecutar_tareas():
    """Equivalente a jobs/run_all.py: leer correo, completar API, asignar, desistir, cerrar y alertar."""
    t0 = ahora()
    res = {"correos": leer_correo(), "api_completadas": completar_radicaciones_api(), "reparto": asignar_pendientes(),
           "desistidas": desistimientos(), "cerradas_auto": cierre_automatico(), "alertas": generar_alertas()}
    evento(None, None, "tareas_programadas", {"resumen": {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()},
                                              "duracion_s": round((ahora() - t0).total_seconds(), 2)})
    return res


# ====================================================================== ADMINISTRACIÓN
EDITABLES = {
    "empresas": {"nombre", "nit", "buzon_correo", "color", "estrategia_reparto", "acepta_anonimas", "activo", "logo_url"},
    "usuarios": {"nombre", "rol", "cargo", "especialidades", "capacidad_max", "disponible", "ausente_desde",
                 "ausente_hasta", "suplente_id", "activo"},
    "tipos_pqrs": {"nombre", "descripcion", "ejemplo", "dias_habiles", "dias_prorroga_max", "peso_carga", "niveles_aprobacion",
                   "palabras_clave", "activo"},
    "temas": {"nombre", "especialidad_requerida", "sensible"},
    "plantillas": {"nombre", "asunto", "cuerpo", "activo"},
    "parametros": {"valor"},
}


def _solo_admin(usuario):
    if _rol(usuario) != "admin":
        raise ErrorNegocio("Solo el administrador puede cambiar la configuración.")


def actualizar_config(tabla, id_, cambios, usuario):
    _solo_admin(usuario)
    limpio = {k: v for k, v in cambios.items() if k in EDITABLES.get(tabla, set())}
    if not limpio:
        return
    clave = "clave" if tabla == "parametros" else "id"
    antes = R().q(f"select * from {tabla} where {clave} = ?", [id_], uno=True) or {}
    R().actualizar(tabla, id_, limpio, clave=clave)
    evento(None, usuario, "configuracion", {"tabla": tabla, "id": id_, "antes": {k: str(antes.get(k)) for k in limpio},
                                            "despues": {k: str(v) for k, v in limpio.items()}})
    C.limpiar_cache()


def crear_config(tabla, datos, usuario):
    _solo_admin(usuario)
    if tabla == "usuario_empresa":
        R().ex("insert into usuario_empresa (usuario_id, empresa_id) values (?, ?) on conflict do nothing",
               [datos["usuario_id"], datos["empresa_id"]])
    elif tabla in ("festivos_extra", "plantillas", "temas", "usuarios"):
        R().insertar(tabla, datos)
    else:
        raise ErrorNegocio("Tabla no permitida.")
    evento(None, usuario, "configuracion_alta", {"tabla": tabla, "datos": {k: str(v) for k, v in datos.items()}})
    C.limpiar_cache()


def quitar_empresa_usuario(usuario_id, empresa_id, usuario):
    _solo_admin(usuario)
    R().ex("delete from usuario_empresa where usuario_id = ? and empresa_id = ?", [usuario_id, empresa_id])
    evento(None, usuario, "configuracion_baja", {"tabla": "usuario_empresa", "usuario_id": usuario_id, "empresa_id": empresa_id})
    C.limpiar_cache()


def borrar_festivo(fid, usuario):
    _solo_admin(usuario)
    R().ex("delete from festivos_extra where id = ?", [fid])
    evento(None, usuario, "configuracion_baja", {"tabla": "festivos_extra", "id": fid})
    C.limpiar_cache()


def guardar_filtro(usuario, nombre, filtros):
    if not (nombre or "").strip():
        raise ErrorNegocio("Póngale un nombre al filtro (por ejemplo «Mis casos rojos»).")
    R().insertar("filtros_guardados", {"usuario_id": usuario["id"], "nombre": nombre.strip(), "filtros": filtros,
                                       "fecha": ahora()})


def filtros_guardados(usuario):
    return R().q("select * from filtros_guardados where usuario_id = ? order by nombre", [usuario["id"]])


def borrar_filtro(fid, usuario):
    R().ex("delete from filtros_guardados where id = ? and usuario_id = ?", [fid, usuario["id"]])

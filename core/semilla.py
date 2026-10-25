"""Datos de demostración FICTICIOS: catálogos + ~300 PQRS con fechas, estados e historial variados."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from core import aprobacion, catalogo_demo as cat, documentos as docs, plantillas, plazos, radicado as rad
from core.reloj import TZ, a_fecha, ahora

ASUNTOS = {
    "P": [("Revisión del {s} en mi sector", "Les pido revisar el {s} en mi sector porque desde hace dos semanas presenta fallas frecuentes."),
          ("Solicitud de visita técnica", "Solicito una visita técnica para revisar la instalación del {s} en mi vivienda."),
          ("Cambio de titular del contrato", "Requiero cambiar el titular del contrato del {s} a nombre de mi hermana.")],
    "D": [("Copia de facturas del último año", "Necesito copia de las facturas del {s} de los últimos doce meses para un trámite."),
          ("Certificado de paz y salvo", "Solicito un certificado de paz y salvo del {s} para vender el inmueble.")],
    "C": [("Requisitos para trasladar el servicio", "¿Cuáles son los requisitos para trasladar el {s} a otra dirección?"),
          ("Consulta sobre tarifas", "Quisiera saber cómo se calcula la tarifa del {s} y qué subsidios existen.")],
    "Q": [("Mala atención en la oficina", "Ayer me atendieron con mal trato en la oficina principal y no resolvieron mi caso."),
          ("Demora en la atención telefónica", "Llamé tres veces a la línea de atención y la demora fue de más de una hora.")],
    "R": [("Cobro doble en la factura", "En la última factura del {s} me cobraron dos veces el mismo periodo. Pido la devolución."),
          ("Factura muy alta sin explicación", "La factura del {s} llegó tres veces más alta de lo normal sin ningún cambio en mi consumo."),
          ("Daño causado por falla del servicio", "Una falla del {s} dañó electrodomésticos en mi casa y solicito la reparación.")],
    "S": [("Sugerencia para pagar por la aplicación", "Sugiero que se pueda pagar el {s} desde la aplicación móvil."),
          ("Felicitación al equipo técnico", "Felicito al equipo técnico que atendió mi solicitud del {s} con rapidez.")],
    "CD": [("¿Qué datos personales tienen de mí?", "Quiero saber qué datos personales míos tienen registrados y para qué los usan.")],
    "RD": [("Eliminar mi número de teléfono", "Solicito la supresión de mi número de teléfono de su base de datos de mercadeo."),
           ("Actualizar mis datos personales", "Pido la rectificación de mi dirección y correo en sus registros.")],
}
CANALES = [("web", 45), ("correo", 30), ("presencial", 12), ("telefonico", 8), ("api", 5)]
PESOS_TIPO = {"P": 30, "R": 25, "Q": 15, "D": 10, "C": 6, "S": 6, "CD": 4, "RD": 4}
# Término exclusivo que solo aparece dentro de un PDF adjunto (criterio de aceptación 9)
PALABRA_PDF = "hidrómetro ultrasónico"


def _elegir(rng, pares):
    return rng.choices([p[0] for p in pares], weights=[p[1] for p in pares])[0]


def _estado_final(rng, r):
    if r > 1.3:
        op = [("CERRADA", 76), ("ENVIADA", 2), ("ANULADA", 3), ("TRASLADADA", 4), ("DESISTIDA", 3), ("EN_TRAMITE", 7),
              ("EN_REVISION", 3), ("REABIERTA", 2)]
    elif r > 1.0:
        op = [("CERRADA", 45), ("ENVIADA", 12), ("EN_TRAMITE", 22), ("EN_REVISION", 11), ("APROBADA", 5), ("PENDIENTE_INFO", 5)]
    elif r > 0.5:
        op = [("EN_TRAMITE", 35), ("EN_REVISION", 20), ("APROBADA", 5), ("PENDIENTE_INFO", 10), ("ENVIADA", 15),
              ("CERRADA", 10), ("ASIGNADA", 5)]
    else:
        op = [("ASIGNADA", 35), ("EN_TRAMITE", 35), ("RECIBIDA", 4), ("PENDIENTE_INFO", 6), ("EN_REVISION", 10),
              ("ENVIADA", 5), ("CERRADA", 5)]
    return _elegir(rng, op)


def _pdf_ciudadano(titulo, texto):
    return plantillas.pdf_texto(titulo, texto.split("\n"))


def generar(n: int = 300, cuando: datetime | None = None, semilla: int = 2026):
    """Devuelve (tablas: dict[nombre, filas], archivos: dict[ruta, bytes])."""
    rng = random.Random(semilla)
    t_ahora = (cuando or ahora()).replace(microsecond=0)
    hoy = t_ahora.date()
    empresas, tipos, temas = cat.empresas(), cat.tipos(), cat.temas()
    usuarios, usuario_empresa = cat.usuarios()
    # EMP01: un abogado ausente para demostrar que no recibe casos
    ab3 = next(u for u in usuarios if u["email"] == f"abogado3.emp01@{cat.DOMINIO}")
    ab3["ausente_desde"] = (hoy - timedelta(days=2)).isoformat()
    ab3["ausente_hasta"] = (hoy + timedelta(days=6)).isoformat()
    festivos = cat.festivos_extra()
    tipo_cod = {t["codigo"]: t for t in tipos}
    abogados_emp = {e["id"]: [u for u in usuarios if u["rol"] == "abogado" and {"usuario_id": u["id"], "empresa_id": e["id"]} in usuario_empresa]
                    for e in empresas}
    sup_emp = {e["id"]: next(u for u in usuarios if u["rol"] == "supervisor" and {"usuario_id": u["id"], "empresa_id": e["id"]} in usuario_empresa)
               for e in empresas}
    director = next(u for u in usuarios if u["rol"] == "director")
    extra_emp = {e["id"]: frozenset(a_fecha(f["fecha"]) for f in festivos if f["empresa_id"] in (None, e["id"])) for e in empresas}

    T = {k: [] for k in ("solicitantes", "solicitudes", "asignaciones", "respuestas", "aprobaciones", "documentos", "eventos",
                         "encuestas", "correos")}
    archivos: dict[str, bytes] = {}
    consecutivos: dict[tuple[int, int], int] = {}
    carga = {u["id"]: 0 for u in usuarios if u["rol"] == "abogado"}
    ids = {k: 0 for k in T}

    def nid(tabla):
        ids[tabla] += 1
        return ids[tabla]

    def ev(sid, uid, accion, detalle, fecha, origen="app"):
        T["eventos"].append({"id": nid("eventos"), "solicitud_id": sid, "usuario_id": uid, "origen": origen, "accion": accion,
                             "detalle": {**detalle, "semilla": True}, "fecha": min(fecha, t_ahora)})

    # Recepción: lista de (recibido, empresa, tipo) ordenada por fecha para que el consecutivo sea creciente
    entradas = []
    for i in range(n):
        emp = rng.choices(empresas, weights=[60] + [27] * 9)[0]
        tcod = rng.choices(list(PESOS_TIPO), weights=list(PESOS_TIPO.values()))[0]
        dias_atras = int(rng.triangular(0, 130, 8))
        recibido = (t_ahora - timedelta(days=dias_atras)).replace(hour=rng.randint(7, 20), minute=rng.randint(0, 59), second=0)
        if recibido > t_ahora:
            recibido = t_ahora - timedelta(minutes=rng.randint(5, 300))
        entradas.append((recibido, emp, tcod))
    # Duplicados: cuatro pares recientes (mismo solicitante, asunto casi igual, 1 día después)
    dup_de = {}
    recientes = [k for k, x in enumerate(entradas) if (t_ahora - x[0]).days <= 3][:4]
    for k in recientes:
        rec, emp, tcod = entradas[k]
        entradas.append((min(rec + timedelta(hours=20), t_ahora - timedelta(minutes=30)), emp, tcod))
        dup_de[len(entradas) - 1] = k
    orden = sorted(range(len(entradas)), key=lambda k: entradas[k][0])
    sol_por_k = {}
    con_pdf = set(rng.sample(range(len(entradas)), min(30, len(entradas))))

    for k in orden:
        recibido, emp, tcod = entradas[k]
        tp = tipo_cod[tcod]
        extra = extra_emp[emp["id"]]
        f_rad = plazos.fecha_radicacion(recibido, plazos.time(17, 0), extra)
        f_ven = plazos.fecha_vencimiento(f_rad, tp["dias_habiles"], extra)
        cons = consecutivos.get((emp["id"], f_rad.year), 0) + 1
        consecutivos[(emp["id"], f_rad.year)] = cons
        numero = rad.formatear(emp["codigo"], f_rad.year, tcod, cons)
        temas_e = [t for t in temas if t["empresa_id"] == emp["id"]]
        tema = next(t for t in temas_e if t["nombre"] == "Datos personales") if tcod in ("CD", "RD") else \
            rng.choice([t for t in temas_e if t["nombre"] != "Datos personales"])
        canal = _elegir(rng, CANALES)
        sid = nid("solicitudes")
        # Solicitante
        if k in dup_de:
            orig = sol_por_k[dup_de[k]]
            sol = dict(next(x for x in T["solicitantes"] if x["id"] == orig["solicitante_id"]))
            sol["id"] = nid("solicitantes")
            asunto, desc = orig["asunto"] + " (reitero)", orig["descripcion"]
        else:
            nom = f"{rng.choice(cat.NOMBRES)} {rng.choice(cat.APELLIDOS)} {rng.choice(cat.APELLIDOS)}"
            usuario_mail = docs.slug(nom.lower()).replace("-", ".")
            sol = {"id": nid("solicitantes"), "tipo_doc": "CC", "num_doc": str(rng.randint(10_000_000, 1_199_999_999)),
                   "nombre": nom + " (ficticio)", "email": f"{usuario_mail}{rng.randint(1, 99)}@correo.example",
                   "telefono": f"+57 300 555 {rng.randint(1000, 9999)}", "direccion": f"Calle {rng.randint(1, 99)} # {rng.randint(1, 99)}-{rng.randint(1, 99)}",
                   "anonimo": False, "autoriza_datos": canal == "web", "fecha_autorizacion": recibido if canal == "web" else None}
            a, d = rng.choice(ASUNTOS[tcod])
            asunto, desc = a.format(s=cat.EMPRESAS[emp["id"] - 1][2]), d.format(s=cat.EMPRESAS[emp["id"] - 1][2])
        T["solicitantes"].append(sol)
        total = max(1, plazos.dias_habiles_entre(f_rad, f_ven, extra))
        transcurridos = plazos.dias_habiles_entre(f_rad, hoy, extra)
        r = transcurridos / total
        estado = "RECIBIDA" if k in dup_de else ("ASIGNADA" if f_rad > hoy else _estado_final(rng, r))
        es_dup = k in dup_de
        # Abogado: especialidad del tema y menor carga; el ausente no recibe casos recientes
        abogado = None
        if not es_dup and not (estado == "RECIBIDA"):
            cands = abogados_emp[emp["id"]]
            if tema["especialidad_requerida"]:
                cands = [a for a in cands if tema["especialidad_requerida"] in a["especialidades"]] or cands
            if (t_ahora - recibido).days <= 10:
                cands = [a for a in cands if a["id"] != ab3["id"]] or cands
            abogado = min(cands, key=lambda a: (carga[a["id"]], a["id"]))
            carga[abogado["id"]] += 1
        fila = {"id": sid, "radicado": numero, "empresa_id": emp["id"], "tipo_id": tp["id"], "tema_id": tema["id"],
                "solicitante_id": sol["id"], "canal": canal, "asunto": asunto, "descripcion": desc, "estado": estado,
                "prioridad": "normal", "fecha_recepcion": recibido, "fecha_radicacion": f_rad, "fecha_vencimiento": f_ven,
                "dias_suspendidos": 0, "suspendida_desde": None, "prorrogada": False, "fecha_respuesta": None,
                "abogado_id": abogado["id"] if abogado else None, "solicitud_padre_id": None,
                "posible_duplicado_de": sol_por_k[dup_de[k]]["id"] if es_dup else None, "revisar_duplicado": es_dup,
                "respuesta_parcial": False, "reabierta": estado == "REABIERTA", "empresa_origen_id": None,
                "entidad_traslado": None, "marca": None,
                "codigo_consulta": rad.hash_codigo(numero, cat.CODIGO_CONSULTA_DEMO), "message_id": None,
                "creado_por": None, "pendiente_completar": False}
        sol_por_k[k] = fila
        T["solicitudes"].append(fila)
        ev(sid, None, "radicada", {"radicado": numero, "canal": canal, "fecha_radicacion": f_rad.isoformat(),
                                   "fecha_vencimiento": f_ven.isoformat()}, recibido, "ciudadano" if canal == "web" else "app")
        if es_dup:
            ev(sid, None, "posible_duplicado", {"de": sol_por_k[dup_de[k]]["radicado"]}, recibido + timedelta(seconds=1))
        if k in con_pdf:
            texto = (f"Documento aportado por el ciudadano (ficticio)\nRadicado: {numero}\n{desc}\n"
                     + (f"Anexo: informe técnico del {PALABRA_PDF} instalado en el predio, lectura 004471 m3."
                        if k == min(con_pdf) else "Anexo: fotografías y soportes del caso."))
            datos = _pdf_ciudadano("Soporte del ciudadano", texto)
            nombre_n = docs.nombre_normalizado(numero, "entrada", recibido, 1, "soporte-ciudadano.pdf")
            ruta = docs.ruta(emp["codigo"], f_rad.year, tcod, numero, "entrada", nombre_n)
            archivos[ruta] = datos
            T["documentos"].append({"id": nid("documentos"), "solicitud_id": sid, "categoria": "entrada", "nombre": nombre_n,
                                    "nombre_original": "soporte-ciudadano.pdf", "ruta": ruta, "mime": "application/pdf",
                                    "tamano": len(datos), "sha256": docs.sha256(datos), "version": 1,
                                    "texto_extraido": docs.extraer_texto("x.pdf", datos)[0], "estado_texto": "ok",
                                    "subido_por": None, "origen": canal, "fecha": recibido})
        if estado == "RECIBIDA":
            if not es_dup:
                T["asignaciones"].append({"id": nid("asignaciones"), "solicitud_id": sid, "abogado_id": None, "motivo": "cola",
                                          "detalle": "Sin candidatos disponibles", "asignado_por": None, "fecha": recibido})
            continue
        # ---- Historial de estados
        t = recibido + timedelta(minutes=3)
        T["asignaciones"].append({"id": nid("asignaciones"), "solicitud_id": sid, "abogado_id": abogado["id"],
                                  "motivo": "automatica", "detalle": None, "asignado_por": None, "fecha": min(t, t_ahora)})
        ev(sid, None, "asignada", {"abogado_id": abogado["id"], "abogado": abogado["nombre"], "motivo": "automatica",
                                   "estrategia": "E"}, t)
        ev(sid, None, "cambio_estado", {"de": "RECIBIDA", "a": "ASIGNADA"}, t)
        if estado == "ASIGNADA":
            continue

        def momento(frac):
            d = plazos.sumar_habiles(f_rad, max(0, int(total * frac)), extra)
            return min(datetime(d.year, d.month, d.day, rng.randint(8, 16), rng.randint(0, 59), tzinfo=TZ), t_ahora)

        t_tramite = max(t + timedelta(minutes=30), momento(0.05))
        ev(sid, abogado["id"], "cambio_estado", {"de": "ASIGNADA", "a": "EN_TRAMITE", "motivo": "El abogado abrió el caso"}, t_tramite)
        if estado == "ANULADA":
            ev(sid, sup_emp[emp["id"]]["id"], "cambio_estado", {"de": "RECIBIDA", "a": "ANULADA", "motivo": "Spam detectado en revisión"},
               t_tramite)
            continue
        if estado == "TRASLADADA":
            fila["entidad_traslado"] = rng.choice(["Superintendencia de Servicios Públicos (ficticia)", "Alcaldía Distrital (ficticia)"])
            fila["fecha_respuesta"] = momento(0.2)
            ev(sid, abogado["id"], "cambio_estado", {"de": "EN_TRAMITE", "a": "TRASLADADA", "entidad": fila["entidad_traslado"],
                                                     "motivo": "Sin competencia"}, fila["fecha_respuesta"])
            continue
        if estado in ("PENDIENTE_INFO", "DESISTIDA"):
            t_p = momento(0.3) if estado == "PENDIENTE_INFO" else momento(0.2)
            fila["suspendida_desde"] = t_p.date()
            ev(sid, abogado["id"], "cambio_estado", {"de": "EN_TRAMITE", "a": "PENDIENTE_INFO",
                                                     "solicitado": "Copia de la factura y del documento de identidad."}, t_p)
            if estado == "DESISTIDA":
                t_d = t_p + timedelta(days=31)
                fila["fecha_respuesta"] = min(t_d, t_ahora)
                ev(sid, None, "cambio_estado", {"de": "PENDIENTE_INFO", "a": "DESISTIDA",
                                                "motivo": "No aportó la información en 30 días"}, t_d, "sistema")
            continue
        if estado == "EN_TRAMITE":
            if rng.random() < 0.4:
                rid = nid("respuestas")
                T["respuestas"].append({"id": rid, "solicitud_id": sid, "version": 1, "contenido": _texto_resp(fila, sol, emp, tp),
                                        "es_parcial": False, "estado": "borrador", "autor_id": abogado["id"], "origen": "app",
                                        "fecha": t_tramite, "actualizado": t_tramite})
                ev(sid, abogado["id"], "borrador_creado", {"version": 1}, t_tramite + timedelta(hours=1))
            if rng.random() < 0.15 and fila["fecha_vencimiento"] >= hoy:
                nueva = plazos.sumar_habiles(f_ven, max(1, tp["dias_habiles"] // 2), extra)
                fila["fecha_vencimiento"], fila["prorrogada"] = nueva, True
                ev(sid, abogado["id"], "prorroga", {"antes": f_ven.isoformat(), "nueva": nueva.isoformat(),
                                                    "motivo": "Se requiere concepto técnico del área operativa"}, t_tramite + timedelta(hours=2))
            continue
        # ---- Respuesta, revisión y aprobación
        niveles = aprobacion.niveles_requeridos(tp["niveles_aprobacion"], tema["sensible"])
        a_tiempo = rng.random() < 0.85
        if estado in ("ENVIADA", "CERRADA", "REABIERTA"):
            t_env = momento(rng.uniform(0.4, 0.98)) if a_tiempo else momento(rng.uniform(1.05, 1.3))
        else:
            t_env = t_ahora
        t_rev = max(t_tramite + timedelta(hours=2), t_env - timedelta(days=rng.randint(1, 3)))
        if estado in ("EN_REVISION",) and r > 1:
            t_rev = momento(0.9)
        devuelta = niveles > 0 and rng.random() < 0.2
        version = 1
        rid = nid("respuestas")
        texto = _texto_resp(fila, sol, emp, tp)
        T["respuestas"].append({"id": rid, "solicitud_id": sid, "version": 1, "contenido": texto, "es_parcial": False,
                                "estado": "devuelta" if devuelta else "en_revision", "autor_id": abogado["id"], "origen": "app",
                                "fecha": t_rev, "actualizado": t_rev})
        ev(sid, abogado["id"], "cambio_estado", {"de": "EN_TRAMITE", "a": "EN_REVISION", "version": 1}, t_rev)
        if devuelta:
            t_dev = t_rev + timedelta(hours=3)
            T["aprobaciones"].append({"id": nid("aprobaciones"), "respuesta_id": rid, "nivel": 1, "aprobador_id": sup_emp[emp["id"]]["id"],
                                      "decision": "devuelta", "comentario": "Falta citar la norma aplicable y el valor exacto.",
                                      "urgente": False, "fecha": t_dev})
            ev(sid, sup_emp[emp["id"]]["id"], "cambio_estado", {"de": "EN_REVISION", "a": "EN_TRAMITE", "version": 1,
                                                                "comentario": "Falta citar la norma aplicable y el valor exacto."}, t_dev)
            version = 2
            rid = nid("respuestas")
            texto = texto + "\n\nDe acuerdo con la Ley 1755 de 2015, el valor ajustado es de $0 (dato ficticio)."
            t_rev = t_dev + timedelta(hours=4)
            T["respuestas"].append({"id": rid, "solicitud_id": sid, "version": 2, "contenido": texto, "es_parcial": False,
                                    "estado": "en_revision", "autor_id": abogado["id"], "origen": "app", "fecha": t_rev,
                                    "actualizado": t_rev})
            ev(sid, abogado["id"], "cambio_estado", {"de": "EN_TRAMITE", "a": "EN_REVISION", "version": 2}, t_rev)
        if estado == "EN_REVISION":
            if niveles == 2 and rng.random() < 0.5:
                T["aprobaciones"].append({"id": nid("aprobaciones"), "respuesta_id": rid, "nivel": 1,
                                          "aprobador_id": sup_emp[emp["id"]]["id"], "decision": "aprobada", "comentario": "",
                                          "urgente": False, "fecha": t_rev + timedelta(hours=2)})
                ev(sid, sup_emp[emp["id"]]["id"], "aprobacion", {"version": version, "nivel": 1}, t_rev + timedelta(hours=2))
            continue
        t_apr = t_rev + timedelta(hours=2)
        for nivel in range(1, niveles + 1):
            ap = sup_emp[emp["id"]] if nivel == 1 else director
            T["aprobaciones"].append({"id": nid("aprobaciones"), "respuesta_id": rid, "nivel": nivel, "aprobador_id": ap["id"],
                                      "decision": "aprobada", "comentario": "", "urgente": False, "fecha": min(t_apr, t_ahora)})
            ev(sid, ap["id"], "aprobacion", {"version": version, "nivel": nivel}, t_apr)
            t_apr += timedelta(hours=1)
        ev(sid, None, "cambio_estado", {"de": "EN_REVISION", "a": "APROBADA", "version": version}, t_apr, "sistema")
        T["respuestas"][-1]["estado"] = "aprobada"
        if estado == "APROBADA":
            continue
        t_env = max(t_env, t_apr + timedelta(minutes=30))
        if t_env > t_ahora:
            t_env = t_ahora - timedelta(minutes=5)
        T["respuestas"][-1]["estado"] = "enviada"
        fila["fecha_respuesta"] = t_env
        ev(sid, abogado["id"], "cambio_estado", {"de": "APROBADA", "a": "ENVIADA", "medio": "correo"}, t_env)
        ev(sid, abogado["id"], "respuesta_enviada", {"medio": "correo", "nota": "PDF no generado en datos de semilla"}, t_env)
        if estado in ("CERRADA", "REABIERTA"):
            t_c = min(t_env + timedelta(days=2), t_ahora)
            ev(sid, None, "cambio_estado", {"de": "ENVIADA", "a": "CERRADA", "motivo": "Cierre automático"}, t_c, "sistema")
            if rng.random() < 0.35:
                T["encuestas"].append({"id": nid("encuestas"), "solicitud_id": sid, "puntaje": rng.choices([5, 4, 3, 2, 1], [45, 30, 12, 8, 5])[0],
                                       "comentario": None, "fecha": t_c})
            if estado == "REABIERTA":
                ev(sid, sup_emp[emp["id"]]["id"], "cambio_estado", {"de": "CERRADA", "a": "REABIERTA",
                                                                    "motivo": "El ciudadano manifestó inconformidad"}, t_c + timedelta(hours=1))

    # Un caso PENDIENTE_INFO antiguo para que la primera ejecución de tareas lo pase a DESISTIDA
    viejos = [s for s in T["solicitudes"] if s["estado"] == "PENDIENTE_INFO"]
    if viejos:
        viejos[0]["suspendida_desde"] = hoy - timedelta(days=35)
    tablas = {
        "empresas": empresas, "usuarios": usuarios, "usuario_empresa": usuario_empresa, "tipos_pqrs": tipos, "temas": temas,
        "parametros": cat.parametros(), "plantillas": cat.plantillas(), "festivos_extra": festivos,
        "solicitantes": T["solicitantes"], "solicitudes": T["solicitudes"], "asignaciones": T["asignaciones"],
        "respuestas": T["respuestas"], "aprobaciones": T["aprobaciones"], "documentos": T["documentos"],
        "eventos": sorted(T["eventos"], key=lambda e: e["id"]), "encuestas": T["encuestas"],
        "consecutivos": [{"empresa_id": e, "anio": a, "ultimo": u} for (e, a), u in consecutivos.items()],
    }
    return tablas, archivos


def _texto_resp(fila, sol, emp, tp):
    return (f"Señor(a) {sol['nombre']}:\n\nEn atención a su {tp['nombre'].lower()} {fila['radicado']} sobre «{fila['asunto']}», "
            f"le informamos que {emp['nombre']} revisó el caso y tomó las acciones correspondientes (respuesta ficticia de "
            "demostración).\n\nAtentamente,")


ORDEN_CARGA = ["empresas", "usuarios", "usuario_empresa", "tipos_pqrs", "temas", "parametros", "plantillas", "festivos_extra",
               "solicitantes", "solicitudes", "asignaciones", "respuestas", "aprobaciones", "documentos", "eventos",
               "encuestas", "consecutivos"]


def cargar(repo, n: int = 300, cuando: datetime | None = None, subir_archivos: bool = True, alertas: bool = True,
           archivo: bool = True) -> dict:
    """Carga todo en el repositorio (SQLite o PostgreSQL) y guarda los PDF en el almacén."""
    from core.almacenamiento import obtener_almacen
    tablas, archivos = generar(n, cuando)
    usuarios = tablas["usuarios"]
    sin_suplente = [{**u, "suplente_id": None} for u in usuarios]
    with repo.transaccion():
        for t in ORDEN_CARGA:
            repo.carga_masiva(t, sin_suplente if t == "usuarios" else tablas[t])
        for u in usuarios:
            if u["suplente_id"]:
                repo.actualizar("usuarios", u["id"], {"suplente_id": u["suplente_id"]})
    repo.reiniciar_secuencias()
    repo.reconstruir_indice()
    if subir_archivos:
        alm = obtener_almacen()
        for ruta, datos in archivos.items():
            try:
                alm.guardar(ruta, datos, "application/pdf")
            except FileExistsError:
                pass
    from core import consultas
    consultas.limpiar_cache()
    extra = {}
    if archivo:  # TRD y archivo físico de demostración (core/semilla_archivo.py)
        from core import semilla_archivo
        extra = semilla_archivo.cargar(repo)
    if alertas:
        from core import servicios
        servicios.generar_alertas()
    return {t: len(v) for t, v in tablas.items()} | {"archivos": len(archivos)} | {f"archivo_{k}": v for k, v in extra.items()}

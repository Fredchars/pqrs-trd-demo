"""Expediente del caso: respuesta con plantillas y versiones, aprobación, documentos, historial y acciones."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import ui
from core import aprobacion, flujo, plantillas, plazos
from core import consultas as C
from core import documentos as docs
from core import servicios as S
from core.reloj import a_fecha, fmt_fecha, fmt_fechahora, hoy

ui.aviso_beta()
u = ui.requiere()
qp = st.query_params.get("caso")
if qp:
    s0 = C.solicitud_por_radicado(qp, u)
    if s0:
        st.session_state["caso_id"] = s0["id"]
sid = st.session_state.get("caso_id")
if not sid:
    st.info("Abra un caso desde su bandeja o desde la búsqueda.")
    st.stop()
s = C.obtener_solicitud(sid, u)
if not s:
    st.error("No tiene permiso para ver este caso o no existe.")
    st.stop()
if u["rol"] == "abogado" and s["estado"] in ("ASIGNADA", "REABIERTA"):
    s = S.abrir_caso(sid, u)
    s = C.obtener_solicitud(sid, u)

solo_lectura = u["rol"] in ("auditor", "integracion")
es_responsable = (u["rol"] == "abogado" and s.get("abogado_id") == u["id"]) or u["rol"] in ("supervisor", "admin")
emp = C.empresa(s["empresa_id"])

# ---------------------------------------------------------------- encabezado
st.markdown(f"## 📂 {s['radicado']}")
st.markdown(f"{ui.semaforo_html(s)} &nbsp; **Estado:** {flujo.explicar(s['estado'])} (`{s['estado']}`)", unsafe_allow_html=True)
c = st.columns(5)
c[0].metric("Empresa", s["empresa_codigo"])
c[1].metric("Tipo", s["tipo_nombre"])
c[2].metric("Radicada", fmt_fecha(s["fecha_radicacion"]))
c[3].metric("Vence", fmt_fecha(s["fecha_vencimiento"]))
c[4].metric("Abogado", (s.get("abogado_nombre") or "Sin asignar").replace(" (ficticio)", ""))
marcas = [m for m, v in (("⏩ Prorrogada", s.get("prorrogada")), ("½ Respuesta parcial enviada", s.get("respuesta_parcial")),
                         ("🔁 Reabierta", s.get("reabierta")), ("⚠️ Posible duplicado", s.get("revisar_duplicado")),
                         (f"🏷 {s.get('marca')}", s.get("marca")),
                         (f"↪ Trasladada desde {C.empresa(s['empresa_origen_id'])['codigo']}" if s.get("empresa_origen_id") else "", s.get("empresa_origen_id")),
                         (f"🔗 Vinculada a otra solicitud", s.get("solicitud_padre_id"))) if v]
if marcas:
    st.caption(" · ".join(marcas))
with st.container(border=True):
    st.markdown(f"**Asunto:** {s['asunto']}")
    st.markdown(s.get("descripcion") or "")
    st.caption(f"Solicitante: {s.get('solicitante_nombre')} · {s.get('solicitante_email') or 'sin correo'} · "
               f"{s.get('solicitante_tipo_doc') or ''} {s.get('solicitante_doc') or ''} · Canal: {C.CANALES.get(s['canal'], s['canal'])} · "
               f"Tema: {s.get('tema_nombre') or '—'} · Recibida: {fmt_fechahora(s['fecha_recepcion'])}")

tab_r, tab_e, tab_h, tab_a = st.tabs(["✍️ Respuesta", "🗂 Expediente", "🕑 Historial", "⚙️ Acciones"])

# ---------------------------------------------------------------- respuesta
with tab_r:
    resp = C.respuestas(sid)
    actual = resp[-1] if resp else None
    aprobs = C.aprobaciones_de([r["id"] for r in resp])
    niveles = S.niveles_caso(s)
    st.caption(f"Esquema de aprobación para este caso: **{niveles} nivel(es)** "
               f"({'sin aprobación' if niveles == 0 else 'supervisor' if niveles == 1 else 'supervisor y director'}).")
    devoluciones = [a for a in aprobs if a["decision"] == "devuelta"]
    if devoluciones and s["estado"] == "EN_TRAMITE":
        d = devoluciones[-1]
        st.warning(f"↩️ **Devuelta por {d['aprobador']}** (nivel {d['nivel']}, {fmt_fechahora(d['fecha'])}): {d['comentario']}")
    if actual and actual["origen"] == "mcp" and actual["estado"] == "borrador":
        st.info("🤖 Este borrador lo redactó el asistente de IA (MCP). Revíselo con cuidado antes de enviarlo a revisión.")
    editable = s["estado"] in ("EN_TRAMITE", "ASIGNADA", "REABIERTA") and es_responsable and not solo_lectura
    if editable:
        clave_txt = f"txt-{sid}"
        if clave_txt not in st.session_state:
            st.session_state[clave_txt] = actual["contenido"] if actual and actual["estado"] in ("borrador", "devuelta") else ""
        ps = C.plantillas("respuesta", s["empresa_id"], s["tipo_id"])
        c1, c2 = st.columns([3, 1])
        p = c1.selectbox("Plantilla", ps, format_func=lambda x: x["nombre"], key=f"pl-{sid}")
        if c2.button("Usar plantilla", key=f"usar-{sid}", width="stretch"):
            st.session_state[clave_txt] = S.texto_plantilla(sid, p["id"], u)
            st.rerun()
        texto = st.text_area("Texto de la respuesta (editable)", key=clave_txt, height=320)
        faltan = plantillas.variables_faltantes(texto)
        if faltan:
            st.caption("Variables sin reemplazar: " + ", ".join(faltan))
        if "[" in texto and "]" in texto:
            st.caption("Recuerde completar los textos entre corchetes [ ].")
        parcial = st.checkbox("Es una respuesta parcial (el caso sigue abierto hasta la respuesta definitiva)", key=f"par-{sid}")
        b1, b2 = st.columns(2)
        try:
            if b1.button("💾 Guardar borrador", key=f"g-{sid}", width="stretch"):
                r = S.guardar_borrador(sid, texto, u, parcial)
                st.success(f"Borrador guardado (versión {r['version']}).")
            if b2.button("📤 Enviar a revisión", key=f"rev-{sid}", type="primary", width="stretch"):
                r = S.enviar_a_revision(sid, texto, u, parcial)
                st.session_state.pop(clave_txt, None)
                st.success("Respuesta enviada a revisión." if r["estado"] == "EN_REVISION" else
                           "Este tipo no requiere aprobación: la respuesta quedó aprobada y lista para enviar.")
                st.rerun()
        except Exception as e:
            ui.error(e)
    elif actual:
        st.markdown(f"**Versión {actual['version']}** · {actual['estado']} · por {actual.get('autor') or 'asistente'} · "
                    f"{fmt_fechahora(actual['actualizado'])}")
        st.markdown(f"<div class='caja'>{actual['contenido'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)

    # Revisión y aprobación (RU-14: cambios entre versiones y comentarios anteriores en la misma pantalla)
    if s["estado"] == "EN_REVISION" and actual:
        st.markdown("#### Revisión")
        anterior = resp[-2] if len(resp) > 1 else None
        if anterior:
            dif = aprobacion.resumen_diff(anterior["contenido"], actual["contenido"])
            st.caption(f"Cambios respecto a la versión {anterior['version']}: +{dif['agregadas']} / −{dif['eliminadas']} palabras "
                       f"({dif['similitud']} % igual).")
            st.markdown(f"<div class='caja'>{aprobacion.diff_html(anterior['contenido'], actual['contenido'])}</div>",
                        unsafe_allow_html=True)
        ok, n, nota = S.puede_aprobar(s, u)
        st.caption(f"Nivel pendiente: {n} ({aprobacion.rol_para_nivel(n) if n else '-'}) {nota}")
        if ok and not solo_lectura:
            com = st.text_area("Comentario (obligatorio para devolver)", key=f"com-{sid}")
            a1, a2, a3 = st.columns(3)
            try:
                if a1.button("✅ Aprobar", key=f"ap-{sid}", type="primary", width="stretch"):
                    r = S.aprobar(sid, u, com)
                    st.success("Aprobada. " + ("Lista para enviar." if r["estado"] == "APROBADA" else "Pasa al siguiente nivel."))
                    st.rerun()
                if a2.button("↩️ Devolver con comentarios", key=f"dev-{sid}", width="stretch"):
                    S.devolver(sid, u, com)
                    st.warning("Devuelta al abogado.")
                    st.rerun()
                if u["rol"] == "supervisor" and s.get("dias_restantes") is not None and s["dias_restantes"] <= 0:
                    if a3.button("⚡ Aprobar y enviar (urgente)", key=f"urg-{sid}", width="stretch"):
                        S.aprobar_y_enviar_urgente(sid, u, com)
                        st.success("Aprobada y enviada en un solo paso (queda marcado en la bitácora).")
                        st.rerun()
            except Exception as e:
                ui.error(e)

    if s["estado"] == "APROBADA" and not solo_lectura and (es_responsable or u["rol"] in ("director", "radicador")):
        st.markdown("#### Enviar al ciudadano")
        medio = st.radio("Medio de envío", ["correo", "publicacion", "fisico"], horizontal=True, key=f"medio-{sid}",
                         format_func=lambda m: {"correo": "Correo con PDF (por defecto)", "publicacion": "Publicar en la consulta web",
                                                "fisico": "Envío físico (correspondencia)"}[m])
        hijos = C.vinculados(sid)
        st.markdown(f"**Resumen:** se generará el PDF firmado (firma simple + código de verificación), se guardará en "
                    f"`03_respuesta` y se enviará a **{s.get('solicitante_email') or 'la consulta web'}**."
                    + (f" También a {len(hijos)} radicado(s) vinculado(s)." if hijos else ""))
        conf = st.checkbox("Confirmo que revisé la respuesta y quiero enviarla (no se puede deshacer)", key=f"conf-{sid}")
        if st.button("📨 Enviar respuesta", disabled=not conf, type="primary", key=f"env-{sid}"):
            try:
                r = S.enviar_respuesta(sid, u, medio)
                st.success(f"Respuesta enviada ({r['medio']}). Código de verificación: {r['codigo_verificacion']}")
                st.rerun()
            except Exception as e:
                ui.error(e)

    if resp:
        with st.expander(f"Historial de versiones ({len(resp)}) y aprobaciones"):
            for r in reversed(resp):
                st.markdown(f"**v{r['version']}** · {r['estado']} · {r.get('autor') or r['origen']} · {fmt_fechahora(r['fecha'])}"
                            + (" · 🤖 asistente" if r["origen"] == "mcp" else "") + (" · parcial" if r["es_parcial"] else ""))
                for a in [a for a in aprobs if a["respuesta_id"] == r["id"]]:
                    st.caption(f"{'✅' if a['decision'] == 'aprobada' else '↩️'} Nivel {a['nivel']} · {a['aprobador']} · "
                               f"{fmt_fechahora(a['fecha'])}{' · URGENTE' if a['urgente'] else ''} · {a['comentario'] or ''}")
                st.text(r["contenido"][:1500])

# ---------------------------------------------------------------- expediente
with tab_e:
    documentos = C.documentos(sid)
    for cat, titulo in docs.NOMBRES_CATEGORIA.items():
        grupo = [d for d in documentos if d["categoria"] == cat]
        st.markdown(f"**{docs.CATEGORIAS[cat]}** · {titulo} ({len(grupo)})")
        for d in grupo:
            c1, c2, c3 = st.columns([5, 2, 2])
            c1.caption(f"📄 {d['nombre_original']} · v{d['version']} · {round((d['tamano'] or 0) / 1024, 1)} KB · "
                       f"{fmt_fechahora(d['fecha'])} · texto: {d['estado_texto'] or '-'}  \nSHA-256 `{d['sha256'][:20]}…`")
            if c2.button("Preparar descarga", key=f"pd-{d['id']}"):
                st.session_state[f"dl-{d['id']}"] = True
            if st.session_state.get(f"dl-{d['id']}"):
                try:
                    datos, dd, integro = S.descargar(d["id"], u)
                    c3.download_button("⬇️ Descargar", datos, dd["nombre_original"], key=f"dl2-{d['id']}",
                                       mime=dd.get("mime") or "application/octet-stream")
                    c2.caption("✔ Íntegro (SHA-256 coincide)" if integro else "⚠️ ¡La huella no coincide!")
                except Exception as e:
                    ui.error(e)
    if s["estado"] == "CERRADA":  # TRD y archivo físico: dónde quedó el expediente y su papel
        from core import archivo as _A
        _x = _A.ubicacion_de_caso(sid, u)
        st.divider()
        if _x:
            _ubic = (f"caja **{_x['caja_codigo']}**, carpeta **{_x['carpeta_codigo']}** (estante {_x['estante']}, entrepaño {_x['entrepano']})"
                     if _x.get("carpeta_codigo") else "aún sin ubicar en el archivo físico")
            st.info(f"🗄️ **Archivo (TRD):** serie **{_x['serie_codigo']} · {_x['serie_nombre']}** · retención hasta "
                    f"**{fmt_fecha(_x['fecha_disposicion'])}** ({_x['fase']}) · {_ubic}.")
        elif _A.puede_gestionar(u):
            st.warning("🗄️ Este caso está cerrado y **aún no tiene serie documental**. Asígnelo en *Expedientes › Cerradas sin serie*.")
    if not solo_lectura and (es_responsable or u["rol"] == "radicador"):
        st.divider()
        with st.form(f"subir-{sid}", clear_on_submit=True):
            st.markdown("**Agregar documento** (los de entrada y respuesta no se borran ni reemplazan: se crea una versión nueva)")
            cat = st.selectbox("Carpeta", ["trabajo", "soporte", "entrada"], format_func=lambda k: f"{docs.CATEGORIAS[k]} · {docs.NOMBRES_CATEGORIA[k]}")
            arch = st.file_uploader("Archivo", type=sorted(docs.EXTENSIONES))
            if st.form_submit_button("Subir"):
                try:
                    if not arch:
                        raise S.ErrorNegocio("Elija un archivo para subir.")
                    r = S.adjuntar(s, cat, arch.name, arch.getvalue(), arch.type, u)
                    st.success(f"Documento guardado (v{r['version']}, texto: {r['estado_texto']}).")
                except Exception as e:
                    ui.error(e)
        with st.form(f"nota-{sid}", clear_on_submit=True):
            nota = st.text_area("Nota interna (queda en 02_trabajo; el ciudadano no la ve)")
            if st.form_submit_button("Guardar nota"):
                try:
                    S.agregar_nota(sid, nota, u)
                    st.success("Nota guardada.")
                except Exception as e:
                    ui.error(e)

# ---------------------------------------------------------------- historial
with tab_h:
    evs = C.eventos(sid)
    df = pd.DataFrame([{"Fecha": fmt_fechahora(e["fecha"]), "Acción": e["accion"], "Usuario": e.get("usuario") or e["origen"],
                        "Origen": e["origen"], "Detalle": ", ".join(f"{k}: {v}" for k, v in (e["detalle"] or {}).items() if k != "semilla")}
                       for e in evs])
    st.dataframe(df, hide_index=True, width="stretch")
    asign = C.asignaciones(sid)
    if asign:
        st.markdown("**Asignaciones**")
        st.dataframe(pd.DataFrame([{"Fecha": fmt_fechahora(a["fecha"]), "Abogado": a.get("abogado") or "Cola del supervisor",
                                    "Motivo": a["motivo"], "Detalle": a.get("detalle") or ""} for a in asign]),
                     hide_index=True, width="stretch")
    lineas = [f"{r['Fecha']} · {r['Acción']} · {r['Usuario']} · {r['Detalle']}" for r in df.to_dict("records")]
    st.download_button("⬇️ Trazabilidad del caso (R8, PDF)", plantillas.pdf_texto(f"Trazabilidad {s['radicado']}", lineas),
                       f"trazabilidad-{s['radicado']}.pdf", mime="application/pdf")

# ---------------------------------------------------------------- acciones
with tab_a:
    if solo_lectura:
        st.info("Su rol es de solo lectura.")
        st.stop()
    hecho = False

    def ejecutar(fn, *a, ok="Hecho."):
        try:
            fn(*a)
            st.success(ok)
            st.rerun()
        except Exception as e:
            ui.error(e)

    if s["estado"] == "EN_TRAMITE" and es_responsable:
        with st.expander("📩 Pedir información al ciudadano (suspende el plazo)"):
            txt = st.text_area("¿Qué información falta?", key=f"pi-{sid}")
            if st.button("Enviar solicitud de información", key=f"pib-{sid}"):
                ejecutar(S.pedir_informacion, sid, txt, u, ok="Solicitud enviada. El plazo quedó suspendido.")
    if s["estado"] == "PENDIENTE_INFO" and es_responsable:
        with st.expander("📥 Registrar información aportada por el ciudadano (por teléfono o ventanilla)"):
            txt = st.text_area("Información recibida", key=f"ai-{sid}")
            if st.button("Registrar y reanudar plazo", key=f"aib-{sid}"):
                ejecutar(S.aportar_informacion, sid, txt, [], "app", u, ok="Información registrada; el plazo se reanudó.")
    if s["estado"] in flujo.ABIERTOS and es_responsable:
        with st.expander("⏩ Registrar prórroga (antes del vencimiento)"):
            maximo = plazos.max_fecha_prorroga(a_fecha(s["fecha_radicacion"]), int(s["dias_habiles"]),
                                               s.get("dias_prorroga_max"), C.festivos(s["empresa_id"]))
            st.caption(f"Vence: {fmt_fecha(s['fecha_vencimiento'])} · Fecha máxima permitida: {fmt_fecha(maximo)}")
            nueva = st.date_input("Nueva fecha de vencimiento", value=min(maximo, a_fecha(s["fecha_vencimiento"]) + timedelta(days=7)),
                                  key=f"pr-{sid}", format="DD/MM/YYYY")
            mot = st.text_input("Motivo (se le informa al ciudadano)", key=f"prm-{sid}")
            if st.button("Registrar prórroga", key=f"prb-{sid}"):
                ejecutar(S.prorrogar, sid, nueva, mot, u, ok="Prórroga registrada y ciudadano notificado.")
    if s["estado"] in flujo.ABIERTOS and (es_responsable or (u["rol"] == "radicador" and s["estado"] == "RECIBIDA")):
        with st.expander("🏷 Corregir clasificación (recalcula el plazo)"):
            tps = C.tipos()
            nt = st.selectbox("Tipo", tps, index=[t["id"] for t in tps].index(s["tipo_id"]), format_func=lambda t: t["nombre"], key=f"ct-{sid}")
            tms = [None] + C.temas(s["empresa_id"])
            ntm = st.selectbox("Tema", tms, format_func=lambda t: "—" if t is None else t["nombre"], key=f"ctm-{sid}")
            marca = st.selectbox("Marca jurídica", [None, "irrespetuosa", "oscura", "reiterativa"], key=f"mk-{sid}",
                                 format_func=lambda m: "Ninguna" if m is None else m)
            mcl = st.text_input("Motivo de la reclasificación (queda en la bitácora)", key=f"ctmo-{sid}")
            if st.button("Guardar clasificación", key=f"ctb-{sid}"):
                try:
                    S.cambiar_clasificacion(sid, nt["id"], ntm["id"] if ntm else None, u, mcl)
                    S.marcar(sid, marca, u)
                    st.success("Clasificación actualizada; el vencimiento se recalculó.")
                    st.rerun()
                except Exception as e:
                    ui.error(e)
    if s["estado"] in ("ASIGNADA", "EN_TRAMITE") and es_responsable:
        with st.expander("🚚 Trasladar a la entidad competente (sin competencia)"):
            ent = st.text_input("Entidad competente", key=f"te-{sid}")
            mot = st.text_input("Motivo", key=f"tem-{sid}")
            conf = st.checkbox(f"Confirmo el traslado de {s['radicado']} a «{ent or '...'}» y el aviso al ciudadano", key=f"tec-{sid}")
            if st.button("Trasladar", disabled=not conf, key=f"teb-{sid}"):
                ejecutar(S.trasladar_externo, sid, ent, mot, u, ok="Caso trasladado y ciudadano informado.")
    if u["rol"] == "abogado" and s.get("abogado_id") == u["id"] and s["estado"] in flujo.ABIERTOS:
        with st.expander("🙅 Devolver el caso (conflicto de interés o tema ajeno)"):
            mot = st.text_input("Motivo", key=f"dc-{sid}")
            if st.button("Devolver para reasignación", key=f"dcb-{sid}"):
                ejecutar(S.rechazar_caso, sid, mot, u, ok="Caso devuelto; se reasignó y el supervisor quedó informado.")
    if u["rol"] in ("supervisor", "admin") and s["estado"] in flujo.ABIERTOS:
        with st.expander("🔀 Reasignar a otro abogado"):
            abog = C.usuarios("abogado", s["empresa_id"])
            na = st.selectbox("Nuevo abogado", abog, format_func=lambda a: a["nombre"], key=f"ra-{sid}")
            mot = st.text_input("Motivo (obligatorio)", key=f"ram-{sid}")
            if st.button("Reasignar", key=f"rab-{sid}"):
                ejecutar(S.reasignar, sid, na["id"], mot, u, ok="Caso reasignado.")
    if u["rol"] in ("supervisor", "admin", "director") and s["estado"] in flujo.ABIERTOS:
        with st.expander("🏢 Trasladar a otra empresa del consorcio (conserva el radicado)"):
            otras = [e for e in C.empresas() if e["id"] != s["empresa_id"]]
            de = st.selectbox("Empresa de destino", otras, format_func=lambda e: e["nombre"], key=f"tr-{sid}")
            mot = st.text_input("Motivo", key=f"trm-{sid}")
            conf = st.checkbox(f"Confirmo el traslado de {s['radicado']} a {de['codigo'] if de else ''}", key=f"trc-{sid}")
            if st.button("Trasladar entre empresas", disabled=not conf, key=f"trb-{sid}"):
                ejecutar(S.trasladar_empresa, sid, de["id"], mot, u, ok="Traslado realizado.")
    if s["estado"] == "RECIBIDA" and u["rol"] in ("radicador", "supervisor", "admin"):
        with st.expander("🗑 Anular (duplicado o spam)"):
            mot = st.text_input("Motivo de la anulación", key=f"an-{sid}")
            conf = st.checkbox(f"Confirmo anular {s['radicado']} (no se puede deshacer)", key=f"anc-{sid}")
            if st.button("Anular", disabled=not conf, key=f"anb-{sid}"):
                ejecutar(S.anular, sid, mot, u, ok="Solicitud anulada.")
        if not s.get("abogado_id") and st.button("Asignar ahora (reparto automático)", key=f"asg-{sid}"):
            ejecutar(S.asignar, sid, u, ok="Reparto ejecutado.")
    if s["estado"] == "ENVIADA" and (es_responsable or u["rol"] == "radicador"):
        if st.button("✔ Confirmar entrega y cerrar", key=f"ce-{sid}"):
            ejecutar(S.cerrar, sid, u, ok="Caso cerrado.")
    if s["estado"] == "CERRADA" and u["rol"] in ("supervisor", "director", "admin"):
        with st.expander("🔁 Reabrir (inconformidad o error)"):
            mot = st.text_input("Motivo", key=f"re-{sid}")
            if st.button("Reabrir", key=f"reb-{sid}"):
                ejecutar(S.reabrir, sid, mot, u, ok="Caso reabierto.")
    st.caption("Transiciones posibles desde este estado: " + (", ".join(flujo.destinos(s["estado"])) or "ninguna (estado final)"))

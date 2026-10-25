"""Vencimientos de retención (alertas a 30 y 90 días) y disposición final: propuesta → revisión → aprobación con acta → ejecución."""
import pandas as pd
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A
from core.reloj import fmt_fecha

ui.aviso_beta()
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor")
tema.hero("Vencimientos y disposición final", "Qué expedientes terminan su retención y cómo se decide su destino, con acta y doble control.", "⏰",
          ["Alertas a 90 y 30 días", "Archivista revisa → Supervisor aprueba"])
emp = UA.selector_empresa(u, "ven_emp")
UA.mostrar_flash()
exps = [x for x in A.expedientes(u, emp["id"]) if x["estado"] != "dispuesto"]
venc = [x for x in exps if x["nivel"] == "vencida"]
n30 = [x for x in exps if x["nivel"] == "30"]
n90 = [x for x in exps if x["nivel"] == "90"]
disp = A.disposiciones(u, empresa_id=emp["id"])
por = {k: [d for d in disp if d["estado"] == k] for k in A.ESTADOS_DISPOSICION}
tema.kpis([("🔴", "Retención vencida", len(venc), "rojo", "Proponer disposición"),
           ("🟠", "Vencen en ≤ 30 días", len(n30), "naranja", "Preparar la propuesta"),
           ("🟡", "Vencen en ≤ 90 días", len(n90), "amarillo", "Planear"),
           ("🟢", "Vigentes", len(exps) - len(venc) - len(n30) - len(n90), "verde", "Sin alerta")])

# Línea del proceso
ya = {d["expediente_id"] for d in disp if d["estado"] in ("propuesta", "revisada", "aprobada")}
pend = [x for x in venc if x["id"] not in ya and x["estado"] == "activo"]
pasos = [("1", "Proponer", "Archivista", len(pend)),
         ("2", "Revisar", "Archivista", len(por["propuesta"])), ("3", "Aprobar", "Supervisor", len(por["revisada"])),
         ("4", "Ejecutar", "Archivista", len(por["aprobada"]))]
cols = st.columns(4)
for c, (n, t, quien, cant) in zip(cols, pasos):
    c.markdown(f"<div class='paso'><span class='n'>{n}</span><b>{t}</b><br><span class='sub'>{quien}</span>"
               f"<br>{tema.badge(str(cant) + ' pendiente(s)', 'amarillo' if cant else 'verde')}</div>",
               unsafe_allow_html=True)

t = st.tabs(["🚨 Alertas 30 / 90", "1️⃣ Proponer", "2️⃣ Revisar", "3️⃣ Aprobar", "4️⃣ Ejecutar", "📜 Actas"])

with t[0]:
    if not (venc or n30 or n90):
        tema.vacio("🟢", "Sin vencimientos próximos", "Ningún expediente vence en los próximos 90 días.")
    else:
        df = UA.df_expedientes(sorted(venc + n30 + n90, key=lambda x: x["dias_restantes"]))
        st.dataframe(df[["Alerta", "Radicado", "Serie", "Vence retención", "Días", "Disposición", "Ubicación", "Estado"]], hide_index=True, width="stretch",
                     height=min(38 * (len(df) + 1) + 3, 460))
        ui.df_descarga(df, f"vencimientos_{emp['codigo']}", "ven")
    if u["rol"] in A.ROLES_GESTION:
        st.caption("Las alertas llegan a la campana 🔔 del archivista (y del supervisor cuando vence o espera aprobación). "
                   "Se generan una sola vez por umbral.")
        if st.button("🔔 Generar alertas ahora", key="ven_alertas"):
            r = A.generar_alertas_archivo()
            st.success("Alertas generadas: " + (", ".join(f"{A.TEXTOS_ALERTA[k]}: {v}" for k, v in r.items()) if r else "no había alertas nuevas."))

with t[1]:
    if not pend:
        tema.vacio("✅", "No hay expedientes por proponer", "Los expedientes con retención vencida ya tienen propuesta de disposición.")
    else:
        df = UA.df_expedientes(pend)[["Radicado", "Serie", "Vence retención", "Días", "Disposición", "Folios"]]
        sel = st.dataframe(df, hide_index=True, width="stretch", key="pro_t", on_select="rerun", selection_mode="multi-row",
                           height=min(38 * (len(df) + 1) + 3, 360))
        if u["rol"] in A.ROLES_GESTION:
            ids = [pend[i]["id"] for i in sel.selection.rows] if sel and sel.selection.rows else None
            c1, c2 = st.columns(2)
            if c1.button(f"📝 Proponer la disposición de los {len(ids)} seleccionados" if ids else "Seleccione filas para proponer", disabled=not ids, key="pro_sel", type="primary"):
                if UA.ejecutar(A.proponer_disposiciones, "Propuestas creadas: pasan a revisión.", u, emp["id"], ids):
                    st.rerun()
            if c2.button(f"📝 Proponer todos los vencidos ({len(pend)})", key="pro_all"):
                if UA.ejecutar(A.proponer_disposiciones, "Propuestas creadas: pasan a revisión.", u, emp["id"]):
                    st.rerun()
        else:
            UA.aviso_permiso(u, "proponer disposiciones")

with t[2]:
    rev = por["propuesta"]
    if not rev:
        tema.vacio("✅", "No hay propuestas por revisar", "")
    else:
        st.dataframe(pd.DataFrame([{"Radicado": d["radicado"], "Serie": f"{d['serie_codigo']} · {d['serie_nombre']}", "Disposición": UA.ICONO_DISP[d["disposicion"]],
                                    "Folios": d["folios"], "Propuesta": fmt_fecha(d["propuesta_en"])} for d in rev]), hide_index=True, width="stretch")
        if u["rol"] in A.ROLES_GESTION:
            d = st.selectbox("Propuesta a revisar", rev, key="rev_sel", format_func=lambda d: f"{d['radicado']} · {A.DISPOSICIONES[d['disposicion']]}")
            st.caption(A.DISPOSICION_AYUDA[d["disposicion"]])
            concepto = st.text_area("Concepto del archivista*", key="rev_txt", height=80,
                                    placeholder="Ej.: Revisados folios y serie; coincide con la TRD vigente.")
            c1, c2 = st.columns(2)
            if c1.button("👍 Concepto favorable (pasa a aprobación)", type="primary", key="rev_ok"):
                if UA.ejecutar(A.revisar_disposicion, "Concepto favorable registrado: queda pendiente de aprobación.", d["id"], True, concepto, u):
                    st.rerun()
            if c2.button("👎 No favorable (devolver)", key="rev_no"):
                if UA.ejecutar(A.revisar_disposicion, "Propuesta devuelta: el expediente sigue activo.", d["id"], False, concepto, u):
                    st.rerun()
        else:
            UA.aviso_permiso(u, "emitir el concepto del archivista")

with t[3]:
    apr = por["revisada"]
    if not apr:
        tema.vacio("✅", "No hay propuestas esperando aprobación", "")
    else:
        df = pd.DataFrame([{"Radicado": d["radicado"], "Serie": f"{d['serie_codigo']} · {d['serie_nombre']}", "Disposición": UA.ICONO_DISP[d["disposicion"]],
                            "Revisó": d["revisor"], "Concepto": d["concepto_archivista"]} for d in apr])
        sel = st.dataframe(df, hide_index=True, width="stretch", key="apr_t", on_select="rerun", selection_mode="multi-row",
                           height=min(38 * (len(df) + 1) + 3, 360))
        if u["rol"] in A.ROLES_APRUEBAN:
            ids = [apr[i]["id"] for i in sel.selection.rows] if sel and sel.selection.rows else []
            obs = st.text_area("Observación para el acta*", key="apr_obs", height=70, placeholder="Ej.: Aprobada según la TRD vigente.")
            c1, c2 = st.columns(2)
            if c1.button(f"✅ Aprobar y generar acta ({len(ids)})" if ids else "Seleccione filas para aprobar", disabled=not ids, type="primary", key="apr_ok"):
                r = UA.ejecutar(A.decidir_disposiciones, "Aprobado. Acta generada con su huella SHA-256.", ids, True, obs, u)
                if r:
                    st.rerun()
            if c2.button("⛔ Rechazar", disabled=not ids, key="apr_no"):
                if UA.ejecutar(A.decidir_disposiciones, "Propuestas rechazadas: los expedientes siguen activos.", ids, False, obs, u):
                    st.rerun()
            st.caption("Doble control: quien aprueba debe ser otra persona distinta del archivista que emitió el concepto.")
        else:
            st.info("🔒 La aprobación la hace el **supervisor** (o el director). Su rol puede consultar, pero no aprobar.")

with t[4]:
    ej = por["aprobada"]
    if not ej:
        tema.vacio("✅", "No hay disposiciones aprobadas por ejecutar", "")
    else:
        st.dataframe(pd.DataFrame([{"Radicado": d["radicado"], "Disposición": UA.ICONO_DISP[d["disposicion"]], "Acta": d["acta_numero"],
                                    "Aprobó": d["aprobador"]} for d in ej]), hide_index=True, width="stretch")
        if u["rol"] in A.ROLES_GESTION:
            d = st.selectbox("Disposición a registrar como ejecutada", ej, key="eje_sel", format_func=lambda d: f"{d['radicado']} · {d['acta_numero']}")
            det = st.text_input("Detalle de la ejecución", key="eje_det", placeholder="Ej.: Caja entregada para destrucción, acta firmada")
            st.warning("🧪 **Demostración:** esto solo **registra** la decisión; no se borra ni se mueve ningún documento.")
            if st.button("🏁 Registrar ejecución", type="primary", key="eje_b"):
                if UA.ejecutar(A.ejecutar_disposicion, "Ejecución registrada en la bitácora.", d["id"], det, u):
                    st.rerun()
        else:
            UA.aviso_permiso(u, "registrar la ejecución")
    hist = por["ejecutada"]
    if hist:
        st.markdown("**Ya ejecutadas**")
        st.dataframe(pd.DataFrame([{"Radicado": d["radicado"], "Disposición": UA.ICONO_DISP[d["disposicion"]], "Acta": d["acta_numero"],
                                    "Ejecutada": fmt_fecha(d["ejecutada_en"]), "Detalle": d["detalle_ejecucion"]} for d in hist]), hide_index=True, width="stretch")

with t[5]:
    actas = A.actas(u, emp["id"])
    if not actas:
        tema.vacio("📜", "Todavía no hay actas", "Se crea una cuando el supervisor aprueba disposiciones.")
    else:
        for a in actas:
            with st.expander(f"📜 {a['numero']} · {fmt_fecha(a['fecha'])} · aprobó {a['aprobada_por_nombre']}"):
                st.code(a["contenido"], language=None)
                st.markdown(f"**Huella SHA-256:** `{a['sha256']}`")
                st.download_button("⬇️ Descargar el acta (texto)", a["contenido"], f"{a['numero']}.txt", key=f"acta-{a['id']}")
        st.caption("La huella permite comprobar que el acta no cambió. En la demostración no lleva firma digital certificada.")

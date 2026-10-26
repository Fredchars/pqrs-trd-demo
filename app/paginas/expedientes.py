"""Expediente electrónico: PQRS cerradas con serie TRD, índice de documentos, fechas de retención y ubicación física."""
import io

import pandas as pd
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A
from core.reloj import fmt_fecha

ui.aviso_beta()
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor", "abogado")
tema.hero("Expedientes electrónicos", "Cada PQRS cerrada se archiva en su serie, con índice de documentos, folios y fechas de retención.", "📁",
          ["Índice con folios y huella", "Ubicación del papel"])
emp = UA.selector_empresa(u, "exp_emp")
UA.mostrar_flash()
exps = A.expedientes(u, emp["id"])
sin_serie = A.cerradas_sin_serie(u, emp["id"])
tema.kpis([("📁", "Expedientes", len(exps), "azul", "Con serie asignada"),
           ("🧾", "Cerradas sin serie", len(sin_serie), "rojo" if sin_serie else "verde", "Falta archivarlas"),
           ("🔴", "Retención vencida", sum(1 for x in exps if x["nivel"] == "vencida"), "rojo", "Proponer disposición"),
           ("📍", "Sin ubicar en el archivo", sum(1 for x in exps if not x.get("carpeta_codigo") and x["estado"] != "dispuesto"), "amarillo", "Papel por guardar")])
t1, t2 = st.tabs(["📁 Expedientes", f"🧾 Cerradas sin serie ({len(sin_serie)})"])

with t1:
    if not exps:
        tema.vacio("📁", "Todavía no hay expedientes", "Cuando una PQRS se cierra y se le asigna una serie TRD aparece aquí. Revise la pestaña «Cerradas sin serie».")
    else:
        c1, c2, c3 = st.columns([2, 2, 2])
        series = sorted({(x["serie_codigo"], x["serie_nombre"]) for x in exps})
        f_serie = c1.selectbox("Serie", [None] + series, format_func=lambda s: "Todas" if s is None else f"{s[0]} · {s[1]}", key="exp_serie")
        f_niv = c2.selectbox("Alerta de retención", ["Todas", "Vencida", "≤ 30 días", "≤ 90 días", "Vigente"], key="exp_niv")
        f_txt = c3.text_input("Buscar por radicado", key="exp_txt")
        mapa = {"Vencida": "vencida", "≤ 30 días": "30", "≤ 90 días": "90", "Vigente": None}
        vista = [x for x in exps if (f_serie is None or (x["serie_codigo"], x["serie_nombre"]) == f_serie)
                 and (f_niv == "Todas" or (x["nivel"] == mapa[f_niv] and x["estado"] != "dispuesto"))
                 and (not f_txt or f_txt.lower() in x["radicado"].lower())]
        df = UA.df_expedientes(vista)
        if df.empty:
            tema.vacio("🔎", "Sin resultados", "Ningún expediente cumple esos filtros. Quite alguno para ver más.")
        else:
            sel = st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 420), key="exp_tabla",
                               on_select="rerun", selection_mode="single-row")
            idx = sel.selection.rows[0] if sel and sel.selection.rows else None
            ui.df_descarga(df, f"expedientes_{emp['codigo']}", "exp")
            st.caption("Seleccione una fila (casilla de la izquierda) para ver la ficha del expediente y su índice.")
            if idx is not None:
                x = vista[idx]
                st.divider()
                st.subheader(f"📂 Expediente {x['radicado']}")
                st.markdown(f"**{x['asunto']}**")
                tono = UA.TONO_NIVEL[x["nivel"]] if x["estado"] != "dispuesto" else "gris"
                st.markdown(tema.badge(f"{x['nivel_icono']} {x['nivel_texto']}", tono) + " " + tema.badge(A.ESTADOS_EXPEDIENTE.get(x["estado"], x["estado"]), "azul")
                            + " " + tema.badge(UA.ICONO_DISP.get(x["disposicion"], ""), "morado"), unsafe_allow_html=True)
                tema.kpis([("🔒", "Cierre de la PQRS", fmt_fecha(x["fecha_cierre"]), "azul", ""),
                           ("🏁", "Fin archivo de gestión", fmt_fecha(x["fecha_fin_gestion"]), "teal", f"{UA.anios(x['anios_gestion'])} de gestión"),
                           ("⌛", "Fin de retención", fmt_fecha(x["fecha_disposicion"]), UA.TONO_NIVEL[x["nivel"]] if x["nivel"] else "verde",
                            f"{UA.anios(x['anios_central'])} en central"),
                           ("📆", "Días restantes", x["dias_restantes"], UA.TONO_NIVEL[x["nivel"]] if x["nivel"] else "verde", f"Fase actual: {x['fase']}")])
                if x.get("observacion"):
                    st.info(f"ℹ️ {x['observacion']}")
                ubic = (f"Caja **{x['caja_codigo']}** · carpeta **{x['carpeta_codigo']}** · estante {x['estante']} · entrepaño {x['entrepano']}"
                        if x.get("carpeta_codigo") else "Aún **sin ubicar** en una carpeta del archivo físico.")
                st.markdown(f"**📍 Ubicación del papel:** {ubic}" + (f" · hojas físicas: {x['hojas_fisicas']}" if x.get("hojas_fisicas") else ""))
                ind = UA.indice_tabla(A.indice(x["id"], u))
                if not ind.empty:
                    st.markdown("**📑 Índice del expediente electrónico**")
                    st.dataframe(ind, hide_index=True, width="stretch")
                    bio = io.BytesIO()
                    ind.to_excel(bio, index=False)
                    st.download_button("⬇️ Descargar el índice (Excel)", bio.getvalue(), f"indice_{x['radicado']}.xlsx", key="exp_ind")
                if x["solicitud_id"] and st.button("📂 Abrir el caso original", key="exp_abrir"):
                    ui.abrir_caso(x["solicitud_id"])
                if u["rol"] in A.ROLES_GESTION and x["estado"] != "dispuesto":
                    cars = [c for c in A.carpetas(u, emp["id"]) if c["estado"] == "en_archivo" and (not c["serie_id"] or c["serie_id"] == x["serie_id"])]
                    with st.expander("📍 Guardar el papel en una carpeta"):
                        if not cars:
                            st.info("No hay carpetas disponibles para esta serie. Cree una en **Cajas y rótulos**.")
                        else:
                            c = st.selectbox("Carpeta", cars, key="exp_carp", format_func=lambda c: f"{c['codigo']} · {c['caja_codigo']} · estante {c['estante']}")
                            if st.button("Guardar en esta carpeta", key="exp_ubicar", type="primary"):
                                if UA.ejecutar(A.ubicar_expediente, "Ubicación guardada.", x["id"], c["id"], u):
                                    st.rerun()

with t2:
    if not sin_serie:
        tema.vacio("✅", "Todo está archivado", "No hay PQRS cerradas pendientes de serie en esta empresa.")
    else:
        st.markdown("Estas PQRS ya están **cerradas**, pero no se les ha asignado una serie TRD: sin serie no se puede calcular la retención.")
        df = pd.DataFrame([{"Radicado": s["radicado"], "Tipo": s["tipo_nombre"], "Asunto": s["asunto"],
                            "Papel": f"{s['hojas_fisicas'] or ''} hojas" if s["docs_fisicos"] else "Solo electrónico"} for s in sin_serie])
        sel = st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 360), key="ss_tabla",
                           on_select="rerun", selection_mode="single-row")
        if u["rol"] in A.ROLES_GESTION:
            asign = A.series_asignables(u, emp["id"])
            c1, c2 = st.columns([1, 2])
            if c1.button("⚡ Asignar las series sugeridas a todas", key="ss_masivo", type="primary",
                         help="Usa los «tipos de PQRS sugeridos» de cada subserie. Las que no tengan sugerencia quedan para asignar a mano."):
                r = UA.ejecutar(A.asignar_series_sugeridas, "Hecho.", u, emp["id"])
                if r:  # se recarga para que la tabla ya no muestre las asignadas
                    st.session_state["flash"] = (f"✅ {r['asignados']} expediente(s) creados. "
                                                 f"{r['sin_sugerencia']} sin sugerencia: asígnelos a mano.")
                    st.rerun()
            if sel and sel.selection.rows:
                s = sin_serie[sel.selection.rows[0]]
                st.markdown(f"**Asignar serie a {s['radicado']}**")
                c = st.selectbox("Serie / subserie", asign, key="ss_serie", format_func=lambda x: f"{x['codigo']} · {x['nombre']} "
                                 f"({x['anios_gestion']}+{x['anios_central']} {'año' if x['anios_gestion'] + x['anios_central'] == 1 else 'años'}, {A.DISPOSICIONES[x['disposicion']]})")
                if st.button("✅ Asignar y crear el expediente", key="ss_asignar"):
                    if UA.ejecutar(A.asignar_serie, f"Expediente creado para {s['radicado']}.", s["id"], c["id"], u):
                        st.rerun()
            else:
                st.caption("Seleccione una fila para asignarle la serie a mano.")
        else:
            UA.aviso_permiso(u, "asignar series")

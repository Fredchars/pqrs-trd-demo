"""Préstamo y devolución de carpetas físicas, con responsable y fecha."""
import pandas as pd
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A
from core.reloj import fmt_fecha

ui.aviso_beta()
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor", "abogado")
tema.hero("Préstamos de carpetas", "Quién tiene cada carpeta, desde cuándo y hasta cuándo. Registro de entrega y devolución.", "🔄",
          ["Responsable y fecha", "Alerta de préstamos vencidos"])
emp = UA.selector_empresa(u, "pre_emp")
UA.mostrar_flash()
pres = A.prestamos(u, empresa_id=emp["id"])
tema.kpis([("🕓", "Solicitadas", sum(p["estado"] == "solicitada" for p in pres), "amarillo", "Esperan entrega"),
           ("📤", "Prestadas", sum(p["estado"] == "prestada" for p in pres), "azul", "Fuera del archivo"),
           ("⏰", "Vencidas", sum(p["vencido"] for p in pres), "rojo" if any(p["vencido"] for p in pres) else "verde", "Reclamar devolución"),
           ("✅", "Devueltas", sum(p["estado"] == "devuelta" for p in pres), "verde", "Historial")])


def tabla(filas):
    return pd.DataFrame([{"Carpeta": p["carpeta_codigo"], "Caja": p["caja_codigo"], "Solicitante": p["solicitante"], "Motivo": p["motivo"],
                          "Solicitud": fmt_fecha(p["fecha_solicitud"]), "Entrega": fmt_fecha(p["fecha_prestamo"]) if p["fecha_prestamo"] else "—",
                          "Vence": fmt_fecha(p["fecha_vence"]) if p["fecha_vence"] else "—",
                          "Responsable (archivista)": p["responsable"] or "—",
                          "Devolución": fmt_fecha(p["fecha_devolucion"]) if p["fecha_devolucion"] else "—",
                          "Estado": ("⏰ Vencida" if p["vencido"] else {"solicitada": "🕓 Solicitada", "prestada": "📤 Prestada", "devuelta": "✅ Devuelta"}[p["estado"]])}
                         for p in filas])


t = st.tabs(["🙋 Pedir una carpeta", "📤 Entregar", "📥 Devolver", "🗒️ Historial"])
with t[0]:
    if u["rol"] == "auditor":
        UA.aviso_permiso(u, "pedir carpetas")
    else:
        cars = [f for f in A.carpetas(u, emp["id"]) if f["estado"] == "en_archivo" and f["n_expedientes"]]
        if not cars:
            tema.vacio("📁", "No hay carpetas disponibles", "Todas están prestadas o aún no tienen expedientes guardados.")
        else:
            with st.form("pre_form", clear_on_submit=True):
                car = st.selectbox("Carpeta", cars, format_func=lambda f: f"{f['codigo']} · serie {f['serie_codigo'] or '—'} · estante {f['estante']} · {f['n_expedientes']} exp.")
                motivo = st.text_input("Motivo del préstamo*", placeholder="Ej.: Consultar antecedentes para responder un recurso")
                dias = st.slider("¿Por cuántos días?", 1, 30, 5)
                if st.form_submit_button("🙋 Solicitar préstamo", type="primary"):
                    if UA.ejecutar(A.solicitar_prestamo, "Solicitud registrada: el archivista la verá en «Entregar».", car["id"], motivo, dias, u):
                        st.rerun()
with t[1]:
    solic = [p for p in pres if p["estado"] == "solicitada"]
    if not solic:
        tema.vacio("🎉", "No hay solicitudes pendientes", "Cuando alguien pida una carpeta aparecerá aquí.")
    else:
        st.dataframe(tabla(solic)[["Carpeta", "Caja", "Solicitante", "Motivo", "Solicitud"]], hide_index=True, width="stretch")
        if u["rol"] in A.ROLES_GESTION:
            p = st.selectbox("Solicitud a entregar", solic, key="pre_ent", format_func=lambda p: f"{p['carpeta_codigo']} → {p['solicitante']}")
            if st.button("📤 Registrar la entrega", type="primary", key="pre_ent_b"):
                if UA.ejecutar(A.entregar_prestamo, "Entrega registrada con su responsable y fecha de vencimiento.", p["id"], u):
                    st.rerun()
        else:
            UA.aviso_permiso(u, "entregar carpetas")
with t[2]:
    prest = [p for p in pres if p["estado"] == "prestada"]
    if not prest:
        tema.vacio("📚", "No hay carpetas prestadas", "Todas las carpetas están en el archivo.")
    else:
        st.dataframe(tabla(prest)[["Carpeta", "Caja", "Solicitante", "Entrega", "Vence", "Responsable (archivista)", "Estado"]], hide_index=True, width="stretch")
        if u["rol"] in A.ROLES_GESTION:
            p = st.selectbox("Carpeta que regresa", prest, key="pre_dev", format_func=lambda p: f"{p['carpeta_codigo']} ← {p['solicitante']}")
            obs = st.text_input("Observaciones de la devolución", key="pre_dev_obs", placeholder="Ej.: Devuelta completa")
            if st.button("📥 Registrar la devolución", type="primary", key="pre_dev_b"):
                if UA.ejecutar(A.devolver_prestamo, "Devolución registrada: la carpeta vuelve a estar disponible.", p["id"], u, obs):
                    st.rerun()
        else:
            UA.aviso_permiso(u, "registrar devoluciones")
with t[3]:
    if not pres:
        tema.vacio("🗒️", "Sin movimientos", "Aún no se han pedido carpetas en esta empresa.")
    else:
        df = tabla(pres)
        st.dataframe(df, hide_index=True, width="stretch")
        ui.df_descarga(df, f"prestamos_{emp['codigo']}", "pre")

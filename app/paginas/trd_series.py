"""TRD: cuadro de series y subseries por empresa, con tiempos de retención y disposición final."""
import pandas as pd
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A

ui.aviso_beta()
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor", "abogado")
tema.hero("Tabla de Retención Documental (TRD)", "Qué documentos se guardan, cuánto tiempo y qué pasa al final.", "🗂️",
          ["Por empresa", "Gestión → Central → Disposición final"])
emp = UA.selector_empresa(u, "trd_emp")
UA.mostrar_flash()
series = A.series(u, emp["id"])
hijas = [s for s in series if s["serie_padre_id"]]
conret = [s for s in series if s["disposicion"]]
tema.kpis([("🗂️", "Series", sum(1 for s in series if not s["serie_padre_id"]), "azul", "Agrupan los documentos por función"),
           ("📑", "Subseries", len(hijas), "teal", "Cada una con su retención"),
           ("📁", "Expedientes asignados", sum(s["n_expedientes"] for s in series), "verde", "PQRS cerradas con serie"),
           ("⏳", "Retención más larga", f"{max((A.retencion_total(s) or 0) for s in conret) if conret else 0} años", "morado", "Gestión + central")])
with st.expander("❓ ¿Cómo se lee esta tabla?"):
    st.markdown(
        "- **Archivo de gestión**: años que el expediente permanece cerca de quien lo tramitó, contados desde el cierre de la PQRS.\n"
        "- **Archivo central**: años adicionales en el archivo central antes de decidir su destino.\n"
        "- **Disposición final**: 🛡️ *Conservar* (valor histórico), 🗑️ *Eliminar* (con acta y aprobación) o 💾 *Digitalizar* "
        "(se guarda electrónico y se elimina el papel).\n- **Tipos sugeridos**: tipos de PQRS que se proponen para esa subserie al archivar.\n\n"
        "_Los tiempos de esta demostración son **ficticios**; la TRD real la define y aprueba el archivista de cada empresa._")
if not series:
    tema.vacio("🗂️", "Esta empresa aún no tiene TRD", "Cree la primera serie con el formulario de abajo (solo el archivista o el administrador).")
else:
    nombres = {s["id"]: s for s in series}
    df = pd.DataFrame([{
        "Código": s["codigo"], "Nivel": "Subserie" if s["serie_padre_id"] else "Serie",
        "Nombre": ("      ↳ " if s["serie_padre_id"] else "") + s["nombre"],
        "Tipos de PQRS": s["tipos_sugeridos"] or "—",
        "Gestión (años)": str(s["anios_gestion"]) if s["anios_gestion"] is not None else "—",
        "Central (años)": str(s["anios_central"]) if s["anios_central"] is not None else "—",
        "Total (años)": str(A.retencion_total(s)) if s["disposicion"] else "—",
        "Disposición final": UA.ICONO_DISP.get(s["disposicion"], "—"),
        "Expedientes": s["n_expedientes"], "Activa": "Sí" if s["activa"] else "No"} for s in series])
    st.dataframe(df, hide_index=True, width="stretch", height=min(40 * (len(df) + 1) + 3, 460))
    ui.df_descarga(df, f"TRD_{emp['codigo']}", "trd")

if u["rol"] in A.ROLES_GESTION:
    st.subheader("➕ Crear o editar una serie / subserie")
    madres = [s for s in series if not s["serie_padre_id"]]
    modo = st.radio("¿Qué desea hacer?", ["Crear nueva", "Editar existente"], horizontal=True, key="trd_modo")
    editar = None
    if modo == "Editar existente":
        if not series:
            st.info("No hay series para editar.")
            st.stop()
        editar = st.selectbox("Serie a editar", series, format_func=lambda s: f"{s['codigo']} · {s['nombre']}", key="trd_edit")
    with st.form("trd_form", clear_on_submit=False):
        c1, c2 = st.columns([1, 3])
        codigo = c1.text_input("Código*", value=editar["codigo"] if editar else "", help="Ej.: 10.6")
        nombre = c2.text_input("Nombre*", value=editar["nombre"] if editar else "")
        madre = st.selectbox("Serie madre (vacío = es una serie)", [None] + madres, key="trd_madre",
                             format_func=lambda s: "— Ninguna (serie principal) —" if s is None else f"{s['codigo']} · {s['nombre']}",
                             index=([None] + madres).index(next((m for m in madres if editar and m["id"] == editar["serie_padre_id"]), None)))
        c3, c4, c5 = st.columns(3)
        g = c3.number_input("Años en archivo de gestión", 0, 100, int(editar["anios_gestion"] or 2) if editar else 2)
        c = c4.number_input("Años en archivo central", 0, 100, int(editar["anios_central"] or 3) if editar else 3)
        disp = c5.selectbox("Disposición final", list(A.DISPOSICIONES), format_func=lambda k: UA.ICONO_DISP[k],
                            index=list(A.DISPOSICIONES).index(editar["disposicion"]) if editar and editar["disposicion"] else 0)
        tipos = st.text_input("Tipos de PQRS sugeridos (códigos separados por coma)", value=(editar or {}).get("tipos_sugeridos") or "",
                              help="Ej.: P, C, Q, R, S, D")
        desc = st.text_area("Descripción / procedimiento", value=(editar or {}).get("descripcion") or "", height=70)
        activa = st.checkbox("Serie activa", value=bool(editar["activa"]) if editar else True)
        ok = st.form_submit_button("💾 Guardar serie", type="primary")
    if ok:
        datos = {"empresa_id": emp["id"], "codigo": codigo, "nombre": nombre, "serie_padre_id": madre["id"] if madre else None,
                 "anios_gestion": g, "anios_central": c, "disposicion": disp, "tipos_sugeridos": tipos, "descripcion": desc,
                 "activa": activa, "procedimiento": (editar or {}).get("procedimiento"), "acto_aprobacion": (editar or {}).get("acto_aprobacion")}
        if UA.ejecutar(A.guardar_serie, "Serie guardada.", datos, u, editar["id"] if editar else None):
            st.rerun()
else:
    UA.aviso_permiso(u, "modificar la TRD")

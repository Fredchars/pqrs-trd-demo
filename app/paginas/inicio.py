"""Inicio: resumen visual por rol, accesos rápidos y alertas recientes."""
import pandas as pd
import plotly.express as px
import streamlit as st

import tema
import ui
from core import archivo as A
from core import consultas as C

ui.aviso_beta()
u = ui.requiere()
rol = u["rol"]
emps = [C.empresa(e) for e in u.get("empresas", []) if C.empresa(e)]
nombre = (u["nombre"] or "").split(" ")[0] or "usuario"
tema.hero(f"Hola, {nombre} 👋", f"Este es su resumen de hoy como {C.ROLES.get(rol, rol)}.", "🏠",
          [e["codigo"] for e in emps][:6] + ([f"+{len(emps) - 6} empresas"] if len(emps) > 6 else []) or ["Todas las empresas"])

# ---------------------------------------------------------------- indicadores de PQRS
if rol in ("abogado", "supervisor", "director", "admin", "radicador", "auditor"):
    casos = C.listar_solicitudes(u, {"abiertos": True})
    por_vencer = [s for s in casos if s.get("dias_restantes") is not None and 0 <= s["dias_restantes"] <= 2 and s["estado"] != "PENDIENTE_INFO"]
    vencidos = [s for s in casos if s["sem_nivel"] == "negro"]
    sin_asig = [s for s in casos if not s.get("abogado_id")]
    st.subheader("📨 PQRS en trámite")
    tema.kpis([("📥", "Casos abiertos", len(casos), "azul", "Alcance de su rol"),
               ("🟠", "Por vencer (≤ 2 días)", len(por_vencer), "naranja" if por_vencer else "verde", "Atender primero"),
               ("⛔", "Vencidos", len(vencidos), "rojo" if vencidos else "verde", "Fuera de plazo"),
               ("📭", "Sin asignar", len(sin_asig), "amarillo" if sin_asig else "verde", "Esperan abogado")])
    if casos:
        c1, c2 = st.columns(2)
        df = pd.DataFrame({"Estado": [s["estado"].replace("_", " ").capitalize() for s in casos]})
        conteo = df["Estado"].value_counts().rename_axis("Estado").reset_index(name="Casos")
        fig = px.bar(conteo, x="Casos", y="Estado", orientation="h", color_discrete_sequence=["#1E5AA8"])
        fig.update_layout(margin=dict(l=0, r=10, t=30, b=0), height=280, title="Casos abiertos por estado", yaxis=dict(autorange="reversed"))
        c1.plotly_chart(fig, width="stretch")
        NOMBRES = {"verde": "En plazo", "amarillo": "Atención", "rojo": "Urgente", "negro": "Vencido", "pausa": "En pausa", "cerrado": "Cerrado", "pendiente": "Pendiente"}
        sem = pd.Series([NOMBRES.get(s["sem_nivel"], s["sem_nivel"]) for s in casos]).value_counts().rename_axis("Plazo").reset_index(name="Casos")
        fig2 = px.pie(sem, names="Plazo", values="Casos", hole=.5, color="Plazo",
                      color_discrete_map={"En plazo": "#16A34A", "Atención": "#CA8A04", "Urgente": "#DC2626", "Vencido": "#1F2937", "En pausa": "#6366F1", "Cerrado": "#94A3B8", "Pendiente": "#94A3B8"})
        fig2.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=280, title="Semáforo de plazos")
        c2.plotly_chart(fig2, width="stretch")
    else:
        tema.vacio("🎉", "No tiene casos abiertos", "Cuando llegue una PQRS aparecerá aquí.")

# ---------------------------------------------------------------- indicadores de archivo
if rol in A.ROLES_ARCHIVO_VE:
    r = A.resumen(u)
    st.subheader("🗂️ TRD y archivo físico")
    tema.kpis([("📁", "Expedientes", r["expedientes"], "azul", f"{r['activos']} activos"),
               ("🔴", "Retención vencida", r["vencidas"], "rojo" if r["vencidas"] else "verde", f"{r['en_30']} en ≤ 30 días · {r['en_90']} en ≤ 90"),
               ("🧾", "Cerradas sin serie", r["sin_serie"], "amarillo" if r["sin_serie"] else "verde", "Falta archivarlas"),
               ("📦", "Ocupación de cajas", f"{r['ocupacion']} %", "teal", f"{r['cajas']} cajas · {r['carpetas']} carpetas"),
               ("🔄", "Carpetas prestadas", r["prestadas"], "morado", f"{r['prestamos_vencidos']} vencidas"),
               ("🖋️", "Disposiciones en curso", r["por_revisar"] + r["por_aprobar"] + r["por_ejecutar"], "azul",
                f"{r['por_revisar']} por revisar · {r['por_aprobar']} por aprobar")])
    if r["expedientes"]:
        activos = [x for x in A.expedientes(u) if x["estado"] != "dispuesto"]
        niv = pd.Series([x["nivel_texto"] for x in activos]).value_counts().rename_axis("Nivel").reset_index(name="Expedientes")
        c1, c2 = st.columns(2)
        fig = px.pie(niv, names="Nivel", values="Expedientes", hole=.5, color="Nivel", title="Expedientes por alerta de retención",
                     color_discrete_map={"Vencida": "#DC2626", "≤ 30 días": "#EA580C", "≤ 90 días": "#CA8A04", "Vigente": "#16A34A"})
        fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=280)
        c1.plotly_chart(fig, width="stretch")
        cj = A.cajas(u)
        if cj:
            dfc = pd.DataFrame([{"Caja": c["codigo"], "Ocupación %": c["ocupacion"]} for c in cj][:12])
            fig = px.bar(dfc, x="Caja", y="Ocupación %", range_y=[0, 100], color_discrete_sequence=["#0EA5A4"], title="Ocupación de las primeras cajas")
            fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=280)
            c2.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- accesos rápidos
ATAJOS = {
    "abogado": ["bandeja", "busqueda", "reportes", "expedientes"],
    "radicador": ["bandeja", "buzon", "busqueda"],
    "supervisor": ["supervision", "aprobaciones", "vencimientos", "expedientes", "reportes", "reportes_archivo"],
    "director": ["aprobaciones", "supervision", "vencimientos", "reportes", "reportes_archivo"],
    "archivista": ["expedientes", "cajas", "prestamos", "vencimientos", "trd", "reportes_archivo"],
    "admin": ["administracion", "supervision", "trd", "cajas", "bitacora", "exportacion"],
    "auditor": ["bitacora", "exportacion", "reportes", "reportes_archivo", "expedientes"],
}
st.subheader("🚀 ¿Qué desea hacer?")
claves = [k for k in ATAJOS.get(rol, []) if k in ui.PAGINAS]
cols = st.columns(3)
for i, k in enumerate(claves):
    pg = ui.PAGINAS[k]
    with cols[i % 3]:
        st.page_link(pg, label=pg.title, icon=pg.icon, width="stretch")

# ---------------------------------------------------------------- alertas recientes
st.subheader("🔔 Alertas recientes")
nuevas = C.alertas_usuario(u["id"], solo_no_leidas=True, limite=5)
if not nuevas:
    tema.vacio("🔕", "No tiene alertas nuevas", "Aquí verá los vencimientos y pendientes que requieren su atención.")
for a in nuevas:
    st.markdown(f"{tema.badge(a['tipo'].replace('_', ' '), 'azul')} {tema.esc(a['mensaje'])}", unsafe_allow_html=True)
